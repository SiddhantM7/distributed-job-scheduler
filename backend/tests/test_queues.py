"""pytest tests for Phase 3 queue endpoints.

Coverage:
- POST /projects/{project_id}/queues
- GET  /projects/{project_id}/queues
- GET  /queues/{queue_id}
- PATCH /queues/{queue_id}
- POST /queues/{queue_id}/pause
- POST /queues/{queue_id}/resume
- GET  /queues/{queue_id}/stats
- DELETE /queues/{queue_id}
"""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _create_queue(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "default",
    **kwargs,
) -> dict:
    """Helper: create a queue and assert 201."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": name, **kwargs},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── create queue ─────────────────────────────────────────────────────────────

async def test_create_queue_success(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Creating a queue returns 201 with expected fields."""
    _, project_id = org_and_project
    data = await _create_queue(
        client, project_id, auth_headers, name="my-queue", priority=5, max_concurrency=3
    )
    assert data["name"] == "my-queue"
    assert data["priority"] == 5
    assert data["max_concurrency"] == 3
    assert data["is_paused"] is False
    assert data["project_id"] == project_id


async def test_create_queue_defaults(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Queue created with minimal body uses schema defaults."""
    _, project_id = org_and_project
    data = await _create_queue(client, project_id, auth_headers, name="minimal")
    assert data["priority"] == 0
    assert data["max_concurrency"] == 10


async def test_create_queue_duplicate_name_409(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Duplicate queue name within the same project returns 409."""
    _, project_id = org_and_project
    await _create_queue(client, project_id, auth_headers, name="dup")
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": "dup"},
        headers=auth_headers,
    )
    assert resp.status_code == 409


async def test_create_queue_invalid_concurrency_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """max_concurrency < 1 is rejected at the schema layer."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": "bad", "max_concurrency": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_queue_unauthenticated_401(
    client: AsyncClient, org_and_project: tuple
) -> None:
    """Missing auth returns 401."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues", json={"name": "x"}
    )
    assert resp.status_code == 401


async def test_create_queue_wrong_project_403(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """A user not in the org cannot create a queue (403)."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": "x"},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


# ─── list queues ──────────────────────────────────────────────────────────────

async def test_list_queues_empty(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Listing queues for a new project returns an empty list."""
    _, project_id = org_and_project
    resp = await client.get(
        f"/api/v1/projects/{project_id}/queues", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_queues_returns_created(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Created queues appear in the list."""
    _, project_id = org_and_project
    await _create_queue(client, project_id, auth_headers, name="q1")
    await _create_queue(client, project_id, auth_headers, name="q2")
    resp = await client.get(
        f"/api/v1/projects/{project_id}/queues", headers=auth_headers
    )
    assert resp.status_code == 200
    names = [q["name"] for q in resp.json()]
    assert "q1" in names
    assert "q2" in names


# ─── get queue detail ─────────────────────────────────────────────────────────

async def test_get_queue_includes_stats(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """GET /queues/{id} includes a stats block with all status buckets."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="with-stats")
    resp = await client.get(f"/api/v1/queues/{q['id']}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "stats" in body
    assert body["stats"]["queued"] == 0
    assert body["stats"]["completed"] == 0


async def test_get_queue_not_found_404(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Unknown queue ID returns 404."""
    resp = await client.get(
        f"/api/v1/queues/{uuid.uuid4()}", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_get_queue_wrong_user_403(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """Another user outside the org cannot read the queue."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="private")
    resp = await client.get(f"/api/v1/queues/{q['id']}", headers=second_auth_headers)
    assert resp.status_code == 403


# ─── patch queue ──────────────────────────────────────────────────────────────

async def test_patch_queue_priority(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """PATCH can update queue priority."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="patchable")
    resp = await client.patch(
        f"/api/v1/queues/{q['id']}",
        json={"priority": 99},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["priority"] == 99


async def test_patch_queue_empty_body_noop(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """PATCH with empty body returns the unchanged queue."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="noop")
    resp = await client.patch(
        f"/api/v1/queues/{q['id']}", json={}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["priority"] == q["priority"]


# ─── pause / resume ───────────────────────────────────────────────────────────

async def test_pause_and_resume_queue(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Pause sets is_paused=true; resume sets it back to false."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="togglable")

    pause_resp = await client.post(
        f"/api/v1/queues/{q['id']}/pause", headers=auth_headers
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["is_paused"] is True

    resume_resp = await client.post(
        f"/api/v1/queues/{q['id']}/resume", headers=auth_headers
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["is_paused"] is False


# ─── stats ────────────────────────────────────────────────────────────────────

async def test_queue_stats_empty(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Stats for an empty queue return zero counts and 0.0 rates."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="empty-stats")
    resp = await client.get(
        f"/api/v1/queues/{q['id']}/stats?window=1h", headers=auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_completed"] == 0
    assert body["total_failed"] == 0
    assert body["failure_rate"] == 0.0


async def test_queue_stats_invalid_window_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Unknown window parameter returns 422."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="bad-window")
    resp = await client.get(
        f"/api/v1/queues/{q['id']}/stats?window=3m", headers=auth_headers
    )
    assert resp.status_code == 422


# ─── delete queue ─────────────────────────────────────────────────────────────

async def test_delete_empty_queue_204(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Deleting an empty queue returns 204."""
    _, project_id = org_and_project
    q = await _create_queue(client, project_id, auth_headers, name="deletable")
    resp = await client.delete(f"/api/v1/queues/{q['id']}", headers=auth_headers)
    assert resp.status_code == 204

    # Verify it's gone
    get_resp = await client.get(f"/api/v1/queues/{q['id']}", headers=auth_headers)
    assert get_resp.status_code == 404


async def test_delete_unknown_queue_404(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Deleting a non-existent queue returns 404."""
    resp = await client.delete(
        f"/api/v1/queues/{uuid.uuid4()}", headers=auth_headers
    )
    assert resp.status_code == 404
