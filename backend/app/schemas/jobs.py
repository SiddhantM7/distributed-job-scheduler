"""Pydantic schemas for Job and Scheduled Job endpoints."""
import uuid
from datetime import datetime
from typing import Any, Literal
from croniter import croniter

from pydantic import BaseModel, Field, model_validator


# ── Create Job Schemas ────────────────────────────────────────────────────────

class JobItemPayload(BaseModel):
    """Payload item for batch submission."""
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    idempotency_key: str | None = None


class CreateJobRequest(BaseModel):
    """Job creation request supporting all 5 kinds."""
    type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    kind: Literal["immediate", "delayed", "scheduled", "recurring", "batch"] = "immediate"
    priority: int = 0
    retry_policy_id: uuid.UUID | None = None
    idempotency_key: str | None = None

    # Kind-specific fields
    run_at: datetime | None = None  # for delayed
    scheduled_for: datetime | None = None  # for scheduled (one-off)
    cron_expression: str | None = None  # for recurring
    items: list[JobItemPayload] | None = None  # for batch

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "CreateJobRequest":
        """Validate required fields according to job kind."""
        if self.kind == "delayed" and self.run_at is None:
            raise ValueError("run_at is required for delayed jobs")
        if self.kind == "scheduled" and self.scheduled_for is None:
            raise ValueError("scheduled_for is required for scheduled jobs")
        if self.kind == "recurring":
            if not self.cron_expression:
                raise ValueError("cron_expression is required for recurring jobs")
            if not croniter.is_valid(self.cron_expression):
                raise ValueError(f"Invalid cron expression: {self.cron_expression}")
        if self.kind == "batch":
            if not self.items or len(self.items) == 0:
                raise ValueError("items array must contain at least one item for batch jobs")
        return self


class CreateBatchJobRequest(BaseModel):
    """Dedicated batch submission request."""
    type: str = Field(min_length=1)
    items: list[JobItemPayload] = Field(min_length=1)
    retry_policy_id: uuid.UUID | None = None


# ── Job Responses ─────────────────────────────────────────────────────────────

class JobResponse(BaseModel):
    """Full job representation."""
    id: uuid.UUID
    queue_id: uuid.UUID
    scheduled_job_id: uuid.UUID | None = None
    retry_policy_id: uuid.UUID | None = None
    claimed_by: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    type: str
    payload: dict[str, Any]
    kind: str
    status: str
    priority: int
    run_at: datetime
    attempt_count: int
    max_attempts: int
    idempotency_key: str | None = None
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class PaginatedJobs(BaseModel):
    """Paginated list of jobs."""
    items: list[JobResponse]
    page: int
    page_size: int
    total: int


class BatchJobResponse(BaseModel):
    """Response returned for batch creation."""
    batch_id: uuid.UUID
    jobs: list[JobResponse]


# ── Execution and Log Schemas ─────────────────────────────────────────────────

class JobExecutionResponse(BaseModel):
    """Audit record for a single job attempt."""
    id: uuid.UUID
    job_id: uuid.UUID
    worker_id: uuid.UUID | None = None
    attempt_number: int
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error: str | None = None
    result: dict[str, Any] | None = None


class JobLogResponse(BaseModel):
    """Single log entry from a job execution."""
    id: int
    job_execution_id: uuid.UUID
    timestamp: datetime
    level: str
    message: str


# ── Scheduled Job Schemas ─────────────────────────────────────────────────────

class ScheduledJobResponse(BaseModel):
    """Scheduled job definition representation."""
    id: uuid.UUID
    queue_id: uuid.UUID
    retry_policy_id: uuid.UUID | None = None
    name: str
    job_type: str
    payload_template: dict[str, Any]
    cron_expression: str | None = None
    is_recurring: bool
    is_active: bool
    next_run_at: datetime
    last_run_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class UpdateScheduledJobRequest(BaseModel):
    """Update scheduled job definition."""
    name: str | None = Field(default=None, min_length=1)
    payload_template: dict[str, Any] | None = None
    cron_expression: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_cron(self) -> "UpdateScheduledJobRequest":
        if self.cron_expression is not None and not croniter.is_valid(self.cron_expression):
            raise ValueError(f"Invalid cron expression: {self.cron_expression}")
        return self
