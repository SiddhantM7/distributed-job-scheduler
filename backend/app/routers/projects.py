"""Projects router: project detail, update, and delete."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import projects, organization_members
from app.schemas.projects import UpdateProjectRequest, ProjectResponse

router = APIRouter(prefix="/projects", tags=["Projects"])


async def _get_project_or_404(project_id: uuid.UUID, db: AsyncConnection) -> dict:
    result = await db.execute(
        select(projects).where(projects.c.id == project_id)
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "PROJECT_NOT_FOUND", "message": "Project not found", "details": {}},
        )
    return dict(row)


async def _require_project_member(
    project: dict,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin", "member"),
) -> None:
    result = await db.execute(
        select(organization_members.c.role)
        .where(
            organization_members.c.organization_id == project["organization_id"],
            organization_members.c.user_id == user_id,
        )
    )
    row = result.first()
    if row is None or row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this project", "details": {}},
        )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Get project detail."""
    project = await _get_project_or_404(project_id, db)
    await _require_project_member(project, current_user["id"], db)
    return ProjectResponse(**project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: uuid.UUID,
    body: UpdateProjectRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Update project name or description. Requires owner or admin."""
    project = await _get_project_or_404(project_id, db)
    await _require_project_member(project, current_user["id"], db, required_roles=("owner", "admin"))

    updates: dict = {}
    if body.name is not None:
        # Check name uniqueness within org
        name_check = await db.execute(
            select(projects.c.id).where(
                projects.c.organization_id == project["organization_id"],
                projects.c.name == body.name,
                projects.c.id != project_id,
            )
        )
        if name_check.first() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "PROJECT_NAME_TAKEN", "message": "A project with this name already exists in the organization", "details": {}},
            )
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description

    if not updates:
        return ProjectResponse(**project)

    result = await db.execute(
        update(projects)
        .where(projects.c.id == project_id)
        .values(**updates)
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


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
):
    """Delete a project (cascades to queues). Requires owner."""
    project = await _get_project_or_404(project_id, db)
    await _require_project_member(project, current_user["id"], db, required_roles=("owner",))

    await db.execute(delete(projects).where(projects.c.id == project_id))
