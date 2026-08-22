"""Organizations router: org CRUD, members, and project creation under an org."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, insert, func
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import organizations, organization_members, projects, users
from app.schemas.organizations import (
    CreateOrgRequest,
    OrgResponse,
    AddMemberRequest,
    MemberResponse,
)
from app.schemas.projects import CreateProjectRequest, ProjectResponse, PaginatedProjects

router = APIRouter(prefix="/organizations", tags=["Organizations"])


async def _require_org_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> str:
    """Assert the user is a member of the org with one of the required roles.
    Returns the user's role. Raises 403 if not a member or insufficient role.
    """
    result = await db.execute(
        select(organization_members.c.role)
        .where(
            organization_members.c.organization_id == org_id,
            organization_members.c.user_id == user_id,
        )
    )
    row = result.first()
    if row is None or row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this organization", "details": {}},
        )
    return row[0]


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(
    body: CreateOrgRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Create an organization; the creator becomes 'owner'."""
    # Check slug uniqueness
    existing = await db.execute(
        select(organizations.c.id).where(organizations.c.slug == body.slug)
    )
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "SLUG_TAKEN", "message": "Organization slug already in use", "details": {}},
        )

    result = await db.execute(
        insert(organizations)
        .values(name=body.name, slug=body.slug)
        .returning(
            organizations.c.id,
            organizations.c.name,
            organizations.c.slug,
            organizations.c.created_at,
            organizations.c.updated_at,
        )
    )
    org = result.mappings().one()

    # Add creator as owner
    await db.execute(
        insert(organization_members).values(
            organization_id=org["id"],
            user_id=current_user["id"],
            role="owner",
        )
    )

    return OrgResponse(**org)


@router.get("", response_model=list[OrgResponse])
async def list_orgs(
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """List all organizations the current user belongs to."""
    result = await db.execute(
        select(
            organizations.c.id,
            organizations.c.name,
            organizations.c.slug,
            organizations.c.created_at,
            organizations.c.updated_at,
        )
        .join(organization_members, organization_members.c.organization_id == organizations.c.id)
        .where(organization_members.c.user_id == current_user["id"])
        .order_by(organizations.c.name)
    )
    return [OrgResponse(**row) for row in result.mappings()]


@router.post("/{org_id}/members", response_model=MemberResponse, status_code=201)
async def add_member(
    org_id: uuid.UUID,
    body: AddMemberRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Add a member to an organization. Requires owner or admin role."""
    await _require_org_member(org_id, current_user["id"], db, required_roles=("owner", "admin"))

    # Verify target user exists
    user_result = await db.execute(select(users.c.id).where(users.c.id == body.user_id))
    if user_result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "Target user not found", "details": {}},
        )

    # Upsert: ignore if already a member (re-adding returns existing record)
    existing = await db.execute(
        select(organization_members)
        .where(
            organization_members.c.organization_id == org_id,
            organization_members.c.user_id == body.user_id,
        )
    )
    existing_row = existing.mappings().first()
    if existing_row is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "ALREADY_MEMBER", "message": "User is already a member of this organization", "details": {}},
        )

    result = await db.execute(
        insert(organization_members)
        .values(
            organization_id=org_id,
            user_id=body.user_id,
            role=body.role,
        )
        .returning(
            organization_members.c.id,
            organization_members.c.organization_id,
            organization_members.c.user_id,
            organization_members.c.role,
            organization_members.c.created_at,
        )
    )
    return MemberResponse(**result.mappings().one())


@router.post("/{org_id}/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    org_id: uuid.UUID,
    body: CreateProjectRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Create a project under an organization."""
    await _require_org_member(org_id, current_user["id"], db)

    # Check org exists
    org_result = await db.execute(select(organizations.c.id).where(organizations.c.id == org_id))
    if org_result.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ORG_NOT_FOUND", "message": "Organization not found", "details": {}},
        )

    # Check project name uniqueness within org
    name_check = await db.execute(
        select(projects.c.id).where(
            projects.c.organization_id == org_id,
            projects.c.name == body.name,
        )
    )
    if name_check.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_NAME_TAKEN", "message": "A project with this name already exists in the organization", "details": {}},
        )

    result = await db.execute(
        insert(projects)
        .values(
            organization_id=org_id,
            created_by=current_user["id"],
            name=body.name,
            description=body.description,
        )
        .returning(
            projects.c.id,
            projects.c.organization_id,
            projects.c.created_by,
            projects.c.name,
            projects.c.description,
            projects.c.created_at,
            projects.c.updated_at,
        )
    )
    return ProjectResponse(**result.mappings().one())


@router.get("/{org_id}/projects", response_model=PaginatedProjects)
async def list_projects(
    org_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """List projects within an organization (paginated)."""
    await _require_org_member(org_id, current_user["id"], db)

    base = select(projects).where(projects.c.organization_id == org_id)

    total_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = total_result.scalar_one()

    rows_result = await db.execute(
        base.order_by(projects.c.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [ProjectResponse(**row) for row in rows_result.mappings()]

    return PaginatedProjects(items=items, page=page, page_size=page_size, total=total)
