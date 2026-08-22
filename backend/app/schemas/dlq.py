"""Pydantic schemas for Dead Letter Queue (DLQ) endpoints."""
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DLQResponse(BaseModel):
    """Dead Letter Queue entry representation."""
    id: uuid.UUID
    job_id: uuid.UUID
    queue_id: uuid.UUID
    reason: str
    last_error: str | None = None
    payload_snapshot: dict[str, Any]
    failed_attempt_count: int
    moved_at: datetime
    resolved: bool
    resolved_at: datetime | None = None


class PaginatedDLQ(BaseModel):
    """Paginated list of DLQ entries."""
    items: list[DLQResponse]
    page: int
    page_size: int
    total: int
