"""pytest tests for Phase 3 retry policy endpoints.

Coverage:
- POST /projects/{project_id}/retry-policies
- GET  /projects/{project_id}/retry-policies
- PATCH /retry-policies/{id}
"""
import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _create_policy(
    client: AsyncClient,
    project_id: str,
    headers: dict,
    name: str = "default-policy",
    **kwargs,
) -> dict:
    """Helper: create a retry policy and assert 201."""
    payload = {
        "name": name,
        "strategy": "exponential",
        "base_delay_seconds": 5,
        "max_attempts": 3,
        **kwargs,
    }
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ─── create ───────────────────────────────────────────────────────────────────

async def test_create_retry_policy_success(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Creating a retry policy returns 201 with expected fields."""
    _, project_id = org_and_project
    data = await _create_policy(
        client,
        project_id,
        auth_headers,
        name="exp-policy",
        strategy="exponential",
        base_delay_seconds=10,
        max_delay_seconds=120,
        multiplier="2.5",
        max_attempts=5,
    )
    assert data["name"] == "exp-policy"
    assert data["strategy"] == "exponential"
    assert data["base_delay_seconds"] == 10
    assert data["max_delay_seconds"] == 120
    assert data["max_attempts"] == 5
    assert data["project_id"] == project_id


async def test_create_retry_policy_fixed_strategy(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Fixed strategy retry policy is created correctly."""
    _, project_id = org_and_project
    data = await _create_policy(
        client, project_id, auth_headers, name="fixed", strategy="fixed",
        base_delay_seconds=30, max_attempts=3,
    )
    assert data["strategy"] == "fixed"


async def test_create_retry_policy_invalid_strategy_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Unknown strategy value is rejected with 422."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json={"name": "bad", "strategy": "random", "base_delay_seconds": 5, "max_attempts": 3},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_retry_policy_negative_base_delay_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """base_delay_seconds < 0 is rejected with 422."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json={"name": "neg", "strategy": "fixed", "base_delay_seconds": -1, "max_attempts": 3},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_retry_policy_max_delay_less_than_base_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """max_delay_seconds < base_delay_seconds is rejected with 422."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json={
            "name": "bad-delays",
            "strategy": "exponential",
            "base_delay_seconds": 60,
            "max_delay_seconds": 10,
            "max_attempts": 3,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_retry_policy_max_attempts_zero_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """max_attempts < 1 is rejected with 422."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json={"name": "zero-attempts", "strategy": "fixed", "base_delay_seconds": 5, "max_attempts": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_retry_policy_unauthenticated_401(
    client: AsyncClient, org_and_project: tuple
) -> None:
    """Missing auth returns 401."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json={"name": "x", "strategy": "fixed", "base_delay_seconds": 5, "max_attempts": 3},
    )
    assert resp.status_code == 401


async def test_create_retry_policy_wrong_user_403(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """User outside the org cannot create a retry policy (403)."""
    _, project_id = org_and_project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/retry-policies",
        json={"name": "x", "strategy": "fixed", "base_delay_seconds": 5, "max_attempts": 3},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


# ─── list ─────────────────────────────────────────────────────────────────────

async def test_list_retry_policies_empty(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Listing policies for a new project returns an empty list."""
    _, project_id = org_and_project
    resp = await client.get(
        f"/api/v1/projects/{project_id}/retry-policies", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_retry_policies_returns_created(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """Created policies appear in the list."""
    _, project_id = org_and_project
    await _create_policy(client, project_id, auth_headers, name="p1")
    await _create_policy(client, project_id, auth_headers, name="p2")
    resp = await client.get(
        f"/api/v1/projects/{project_id}/retry-policies", headers=auth_headers
    )
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "p1" in names
    assert "p2" in names


async def test_list_retry_policies_wrong_user_403(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """User outside the org cannot list policies (403)."""
    _, project_id = org_and_project
    resp = await client.get(
        f"/api/v1/projects/{project_id}/retry-policies", headers=second_auth_headers
    )
    assert resp.status_code == 403


# ─── patch ────────────────────────────────────────────────────────────────────

async def test_patch_retry_policy_name(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """PATCH can rename a retry policy."""
    _, project_id = org_and_project
    p = await _create_policy(client, project_id, auth_headers, name="old-name")
    resp = await client.patch(
        f"/api/v1/retry-policies/{p['id']}",
        json={"name": "new-name"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "new-name"


async def test_patch_retry_policy_strategy(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """PATCH can change the retry strategy."""
    _, project_id = org_and_project
    p = await _create_policy(client, project_id, auth_headers, name="strat-change")
    resp = await client.patch(
        f"/api/v1/retry-policies/{p['id']}",
        json={"strategy": "linear"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["strategy"] == "linear"


async def test_patch_retry_policy_empty_body_noop(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """PATCH with empty body returns the unchanged policy."""
    _, project_id = org_and_project
    p = await _create_policy(client, project_id, auth_headers, name="noop-policy")
    resp = await client.patch(
        f"/api/v1/retry-policies/{p['id']}", json={}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "noop-policy"


async def test_patch_retry_policy_invalid_delay_range_422(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """PATCH that would make max_delay < base_delay returns 422."""
    _, project_id = org_and_project
    p = await _create_policy(
        client, project_id, auth_headers, name="delay-range",
        base_delay_seconds=60, max_delay_seconds=120,
    )
    resp = await client.patch(
        f"/api/v1/retry-policies/{p['id']}",
        json={"max_delay_seconds": 5},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_patch_retry_policy_not_found_404(
    client: AsyncClient, auth_headers: dict
) -> None:
    """Patching a non-existent policy returns 404."""
    resp = await client.patch(
        f"/api/v1/retry-policies/{uuid.uuid4()}",
        json={"name": "ghost"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


async def test_patch_retry_policy_wrong_user_403(
    client: AsyncClient,
    auth_headers: dict,
    second_auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """User outside the org cannot patch a retry policy (403)."""
    _, project_id = org_and_project
    p = await _create_policy(client, project_id, auth_headers, name="other-user")
    resp = await client.patch(
        f"/api/v1/retry-policies/{p['id']}",
        json={"name": "hacked"},
        headers=second_auth_headers,
    )
    assert resp.status_code == 403


# ─── queue + retry policy integration ────────────────────────────────────────

async def test_create_queue_with_retry_policy(
    client: AsyncClient, auth_headers: dict, org_and_project: tuple
) -> None:
    """A queue can be created with a default_retry_policy_id."""
    _, project_id = org_and_project
    policy = await _create_policy(client, project_id, auth_headers, name="linked-policy")

    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": "linked-queue", "default_retry_policy_id": policy["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["default_retry_policy_id"] == policy["id"]


async def test_create_queue_with_foreign_retry_policy_422(
    client: AsyncClient,
    auth_headers: dict,
    org_and_project: tuple,
) -> None:
    """Using a retry policy from a different project returns 422."""
    _, project_id = org_and_project
    # Use a random UUID that doesn't belong to this project
    resp = await client.post(
        f"/api/v1/projects/{project_id}/queues",
        json={"name": "bad-policy-queue", "default_retry_policy_id": str(uuid.uuid4())},
        headers=auth_headers,
    )
    assert resp.status_code == 422
