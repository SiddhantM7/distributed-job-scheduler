"""Shared pytest fixtures for all Phase 3+ tests.

Architecture:
- Uses a real PostgreSQL instance (the same one Docker Compose provides).
- DATABASE_URL is read from the environment (set in docker-compose.yml).
- Each test creates its own unique org/project so tests are independent.
- An AsyncClient is used against the live FastAPI app via httpx.
- Test engine uses NullPool to prevent asyncpg connection reuse across different asyncio event loops.
"""
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncConnection
from sqlalchemy.pool import NullPool

from app.config import settings
from app.dependencies import get_db
from app.main import app

# Test engine configured with NullPool: connections are opened and closed per request
# on the active event loop, preventing event-loop mismatch across async tests.
test_engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
    echo=False,
)


async def override_get_db() -> AsyncGenerator[AsyncConnection, None]:
    """Test dependency override for get_db using NullPool engine."""
    async with test_engine.connect() as conn:
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Override get_db dependency for every test and clean up after."""
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    await test_engine.dispose()


# ── HTTP client ────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP test client pointed at the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Auth helpers ───────────────────────────────────────────────────────────────

def _unique_email() -> str:
    return f"test-{uuid.uuid4().hex[:8]}@example.com"


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a fresh user and return Bearer headers."""
    email = _unique_email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "name": "Test User"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def second_auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register a second independent user and return Bearer headers."""
    email = _unique_email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "name": "Second User"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Org / project helpers ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def org_and_project(
    client: AsyncClient, auth_headers: dict[str, str]
) -> tuple[str, str]:
    """Create a fresh org and project, return (org_id, project_id)."""
    slug = f"test-org-{uuid.uuid4().hex[:8]}"
    org_resp = await client.post(
        "/api/v1/organizations",
        json={"name": "Test Org", "slug": slug},
        headers=auth_headers,
    )
    assert org_resp.status_code == 201, org_resp.text
    org_id = org_resp.json()["id"]

    proj_resp = await client.post(
        f"/api/v1/organizations/{org_id}/projects",
        json={"name": "Test Project"},
        headers=auth_headers,
    )
    assert proj_resp.status_code == 201, proj_resp.text
    project_id = proj_resp.json()["id"]

    return org_id, project_id
