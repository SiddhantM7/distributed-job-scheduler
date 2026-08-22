"""Business logic for worker registration, heartbeats, deregistration, and stale worker recovery."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.tables import (
    job_executions,
    jobs,
    worker_heartbeats,
    worker_queues,
    workers,
)
from app.schemas.workers import RegisterWorkerRequest, WorkerHeartbeatRequest


async def register_worker_service(
    db: AsyncConnection,
    body: RegisterWorkerRequest,
) -> dict:
    """Register a new worker process."""
    res = await db.execute(
        insert(workers)
        .values(
            hostname=body.hostname,
            pid=body.pid,
            status="idle",
            concurrency=body.concurrency,
            metadata=body.metadata,
        )
        .returning(*workers.c)
    )
    row = dict(res.mappings().one())
    row["assigned_queue_ids"] = []
    row["active_job_count"] = 0
    return row


async def heartbeat_worker_service(
    db: AsyncConnection,
    worker_id: uuid.UUID,
    body: WorkerHeartbeatRequest,
) -> dict:
    """Process heartbeat from worker and record telemetry."""
    w_res = await db.execute(select(workers).where(workers.c.id == worker_id))
    w_row = w_res.mappings().first()
    if w_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKER_NOT_FOUND", "message": "Worker not found", "details": {}},
        )

    now = datetime.now(tz=timezone.utc)

    # Determine status: don't overwrite 'draining' or 'offline' if already set
    new_status = w_row["status"]
    if w_row["status"] not in ("draining", "offline"):
        new_status = "busy" if body.active_job_count >= w_row["concurrency"] else "idle"

    # Update worker pointer
    upd_res = await db.execute(
        update(workers)
        .where(workers.c.id == worker_id)
        .values(
            last_heartbeat_at=now,
            status=new_status,
        )
        .returning(*workers.c)
    )
    updated_worker = dict(upd_res.mappings().one())

    # Insert time-series heartbeat record
    await db.execute(
        insert(worker_heartbeats).values(
            worker_id=worker_id,
            heartbeat_at=now,
            active_job_count=body.active_job_count,
            cpu_pct=body.cpu_pct,
            mem_mb=body.mem_mb,
        )
    )

    # Get assigned queue IDs
    q_res = await db.execute(
        select(worker_queues.c.queue_id).where(worker_queues.c.worker_id == worker_id)
    )
    updated_worker["assigned_queue_ids"] = [r[0] for r in q_res.all()]
    updated_worker["active_job_count"] = body.active_job_count
    return updated_worker


async def deregister_worker_service(
    db: AsyncConnection,
    worker_id: uuid.UUID,
) -> dict:
    """Gracefully deregister worker, setting status='offline' and releasing any claimed jobs."""
    w_res = await db.execute(select(workers).where(workers.c.id == worker_id))
    w_row = w_res.mappings().first()
    if w_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKER_NOT_FOUND", "message": "Worker not found", "details": {}},
        )

    # Mark worker offline
    upd_res = await db.execute(
        update(workers)
        .where(workers.c.id == worker_id)
        .values(status="offline")
        .returning(*workers.c)
    )
    worker_data = dict(upd_res.mappings().one())

    # Release any claimed/running jobs back to queued
    await db.execute(
        update(jobs)
        .where(
            jobs.c.claimed_by == worker_id,
            jobs.c.status.in_(("claimed", "running")),
        )
        .values(
            status="queued",
            claimed_by=None,
            claimed_at=None,
        )
    )

    # Mark active executions as failed
    await db.execute(
        update(job_executions)
        .where(
            job_executions.c.worker_id == worker_id,
            job_executions.c.status == "running",
        )
        .values(
            status="failed",
            error="Worker deregistered / shutdown",
            completed_at=datetime.now(tz=timezone.utc),
        )
    )

    # Assigned queues
    q_res = await db.execute(
        select(worker_queues.c.queue_id).where(worker_queues.c.worker_id == worker_id)
    )
    worker_data["assigned_queue_ids"] = [r[0] for r in q_res.all()]
    worker_data["active_job_count"] = 0
    return worker_data


async def sweep_stale_workers(
    db: AsyncConnection,
    timeout_seconds: int = 60,
) -> int:
    """Detect dead/stale workers whose last_heartbeat_at > timeout_seconds.

    Sets status to 'offline' and recovers any stranded in-flight jobs.
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(seconds=timeout_seconds)

    stale_query = select(workers.c.id).where(
        workers.c.status != "offline",
        workers.c.last_heartbeat_at < cutoff,
    )
    stale_res = await db.execute(stale_query)
    stale_worker_ids = [r[0] for r in stale_res.all()]

    if not stale_worker_ids:
        return 0

    # 1. Mark stale workers offline
    await db.execute(
        update(workers)
        .where(workers.c.id.in_(stale_worker_ids))
        .values(status="offline")
    )

    # 2. Release in-flight jobs back to queued
    await db.execute(
        update(jobs)
        .where(
            jobs.c.claimed_by.in_(stale_worker_ids),
            jobs.c.status.in_(("claimed", "running")),
        )
        .values(
            status="queued",
            claimed_by=None,
            claimed_at=None,
        )
    )

    # 3. Mark running executions as failed
    await db.execute(
        update(job_executions)
        .where(
            job_executions.c.worker_id.in_(stale_worker_ids),
            job_executions.c.status == "running",
        )
        .values(
            status="failed",
            error="Worker heartbeat timeout / offline",
            completed_at=datetime.now(tz=timezone.utc),
        )
    )

    return len(stale_worker_ids)


async def get_worker_details_service(
    db: AsyncConnection,
    worker_id: uuid.UUID,
) -> dict:
    """Retrieve full worker detail including assigned queues and active job count."""
    res = await db.execute(select(workers).where(workers.c.id == worker_id))
    w_row = res.mappings().first()
    if w_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKER_NOT_FOUND", "message": "Worker not found", "details": {}},
        )

    data = dict(w_row)

    # Get active job count
    active_count_res = await db.execute(
        select(func.count())
        .select_from(jobs)
        .where(
            jobs.c.claimed_by == worker_id,
            jobs.c.status.in_(("claimed", "running")),
        )
    )
    data["active_job_count"] = active_count_res.scalar_one()

    # Get assigned queues
    q_res = await db.execute(
        select(worker_queues.c.queue_id).where(worker_queues.c.worker_id == worker_id)
    )
    data["assigned_queue_ids"] = [r[0] for r in q_res.all()]
    return data
