"""Dead Letter Queue (DLQ) router: list, detail, retry, and resolve."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import dead_letter_queue, organization_members, projects, queues
from app.schemas.dlq import DLQResponse, PaginatedDLQ
from app.schemas.jobs import JobResponse
from app.services.dlq import resolve_dlq_entry_service, retry_dlq_entry_service

router = APIRouter(tags=["Dead Letter Queue"])


# ── Auth & Existence Helpers ──────────────────────────────────────────────────

async def _require_queue_access(
    queue_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> dict:
    """Validate queue exists and user has membership in the owning organization."""
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

    mem_res = await db.execute(
        select(organization_members.c.role).where(
            organization_members.c.organization_id == row["organization_id"],
            organization_members.c.user_id == user_id,
        )
    )
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this queue", "details": {}},
        )
    return dict(row)


async def _require_dlq_access(
    dlq_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> dict:
    """Validate DLQ entry exists and user has membership in the owning organization."""
    stmt = (
        select(
            dead_letter_queue,
            queues.c.project_id,
            projects.c.organization_id,
        )
        .join(queues, queues.c.id == dead_letter_queue.c.queue_id)
        .join(projects, projects.c.id == queues.c.project_id)
        .where(dead_letter_queue.c.id == dlq_id)
    )
    res = await db.execute(stmt)
    row = res.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DLQ_ENTRY_NOT_FOUND", "message": "DLQ entry not found", "details": {}},
        )

    mem_res = await db.execute(
        select(organization_members.c.role).where(
            organization_members.c.organization_id == row["organization_id"],
            organization_members.c.user_id == user_id,
        )
    )
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this DLQ entry", "details": {}},
        )
    return dict(row)


# ── DLQ Endpoints ─────────────────────────────────────────────────────────────

@router.get("/queues/{queue_id}/dlq", response_model=PaginatedDLQ)
async def list_queue_dlq(
    queue_id: uuid.UUID,
    resolved: Optional[bool] = Query(default=None, description="Filter by resolved status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> PaginatedDLQ:
    """List Dead Letter Queue entries for a specific queue."""
    await _require_queue_access(queue_id, current_user["id"], db)

    base = select(dead_letter_queue).where(dead_letter_queue.c.queue_id == queue_id)
    if resolved is not None:
        base = base.where(dead_letter_queue.c.resolved == resolved)

    # Count total
    total_res = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_res.scalar_one()

    # Query page
    items_res = await db.execute(
        base.order_by(dead_letter_queue.c.moved_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [DLQResponse(**dict(r)) for r in items_res.mappings()]

    return PaginatedDLQ(items=items, page=page, page_size=page_size, total=total)


@router.get("/dlq/{id}", response_model=DLQResponse)
async def get_dlq_entry(
    id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> DLQResponse:
    """Get single DLQ entry detail."""
    row = await _require_dlq_access(id, current_user["id"], db)
    return DLQResponse(**row)


@router.post("/dlq/{id}/retry", response_model=JobResponse, status_code=201)
async def retry_dlq_job(
    id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> JobResponse:
    """Re-submit the dead-lettered job and mark DLQ entry resolved."""
    await _require_dlq_access(id, current_user["id"], db, required_roles=("owner", "admin"))
    new_job, _ = await retry_dlq_entry_service(db, id)
    return JobResponse(**new_job)


@router.post("/dlq/{id}/resolve", response_model=DLQResponse)
async def resolve_dlq_entry(
    id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> DLQResponse:
    """Mark a DLQ entry resolved without retrying."""
    await _require_dlq_access(id, current_user["id"], db, required_roles=("owner", "admin"))
    updated_row = await resolve_dlq_entry_service(db, id)
    return DLQResponse(**updated_row)
