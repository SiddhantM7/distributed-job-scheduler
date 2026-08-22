"""Pydantic schemas for Worker endpoints."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RegisterWorkerRequest(BaseModel):
    """Request body for worker registration."""
    hostname: str = Field(min_length=1)
    pid: int | None = None
    concurrency: int = Field(default=5, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkerHeartbeatRequest(BaseModel):
    """Heartbeat telemetry sent by active worker."""
    active_job_count: int = Field(default=0, ge=0)
    cpu_pct: float | None = None
    mem_mb: int | None = None


class WorkerResponse(BaseModel):
    """Worker detail representation."""
    id: uuid.UUID
    hostname: str
    pid: int | None = None
    status: str
    concurrency: int
    started_at: datetime
    last_heartbeat_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    assigned_queue_ids: list[uuid.UUID] = Field(default_factory=list)
    active_job_count: int = 0


class AssignQueuesRequest(BaseModel):
    """Assign worker to a list of queues."""
    queue_ids: list[uuid.UUID] = Field(min_length=1)


class WorkerQueueResponse(BaseModel):
    """Worker queue mapping response."""
    id: uuid.UUID
    worker_id: uuid.UUID
    queue_id: uuid.UUID
