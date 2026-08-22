"""Queues router: full queue CRUD, pause/resume, stats."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, insert, update, delete, func, case, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import (
    queues,
    projects,
    organization_members,
    jobs,
    retry_policies,
)
from app.schemas.queues import (
    CreateQueueRequest,
    UpdateQueueRequest,
    QueueResponse,
    QueueStatsLive,
    QueueThroughputStats,
)

router = APIRouter(tags=["Queues"])

# ── Non-terminal statuses that block queue deletion ───────────────────────────
_NON_TERMINAL = ("queued", "scheduled", "claimed", "running")


# ── Authorization helpers ─────────────────────────────────────────────────────

async def _get_project_org(project_id: uuid.UUID, db: AsyncConnection) -> uuid.UUID:
    """Return the organization_id for a project, or raise 404."""
    result = await db.execute(
        select(projects.c.organization_id).where(projects.c.id == project_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found", "details": {}},
        )
    return row[0]


async def _require_project_access(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> None:
    """Assert user is a member of the project's org with one of required_roles."""
    org_id = await _get_project_org(project_id, db)
    result = await db.execute(
        select(organization_members.c.role).where(
            organization_members.c.organization_id == org_id,
            organization_members.c.user_id == user_id,
        )
    )
    row = result.first()
    if row is None or row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this project", "details": {}},
        )


async def _get_queue_or_404(queue_id: uuid.UUID, db: AsyncConnection) -> dict:
    """Return a queue row dict or raise 404."""
    result = await db.execute(select(queues).where(queues.c.id == queue_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUEUE_NOT_FOUND", "message": "Queue not found", "details": {}},
        )
    return dict(row)


async def _require_queue_access(
    queue: dict,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> None:
    """Assert user has access to the queue's project."""
    await _require_project_access(queue["project_id"], user_id, db, required_roles)


async def _live_stats(queue_id: uuid.UUID, db: AsyncConnection) -> QueueStatsLive:
    """Compute live job counts for a queue by status bucket."""
    result = await db.execute(
        select(jobs.c.status, func.count().label("cnt"))
        .where(jobs.c.queue_id == queue_id)
        .group_by(jobs.c.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in result}
    return QueueStatsLive(
        queued=counts.get("queued", 0),
        scheduled=counts.get("scheduled", 0),
        claimed=counts.get("claimed", 0),
        running=counts.get("running", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        dead_letter=counts.get("dead_letter", 0),
        cancelled=counts.get("cancelled", 0),
    )


def _queue_row_to_response(row: dict, stats: QueueStatsLive | None = None) -> QueueResponse:
    """Convert a queue DB row to a QueueResponse, optionally attaching stats."""
    return QueueResponse(
        id=row["id"],
        project_id=row["project_id"],
        default_retry_policy_id=row.get("default_retry_policy_id"),
        name=row["name"],
        priority=row["priority"],
        max_concurrency=row["max_concurrency"],
        is_paused=row["is_paused"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        stats=stats,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/projects/{project_id}/queues", response_model=QueueResponse, status_code=201)
async def create_queue(
    project_id: uuid.UUID,
    body: CreateQueueRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> QueueResponse:
    """Create a queue under a project.

    Requires org membership. If default_retry_policy_id is supplied it must
    belong to the same project.
    """
    await _require_project_access(project_id, current_user["id"], db)

    # Validate retry policy belongs to same project
    if body.default_retry_policy_id is not None:
        rp_result = await db.execute(
            select(retry_policies.c.id).where(
                retry_policies.c.id == body.default_retry_policy_id,
                retry_policies.c.project_id == project_id,
            )
        )
        if rp_result.first() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_RETRY_POLICY",
                    "message": "Retry policy not found in this project",
                    "details": {},
                },
            )

    # Check name uniqueness within project
    name_check = await db.execute(
        select(queues.c.id).where(
            queues.c.project_id == project_id,
            queues.c.name == body.name,
        )
    )
    if name_check.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "QUEUE_NAME_TAKEN", "message": "A queue with this name already exists in the project", "details": {}},
        )

    result = await db.execute(
        insert(queues)
        .values(
            project_id=project_id,
            name=body.name,
            priority=body.priority,
            max_concurrency=body.max_concurrency,
            default_retry_policy_id=body.default_retry_policy_id,
        )
        .returning(*queues.c)
    )
    row = dict(result.mappings().one())
    return _queue_row_to_response(row)


@router.get("/projects/{project_id}/queues", response_model=list[QueueResponse])
async def list_queues(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> list[QueueResponse]:
    """List all queues for a project."""
    await _require_project_access(project_id, current_user["id"], db)

    result = await db.execute(
        select(queues)
        .where(queues.c.project_id == project_id)
        .order_by(queues.c.name)
    )
    return [_queue_row_to_response(dict(row)) for row in result.mappings()]


@router.get("/queues/{queue_id}", response_model=QueueResponse)
async def get_queue(
    queue_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> QueueResponse:
    """Queue detail including live job-count stats by status."""
    queue = await _get_queue_or_404(queue_id, db)
    await _require_queue_access(queue, current_user["id"], db)
    stats = await _live_stats(queue_id, db)
    return _queue_row_to_response(queue, stats)


@router.patch("/queues/{queue_id}", response_model=QueueResponse)
async def update_queue(
    queue_id: uuid.UUID,
    body: UpdateQueueRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> QueueResponse:
    """Update queue priority, max_concurrency, or default retry policy.

    Requires owner or admin role.
    """
    queue = await _get_queue_or_404(queue_id, db)
    await _require_queue_access(queue, current_user["id"], db, required_roles=("owner", "admin"))

    updates: dict = {}
    if body.priority is not None:
        updates["priority"] = body.priority
    if body.max_concurrency is not None:
        updates["max_concurrency"] = body.max_concurrency
    if body.default_retry_policy_id is not None:
        # Validate it belongs to the same project
        rp_result = await db.execute(
            select(retry_policies.c.id).where(
                retry_policies.c.id == body.default_retry_policy_id,
                retry_policies.c.project_id == queue["project_id"],
            )
        )
        if rp_result.first() is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_RETRY_POLICY",
                    "message": "Retry policy not found in this project",
                    "details": {},
                },
            )
        updates["default_retry_policy_id"] = body.default_retry_policy_id

    if not updates:
        return _queue_row_to_response(queue)

    result = await db.execute(
        update(queues)
        .where(queues.c.id == queue_id)
        .values(**updates)
        .returning(*queues.c)
    )
    return _queue_row_to_response(dict(result.mappings().one()))


@router.post("/queues/{queue_id}/pause", response_model=QueueResponse)
async def pause_queue(
    queue_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> QueueResponse:
    """Pause a queue: no new jobs will be claimed while paused."""
    queue = await _get_queue_or_404(queue_id, db)
    await _require_queue_access(queue, current_user["id"], db, required_roles=("owner", "admin"))

    result = await db.execute(
        update(queues)
        .where(queues.c.id == queue_id)
        .values(is_paused=True)
        .returning(*queues.c)
    )
    return _queue_row_to_response(dict(result.mappings().one()))


@router.post("/queues/{queue_id}/resume", response_model=QueueResponse)
async def resume_queue(
    queue_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> QueueResponse:
    """Resume a paused queue."""
    queue = await _get_queue_or_404(queue_id, db)
    await _require_queue_access(queue, current_user["id"], db, required_roles=("owner", "admin"))

    result = await db.execute(
        update(queues)
        .where(queues.c.id == queue_id)
        .values(is_paused=False)
        .returning(*queues.c)
    )
    return _queue_row_to_response(dict(result.mappings().one()))


@router.get("/queues/{queue_id}/stats", response_model=QueueThroughputStats)
async def queue_stats(
    queue_id: uuid.UUID,
    window: str = Query(default="1h", description="Time window: 1h, 24h, 7d"),
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> QueueThroughputStats:
    """Throughput and health metrics for a queue over a time window."""
    queue = await _get_queue_or_404(queue_id, db)
    await _require_queue_access(queue, current_user["id"], db)

    # Parse window string into a timedelta
    _window_map: dict[str, timedelta] = {
        "1h": timedelta(hours=1),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }
    if window not in _window_map:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_WINDOW", "message": "window must be one of: 1h, 24h, 7d", "details": {}},
        )
    delta = _window_map[window]
    since = datetime.now(tz=timezone.utc) - delta
    minutes_in_window = delta.total_seconds() / 60.0

    # Aggregate completed and failed jobs in the window using completed_at
    from app.models.tables import job_executions  # local to avoid top-level circular

    result = await db.execute(
        select(
            func.count(case((job_executions.c.status == "completed", 1))).label("completed"),
            func.count(case((job_executions.c.status == "failed", 1))).label("failed"),
            func.avg(job_executions.c.duration_ms).label("avg_duration_ms"),
        )
        .join(jobs, jobs.c.id == job_executions.c.job_id)
        .where(
            jobs.c.queue_id == queue_id,
            job_executions.c.started_at >= since,
        )
    )
    row = result.mappings().one()
    completed = row["completed"] or 0
    failed = row["failed"] or 0
    total = completed + failed

    return QueueThroughputStats(
        window=window,
        total_completed=completed,
        total_failed=failed,
        jobs_per_minute=round(total / minutes_in_window, 4) if minutes_in_window > 0 else 0.0,
        avg_duration_ms=float(row["avg_duration_ms"]) if row["avg_duration_ms"] is not None else None,
        failure_rate=round(failed / total, 4) if total > 0 else 0.0,
    )


@router.delete("/queues/{queue_id}", status_code=204)
async def delete_queue(
    queue_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> None:
    """Delete a queue.

    Returns 409 Conflict if the queue has any non-terminal jobs
    (queued, scheduled, claimed, or running). Per database-design.md §5,
    the jobs→queues FK is RESTRICT, so the application must guard this
    explicitly to return a meaningful error instead of a FK violation.
    """
    queue = await _get_queue_or_404(queue_id, db)
    await _require_queue_access(queue, current_user["id"], db, required_roles=("owner", "admin"))

    # Check for non-terminal jobs
    active_result = await db.execute(
        select(func.count())
        .select_from(jobs)
        .where(
            jobs.c.queue_id == queue_id,
            jobs.c.status.in_(_NON_TERMINAL),
        )
    )
    active_count = active_result.scalar_one()
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "QUEUE_HAS_ACTIVE_JOBS",
                "message": f"Queue has {active_count} non-terminal job(s). Drain or cancel them before deleting.",
                "details": {"active_job_count": active_count},
            },
        )

    await db.execute(delete(queues).where(queues.c.id == queue_id))
