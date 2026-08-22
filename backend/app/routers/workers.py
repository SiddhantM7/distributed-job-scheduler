"""Workers router: registration, heartbeat, listing, and queue assignments."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.dependencies import get_db, get_current_user
from app.models.tables import (
    organization_members,
    projects,
    queues,
    worker_queues,
    workers,
)
from app.schemas.workers import (
    AssignQueuesRequest,
    RegisterWorkerRequest,
    WorkerHeartbeatRequest,
    WorkerQueueResponse,
    WorkerResponse,
)
from app.services.workers import (
    deregister_worker_service,
    get_worker_details_service,
    heartbeat_worker_service,
    register_worker_service,
)

router = APIRouter(tags=["Workers"])


# ── Auth Helpers ──────────────────────────────────────────────────────────────

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


async def _require_queue_access(
    queue_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncConnection,
    required_roles: tuple[str, ...] = ("owner", "admin"),
) -> None:
    """Ensure user has admin/owner rights to the queue's project."""
    stmt = (
        select(projects.c.organization_id)
        .join(queues, queues.c.project_id == projects.c.id)
        .where(queues.c.id == queue_id)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "QUEUE_NOT_FOUND", "message": "Queue not found", "details": {}},
        )

    mem_res = await db.execute(
        select(organization_members.c.role).where(
            organization_members.c.organization_id == row[0],
            organization_members.c.user_id == user_id,
        )
    )
    mem_row = mem_res.first()
    if mem_row is None or mem_row[0] not in required_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Insufficient permissions for this queue", "details": {}},
        )


# ── Worker Lifecycle Endpoints ────────────────────────────────────────────────

@router.post("/workers/register", response_model=WorkerResponse, status_code=201)
async def register_worker(
    body: RegisterWorkerRequest,
    db: AsyncConnection = Depends(get_db),
) -> WorkerResponse:
    """Register a new worker process on startup."""
    row = await register_worker_service(db, body)
    return WorkerResponse(**row)


@router.post("/workers/{worker_id}/heartbeat", response_model=WorkerResponse)
async def worker_heartbeat(
    worker_id: uuid.UUID,
    body: WorkerHeartbeatRequest,
    db: AsyncConnection = Depends(get_db),
) -> WorkerResponse:
    """Worker reports heartbeat and load."""
    row = await heartbeat_worker_service(db, worker_id, body)
    return WorkerResponse(**row)


@router.post("/workers/{worker_id}/deregister", response_model=WorkerResponse)
async def deregister_worker(
    worker_id: uuid.UUID,
    db: AsyncConnection = Depends(get_db),
) -> WorkerResponse:
    """Graceful worker shutdown."""
    row = await deregister_worker_service(db, worker_id)
    return WorkerResponse(**row)


@router.get("/workers/{worker_id}", response_model=WorkerResponse)
async def get_worker(
    worker_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> WorkerResponse:
    """Get single worker details and status."""
    row = await get_worker_details_service(db, worker_id)
    return WorkerResponse(**row)


# ── Project Worker Listing ───────────────────────────────────────────────────

@router.get("/projects/{project_id}/workers", response_model=List[WorkerResponse])
async def list_project_workers(
    project_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> List[WorkerResponse]:
    """List workers associated with a project's queues, or active global workers."""
    await _require_project_access(project_id, current_user["id"], db)

    # Get project queues
    q_res = await db.execute(select(queues.c.id).where(queues.c.project_id == project_id))
    project_queue_ids = [r[0] for r in q_res.all()]

    # Query workers that are either assigned to project queues or active with no queue assignments
    assigned_worker_ids_res = await db.execute(
        select(worker_queues.c.worker_id).where(worker_queues.c.queue_id.in_(project_queue_ids))
    ) if project_queue_ids else None

    assigned_worker_ids = [r[0] for r in assigned_worker_ids_res.all()] if assigned_worker_ids_res else []

    # Select all relevant workers
    if assigned_worker_ids:
        w_stmt = select(workers).where(
            (workers.c.id.in_(assigned_worker_ids)) | (workers.c.status != "offline")
        )
    else:
        w_stmt = select(workers).where(workers.c.status != "offline")

    w_res = await db.execute(w_stmt.order_by(workers.c.started_at.desc()))
    workers_list = []
    for w in w_res.mappings():
        worker_dict = dict(w)
        # Fetch assigned queues
        wq_res = await db.execute(
            select(worker_queues.c.queue_id).where(worker_queues.c.worker_id == w["id"])
        )
        worker_dict["assigned_queue_ids"] = [r[0] for r in wq_res.all()]
        worker_dict["active_job_count"] = 0
        workers_list.append(WorkerResponse(**worker_dict))

    return workers_list


# ── Worker Queue Assignments ──────────────────────────────────────────────────

@router.post("/workers/{worker_id}/queues", response_model=List[WorkerQueueResponse], status_code=201)
async def assign_worker_queues(
    worker_id: uuid.UUID,
    body: AssignQueuesRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> List[WorkerQueueResponse]:
    """Assign worker to a list of queues."""
    # Verify worker exists
    w_res = await db.execute(select(workers.c.id).where(workers.c.id == worker_id))
    if w_res.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKER_NOT_FOUND", "message": "Worker not found", "details": {}},
        )

    responses = []
    for q_id in body.queue_ids:
        await _require_queue_access(q_id, current_user["id"], db, required_roles=("owner", "admin"))

        # Upsert / check existing
        existing = await db.execute(
            select(worker_queues).where(
                worker_queues.c.worker_id == worker_id,
                worker_queues.c.queue_id == q_id,
            )
        )
        existing_row = existing.mappings().first()
        if existing_row:
            responses.append(WorkerQueueResponse(**dict(existing_row)))
        else:
            ins = await db.execute(
                insert(worker_queues)
                .values(worker_id=worker_id, queue_id=q_id)
                .returning(*worker_queues.c)
            )
            responses.append(WorkerQueueResponse(**dict(ins.mappings().one())))

    return responses


@router.get("/workers/{worker_id}/queues", response_model=List[WorkerQueueResponse])
async def list_worker_queues(
    worker_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> List[WorkerQueueResponse]:
    """List queues assigned to a worker."""
    w_res = await db.execute(select(workers.c.id).where(workers.c.id == worker_id))
    if w_res.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "WORKER_NOT_FOUND", "message": "Worker not found", "details": {}},
        )

    res = await db.execute(
        select(worker_queues).where(worker_queues.c.worker_id == worker_id)
    )
    return [WorkerQueueResponse(**dict(r)) for r in res.mappings()]


@router.delete("/workers/{worker_id}/queues/{queue_id}", status_code=204)
async def unassign_worker_queue(
    worker_id: uuid.UUID,
    queue_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncConnection = Depends(get_db),
) -> None:
    """Unassign a worker from a queue."""
    await _require_queue_access(queue_id, current_user["id"], db, required_roles=("owner", "admin"))

    await db.execute(
        delete(worker_queues).where(
            worker_queues.c.worker_id == worker_id,
            worker_queues.c.queue_id == queue_id,
        )
    )
