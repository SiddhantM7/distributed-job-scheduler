"""Business logic for project-level metrics aggregation and time-bucketed throughput."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import HTTPException, status
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.models.tables import (
    job_executions,
    jobs,
    queues,
    worker_queues,
    workers,
)
from app.schemas.metrics import (
    JobStatusCounts,
    ProjectMetricsOverview,
    ProjectThroughputMetrics,
    ThroughputBucket,
)

_WINDOW_CONFIG = {
    "1h": {"delta": timedelta(hours=1), "bucket_size": "5m", "trunc": "minute", "stride_m": 5},
    "24h": {"delta": timedelta(hours=24), "bucket_size": "1h", "trunc": "hour", "stride_m": 60},
    "7d": {"delta": timedelta(days=7), "bucket_size": "1d", "trunc": "day", "stride_m": 1440},
}


async def get_project_metrics_overview_service(
    db: AsyncConnection,
    project_id: uuid.UUID,
) -> ProjectMetricsOverview:
    """Calculate cross-queue overview metrics for a project."""
    # 1. Total queues count
    q_count_res = await db.execute(
        select(func.count()).select_from(queues).where(queues.c.project_id == project_id)
    )
    total_queues = q_count_res.scalar_one()

    # 2. Get project queue IDs
    q_ids_res = await db.execute(
        select(queues.c.id).where(queues.c.project_id == project_id)
    )
    project_queue_ids = [r[0] for r in q_ids_res.all()]

    if not project_queue_ids:
        return ProjectMetricsOverview(
            project_id=project_id,
            total_queues=0,
            active_workers=0,
            job_status_counts=JobStatusCounts(),
            total_jobs=0,
            total_completed=0,
            total_failed=0,
            failure_rate=0.0,
            avg_duration_ms=None,
        )

    # 3. Active workers count in project scope (assigned to project queues or active shared workers)
    w_count_res = await db.execute(
        select(func.count(func.distinct(workers.c.id)))
        .select_from(workers)
        .outerjoin(worker_queues, worker_queues.c.worker_id == workers.c.id)
        .where(
            workers.c.status != "offline",
            (worker_queues.c.queue_id.in_(project_queue_ids)) | (worker_queues.c.queue_id.is_(None)),
        )
    )
    active_workers = w_count_res.scalar_one()

    # 4. Job status breakdown
    status_res = await db.execute(
        select(jobs.c.status, func.count().label("cnt"))
        .where(jobs.c.queue_id.in_(project_queue_ids))
        .group_by(jobs.c.status)
    )
    counts: Dict[str, int] = {row[0]: row[1] for row in status_res}
    status_counts = JobStatusCounts(
        queued=counts.get("queued", 0),
        scheduled=counts.get("scheduled", 0),
        claimed=counts.get("claimed", 0),
        running=counts.get("running", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        dead_letter=counts.get("dead_letter", 0),
        cancelled=counts.get("cancelled", 0),
    )
    total_jobs = sum(counts.values())
    total_completed = status_counts.completed
    total_failed = status_counts.failed + status_counts.dead_letter
    term_total = total_completed + total_failed
    failure_rate = round(total_failed / term_total, 4) if term_total > 0 else 0.0

    # 5. Average duration across completed executions
    avg_dur_res = await db.execute(
        select(func.avg(job_executions.c.duration_ms))
        .select_from(job_executions)
        .join(jobs, jobs.c.id == job_executions.c.job_id)
        .where(
            jobs.c.queue_id.in_(project_queue_ids),
            job_executions.c.status == "completed",
            job_executions.c.duration_ms.is_not(None),
        )
    )
    avg_dur = avg_dur_res.scalar_one()
    avg_duration_ms = float(avg_dur) if avg_dur is not None else None

    return ProjectMetricsOverview(
        project_id=project_id,
        total_queues=total_queues,
        active_workers=active_workers,
        job_status_counts=status_counts,
        total_jobs=total_jobs,
        total_completed=total_completed,
        total_failed=total_failed,
        failure_rate=failure_rate,
        avg_duration_ms=avg_duration_ms,
    )


async def get_project_throughput_metrics_service(
    db: AsyncConnection,
    project_id: uuid.UUID,
    window: str = "1h",
) -> ProjectThroughputMetrics:
    """Calculate time-bucketed throughput metrics for charts."""
    if window not in _WINDOW_CONFIG:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_WINDOW", "message": "window must be one of: 1h, 24h, 7d", "details": {}},
        )

    cfg = _WINDOW_CONFIG[window]
    now = datetime.now(tz=timezone.utc)
    since = now - cfg["delta"]
    window_minutes = cfg["delta"].total_seconds() / 60.0

    # Get project queue IDs
    q_ids_res = await db.execute(
        select(queues.c.id).where(queues.c.project_id == project_id)
    )
    project_queue_ids = [r[0] for r in q_ids_res.all()]

    if not project_queue_ids:
        return ProjectThroughputMetrics(
            project_id=project_id,
            window=window,
            bucket_size=cfg["bucket_size"],
            buckets=[],
            total_completed=0,
            total_failed=0,
            jobs_per_minute=0.0,
            overall_failure_rate=0.0,
        )

    # Time-bucketed query using date_trunc
    trunc_field = cfg["trunc"]
    bucket_expr = func.date_trunc(trunc_field, job_executions.c.started_at).label("bucket_time")

    stmt = (
        select(
            bucket_expr,
            func.count(case((job_executions.c.status == "completed", 1))).label("completed"),
            func.count(case((job_executions.c.status == "failed", 1))).label("failed"),
            func.avg(case((job_executions.c.status == "completed", job_executions.c.duration_ms))).label("avg_dur"),
        )
        .select_from(job_executions)
        .join(jobs, jobs.c.id == job_executions.c.job_id)
        .where(
            jobs.c.queue_id.in_(project_queue_ids),
            job_executions.c.started_at >= since,
        )
        .group_by(bucket_expr)
        .order_by(bucket_expr.asc())
    )

    res = await db.execute(stmt)
    buckets = []
    total_completed = 0
    total_failed = 0

    for row in res.mappings():
        c = row["completed"] or 0
        f = row["failed"] or 0
        dur = float(row["avg_dur"]) if row["avg_dur"] is not None else None
        total_completed += c
        total_failed += f
        buckets.append(
            ThroughputBucket(
                timestamp=row["bucket_time"],
                completed=c,
                failed=f,
                avg_duration_ms=dur,
            )
        )

    term_total = total_completed + total_failed
    jobs_per_min = round(term_total / window_minutes, 4) if window_minutes > 0 else 0.0
    overall_failure_rate = round(total_failed / term_total, 4) if term_total > 0 else 0.0

    return ProjectThroughputMetrics(
        project_id=project_id,
        window=window,
        bucket_size=cfg["bucket_size"],
        buckets=buckets,
        total_completed=total_completed,
        total_failed=total_failed,
        jobs_per_minute=jobs_per_min,
        overall_failure_rate=overall_failure_rate,
    )
