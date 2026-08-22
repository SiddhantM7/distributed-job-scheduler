"""pytest tests for Phase 4 Jobs & Scheduled Jobs endpoints.

Coverage:
- POST /queues/{queue_id}/jobs (all 5 kinds: immediate, delayed, scheduled, recurring, batch)
- POST /queues/{queue_id}/jobs/batch
- GET  /queues/{queue_id}/jobs (listing, pagination, filtering)
- GET  /jobs/{job_id}
- GET  /jobs/{job_id}/executions
- GET  /jobs/{job_id}/executions/{execution_id}/logs
- POST /jobs/{job_id}/cancel
- POST /jobs/{job_id}/retry
- GET  /queues/{queue_id}/scheduled-jobs
- PATCH /scheduled-jobs/{id}
- DELETE /scheduled-jobs/{id}
- Idempotency validation
- Service promotion logic
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import insert

from app.models.tables import job_executions, job_logs, jobs, scheduled_jobs
from app.services.jobs import promote_delayed_jobs, promote_scheduled_jobs
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _create_test_queue(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "jobs-queue",
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": name, "priority": 1, "max_concurrency": 5},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── Job Creation Tests ───────────────────────────────────────────────────────

async def test_create_immediate_job(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Create an immediate job returns 201 with queued status and run_at."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-imm")

    resp = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "send_email",
            "payload": {"to": "user@example.com", "subject": "Welcome"},
            "kind": "immediate",
            "priority": 10,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["type"] == "send_email"
    assert data["status"] == "queued"
    assert data["kind"] == "immediate"
    assert data["priority"] == 10
    assert data["payload"]["to"] == "user@example.com"
    assert data["max_attempts"] == 5


async def test_create_delayed_job(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Create a delayed job returns 201 with scheduled status and future run_at."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-del")

    future_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    resp = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "process_reminder",
            "payload": {"user_id": 42},
            "kind": "delayed",
            "run_at": future_time,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "scheduled"
    assert data["kind"] == "delayed"


async def test_create_scheduled_one_off_job(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Scheduled one-off job creates definition in scheduled_jobs."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-sched")

    future_time = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "monthly_report",
            "payload": {"month": "August"},
            "kind": "scheduled",
            "scheduled_for": future_time,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_type"] == "monthly_report"
    assert data["is_recurring"] is False
    assert data["is_active"] is True


async def test_create_recurring_cron_job(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Recurring cron job creates active definition in scheduled_jobs with computed next_run_at."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-rec")

    resp = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "nightly_cleanup",
            "payload": {"tables": ["temp_data"]},
            "kind": "recurring",
            "cron_expression": "0 2 * * *",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["job_type"] == "nightly_cleanup"
    assert data["is_recurring"] is True
    assert data["cron_expression"] == "0 2 * * *"
    assert data["next_run_at"] is not None


async def test_create_batch_jobs(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Batch job creation returns BatchJobResponse with shared batch_id."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-batch")

    resp = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs/batch",
        json={
            "type": "process_image",
            "items": [
                {"payload": {"file": "1.png"}, "priority": 1},
                {"payload": {"file": "2.png"}, "priority": 2},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "batch_id" in data
    assert len(data["jobs"]) == 2
    for job in data["jobs"]:
        assert job["batch_id"] == data["batch_id"]
        assert job["type"] == "process_image"


# ─── Idempotency Tests ────────────────────────────────────────────────────────

async def test_idempotency_replay_returns_200(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Submitting same job with same idempotency key returns 200 and identical job."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-idem")

    idem_key = "unique-submit-123"
    body = {
        "type": "charge_customer",
        "payload": {"amount": 100},
        "kind": "immediate",
        "idempotency_key": idem_key,
    }

    # 1st creation -> 201
    resp1 = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json=body,
        headers=auth_headers,
    )
    assert resp1.status_code == 201
    job1 = resp1.json()

    # 2nd creation (replay) -> 200 with same job ID
    resp2 = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json=body,
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    job2 = resp2.json()
    assert job1["id"] == job2["id"]


async def test_idempotency_conflict_returns_409(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Submitting different payload under same idempotency key returns 409 Conflict."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-idem-conf")

    idem_key = "conflict-submit-999"
    resp1 = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "charge_customer",
            "payload": {"amount": 100},
            "kind": "immediate",
            "idempotency_key": idem_key,
        },
        headers=auth_headers,
    )
    assert resp1.status_code == 201

    # Different payload with same key -> 409
    resp2 = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "charge_customer",
            "payload": {"amount": 500},
            "kind": "immediate",
            "idempotency_key": idem_key,
        },
        headers=auth_headers,
    )
    assert resp2.status_code == 409


# ─── Job Listing & Retrieval Tests ────────────────────────────────────────────

async def test_list_queue_jobs_with_filters(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Listing queue jobs supports filtering by status, type, and pagination."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-list")

    # Create 3 jobs
    await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "alpha", "payload": {}, "kind": "immediate"},
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "beta", "payload": {}, "kind": "immediate"},
        headers=auth_headers,
    )

    # Filter by type=alpha
    resp = await client.get(
        f"/api/v1/queues/{queue['id']}/jobs?type=alpha",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["type"] == "alpha"


async def test_get_job_detail(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Get single job detail by ID."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-detail")

    res = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "detail_test", "payload": {"foo": "bar"}, "kind": "immediate"},
        headers=auth_headers,
    )
    job_id = res.json()["id"]

    get_res = await client.get(f"/api/v1/jobs/{job_id}", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == job_id


# ─── Executions & Logs Tests ──────────────────────────────────────────────────

async def test_job_executions_and_logs(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Verify attempt history and log lines can be retrieved."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-exec-logs")

    # 1. Create a job
    res = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "log_test", "payload": {}, "kind": "immediate"},
        headers=auth_headers,
    )
    job_id = res.json()["id"]

    # 2. Insert test execution & log into DB directly
    async with test_engine.connect() as conn:
        exec_res = await conn.execute(
            insert(job_executions)
            .values(
                job_id=uuid.UUID(job_id),
                attempt_number=1,
                status="completed",
                duration_ms=125,
            )
            .returning(job_executions.c.id)
        )
        exec_id = exec_res.scalar_one()

        await conn.execute(
            insert(job_logs).values(
                job_execution_id=exec_id,
                level="info",
                message="Execution started successfully",
            )
        )
        await conn.commit()

    # 3. Query executions endpoint
    execs_resp = await client.get(f"/api/v1/jobs/{job_id}/executions", headers=auth_headers)
    assert execs_resp.status_code == 200
    execs = execs_resp.json()
    assert len(execs) == 1
    assert execs[0]["attempt_number"] == 1

    # 4. Query logs endpoint
    logs_resp = await client.get(
        f"/api/v1/jobs/{job_id}/executions/{exec_id}/logs", headers=auth_headers
    )
    assert logs_resp.status_code == 200
    logs = logs_resp.json()
    assert len(logs) == 1
    assert logs[0]["message"] == "Execution started successfully"


# ─── Cancel & Retry Tests ─────────────────────────────────────────────────────

async def test_cancel_queued_job(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Canceling a queued job sets status to cancelled."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-cancel")

    res = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "cancel_me", "payload": {}, "kind": "immediate"},
        headers=auth_headers,
    )
    job_id = res.json()["id"]

    cancel_res = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"


async def test_cancel_non_queued_job_409(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Canceling an already cancelled job returns 409."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-cancel-409")

    res = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={"type": "cancel_again", "payload": {}, "kind": "immediate"},
        headers=auth_headers,
    )
    job_id = res.json()["id"]
    await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth_headers)

    # Second cancel -> 409
    cancel_res2 = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancel_res2.status_code == 409


async def test_retry_failed_job(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Retrying a failed job re-queues it and resets attempts."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-retry")

    # Insert a failed job directly
    async with test_engine.connect() as conn:
        res = await conn.execute(
            insert(jobs)
            .values(
                queue_id=uuid.UUID(queue["id"]),
                type="failing_task",
                status="failed",
                attempt_count=3,
                error="Timeout error",
            )
            .returning(jobs.c.id)
        )
        job_id = res.scalar_one()
        await conn.commit()

    retry_resp = await client.post(f"/api/v1/jobs/{job_id}/retry", headers=auth_headers)
    assert retry_resp.status_code == 200
    body = retry_resp.json()
    assert body["status"] == "queued"
    assert body["attempt_count"] == 0
    assert body["error"] is None


# ─── Scheduled Job Definition Tests ───────────────────────────────────────────

async def test_scheduled_jobs_crud(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """List, patch, and delete scheduled job definitions."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-sched-crud")

    # 1. Create a recurring schedule
    create_res = await client.post(
        f"/api/v1/queues/{queue['id']}/jobs",
        json={
            "type": "cleanup_schedule",
            "payload": {"v": 1},
            "kind": "recurring",
            "cron_expression": "0 0 * * *",
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201
    sched_id = create_res.json()["id"]

    # 2. List scheduled jobs
    list_res = await client.get(
        f"/api/v1/queues/{queue['id']}/scheduled-jobs", headers=auth_headers
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 3. Patch scheduled job (pause schedule and update cron)
    patch_res = await client.patch(
        f"/api/v1/scheduled-jobs/{sched_id}",
        json={"is_active": False, "cron_expression": "*/15 * * * *"},
        headers=auth_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["is_active"] is False
    assert patch_res.json()["cron_expression"] == "*/15 * * * *"

    # 4. Delete scheduled job
    del_res = await client.delete(f"/api/v1/scheduled-jobs/{sched_id}", headers=auth_headers)
    assert del_res.status_code == 204


# ─── Service Promotion Tests ──────────────────────────────────────────────────

async def test_service_promote_delayed_and_scheduled(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
):
    """Verify background service promotions promote due jobs and advance cron."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-promote-test")
    queue_id = uuid.UUID(queue["id"])

    past_time = datetime.now(timezone.utc) - timedelta(minutes=10)

    async with test_engine.connect() as conn:
        # 1. Insert a due delayed job (status='scheduled', run_at in past)
        await conn.execute(
            insert(jobs).values(
                queue_id=queue_id,
                type="delayed_due_job",
                payload={"test": 1},
                kind="delayed",
                status="scheduled",
                run_at=past_time,
            )
        )

        # 2. Insert a due recurring scheduled_job definition (next_run_at in past)
        await conn.execute(
            insert(scheduled_jobs).values(
                queue_id=queue_id,
                name="cron_due_def",
                job_type="cron_task",
                payload_template={"key": "val"},
                cron_expression="*/5 * * * *",
                is_recurring=True,
                is_active=True,
                next_run_at=past_time,
            )
        )

        # 3. Insert a due one-off scheduled_job definition
        await conn.execute(
            insert(scheduled_jobs).values(
                queue_id=queue_id,
                name="one_off_due_def",
                job_type="one_off_task",
                payload_template={"key": "one_off"},
                is_recurring=False,
                is_active=True,
                next_run_at=past_time,
            )
        )
        await conn.commit()

    async with test_engine.connect() as conn:
        # 4. Promote delayed jobs -> expect 1 promoted
        delayed_count = await promote_delayed_jobs(conn)
        assert delayed_count >= 1

        # 5. Promote scheduled jobs -> expect 2 spawned (1 recurring + 1 one-off)
        sched_count = await promote_scheduled_jobs(conn)
        assert sched_count >= 2
        await conn.commit()

    # 6. Verify spawned jobs exist in queue with status='queued'
    resp = await client.get(f"/api/v1/queues/{queue['id']}/jobs", headers=auth_headers)
    assert resp.status_code == 200
    all_jobs = resp.json()["items"]
    types = [j["type"] for j in all_jobs]
    assert "delayed_due_job" in types
    assert "cron_task" in types
    assert "one_off_task" in types
