"""Metrics router: project overview and time-bucketed throughput."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import organization_members, projects
from app.schemas.metrics import ProjectMetricsOverview, ProjectThroughputMetrics
from app.services.metrics import (
    get_project_metrics_overview_service,
    get_project_throughput_metrics_service,
)

router = APIRouter(tags=["Metrics"])


# ── Auth Helper ───────────────────────────────────────────────────────────────

async def _require_project_access(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> None:
    """Ensure user is a member of the project's organization."""
    p_res = await db.execute(select(projects.c.organization_id).where(projects.c.id == project_id))
    p_row = p_res.first()
    if p_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found", "details": {}},
        )

    mem_res = await db.execute(
        select(organization_members.c.role).where(
            organization_members.c.organization_id == p_row[0],
            organization_members.c.user_id == user_id,
        )
    )
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this project", "details": {}},
        )


# ── Metrics Endpoints ─────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/metrics/overview", response_model=ProjectMetricsOverview)
async def get_project_metrics_overview(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> ProjectMetricsOverview:
    """Cross-queue project metrics summary: totals by status, failure rate, active workers."""
    await _require_project_access(project_id, current_user["id"], db)
    return await get_project_metrics_overview_service(db, project_id)


@router.get("/projects/{project_id}/metrics/throughput", response_model=ProjectThroughputMetrics)
async def get_project_throughput_metrics(
    project_id: uuid.UUID,
    window: str = Query(default="1h", description="Time window: 1h, 24h, 7d"),
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> ProjectThroughputMetrics:
    """Time-bucketed completed/failed throughput metrics for charts."""
    await _require_project_access(project_id, current_user["id"], db)
    return await get_project_throughput_metrics_service(db, project_id, window=window)
