"""Pydantic schemas for queue endpoints."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateQueueRequest(BaseModel):
    """Request body for creating a queue."""

    name: str = Field(min_length=1)
    priority: int = Field(default=0)
    max_concurrency: int = Field(default=10, ge=1)
    default_retry_policy_id: uuid.UUID | None = None


class UpdateQueueRequest(BaseModel):
    """Request body for patching a queue. All fields optional."""

    priority: int | None = None
    max_concurrency: int | None = Field(default=None, ge=1)
    default_retry_policy_id: uuid.UUID | None = None


class QueueStatsLive(BaseModel):
    """Live job counts by terminal/active status bucket."""

    queued: int
    scheduled: int
    claimed: int
    running: int
    completed: int
    failed: int
    dead_letter: int
    cancelled: int


class QueueResponse(BaseModel):
    """Full queue representation including live stats when requested."""

    id: uuid.UUID
    project_id: uuid.UUID
    default_retry_policy_id: uuid.UUID | None
    name: str
    priority: int
    max_concurrency: int
    is_paused: bool
    created_at: datetime
    updated_at: datetime
    stats: QueueStatsLive | None = None


class QueueThroughputStats(BaseModel):
    """Throughput/health metrics for dashboard charts."""

    window: str
    total_completed: int
    total_failed: int
    jobs_per_minute: float
    avg_duration_ms: float | None
    failure_rate: float
