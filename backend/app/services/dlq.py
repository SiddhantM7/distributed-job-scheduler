"""Business logic for Dead Letter Queue: moving exhausted jobs, retrying, and resolving."""
import uuid
from datetime import datetime, timezone
from typing import Tuple

from fastapi import HTTPException, status
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.tables import dead_letter_queue, jobs
from app.services.jobs import create_single_job


async def move_job_to_dlq(
    db: AsyncConnection,
    job_id: uuid.UUID,
    reason: str,
    last_error: str | None = None,
) -> dict:
    """Move an exhausted or failed job to the Dead Letter Queue."""
    j_res = await db.execute(select(jobs).where(jobs.c.id == job_id))
    job = j_res.mappings().first()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "Job not found", "details": {}},
        )

    now = datetime.now(tz=timezone.utc)

    # 1. Update job status to dead_letter
    await db.execute(
        update(jobs)
        .where(jobs.c.id == job_id)
        .values(
            status="dead_letter",
            error=last_error or job["error"],
            completed_at=now,
        )
    )

    # 2. Insert into dead_letter_queue
    dlq_res = await db.execute(
        insert(dead_letter_queue)
        .values(
            job_id=job_id,
            queue_id=job["queue_id"],
            reason=reason,
            last_error=last_error or job["error"],
            payload_snapshot=job["payload"],
            failed_attempt_count=job["attempt_count"],
            moved_at=now,
            resolved=False,
        )
        .returning(*dead_letter_queue.c)
    )
    return dict(dlq_res.mappings().one())


async def retry_dlq_entry_service(
    db: AsyncConnection,
    dlq_id: uuid.UUID,
) -> Tuple[dict, dict]:
    """Re-submit dead letter job as a fresh job and mark DLQ resolved."""
    dlq_res = await db.execute(
        select(dead_letter_queue).where(dead_letter_queue.c.id == dlq_id)
    )
    dlq_row = dlq_res.mappings().first()
    if dlq_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DLQ_ENTRY_NOT_FOUND", "message": "DLQ entry not found", "details": {}},
        )

    # Fetch original job to get job type
    j_res = await db.execute(select(jobs).where(jobs.c.id == dlq_row["job_id"]))
    job_row = j_res.mappings().first()
    job_type = job_row["type"] if job_row else "retried_dlq_job"

    now = datetime.now(tz=timezone.utc)

    # 1. Create fresh job from payload_snapshot
    new_job, _ = await create_single_job(
        db=db,
        queue_id=dlq_row["queue_id"],
        job_type=job_type,
        payload=dlq_row["payload_snapshot"],
        kind="immediate",
    )

    # 2. Mark DLQ entry resolved
    upd_dlq = await db.execute(
        update(dead_letter_queue)
        .where(dead_letter_queue.c.id == dlq_id)
        .values(
            resolved=True,
            resolved_at=now,
        )
        .returning(*dead_letter_queue.c)
    )
    updated_dlq = dict(upd_dlq.mappings().one())

    return new_job, updated_dlq


async def resolve_dlq_entry_service(
    db: AsyncConnection,
    dlq_id: uuid.UUID,
) -> dict:
    """Mark a DLQ entry resolved without retrying."""
    dlq_res = await db.execute(
        select(dead_letter_queue).where(dead_letter_queue.c.id == dlq_id)
    )
    dlq_row = dlq_res.mappings().first()
    if dlq_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DLQ_ENTRY_NOT_FOUND", "message": "DLQ entry not found", "details": {}},
        )

    now = datetime.now(tz=timezone.utc)

    upd_dlq = await db.execute(
        update(dead_letter_queue)
        .where(dead_letter_queue.c.id == dlq_id)
        .values(
            resolved=True,
            resolved_at=now,
        )
        .returning(*dead_letter_queue.c)
    )
    return dict(upd_dlq.mappings().one())
