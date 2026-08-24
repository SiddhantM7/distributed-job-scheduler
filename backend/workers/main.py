"""Worker process: registration, heartbeats, atomic job claim loop, and execution lifecycle."""
import asyncio
import logging
import os
import signal
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Set

from sqlalchemy import insert, select, update

from app.config import settings
from app.database import dispose_engine, engine
from app.models.tables import (
    job_executions,
    job_logs,
    jobs,
    queues,
    retry_policies,
    worker_queues,
)
from app.schemas.workers import RegisterWorkerRequest, WorkerHeartbeatRequest
from app.services.dlq import move_job_to_dlq
from app.services.jobs import claim_job_atomic
from app.services.workers import (
    deregister_worker_service,
    heartbeat_worker_service,
    register_worker_service,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [worker] %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Retry Calculation Helper ─────────────────────────────────────────────────

def _compute_retry_delay(
    strategy: str,
    base_delay_seconds: int,
    multiplier: float | None,
    max_delay_seconds: int | None,
    attempt_count: int,
) -> int:
    """Calculate next retry delay in seconds according to policy strategy."""
    multiplier_val = float(multiplier) if multiplier is not None else 2.0
    if strategy == "fixed":
        delay = base_delay_seconds
    elif strategy == "linear":
        delay = base_delay_seconds * attempt_count
    elif strategy == "exponential":
        delay = int(base_delay_seconds * (multiplier_val ** max(0, attempt_count - 1)))
    else:
        delay = base_delay_seconds

    if max_delay_seconds is not None:
        delay = min(delay, max_delay_seconds)
    return max(1, delay)


# ─── Job Handler Execution ────────────────────────────────────────────────────

async def execute_job_handler(job_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic job execution handler supporting standard workloads and failure testing."""
    # Check for forced test failure
    if payload.get("force_failure") is True or "error" in payload:
        error_msg = payload.get("error") or f"Forced failure in job type '{job_type}'"
        raise RuntimeError(error_msg)

    # Simulate delay if requested
    if "delay_ms" in payload:
        await asyncio.sleep(payload["delay_ms"] / 1000.0)

    # Return output payload or standard success response
    return payload.get("result") or {
        "status": "completed",
        "job_type": job_type,
        "processed_at": datetime.now(tz=timezone.utc).isoformat(),
    }


# ─── Job Processor ────────────────────────────────────────────────────────────

async def process_claimed_job(job: Dict[str, Any], worker_id: uuid.UUID) -> None:
    """Run full execution lifecycle for a claimed job: running -> success / retry / DLQ."""
    job_id = job["id"]
    queue_id = job["queue_id"]
    job_type = job["type"]
    payload = job["payload"] or {}
    attempt_number = (job["attempt_count"] or 0) + 1
    max_attempts = job["max_attempts"] or 5
    started_at = datetime.now(tz=timezone.utc)

    logger.info(f"Processing job {job_id} (type='{job_type}', attempt={attempt_number}/{max_attempts})")

    # 1. Record running execution
    async with engine.connect() as conn:
        await conn.execute(
            update(jobs)
            .where(jobs.c.id == job_id)
            .values(status="running", started_at=started_at)
        )
        exec_res = await conn.execute(
            insert(job_executions)
            .values(
                job_id=job_id,
                worker_id=worker_id,
                attempt_number=attempt_number,
                status="running",
                started_at=started_at,
            )
            .returning(job_executions.c.id)
        )
        exec_id = exec_res.scalar_one()
        await conn.commit()

    start_monotonic = time.monotonic()

    # 2. Execute Handler
    try:
        result = await execute_job_handler(job_type, payload)
        duration_ms = max(1, int((time.monotonic() - start_monotonic) * 1000))
        completed_at = datetime.now(tz=timezone.utc)

        # 3. Success handling
        async with engine.connect() as conn:
            await conn.execute(
                update(job_executions)
                .where(job_executions.c.id == exec_id)
                .values(
                    status="completed",
                    completed_at=completed_at,
                    duration_ms=duration_ms,
                    result=result,
                    error=None,
                )
            )
            await conn.execute(
                insert(job_logs).values(
                    job_execution_id=exec_id,
                    timestamp=completed_at,
                    level="info",
                    message=f"Job '{job_type}' executed successfully in {duration_ms}ms",
                )
            )
            await conn.execute(
                update(jobs)
                .where(jobs.c.id == job_id)
                .values(
                    status="completed",
                    attempt_count=attempt_number,
                    completed_at=completed_at,
                    result=result,
                    error=None,
                )
            )
            await conn.commit()
        logger.info(f"Job {job_id} completed successfully ({duration_ms}ms)")

    except Exception as exc:
        duration_ms = max(1, int((time.monotonic() - start_monotonic) * 1000))
        failed_at = datetime.now(tz=timezone.utc)
        error_msg = str(exc)
        logger.warning(f"Job {job_id} attempt {attempt_number} failed: {error_msg}")

        # 4. Failure handling
        async with engine.connect() as conn:
            await conn.execute(
                update(job_executions)
                .where(job_executions.c.id == exec_id)
                .values(
                    status="failed",
                    completed_at=failed_at,
                    duration_ms=duration_ms,
                    error=error_msg,
                )
            )
            await conn.execute(
                insert(job_logs).values(
                    job_execution_id=exec_id,
                    timestamp=failed_at,
                    level="error",
                    message=f"Execution error on attempt {attempt_number}: {error_msg}",
                )
            )

            # Check if retry attempts exhausted
            if attempt_number >= max_attempts:
                logger.error(f"Job {job_id} exhausted all {max_attempts} attempts. Moving to DLQ.")
                await conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job_id)
                    .values(attempt_count=attempt_number)
                )
                await move_job_to_dlq(
                    db=conn,
                    job_id=job_id,
                    reason=f"Max attempts ({max_attempts}) exhausted",
                    last_error=error_msg,
                )
            else:
                # Resolve retry policy
                policy_row = None
                if job.get("retry_policy_id"):
                    p_res = await conn.execute(
                        select(retry_policies).where(retry_policies.c.id == job["retry_policy_id"])
                    )
                    policy_row = p_res.mappings().first()

                if not policy_row:
                    q_res = await conn.execute(
                        select(queues.c.default_retry_policy_id).where(queues.c.id == queue_id)
                    )
                    q_row = q_res.first()
                    if q_row and q_row[0]:
                        p_res = await conn.execute(
                            select(retry_policies).where(retry_policies.c.id == q_row[0])
                        )
                        policy_row = p_res.mappings().first()

                strategy = policy_row["strategy"] if policy_row else "exponential"
                base_delay = policy_row["base_delay_seconds"] if policy_row else 5
                multiplier = policy_row["multiplier"] if policy_row else 2.0
                max_delay = policy_row["max_delay_seconds"] if policy_row else None

                delay_sec = _compute_retry_delay(strategy, base_delay, multiplier, max_delay, attempt_number)
                next_run_at = failed_at + timedelta(seconds=delay_sec)

                logger.info(f"Scheduling retry for job {job_id} in {delay_sec}s at {next_run_at.isoformat()}")

                await conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job_id)
                    .values(
                        status="queued",
                        attempt_count=attempt_number,
                        run_at=next_run_at,
                        claimed_by=None,
                        claimed_at=None,
                        started_at=None,
                        completed_at=None,
                        error=error_msg,
                    )
                )
            await conn.commit()


# ─── Worker Process Engine ────────────────────────────────────────────────────

class WorkerProcess:
    """Worker node managing registration, heartbeats, concurrent claims, and graceful shutdown."""

    def __init__(self, concurrency: int = 5) -> None:
        self.concurrency = concurrency
        self.worker_id: uuid.UUID | None = None
        self.hostname = socket.gethostname()
        self.pid = os.getpid()
        self.stop_event = asyncio.Event()
        self.active_tasks: Set[asyncio.Task] = set()
        self.semaphore = asyncio.Semaphore(concurrency)

    async def register(self) -> None:
        """Register worker with the backend service."""
        async with engine.connect() as conn:
            reg_req = RegisterWorkerRequest(
                hostname=self.hostname,
                pid=self.pid,
                concurrency=self.concurrency,
                metadata={"process": "worker_daemon"},
            )
            row = await register_worker_service(conn, reg_req)
            self.worker_id = row["id"]
            await conn.commit()
        logger.info(f"Worker registered successfully with ID: {self.worker_id} (concurrency={self.concurrency})")

    async def heartbeat_loop(self) -> None:
        """Periodic heartbeat background loop reporting telemetry."""
        while not self.stop_event.is_set():
            try:
                if self.worker_id:
                    active_count = len(self.active_tasks)
                    async with engine.connect() as conn:
                        await heartbeat_worker_service(
                            conn,
                            self.worker_id,
                            WorkerHeartbeatRequest(active_job_count=active_count),
                        )
                        await conn.commit()
            except Exception as exc:
                logger.warning(f"Error during heartbeat: {exc}")

            try:
                await asyncio.wait_for(
                    self.stop_event.wait(), timeout=settings.WORKER_HEARTBEAT_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass

    async def get_eligible_queue_ids(self) -> list[uuid.UUID]:
        """Fetch unpaused queue IDs assigned to this worker or available across projects."""
        if not self.worker_id:
            return []

        async with engine.connect() as conn:
            assigned_res = await conn.execute(
                select(worker_queues.c.queue_id).where(worker_queues.c.worker_id == self.worker_id)
            )
            assigned_ids = [r[0] for r in assigned_res.all()]

            if not assigned_ids:
                # Service all unpaused queues
                all_res = await conn.execute(select(queues.c.id).where(queues.c.is_paused == False))
                return [r[0] for r in all_res.all()]
            else:
                unpaused_res = await conn.execute(
                    select(queues.c.id).where(
                        queues.c.id.in_(assigned_ids), queues.c.is_paused == False
                    )
                )
                return [r[0] for r in unpaused_res.all()]

    async def claim_and_execute_loop(self) -> None:
        """Main polling loop claiming available jobs and dispatching async execution tasks."""
        logger.info("Worker ready. Starting claim loop...")

        while not self.stop_event.is_set():
            try:
                # Check concurrency capacity
                if self.semaphore.locked():
                    await asyncio.sleep(0.2)
                    continue

                eligible_queues = await self.get_eligible_queue_ids()
                claimed_any = False

                for q_id in eligible_queues:
                    if self.stop_event.is_set() or self.semaphore.locked():
                        break

                    claimed_job = None
                    async with engine.connect() as conn:
                        if self.worker_id:
                            claimed_job = await claim_job_atomic(conn, q_id, self.worker_id)
                            await conn.commit()

                    if claimed_job:
                        claimed_any = True
                        await self.semaphore.acquire()

                        async def _task_runner(job_dict: Dict[str, Any]):
                            try:
                                if self.worker_id:
                                    await process_claimed_job(job_dict, self.worker_id)
                            finally:
                                self.semaphore.release()

                        task = asyncio.create_task(_task_runner(claimed_job))
                        self.active_tasks.add(task)
                        task.add_done_callback(self.active_tasks.discard)

                if not claimed_any:
                    try:
                        await asyncio.wait_for(
                            self.stop_event.wait(), timeout=settings.WORKER_POLL_INTERVAL_SECONDS
                        )
                    except asyncio.TimeoutError:
                        pass

            except Exception as exc:
                logger.error(f"Error in worker claim loop: {exc}", exc_info=True)
                await asyncio.sleep(1.0)

    async def shutdown(self) -> None:
        """Gracefully shut down: stop new claims, wait for in-flight tasks, and deregister."""
        logger.info("Worker shutdown initiated. Stopping new job claims...")
        self.stop_event.set()

        if self.active_tasks:
            logger.info(f"Waiting for {len(self.active_tasks)} in-flight job(s) to finish...")
            await asyncio.gather(*self.active_tasks, return_exceptions=True)

        if self.worker_id:
            try:
                async with engine.connect() as conn:
                    await deregister_worker_service(conn, self.worker_id)
                    await conn.commit()
                logger.info(f"Worker {self.worker_id} deregistered cleanly.")
            except Exception as exc:
                logger.error(f"Error during worker deregistration: {exc}")

        await dispose_engine()
        logger.info("Worker process terminated cleanly.")


async def main() -> None:
    """Worker process entrypoint."""
    worker = WorkerProcess(concurrency=5)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, worker.stop_event.set)
        except NotImplementedError:
            pass

    try:
        await worker.register()
        heartbeat_task = asyncio.create_task(worker.heartbeat_loop())
        claim_task = asyncio.create_task(worker.claim_and_execute_loop())
        await asyncio.gather(heartbeat_task, claim_task)
    except asyncio.CancelledError:
        pass
    finally:
        await worker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
