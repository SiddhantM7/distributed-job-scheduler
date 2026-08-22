"""Jobs and Scheduled Jobs router."""
import uuid
from datetime import datetime
from typing import Any, Optional

from croniter import croniter
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import (
    job_executions,
    job_logs,
    jobs,
    organization_members,
    projects,
    queues,
    scheduled_jobs,
)
from app.schemas.jobs import (
    BatchJobResponse,
    CreateBatchJobRequest,
    CreateJobRequest,
    JobExecutionResponse,
    JobLogResponse,
    JobResponse,
    PaginatedJobs,
    ScheduledJobResponse,
    UpdateScheduledJobRequest,
)
from app.services.jobs import create_job_service, create_single_job

router = APIRouter(tags=["Jobs"])


# ── Auth & Existence Helpers ──────────────────────────────────────────────────

async def _get_queue_and_require_access(
    queue_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> dict:
    """Validate queue exists and user has access to its owning organization."""
    stmt = (
        select(queues.c.id, queues.c.project_id, projects.c.organization_id)
        .join(projects, projects.c.id == queues.c.project_id)
        .where(queues.c.id == queue_id)
    )
    res = await db.execute(stmt)
    row = res.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUEUE_NOT_FOUND", "message": "Queue not found", "details": {}},
        )

    mem_stmt = select(organization_members.c.role).where(
        organization_members.c.organization_id == row["organization_id"],
        organization_members.c.user_id == user_id,
    )
    mem_res = await db.execute(mem_stmt)
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this queue", "details": {}},
        )
    return dict(row)


async def _get_job_and_require_access(
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> dict:
    """Validate job exists and user has access to its owning organization."""
    stmt = (
        select(
            jobs,
            queues.c.project_id,
            projects.c.organization_id,
        )
        .join(queues, queues.c.id == jobs.c.queue_id)
        .join(projects, projects.c.id == queues.c.project_id)
        .where(jobs.c.id == job_id)
    )
    res = await db.execute(stmt)
    row = res.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "JOB_NOT_FOUND", "message": "Job not found", "details": {}},
        )

    mem_stmt = select(organization_members.c.role).where(
        organization_members.c.organization_id == row["organization_id"],
        organization_members.c.user_id == user_id,
    )
    mem_res = await db.execute(mem_stmt)
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this job", "details": {}},
        )
    return dict(row)


async def _get_scheduled_job_and_require_access(
    sched_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> dict:
    """Validate scheduled job exists and user has access to its owning organization."""
    stmt = (
        select(
            scheduled_jobs,
            queues.c.project_id,
            projects.c.organization_id,
        )
        .join(queues, queues.c.id == scheduled_jobs.c.queue_id)
        .join(projects, projects.c.id == queues.c.project_id)
        .where(scheduled_jobs.c.id == sched_id)
    )
    res = await db.execute(stmt)
    row = res.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SCHEDULED_JOB_NOT_FOUND", "message": "Scheduled job definition not found", "details": {}},
        )

    mem_stmt = select(organization_members.c.role).where(
        organization_members.c.organization_id == row["organization_id"],
        organization_members.c.user_id == user_id,
    )
    mem_res = await db.execute(mem_stmt)
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this scheduled job", "details": {}},
        )
    return dict(row)


# ── Job Endpoints ─────────────────────────────────────────────────────────────

@router.post("/queues/{queue_id}/jobs")
async def create_job(
    queue_id: uuid.UUID,
    body: CreateJobRequest,
    response: Response,
    idempotency_key_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> Any:
    """Create a job of any kind (immediate, delayed, scheduled, recurring, batch)."""
    await _get_queue_and_require_access(queue_id, current_user["id"], db)

    result_obj, is_new = await create_job_service(
        db=db,
        queue_id=queue_id,
        body=body,
        current_user_id=current_user["id"],
        header_idempotency_key=idempotency_key_header,
    )
    response.status_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
    return result_obj


@router.post("/queues/{queue_id}/jobs/batch", response_model=BatchJobResponse, status_code=201)
async def create_job_batch(
    queue_id: uuid.UUID,
    body: CreateBatchJobRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> BatchJobResponse:
    """Dedicated endpoint to create a batch of jobs sharing a batch_id."""
    await _get_queue_and_require_access(queue_id, current_user["id"], db)

    batch_id = uuid.uuid4()
    created_jobs = []
    for item in body.items:
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
    return BatchJobResponse(batch_id=batch_id, jobs=created_jobs)


@router.get("/queues/{queue_id}/jobs", response_model=PaginatedJobs)
async def list_queue_jobs(
    queue_id: uuid.UUID,
    job_status: Optional[str] = Query(default=None, alias="status"),
    job_type: Optional[str] = Query(default=None, alias="type"),
    batch_id: Optional[uuid.UUID] = Query(default=None),
    created_after: Optional[datetime] = Query(default=None),
    created_before: Optional[datetime] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> PaginatedJobs:
    """List jobs in a queue with filtering and pagination."""
    await _get_queue_and_require_access(queue_id, current_user["id"], db)

    base = select(jobs).where(jobs.c.queue_id == queue_id)

    if job_status:
        base = base.where(jobs.c.status == job_status)
    if job_type:
        base = base.where(jobs.c.type == job_type)
    if batch_id:
        base = base.where(jobs.c.batch_id == batch_id)
    if created_after:
        base = base.where(jobs.c.created_at >= created_after)
    if created_before:
        base = base.where(jobs.c.created_at <= created_before)

    # Count total
    total_res = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_res.scalar_one()

    # Query page
    items_res = await db.execute(
        base.order_by(jobs.c.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [JobResponse(**dict(r)) for r in items_res.mappings()]

    return PaginatedJobs(items=items, page=page, page_size=page_size, total=total)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> JobResponse:
    """Get job detail."""
    job_row = await _get_job_and_require_access(job_id, current_user["id"], db)
    return JobResponse(**job_row)


@router.get("/jobs/{job_id}/executions", response_model=list[JobExecutionResponse])
async def list_job_executions(
    job_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> list[JobExecutionResponse]:
    """Get full attempt history for a job."""
    await _get_job_and_require_access(job_id, current_user["id"], db)

    res = await db.execute(
        select(job_executions)
        .where(job_executions.c.job_id == job_id)
        .order_by(job_executions.c.attempt_number.asc())
    )
    return [JobExecutionResponse(**dict(r)) for r in res.mappings()]


@router.get("/jobs/{job_id}/executions/{execution_id}/logs", response_model=list[JobLogResponse])
async def list_execution_logs(
    job_id: uuid.UUID,
    execution_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> list[JobLogResponse]:
    """Get log lines for a single attempt."""
    await _get_job_and_require_access(job_id, current_user["id"], db)

    # Verify execution belongs to job
    exec_res = await db.execute(
        select(job_executions.c.id).where(
            job_executions.c.id == execution_id,
            job_executions.c.job_id == job_id,
        )
    )
    if exec_res.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "EXECUTION_NOT_FOUND", "message": "Execution not found for this job", "details": {}},
        )

    logs_res = await db.execute(
        select(job_logs)
        .where(job_logs.c.job_execution_id == execution_id)
        .order_by(job_logs.c.id.asc())
    )
    return [JobLogResponse(**dict(r)) for r in logs_res.mappings()]


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> JobResponse:
    """Cancel a job that hasn't started running (must be queued or scheduled)."""
    job_row = await _get_job_and_require_access(job_id, current_user["id"], db)

    if job_row["status"] not in ("queued", "scheduled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CANNOT_CANCEL",
                "message": f"Cannot cancel job with status '{job_row['status']}'",
                "details": {"current_status": job_row["status"]},
            },
        )

    res = await db.execute(
        update(jobs)
        .where(jobs.c.id == job_id)
        .values(status="cancelled")
        .returning(*jobs.c)
    )
    return JobResponse(**dict(res.mappings().one()))


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
async def retry_job(
    job_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> JobResponse:
    """Manually re-queue a failed or dead_letter job."""
    job_row = await _get_job_and_require_access(job_id, current_user["id"], db)

    if job_row["status"] not in ("failed", "dead_letter"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CANNOT_RETRY",
                "message": f"Only failed or dead_letter jobs can be retried. Current status is '{job_row['status']}'",
                "details": {"current_status": job_row["status"]},
            },
        )

    now = datetime.now()
    res = await db.execute(
        update(jobs)
        .where(jobs.c.id == job_id)
        .values(
            status="queued",
            attempt_count=0,
            run_at=now,
            claimed_by=None,
            claimed_at=None,
            started_at=None,
            completed_at=None,
            error=None,
            result=None,
        )
        .returning(*jobs.c)
    )
    return JobResponse(**dict(res.mappings().one()))


# ── Scheduled Jobs Endpoints ──────────────────────────────────────────────────

@router.get("/queues/{queue_id}/scheduled-jobs", response_model=list[ScheduledJobResponse])
async def list_scheduled_jobs(
    queue_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> list[ScheduledJobResponse]:
    """List scheduled and recurring job definitions for a queue."""
    await _get_queue_and_require_access(queue_id, current_user["id"], db)

    res = await db.execute(
        select(scheduled_jobs)
        .where(scheduled_jobs.c.queue_id == queue_id)
        .order_by(scheduled_jobs.c.created_at.desc())
    )
    return [ScheduledJobResponse(**dict(r)) for r in res.mappings()]


@router.patch("/scheduled-jobs/{id}", response_model=ScheduledJobResponse)
async def update_scheduled_job(
    id: uuid.UUID,
    body: UpdateScheduledJobRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> ScheduledJobResponse:
    """Update scheduled job definition."""
    sched_row = await _get_scheduled_job_and_require_access(
        id, current_user["id"], db, required_roles=("owner", "admin")
    )

    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.payload_template is not None:
        updates["payload_template"] = body.payload_template
    if body.is_active is not None:
        updates["is_active"] = body.is_active
    if body.cron_expression is not None:
        updates["cron_expression"] = body.cron_expression
        # Re-compute next_run_at if cron updated
        now = datetime.now()
        iter_cron = croniter(body.cron_expression, now)
        next_run = iter_cron.get_next(datetime)
        updates["next_run_at"] = next_run

    if not updates:
        return ScheduledJobResponse(**sched_row)

    res = await db.execute(
        update(scheduled_jobs)
        .where(scheduled_jobs.c.id == id)
        .values(**updates)
        .returning(*scheduled_jobs.c)
    )
    return ScheduledJobResponse(**dict(res.mappings().one()))


@router.delete("/scheduled-jobs/{id}", status_code=204)
async def delete_scheduled_job(
    id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> None:
    """Delete a scheduled job definition. Spawned jobs remain intact."""
    await _get_scheduled_job_and_require_access(
        id, current_user["id"], db, required_roles=("owner", "admin")
    )
    await db.execute(delete(scheduled_jobs).where(scheduled_jobs.c.id == id))
