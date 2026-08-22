"""pytest tests for Phase 6 Dead Letter Queue (DLQ) endpoints and lifecycle behavior."""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select

from app.models.tables import dead_letter_queue, jobs
from app.services.dlq import move_job_to_dlq
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _create_test_queue(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "dlq-queue",
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": name, "priority": 1, "max_concurrency": 5},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── DLQ Tests ────────────────────────────────────────────────────────────────

async def test_list_dlq_empty(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Empty queue returns empty DLQ list with total 0."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-empty")

    resp = await client.get(f"/api/v1/queues/{queue['id']}/dlq", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1


async def test_job_moves_to_dlq_and_payload_snapshot(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Job moving to DLQ updates job status and creates DLQ row with payload snapshot."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-move")
    queue_id = uuid.UUID(queue["id"])

    # 1. Create a job
    create_res = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "failing_task", "payload": {"data": "critical_payload"}, "kind": "immediate"},
        headers=auth_headers,
    )
    job_id = uuid.UUID(create_res.json()["id"])

    # 2. Move job to DLQ via service
    async with test_engine.connect() as conn:
        dlq_row = await move_job_to_dlq(
            db=conn,
            job_id=job_id,
            reason="Max retry attempts exhausted",
            last_error="Connection refused: 503 Service Unavailable",
        )
        await conn.commit()

    assert dlq_row["reason"] == "Max retry attempts exhausted"
    assert dlq_row["payload_snapshot"] == {"data": "critical_payload"}
    assert dlq_row["resolved"] is False

    # 3. Verify original job status updated to dead_letter
    async with test_engine.connect() as conn:
        j_res = await conn.execute(select(jobs).where(jobs.c.id == job_id))
        j_row = j_res.mappings().one()
        assert j_row["status"] == "dead_letter"
        assert j_row["error"] == "Connection refused: 503 Service Unavailable"


async def test_list_dlq_filtering_resolved(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """List DLQ entries filtered by resolved status."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-filter")
    queue_id = uuid.UUID(queue["id"])

    # Insert 2 DLQ entries: 1 unresolved, 1 resolved
    async with test_engine.connect() as conn:
        # Create 2 jobs
        j1 = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="j1", status="dead_letter").returning(jobs.c.id)
        )).scalar_one()
        j2 = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="j2", status="dead_letter").returning(jobs.c.id)
        )).scalar_one()

        await conn.execute(
            insert(dead_letter_queue).values(
                job_id=j1,
                queue_id=queue_id,
                reason="Error 1",
                payload_snapshot={"id": 1},
                failed_attempt_count=5,
                resolved=False,
            )
        )
        await conn.execute(
            insert(dead_letter_queue).values(
                job_id=j2,
                queue_id=queue_id,
                reason="Error 2",
                payload_snapshot={"id": 2},
                failed_attempt_count=5,
                resolved=True,
                resolved_at=datetime.now(timezone.utc),
            )
        )
        await conn.commit()

    # Filter unresolved (resolved=false)
    resp_unres = await client.get(
        f"/api/v1/queues/{queue['id']}/dlq?resolved=false", headers=auth_headers
    )
    assert resp_unres.status_code == 200
    assert resp_unres.json()["total"] == 1
    assert resp_unres.json()["items"][0]["resolved"] is False

    # Filter resolved (resolved=true)
    resp_res = await client.get(
        f"/api/v1/queues/{queue['id']}/dlq?resolved=true", headers=auth_headers
    )
    assert resp_res.status_code == 200
    assert resp_res.json()["total"] == 1
    assert resp_res.json()["items"][0]["resolved"] is True


async def test_get_dlq_detail(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Retrieve single DLQ record detail by ID."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-detail")
    queue_id = uuid.UUID(queue["id"])

    async with test_engine.connect() as conn:
        job_id = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="detail_job", status="dead_letter").returning(jobs.c.id)
        )).scalar_one()

        dlq_id = (await conn.execute(
            insert(dead_letter_queue).values(
                job_id=job_id,
                queue_id=queue_id,
                reason="Network timeout",
                payload_snapshot={"val": 42},
                failed_attempt_count=3,
                resolved=False,
            ).returning(dead_letter_queue.c.id)
        )).scalar_one()
        await conn.commit()

    get_resp = await client.get(f"/api/v1/dlq/{dlq_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["id"] == str(dlq_id)
    assert body["reason"] == "Network timeout"
    assert body["payload_snapshot"] == {"val": 42}


async def test_dlq_resolve_endpoint(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """POST /dlq/{id}/resolve marks entry resolved without creating a job."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-res")
    queue_id = uuid.UUID(queue["id"])

    async with test_engine.connect() as conn:
        job_id = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="res_job", status="dead_letter").returning(jobs.c.id)
        )).scalar_one()

        dlq_id = (await conn.execute(
            insert(dead_letter_queue).values(
                job_id=job_id,
                queue_id=queue_id,
                reason="Unrecoverable format error",
                payload_snapshot={"bad": True},
                failed_attempt_count=1,
                resolved=False,
            ).returning(dead_letter_queue.c.id)
        )).scalar_one()
        await conn.commit()

    res = await client.post(f"/api/v1/dlq/{dlq_id}/resolve", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["resolved"] is True
    assert body["resolved_at"] is not None


async def test_dlq_retry_endpoint(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """POST /dlq/{id}/retry creates a fresh queued job and marks DLQ resolved."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-retry")
    queue_id = uuid.UUID(queue["id"])

    async with test_engine.connect() as conn:
        job_id = (await conn.execute(
            insert(jobs).values(queue_id=queue_id, type="retry_target", status="dead_letter").returning(jobs.c.id)
        )).scalar_one()

        dlq_id = (await conn.execute(
            insert(dead_letter_queue).values(
                job_id=job_id,
                queue_id=queue_id,
                reason="Transient failure exhausted",
                payload_snapshot={"retry_key": "success"},
                failed_attempt_count=5,
                resolved=False,
            ).returning(dead_letter_queue.c.id)
        )).scalar_one()
        await conn.commit()

    retry_resp = await client.post(f"/api/v1/dlq/{dlq_id}/retry", headers=auth_headers)
    assert retry_resp.status_code == 201
    new_job = retry_resp.json()
    assert new_job["type"] == "retry_target"
    assert new_job["status"] == "queued"
    assert new_job["payload"] == {"retry_key": "success"}
    assert new_job["attempt_count"] == 0

    # Verify DLQ entry is now marked resolved
    async with test_engine.connect() as conn:
        d_res = await conn.execute(
            select(dead_letter_queue).where(dead_letter_queue.c.id == dlq_id)
        )
        d_row = d_res.mappings().one()
        assert d_row["resolved"] is True
        assert d_row["resolved_at"] is not None


async def test_dlq_authorization(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """401 for unauthenticated and 403 for unauthorized users."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dlq-auth")
    queue_id = uuid.UUID(queue["id"])

    # Unauthenticated -> 401
    resp401 = await client.get(f"/api/v1/queues/{queue_id}/dlq")
    assert resp401.status_code == 401

    # Unauthorized foreign user -> 403
    resp403 = await client.get(
        f"/api/v1/queues/{queue_id}/dlq", headers=second_auth_headers
    )
    assert resp403.status_code == 403


async def test_dlq_not_found(client: AsyncClient, auth_headers: dict) -> None:
    """Non-existent DLQ entry returns 404."""
    resp404 = await client.get(f"/api/v1/dlq/{uuid.uuid4()}", headers=auth_headers)
    assert resp404.status_code == 404
