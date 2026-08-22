"""Pydantic schemas for Metrics endpoints."""
import uuid
from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel, Field


class JobStatusCounts(BaseModel):
    """Job count breakdown by status."""
    queued: int = 0
    scheduled: int = 0
    claimed: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0
    dead_letter: int = 0
    cancelled: int = 0


class ProjectMetricsOverview(BaseModel):
    """Cross-queue project metrics summary."""
    project_id: uuid.UUID
    total_queues: int
    active_workers: int
    job_status_counts: JobStatusCounts
    total_jobs: int
    total_completed: int
    total_failed: int
    failure_rate: float
    avg_duration_ms: float | None = None


class ThroughputBucket(BaseModel):
    """Time-bucketed throughput data point."""
    timestamp: datetime
    completed: int = 0
    failed: int = 0
    avg_duration_ms: float | None = None


class ProjectThroughputMetrics(BaseModel):
    """Throughput metrics for charts over a time window."""
    project_id: uuid.UUID
    window: str
    bucket_size: str
    buckets: List[ThroughputBucket]
    total_completed: int
    total_failed: int
    jobs_per_minute: float
    overall_failure_rate: float
