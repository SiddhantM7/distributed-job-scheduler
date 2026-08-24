"""pytest tests for POST /api/v1/dlq/{id}/summary endpoint."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select

from app.models.tables import dead_letter_queue, jobs
from app.schemas.dlq import DLQSummaryResponse
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _create_test_queue(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "dlq-sum-queue",
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": name, "priority": 1, "max_concurrency": 5},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_dlq_entry(
    queue_id: uuid.UUID,
    job_type: str = "webhook_task",
    reason: str = "Max attempts exceeded",
    last_error: str = "Connection timeout after 30s",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Helper to insert job and dead_letter_queue rows."""
    async with test_engine.connect() as conn:
        job_id = (
            await conn.execute(
                insert(jobs)
                .values(
                    queue_id=queue_id,
                    type=job_type,
                    payload={"target": "api.example.com"},
                    status="dead_letter",
                    error=last_error,
                    attempt_count=5,
                    max_attempts=5,
                )
                .returning(jobs.c.id)
            )
        ).scalar_one()

        dlq_id = (
            await conn.execute(
                insert(dead_letter_queue)
                .values(
                    job_id=job_id,
                    queue_id=queue_id,
                    reason=reason,
                    last_error=last_error,
                    payload_snapshot={"target": "api.example.com"},
                    failed_attempt_count=5,
                    resolved=False,
                )
                .returning(dead_letter_queue.c.id)
            )
        ).scalar_one()
        await conn.commit()
    return job_id, dlq_id


# ─── Tests ────────────────────────────────────────────────────────────────────

async def test_dlq_summary_endpoint_success(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
):
    """POST /api/v1/dlq/{id}/summary returns structured failure analysis for valid DLQ entry."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-sum-success")
    queue_id = uuid.UUID(queue["id"])

    job_id, dlq_id = await _create_dlq_entry(
        queue_id=queue_id,
        job_type="payment_charge",
        reason="Payment gateway timed out",
        last_error="ConnectTimeout: Request to gateway timed out",
    )

    resp = await client.post(
        f"/api/v1/dlq/{dlq_id}/summary",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["dlq_id"] == str(dlq_id)
    assert data["job_id"] == str(job_id)
    assert data["job_type"] == "payment_charge"
    assert data["category"] == "TIMEOUT_ERROR"
    assert "summary" in data and len(data["summary"]) > 0
    assert "root_cause" in data and len(data["root_cause"]) > 0
    assert "suggested_action" in data and len(data["suggested_action"]) > 0
    assert "generated_at" in data


async def test_dlq_summary_endpoint_unauthenticated(
    client: AsyncClient, org_and_project: tuple
):
    """POST /api/v1/dlq/{id}/summary returns 401 without authentication."""
    resp = await client.post(f"/api/v1/dlq/{uuid.uuid4()}/summary")
    assert resp.status_code == 401


async def test_dlq_summary_endpoint_unauthorized(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
):
    """User from another organization receives 403 Forbidden."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-sum-auth")
    queue_id = uuid.UUID(queue["id"])

    _, dlq_id = await _create_dlq_entry(queue_id=queue_id)

    resp = await client.post(
        f"/api/v1/dlq/{dlq_id}/summary",
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


async def test_dlq_summary_endpoint_not_found(
    client: AsyncClient, auth_headers: dict
):
    """Non-existent DLQ ID returns 404 Not Found."""
    non_existent_id = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/dlq/{non_existent_id}/summary",
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_dlq_summary_endpoint_uses_analyzer(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
):
    """Verify endpoint properly delegates to generate_dlq_summary service."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-sum-mock")
    queue_id = uuid.UUID(queue["id"])

    job_id, dlq_id = await _create_dlq_entry(queue_id=queue_id)

    mock_summary_response = DLQSummaryResponse(
        dlq_id=dlq_id,
        job_id=job_id,
        job_type="custom_job",
        category="VALIDATION_ERROR",
        summary="Custom mocked summary",
        root_cause="Custom mocked root cause",
        suggested_action="Custom mocked action",
        generated_at=datetime.now(tz=timezone.utc),
    )

    with patch(
        "app.routers.dlq.generate_dlq_summary",
        new_callable=AsyncMock,
        return_value=mock_summary_response,
    ) as mock_service:
        resp = await client.post(
            f"/api/v1/dlq/{dlq_id}/summary",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "VALIDATION_ERROR"
        assert data["summary"] == "Custom mocked summary"
        mock_service.assert_awaited_once()


async def test_dlq_summary_endpoint_does_not_modify_dlq(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
):
    """Advisory check: Generating a summary must not resolve or alter the DLQ entry."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-sum-nomod")
    queue_id = uuid.UUID(queue["id"])

    job_id, dlq_id = await _create_dlq_entry(queue_id=queue_id)

    resp = await client.post(
        f"/api/v1/dlq/{dlq_id}/summary",
        headers=auth_headers,
    )
    assert resp.status_code == 200

    # Verify DLQ row remains unresolved and unaltered in DB
    async with test_engine.connect() as conn:
        dlq_res = await conn.execute(
            select(dead_letter_queue).where(dead_letter_queue.c.id == dlq_id)
        )
        dlq_row = dlq_res.mappings().one()
        assert dlq_row["resolved"] is False
        assert dlq_row["resolved_at"] is None

        job_res = await conn.execute(select(jobs).where(jobs.c.id == job_id))
        job_row = job_res.mappings().one()
        assert job_row["status"] == "dead_letter"
