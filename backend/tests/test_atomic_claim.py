"""Concurrency test for atomic job claiming with FOR UPDATE SKIP LOCKED.

Validates:
1. Two concurrent claim attempts cannot claim the same job.
2. 10 concurrent workers claiming 50 jobs claim every job exactly once with zero collisions.
3. Higher priority jobs are claimed before lower priority jobs.
4. Jobs with future run_at are skipped.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert

from app.models.tables import jobs, organizations, projects, queues, workers
from app.services.jobs import claim_job_atomic
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


async def _setup_test_queue():
    """Helper to create a fresh queue directly in DB."""
    async with test_engine.connect() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            insert(organizations).values(
                id=org_id,
                name="Claim Org",
                slug=f"claim-org-{uuid.uuid4().hex[:8]}",
            )
        )
        proj_id = uuid.uuid4()
        await conn.execute(
            insert(projects).values(
                id=proj_id,
                organization_id=org_id,
                name=f"Claim Proj-{uuid.uuid4().hex[:8]}",
            )
        )
        queue_id = uuid.uuid4()
        await conn.execute(
            insert(queues).values(
                id=queue_id,
                project_id=proj_id,
                name="claim-queue",
            )
        )
        await conn.commit()
        return queue_id


async def _create_worker_record(conn, hostname: str = "test-worker") -> uuid.UUID:
    """Insert a valid worker row into workers table to satisfy foreign keys."""
    worker_id = uuid.uuid4()
    await conn.execute(
        insert(workers).values(
            id=worker_id,
            hostname=hostname,
            pid=1234,
            status="idle",
            concurrency=5,
        )
    )
    return worker_id


async def test_atomic_claim_no_duplicates_under_concurrency():
    """50 jobs claimed by 10 concurrent worker tasks: exactly 50 distinct jobs claimed."""
    queue_id = await _setup_test_queue()
    num_jobs = 50
    num_workers = 10

    # 1. Insert 50 jobs and 10 worker records
    worker_ids = []
    async with test_engine.connect() as conn:
        for w in range(num_workers):
            w_id = await _create_worker_record(conn, hostname=f"worker-{w}")
            worker_ids.append(w_id)

        for i in range(num_jobs):
            await conn.execute(
                insert(jobs).values(
                    queue_id=queue_id,
                    type="concurrent_task",
                    payload={"index": i},
                    status="queued",
                    priority=i,
                )
            )
        await conn.commit()

    claimed_job_ids = []
    claimed_lock = asyncio.Lock()

    # 2. Worker coroutine that continuously claims until queue is drained
    async def worker_loop(w_idx: int):
        worker_id = worker_ids[w_idx]
        while True:
            # Each claim runs in its own connection/transaction
            async with test_engine.connect() as conn:
                claimed = await claim_job_atomic(conn, queue_id, worker_id)
                if claimed is None:
                    break
                async with claimed_lock:
                    claimed_job_ids.append((claimed["id"], worker_id))
                await conn.commit()

    # 3. Run 10 workers concurrently
    tasks = [asyncio.create_task(worker_loop(w)) for w in range(num_workers)]
    await asyncio.gather(*tasks)

    # 4. Assert: Exactly 50 jobs claimed, all IDs unique (zero duplicate executions)
    assert len(claimed_job_ids) == num_jobs
    unique_ids = set(job_id for job_id, _ in claimed_job_ids)
    assert len(unique_ids) == num_jobs


async def test_claim_respects_priority():
    """Higher priority jobs are claimed before lower priority jobs."""
    queue_id = await _setup_test_queue()

    async with test_engine.connect() as conn:
        worker_id = await _create_worker_record(conn, hostname="prio-worker")

        # Insert low priority first, then high priority
        await conn.execute(
            insert(jobs).values(
                queue_id=queue_id,
                type="low_prio",
                status="queued",
                priority=1,
            )
        )
        high_res = await conn.execute(
            insert(jobs).values(
                queue_id=queue_id,
                type="high_prio",
                status="queued",
                priority=100,
            ).returning(jobs.c.id)
        )
        high_id = high_res.scalar_one()
        await conn.commit()

    async with test_engine.connect() as conn:
        claimed = await claim_job_atomic(conn, queue_id, worker_id)
        await conn.commit()

    assert claimed is not None
    assert claimed["id"] == high_id
    assert claimed["priority"] == 100


async def test_claim_skips_future_jobs():
    """Jobs scheduled in the future are not claimed."""
    queue_id = await _setup_test_queue()

    async with test_engine.connect() as conn:
        worker_id = await _create_worker_record(conn, hostname="future-worker")
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        await conn.execute(
            insert(jobs).values(
                queue_id=queue_id,
                type="future_job",
                status="queued",
                run_at=future_time,
            )
        )
        await conn.commit()

    async with test_engine.connect() as conn:
        claimed = await claim_job_atomic(conn, queue_id, worker_id)
        await conn.commit()

    assert claimed is None
