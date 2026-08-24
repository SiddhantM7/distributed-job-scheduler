"""pytest tests for Worker and Scheduler runtime loops."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select

from app.models.tables import (
    dead_letter_queue,
    job_executions,
    jobs,
    organizations,
    projects,
    queues,
    retry_policies,
    scheduled_jobs,
    workers,
)
from scheduler.main import run_scheduler_tick
from tests.conftest import test_engine
from workers.main import WorkerProcess, process_claimed_job

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _setup_runtime_fixture() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Helper to create Org, Project, and Queue."""
    async with test_engine.connect() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            insert(organizations).values(
                id=org_id,
                name="Runtime Org",
                slug=f"rt-org-{uuid.uuid4().hex[:8]}",
            )
        )
        proj_id = uuid.uuid4()
        await conn.execute(
            insert(projects).values(
                id=proj_id,
                organization_id=org_id,
                name=f"RT Proj-{uuid.uuid4().hex[:8]}",
            )
        )
        queue_id = uuid.uuid4()
        await conn.execute(
            insert(queues).values(
                id=queue_id,
                project_id=proj_id,
                name="rt-queue",
                max_concurrency=5,
            )
        )
        await conn.commit()
    return org_id, proj_id, queue_id


# ─── Tests ────────────────────────────────────────────────────────────────────

async def test_worker_process_success():
    """Worker process executes job handler and transitions job to completed with execution audit."""
    _, _, queue_id = await _setup_runtime_fixture()

    worker = WorkerProcess(concurrency=2)
    await worker.register()
    assert worker.worker_id is not None

    # Insert a job
    async with test_engine.connect() as conn:
        j_id = (
            await conn.execute(
                insert(jobs)
                .values(
                    queue_id=queue_id,
                    type="sample_task",
                    payload={"data": "hello"},
                    status="claimed",
                    claimed_by=worker.worker_id,
                    attempt_count=0,
                    max_attempts=3,
                )
                .returning(jobs.c.id)
            )
        ).scalar_one()
        await conn.commit()

        job_dict = dict(
            (await conn.execute(select(jobs).where(jobs.c.id == j_id))).mappings().one()
        )

    # Process job
    await process_claimed_job(job_dict, worker.worker_id)

    # Verify job marked completed
    async with test_engine.connect() as conn:
        j_res = await conn.execute(select(jobs).where(jobs.c.id == j_id))
        j_row = j_res.mappings().one()
        assert j_row["status"] == "completed"
        assert j_row["attempt_count"] == 1
        assert j_row["completed_at"] is not None

        # Verify job_executions record
        exec_res = await conn.execute(
            select(job_executions).where(job_executions.c.job_id == j_id)
        )
        exec_row = exec_res.mappings().one()
        assert exec_row["status"] == "completed"
        assert exec_row["attempt_number"] == 1
        assert exec_row["duration_ms"] is not None

    await worker.shutdown()


async def test_worker_process_retry_and_dlq_exhaustion():
    """Worker executes failing job, schedules retry, and moves to DLQ when max_attempts reached."""
    _, _, queue_id = await _setup_runtime_fixture()

    worker = WorkerProcess(concurrency=2)
    await worker.register()
    assert worker.worker_id is not None

    # Insert failing job (max_attempts = 2)
    async with test_engine.connect() as conn:
        j_id = (
            await conn.execute(
                insert(jobs)
                .values(
                    queue_id=queue_id,
                    type="failing_task",
                    payload={"force_failure": True, "error": "Gateway Timeout 504"},
                    status="claimed",
                    claimed_by=worker.worker_id,
                    attempt_count=0,
                    max_attempts=2,
                )
                .returning(jobs.c.id)
            )
        ).scalar_one()
        await conn.commit()

        job_dict = dict(
            (await conn.execute(select(jobs).where(jobs.c.id == j_id))).mappings().one()
        )

    # Attempt 1: Should fail and be re-queued with retry delay
    await process_claimed_job(job_dict, worker.worker_id)

    async with test_engine.connect() as conn:
        j_res = await conn.execute(select(jobs).where(jobs.c.id == j_id))
        j_row = j_res.mappings().one()
        assert j_row["status"] == "queued"
        assert j_row["attempt_count"] == 1
        assert j_row["error"] == "Gateway Timeout 504"
        assert j_row["claimed_by"] is None

        # Attempt 2 input
        job_dict_2 = dict(j_row)
        job_dict_2["status"] = "claimed"
        job_dict_2["claimed_by"] = worker.worker_id

    # Attempt 2: Max attempts (2) reached -> Should move to DLQ
    await process_claimed_job(job_dict_2, worker.worker_id)

    async with test_engine.connect() as conn:
        j_res = await conn.execute(select(jobs).where(jobs.c.id == j_id))
        j_row = j_res.mappings().one()
        assert j_row["status"] == "dead_letter"
        assert j_row["attempt_count"] == 2

        # Verify entry in dead_letter_queue table
        dlq_res = await conn.execute(
            select(dead_letter_queue).where(dead_letter_queue.c.job_id == j_id)
        )
        dlq_row = dlq_res.mappings().one()
        assert dlq_row["resolved"] is False
        assert "Gateway Timeout 504" in dlq_row["last_error"]

    await worker.shutdown()


async def test_scheduler_tick_cycle():
    """Scheduler tick promotes delayed jobs and scheduled definitions."""
    _, proj_id, queue_id = await _setup_runtime_fixture()

    past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with test_engine.connect() as conn:
        # 1. Delayed job that is due
        d_id = (
            await conn.execute(
                insert(jobs)
                .values(
                    queue_id=queue_id,
                    type="delayed_due",
                    status="scheduled",
                    run_at=past_time,
                )
                .returning(jobs.c.id)
            )
        ).scalar_one()

        # 2. Scheduled recurring job that is due
        s_id = (
            await conn.execute(
                insert(scheduled_jobs)
                .values(
                    queue_id=queue_id,
                    name="cron_due",
                    job_type="cron_task",
                    cron_expression="*/5 * * * *",
                    is_recurring=True,
                    is_active=True,
                    next_run_at=past_time,
                )
                .returning(scheduled_jobs.c.id)
            )
        ).scalar_one()
        await conn.commit()

    # Run scheduler tick
    await run_scheduler_tick()

    async with test_engine.connect() as conn:
        # Delayed job should now be queued
        d_res = await conn.execute(select(jobs).where(jobs.c.id == d_id))
        assert d_res.mappings().one()["status"] == "queued"

        # Scheduled definition should have spawned a new job and advanced next_run_at
        spawned_res = await conn.execute(
            select(jobs).where(jobs.c.scheduled_job_id == s_id)
        )
        assert len(spawned_res.all()) == 1

        sched_res = await conn.execute(
            select(scheduled_jobs).where(scheduled_jobs.c.id == s_id)
        )
        assert sched_res.mappings().one()["next_run_at"] > datetime.now(timezone.utc)
