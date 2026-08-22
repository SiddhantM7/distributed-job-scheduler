"""pytest tests for Phase 7 Metrics endpoints."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import insert

from app.models.tables import job_executions, jobs, queues
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _create_test_queue(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "metrics-queue",
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": name, "priority": 1, "max_concurrency": 5},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── Metrics Overview Tests ───────────────────────────────────────────────────

async def test_project_metrics_overview_empty(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Empty project returns 0 queues, 0 workers, 0 jobs, and 0.0 failure rate."""
    _, project_id = org_and_project
    resp = await client.get(
        f"/api/v1/projects/{project_id}/metrics/overview", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_queues"] == 0
    assert data["total_jobs"] == 0
    assert data["failure_rate"] == 0.0
    assert data["job_status_counts"]["queued"] == 0


async def test_project_metrics_overview_populated(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Project metrics calculate accurate status breakdowns, failure rate, and avg duration."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-met-pop")
    queue_id = uuid.UUID(queue["id"])

    # Insert jobs in multiple statuses
    async with test_engine.connect() as conn:
        j_comp = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="task", status="completed").returning(jobs.c.id)
        )).scalar_one()

        j_fail = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="task", status="failed").returning(jobs.c.id)
        )).scalar_one()

        await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="task", status="queued")
        )

        # Insert executions for duration calculation
        await conn.execute(
            insert(job_executions).values(
                job_id=j_comp, attempt_number=1, status="completed", duration_ms=120
            )
        )
        await conn.execute(
            insert(job_executions).values(
                job_id=j_fail, attempt_number=1, status="failed", duration_ms=50
            )
        )
        await conn.commit()

    resp = await client.get(
        f"/api/v1/projects/{project_id}/metrics/overview", headers=auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_queues"] == 1
    assert data["total_jobs"] == 3
    assert data["total_completed"] == 1
    assert data["total_failed"] == 1
    assert data["failure_rate"] == 0.5
    assert data["avg_duration_ms"] == 120.0
    assert data["job_status_counts"]["completed"] == 1
    assert data["job_status_counts"]["failed"] == 1
    assert data["job_status_counts"]["queued"] == 1


# ─── Throughput Tests ─────────────────────────────────────────────────────────

async def test_project_metrics_throughput_1h_window(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Throughput returns time-bucketed points and overall rates."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-thru-1h")
    queue_id = uuid.UUID(queue["id"])

    # Insert executions within the past 30 mins
    recent = datetime.now(timezone.utc) - timedelta(minutes=15)
    async with test_engine.connect() as conn:
        j1 = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="task", status="completed").returning(jobs.c.id)
        )).scalar_one()

        await conn.execute(
            insert(job_executions).values(
                job_id=j1,
                attempt_number=1,
                status="completed",
                started_at=recent,
                completed_at=recent,
                duration_ms=100,
            )
        )
        await conn.commit()

    resp = await client.get(
        f"/api/v1/projects/{project_id}/metrics/throughput?window=1h",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["window"] == "1h"
    assert data["bucket_size"] == "5m"
    assert data["total_completed"] == 1
    assert len(data["buckets"]) >= 1
    assert data["jobs_per_minute"] > 0.0


async def test_project_metrics_throughput_24h_and_7d(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Throughput supports 24h and 7d windows."""
    _, project_id = org_and_project
    await _create_test_queue(client, project_id, auth_headers, "q-thru-multi")

    resp24h = await client.get(
        f"/api/v1/projects/{project_id}/metrics/throughput?window=24h",
        headers=auth_headers,
    )
    assert resp24h.status_code == 200
    assert resp24h.json()["bucket_size"] == "1h"

    resp7d = await client.get(
        f"/api/v1/projects/{project_id}/metrics/throughput?window=7d",
        headers=auth_headers,
    )
    assert resp7d.status_code == 200
    assert resp7d.json()["bucket_size"] == "1d"


async def test_project_metrics_invalid_window_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Invalid window parameter returns 422."""
    _, project_id = org_and_project
    resp = await client.get(
        f"/api/v1/projects/{project_id}/metrics/throughput?window=invalid_window",
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ─── Auth & Error Tests ───────────────────────────────────────────────────────

async def test_metrics_auth_checks(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """401 unauthenticated and 403 unauthorized for foreign users."""
    _, project_id = org_and_project

    # 401 unauthenticated
    resp401 = await client.get(f"/api/v1/projects/{project_id}/metrics/overview")
    assert resp401.status_code == 401

    # 403 foreign user
    resp403 = await client.get(
        f"/api/v1/projects/{project_id}/metrics/overview",
        headers=second_auth_headers,
    )
    assert resp403.status_code == 403


async def test_metrics_not_found(client: AsyncClient, auth_headers: dict) -> None:
    """Unknown project returns 404."""
    resp404 = await client.get(
        f"/api/v1/projects/{uuid.uuid4()}/metrics/overview",
        headers=auth_headers,
    )
    assert resp404.status_code == 404
