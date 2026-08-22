"""Business logic for job creation, idempotency, claiming, and scheduled promotions."""
import uuid
from datetime import datetime, timezone
from typing import Any, Tuple

from croniter import croniter
from fastapi import HTTPException, status
from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.tables import (
    jobs,
    queues,
    retry_policies,
    scheduled_jobs,
)
from app.schemas.jobs import CreateJobRequest, JobResponse, ScheduledJobResponse, BatchJobResponse


async def resolve_max_attempts(
    db: AsyncConnection,
    retry_policy_id: uuid.UUID | None,
    queue_id: uuid.UUID,
) -> int:
    """Resolve max_attempts from retry_policy or queue default, falling back to 5."""
    target_policy_id = retry_policy_id
    if target_policy_id is None:
        q_res = await db.execute(
            select(queues.c.default_retry_policy_id).where(queues.c.id == queue_id)
        )
        q_row = q_res.first()
        if q_row and q_row[0] is not None:
            target_policy_id = q_row[0]

    if target_policy_id is not None:
        rp_res = await db.execute(
            select(retry_policies.c.max_attempts).where(retry_policies.c.id == target_policy_id)
        )
        rp_row = rp_res.first()
        if rp_row and rp_row[0] is not None:
            return rp_row[0]

    return 5


async def create_single_job(
    db: AsyncConnection,
    queue_id: uuid.UUID,
    job_type: str,
    payload: dict[str, Any],
    kind: str,
    priority: int = 0,
    retry_policy_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    batch_id: uuid.UUID | None = None,
    scheduled_job_id: uuid.UUID | None = None,
) -> Tuple[dict, bool]:
    """Insert a job row handling idempotency. Returns (row_dict, is_new)."""
    now = datetime.now(tz=timezone.utc)
    max_attempts = await resolve_max_attempts(db, retry_policy_id, queue_id)

    # Check for existing idempotent submission
    if idempotency_key:
        existing = await db.execute(
            select(jobs).where(
                jobs.c.queue_id == queue_id,
                jobs.c.idempotency_key == idempotency_key,
            )
        )
        existing_row = existing.mappings().first()
        if existing_row is not None:
            # Check for payload conflict
            if existing_row["type"] != job_type or existing_row["payload"] != payload:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "IDEMPOTENCY_CONFLICT",
                        "message": "A job with this idempotency key already exists with different payload or type",
                        "details": {"job_id": str(existing_row["id"])},
                    },
                )
            return dict(existing_row), False

    # Determine status & run_at
    if kind == "delayed":
        job_status = "scheduled"
        effective_run_at = run_at or now
    else:
        job_status = "queued"
        effective_run_at = now

    result = await db.execute(
        insert(jobs)
        .values(
            queue_id=queue_id,
            scheduled_job_id=scheduled_job_id,
            retry_policy_id=retry_policy_id,
            batch_id=batch_id,
            type=job_type,
            payload=payload,
            kind=kind,
            status=job_status,
            priority=priority,
            run_at=effective_run_at,
            attempt_count=0,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
        )
        .returning(*jobs.c)
    )
    return dict(result.mappings().one()), True


async def create_job_service(
    db: AsyncConnection,
    queue_id: uuid.UUID,
    body: CreateJobRequest,
    current_user_id: uuid.UUID | None,
    header_idempotency_key: str | None = None,
) -> Tuple[Any, bool]:
    """High level service dispatching job creation across all 5 kinds."""
    idempotency_key = body.idempotency_key or header_idempotency_key
    now = datetime.now(tz=timezone.utc)

    # 1. Immediate
    if body.kind == "immediate":
        row, is_new = await create_single_job(
            db=db,
            queue_id=queue_id,
            job_type=body.type,
            payload=body.payload,
            kind="immediate",
            priority=body.priority,
            retry_policy_id=body.retry_policy_id,
            idempotency_key=idempotency_key,
        )
        return JobResponse(**row), is_new

    # 2. Delayed
    elif body.kind == "delayed":
        row, is_new = await create_single_job(
            db=db,
            queue_id=queue_id,
            job_type=body.type,
            payload=body.payload,
            kind="delayed",
            priority=body.priority,
            retry_policy_id=body.retry_policy_id,
            idempotency_key=idempotency_key,
            run_at=body.run_at,
        )
        return JobResponse(**row), is_new

    # 3. Scheduled (One-off via scheduled_jobs)
    elif body.kind == "scheduled":
        res = await db.execute(
            insert(scheduled_jobs)
            .values(
                queue_id=queue_id,
                retry_policy_id=body.retry_policy_id,
                name=body.type,
                job_type=body.type,
                payload_template=body.payload,
                cron_expression=None,
                is_recurring=False,
                is_active=True,
                next_run_at=body.scheduled_for,
                created_by=current_user_id,
            )
            .returning(*scheduled_jobs.c)
        )
        row = dict(res.mappings().one())
        return ScheduledJobResponse(**row), True

    # 4. Recurring (Cron via scheduled_jobs)
    elif body.kind == "recurring":
        iter_cron = croniter(body.cron_expression, now)
        next_run = iter_cron.get_next(datetime)
        if next_run.tzinfo is None:
            next_run = next_run.replace(tzinfo=timezone.utc)

        res = await db.execute(
            insert(scheduled_jobs)
            .values(
                queue_id=queue_id,
                retry_policy_id=body.retry_policy_id,
                name=body.type,
                job_type=body.type,
                payload_template=body.payload,
                cron_expression=body.cron_expression,
                is_recurring=True,
                is_active=True,
                next_run_at=next_run,
                created_by=current_user_id,
            )
            .returning(*scheduled_jobs.c)
        )
        row = dict(res.mappings().one())
        return ScheduledJobResponse(**row), True

    # 5. Batch
    elif body.kind == "batch":
        batch_id = uuid.uuid4()
        created_jobs = []
        for item in body.items or []:
            row, _ = await create_single_job(
                db=db,
                queue_id=queue_id,
                job_type=body.type,
                payload=item.payload,
                kind="batch",
                priority=item.priority,
                retry_policy_id=body.retry_policy_id,
                idempotency_key=item.idempotency_key,
                batch_id=batch_id,
            )
            created_jobs.append(JobResponse(**row))
        return BatchJobResponse(batch_id=batch_id, jobs=created_jobs), True


async def claim_job_atomic(
    db: AsyncConnection,
    queue_id: uuid.UUID,
    worker_id: uuid.UUID,
) -> dict | None:
    """Atomic claim query using FOR UPDATE SKIP LOCKED.

    Guarantees no two workers can claim the same job.
    """
    subquery = (
        select(jobs.c.id)
        .where(
            jobs.c.queue_id == queue_id,
            jobs.c.status == "queued",
            jobs.c.run_at <= func.now(),
        )
        .order_by(jobs.c.priority.desc(), jobs.c.run_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
        .scalar_subquery()
    )

    stmt = (
        update(jobs)
        .where(jobs.c.id == subquery)
        .values(
            status="claimed",
            claimed_by=worker_id,
            claimed_at=func.now(),
        )
        .returning(*jobs.c)
    )

    result = await db.execute(stmt)
    row = result.mappings().first()
    return dict(row) if row else None


async def promote_delayed_jobs(db: AsyncConnection) -> int:
    """Promote delayed jobs (status='scheduled' and run_at <= now()) to 'queued'."""
    stmt = (
        update(jobs)
        .where(
            jobs.c.status == "scheduled",
            jobs.c.run_at <= func.now(),
        )
        .values(status="queued")
        .returning(jobs.c.id)
    )
    res = await db.execute(stmt)
    return len(res.all())


async def promote_scheduled_jobs(db: AsyncConnection) -> int:
    """Spawn jobs from due scheduled_jobs definitions and advance/deactivate schedules."""
    now = datetime.now(tz=timezone.utc)
    due_stmt = select(scheduled_jobs).where(
        scheduled_jobs.c.is_active == True,  # noqa: E712
        scheduled_jobs.c.next_run_at <= now,
    )
    due_res = await db.execute(due_stmt)
    due_schedules = due_res.mappings().all()

    promoted_count = 0
    for sched in due_schedules:
        # Spawn job instance
        await create_single_job(
            db=db,
            queue_id=sched["queue_id"],
            job_type=sched["job_type"],
            payload=sched["payload_template"],
            kind="scheduled" if not sched["is_recurring"] else "recurring",
            retry_policy_id=sched["retry_policy_id"],
            scheduled_job_id=sched["id"],
        )
        promoted_count += 1

        # Advance or deactivate schedule
        if sched["is_recurring"] and sched["cron_expression"]:
            iter_cron = croniter(sched["cron_expression"], now)
            next_run = iter_cron.get_next(datetime)
            if next_run.tzinfo is None:
                next_run = next_run.replace(tzinfo=timezone.utc)

            await db.execute(
                update(scheduled_jobs)
                .where(scheduled_jobs.c.id == sched["id"])
                .values(next_run_at=next_run, last_run_at=now)
            )
        else:
            await db.execute(
                update(scheduled_jobs)
                .where(scheduled_jobs.c.id == sched["id"])
                .values(is_active=False, last_run_at=now)
            )

    return promoted_count
