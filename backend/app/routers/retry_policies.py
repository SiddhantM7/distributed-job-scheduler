"""Retry policies router: CRUD scoped to projects."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, insert, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import retry_policies, projects, organization_members
from app.schemas.retry_policies import (
    CreateRetryPolicyRequest,
    UpdateRetryPolicyRequest,
    RetryPolicyResponse,
)

router = APIRouter(tags=["Retry Policies"])


# ── Authorization helpers ─────────────────────────────────────────────────────

async def _require_project_access(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> None:
    """Assert the user is a member of the project's organization."""
    result = await db.execute(
        select(projects.c.organization_id).where(projects.c.id == project_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found", "details": {}},
        )
    org_id: uuid.UUID = row[0]

    membership = await db.execute(
        select(organization_members.c.role).where(
            organization_members.c.organization_id == org_id,
            organization_members.c.user_id == user_id,
        )
    )
    mem_row = membership.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this project", "details": {}},
        )


async def _get_retry_policy_or_404(
    policy_id: uuid.UUID, db: AsyncConnection
) -> dict:
    """Return a retry policy row dict, or raise 404."""
    result = await db.execute(
        select(retry_policies).where(retry_policies.c.id == policy_id)
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RETRY_POLICY_NOT_FOUND", "message": "Retry policy not found", "details": {}},
        )
    return dict(row)


def _policy_row_to_response(row: dict) -> RetryPolicyResponse:
    """Convert a DB row to a RetryPolicyResponse."""
    return RetryPolicyResponse(
        id=row["id"],
        project_id=row["project_id"],
        name=row["name"],
        strategy=row["strategy"],
        base_delay_seconds=row["base_delay_seconds"],
        max_delay_seconds=row.get("max_delay_seconds"),
        multiplier=row.get("multiplier"),
        max_attempts=row["max_attempts"],
        created_at=row["created_at"],
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/retry-policies",
    response_model=RetryPolicyResponse,
    status_code=201,
)
async def create_retry_policy(
    project_id: uuid.UUID,
    body: CreateRetryPolicyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> RetryPolicyResponse:
    """Create a retry policy scoped to a project."""
    await _require_project_access(project_id, current_user["id"], db)

    result = await db.execute(
        insert(retry_policies)
        .values(
            project_id=project_id,
            name=body.name,
            strategy=body.strategy,
            base_delay_seconds=body.base_delay_seconds,
            max_delay_seconds=body.max_delay_seconds,
            multiplier=body.multiplier,
            max_attempts=body.max_attempts,
        )
        .returning(*retry_policies.c)
    )
    return _policy_row_to_response(dict(result.mappings().one()))


@router.get(
    "/projects/{project_id}/retry-policies",
    response_model=list[RetryPolicyResponse],
)
async def list_retry_policies(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> list[RetryPolicyResponse]:
    """List all retry policies for a project."""
    await _require_project_access(project_id, current_user["id"], db)

    result = await db.execute(
        select(retry_policies)
        .where(retry_policies.c.project_id == project_id)
        .order_by(retry_policies.c.name)
    )
    return [_policy_row_to_response(dict(row)) for row in result.mappings()]


@router.patch("/retry-policies/{policy_id}", response_model=RetryPolicyResponse)
async def update_retry_policy(
    policy_id: uuid.UUID,
    body: UpdateRetryPolicyRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> RetryPolicyResponse:
    """Update a retry policy.

    Per database-design.md §7, changes do not affect jobs already created
    (their max_attempts was copied at creation time).
    Requires owner or admin role.
    """
    policy = await _get_retry_policy_or_404(policy_id, db)
    await _require_project_access(
        policy["project_id"], current_user["id"], db, required_roles=("owner", "admin")
    )

    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.strategy is not None:
        updates["strategy"] = body.strategy
    if body.base_delay_seconds is not None:
        updates["base_delay_seconds"] = body.base_delay_seconds
    if body.max_delay_seconds is not None:
        updates["max_delay_seconds"] = body.max_delay_seconds
    if body.multiplier is not None:
        updates["multiplier"] = body.multiplier
    if body.max_attempts is not None:
        updates["max_attempts"] = body.max_attempts

    # Validate max_delay >= base_delay after merging
    effective_base = updates.get("base_delay_seconds", policy["base_delay_seconds"])
    effective_max = updates.get("max_delay_seconds", policy.get("max_delay_seconds"))
    if effective_max is not None and effective_max < effective_base:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_DELAY_RANGE",
                "message": "max_delay_seconds must be >= base_delay_seconds",
                "details": {},
            },
        )

    if not updates:
        return _policy_row_to_response(policy)

    result = await db.execute(
        update(retry_policies)
        .where(retry_policies.c.id == policy_id)
        .values(**updates)
        .returning(*retry_policies.c)
    )
    return _policy_row_to_response(dict(result.mappings().one()))
