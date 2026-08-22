"""pytest tests for Phase 5 Worker Management endpoints and lifecycle behavior."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select

from app.models.tables import (
    job_executions,
    jobs,
    worker_heartbeats,
    worker_queues,
    workers,
)
from app.services.workers import sweep_stale_workers
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _create_test_queue(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "w-queue",
) -> dict:
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": name, "priority": 1, "max_concurrency": 5},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── Registration Tests ───────────────────────────────────────────────────────

async def test_worker_registration(client: AsyncClient) -> None:
    """Worker can register with hostname, pid, concurrency, and metadata."""
    resp = await client.post(
        "/api/v1/workers/register",
        json={
            "hostname": "node-1.cluster.local",
            "pid": 4321,
            "concurrency": 8,
            "metadata": {"version": "1.0.0", "region": "us-east"},
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["hostname"] == "node-1.cluster.local"
    assert data["pid"] == 4321
    assert data["concurrency"] == 8
    assert data["status"] == "idle"
    assert data["metadata"]["version"] == "1.0.0"
    assert "id" in data


# ─── Heartbeat Tests ──────────────────────────────────────────────────────────

async def test_worker_heartbeat_updates_timestamp_and_telemetry(
    client: AsyncClient,
) -> None:
    """Worker heartbeat updates last_heartbeat_at and appends telemetry row."""
    # 1. Register
    reg_resp = await client.post(
        "/api/v1/workers/register",
        json={"hostname": "hb-node", "pid": 111, "concurrency": 5},
    )
    worker_id = reg_resp.json()["id"]

    # 2. Send heartbeat
    hb_resp = await client.post(
        f"/api/v1/workers/{worker_id}/heartbeat",
        json={"active_job_count": 2, "cpu_pct": 24.5, "mem_mb": 512},
    )
    assert hb_resp.status_code == 200
    data = hb_resp.json()
    assert data["status"] == "idle"
    assert data["active_job_count"] == 2

    # 3. Verify row in worker_heartbeats
    async with test_engine.connect() as conn:
        res = await conn.execute(
            select(worker_heartbeats).where(
                worker_heartbeats.c.worker_id == uuid.UUID(worker_id)
            )
        )
        row = res.mappings().first()
        assert row is not None
        assert row["active_job_count"] == 2
        assert float(row["cpu_pct"]) == 24.5
        assert row["mem_mb"] == 512


async def test_worker_heartbeat_busy_transition(client: AsyncClient) -> None:
    """Worker status transitions to busy when active_job_count >= concurrency."""
    reg_resp = await client.post(
        "/api/v1/workers/register",
        json={"hostname": "busy-node", "pid": 222, "concurrency": 3},
    )
    worker_id = reg_resp.json()["id"]

    # Heartbeat at capacity (3 active / 3 concurrency) -> busy
    hb1 = await client.post(
        f"/api/v1/workers/{worker_id}/heartbeat",
        json={"active_job_count": 3},
    )
    assert hb1.status_code == 200
    assert hb1.json()["status"] == "busy"

    # Heartbeat below capacity (1 active / 3 concurrency) -> idle
    hb2 = await client.post(
        f"/api/v1/workers/{worker_id}/heartbeat",
        json={"active_job_count": 1},
    )
    assert hb2.status_code == 200
    assert hb2.json()["status"] == "idle"


# ─── Deregister Tests ─────────────────────────────────────────────────────────

async def test_worker_deregister_and_job_release(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Deregistration sets status to offline and releases claimed/running jobs."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-dereg")
    queue_id = uuid.UUID(queue["id"])

    # 1. Register worker
    reg_resp = await client.post(
        "/api/v1/workers/register",
        json={"hostname": "dereg-node", "concurrency": 2},
    )
    worker_id = uuid.UUID(reg_resp.json()["id"])

    # 2. Insert claimed job and execution assigned to worker
    async with test_engine.connect() as conn:
        job_res = await conn.execute(
            insert(jobs)
            .values(
                queue_id=queue_id,
                type="active_task",
                status="claimed",
                claimed_by=worker_id,
                claimed_at=datetime.now(timezone.utc),
            )
            .returning(jobs.c.id)
        )
        job_id = job_res.scalar_one()

        await conn.execute(
            insert(job_executions).values(
                job_id=job_id,
                worker_id=worker_id,
                attempt_number=1,
                status="running",
            )
        )
        await conn.commit()

    # 3. Deregister worker
    dereg_resp = await client.post(f"/api/v1/workers/{worker_id}/deregister")
    assert dereg_resp.status_code == 200
    assert dereg_resp.json()["status"] == "offline"

    # 4. Verify job released to queued
    async with test_engine.connect() as conn:
        j_res = await conn.execute(select(jobs).where(jobs.c.id == job_id))
        j_row = j_res.mappings().one()
        assert j_row["status"] == "queued"
        assert j_row["claimed_by"] is None

        # Verify execution marked failed
        exec_res = await conn.execute(
            select(job_executions).where(job_executions.c.job_id == job_id)
        )
        exec_row = exec_res.mappings().one()
        assert exec_row["status"] == "failed"


# ─── Worker Details & Listing Tests ───────────────────────────────────────────

async def test_get_worker_detail(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Get single worker detail."""
    reg_resp = await client.post(
        "/api/v1/workers/register",
        json={"hostname": "detail-node", "pid": 333, "concurrency": 4},
    )
    worker_id = reg_resp.json()["id"]

    get_resp = await client.get(f"/api/v1/workers/{worker_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == worker_id
    assert get_resp.json()["hostname"] == "detail-node"


async def test_list_project_workers(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """List workers associated with a project."""
    _, project_id = org_and_project
    await _create_test_queue(client, project_id, auth_headers, "q-proj-w")

    # Register worker
    await client.post(
        "/api/v1/workers/register",
        json={"hostname": "proj-worker-1", "concurrency": 2},
    )

    list_resp = await client.get(
        f"/api/v1/projects/{project_id}/workers", headers=auth_headers
    )
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)


# ─── Worker Queue Assignments Tests ───────────────────────────────────────────

async def test_worker_queue_assignment_and_unassignment(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Assign worker to queues, list assignments, and unassign."""
    _, project_id = org_and_project
    queue1 = await _create_test_queue(client, project_id, auth_headers, "q-assign-1")
    queue2 = await _create_test_queue(client, project_id, auth_headers, "q-assign-2")

    # 1. Register worker
    reg_resp = await client.post(
        "/api/v1/workers/register",
        json={"hostname": "assignable-worker", "concurrency": 5},
    )
    worker_id = reg_resp.json()["id"]

    # 2. Assign to queues
    assign_resp = await client.post(
        f"/api/v1/workers/{worker_id}/queues",
        json={"queue_ids": [queue1["id"], queue2["id"]]},
        headers=auth_headers,
    )
    assert assign_resp.status_code == 201
    assert len(assign_resp.json()) == 2

    # 3. List assigned queues
    list_q_resp = await client.get(
        f"/api/v1/workers/{worker_id}/queues", headers=auth_headers
    )
    assert list_q_resp.status_code == 200
    assert len(list_q_resp.json()) == 2

    # 4. Unassign one queue
    unassign_resp = await client.delete(
        f"/api/v1/workers/{worker_id}/queues/{queue1['id']}", headers=auth_headers
    )
    assert unassign_resp.status_code == 204

    # 5. Verify remaining assignment
    list_q_resp2 = await client.get(
        f"/api/v1/workers/{worker_id}/queues", headers=auth_headers
    )
    assert list_q_resp2.status_code == 200
    assert len(list_q_resp2.json()) == 1


# ─── Stale Worker Sweeper Tests ───────────────────────────────────────────────

async def test_stale_worker_recovery(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Inactive workers (>60s) are marked offline and their jobs recovered."""
    _, project_id = org_and_project
    queue = await _create_test_queue(client, project_id, auth_headers, "q-stale")
    queue_id = uuid.UUID(queue["id"])

    stale_time = datetime.now(timezone.utc) - timedelta(seconds=120)

    # 1. Create a stale worker and an assigned in-flight job
    async with test_engine.connect() as conn:
        w_res = await conn.execute(
            insert(workers)
            .values(
                hostname="crashed-host",
                status="busy",
                concurrency=2,
                last_heartbeat_at=stale_time,
            )
            .returning(workers.c.id)
        )
        stale_worker_id = w_res.scalar_one()

        job_res = await conn.execute(
            insert(jobs)
            .values(
                queue_id=queue_id,
                type="stranded_task",
                status="running",
                claimed_by=stale_worker_id,
                claimed_at=stale_time,
                started_at=stale_time,
            )
            .returning(jobs.c.id)
        )
        stranded_job_id = job_res.scalar_one()

        await conn.execute(
            insert(job_executions).values(
                job_id=stranded_job_id,
                worker_id=stale_worker_id,
                attempt_number=1,
                status="running",
                started_at=stale_time,
            )
        )
        await conn.commit()

    # 2. Run stale worker sweep
    async with test_engine.connect() as conn:
        swept_count = await sweep_stale_workers(conn, timeout_seconds=60)
        assert swept_count >= 1
        await conn.commit()

    # 3. Verify worker is offline
    async with test_engine.connect() as conn:
        w_check = await conn.execute(
            select(workers).where(workers.c.id == stale_worker_id)
        )
        assert w_check.mappings().one()["status"] == "offline"

        # Verify job is recovered to queued
        j_check = await conn.execute(
            select(jobs).where(jobs.c.id == stranded_job_id)
        )
        j_row = j_check.mappings().one()
        assert j_row["status"] == "queued"
        assert j_row["claimed_by"] is None

        # Verify execution attempt marked failed
        e_check = await conn.execute(
            select(job_executions).where(job_executions.c.job_id == stranded_job_id)
        )
        assert e_check.mappings().one()["status"] == "failed"
