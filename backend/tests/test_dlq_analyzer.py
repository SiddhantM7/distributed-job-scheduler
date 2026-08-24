"""Unit and integration tests for AI/heuristic DLQ failure analysis service."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import insert

from app.config import settings
from app.models.tables import dead_letter_queue, job_executions, job_logs, jobs, organizations, projects, queues
from app.services.dlq_analyzer import generate_dlq_summary
from tests.conftest import test_engine

pytestmark = pytest.mark.asyncio


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _setup_dlq_test_fixture(
    reason: str = "Max retries exhausted",
    last_error: str = "Connection timeout after 30s",
    log_message: str | None = None,
) -> uuid.UUID:
    """Insert complete test fixture in database and return dlq_id."""
    effective_log = log_message if log_message is not None else last_error
    async with test_engine.connect() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            insert(organizations).values(
                id=org_id,
                name="AI Test Org",
                slug=f"ai-org-{uuid.uuid4().hex[:8]}",
            )
        )

        proj_id = uuid.uuid4()
        await conn.execute(
            insert(projects).values(
                id=proj_id,
                organization_id=org_id,
                name=f"AI Proj-{uuid.uuid4().hex[:8]}",
            )
        )

        queue_id = uuid.uuid4()
        await conn.execute(
            insert(queues).values(
                id=queue_id,
                project_id=proj_id,
                name="ai-queue",
            )
        )

        job_id = uuid.uuid4()
        await conn.execute(
            insert(jobs).values(
                id=job_id,
                queue_id=queue_id,
                type="process_webhook",
                payload={"webhook_url": "https://api.example.com", "secret_token": "hidden"},
                status="dead_letter",
                error=last_error,
                attempt_count=5,
                max_attempts=5,
            )
        )

        exec_res = await conn.execute(
            insert(job_executions).values(
                job_id=job_id,
                attempt_number=1,
                status="failed",
                error=last_error,
                duration_ms=30000,
            ).returning(job_executions.c.id)
        )
        exec_id = exec_res.scalar_one()

        if effective_log:
            await conn.execute(
                insert(job_logs).values(
                    job_execution_id=exec_id,
                    level="error",
                    message=effective_log,
                )
            )

        dlq_id = uuid.uuid4()
        await conn.execute(
            insert(dead_letter_queue).values(
                id=dlq_id,
                job_id=job_id,
                queue_id=queue_id,
                reason=reason,
                last_error=last_error,
                payload_snapshot={"webhook_url": "https://api.example.com", "secret_token": "hidden"},
                failed_attempt_count=5,
                resolved=False,
            )
        )
        await conn.commit()
        return dlq_id


# ─── Tests ────────────────────────────────────────────────────────────────────

async def test_dlq_summary_llm_success():
    """Verify successful AI analysis using mocked OpenAI/NVIDIA client."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Rate limit exceeded",
        last_error="HTTP 429 Too Many Requests: Rate limit exceeded",
    )

    mock_llm_response = {
        "category": "HTTP_4XX_CLIENT_ERROR",
        "summary": "The webhook job was throttled due to upstream rate limits.",
        "root_cause": "The external API returned HTTP 429 Too Many Requests across 5 consecutive attempts.",
        "suggested_action": "Reduce request concurrency or request a higher rate limit quota from the provider.",
    }

    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(mock_llm_response)
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client_instance = MagicMock()
    mock_client_instance.chat.completions.create.return_value = mock_completion

    with patch.object(settings, "LLM_API_KEY", "mock-nvidia-key"):
        with patch("openai.OpenAI", return_value=mock_client_instance):
            async with test_engine.connect() as conn:
                res = await generate_dlq_summary(conn, dlq_id)

    assert res.dlq_id == dlq_id
    assert res.job_type == "process_webhook"
    assert res.category == "HTTP_4XX_CLIENT_ERROR"
    assert "throttled" in res.summary
    assert "HTTP 429" in res.root_cause
    assert "concurrency" in res.suggested_action
    assert isinstance(res.generated_at, datetime)


async def test_dlq_summary_missing_api_key_fallback():
    """When LLM_API_KEY is not set, deterministic heuristic fallback is used."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Job failed permanently",
        last_error="ConnectTimeout: Request timed out after 30000ms",
    )

    with patch.object(settings, "LLM_API_KEY", None):
        async with test_engine.connect() as conn:
            res = await generate_dlq_summary(conn, dlq_id)

    assert res.dlq_id == dlq_id
    assert res.category == "TIMEOUT_ERROR"
    assert "timed out" in res.summary
    assert "timeout" in res.suggested_action.lower()


async def test_dlq_summary_network_error_fallback():
    """Heuristic categorizes ECONNREFUSED as NETWORK_ERROR."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Max retries reached",
        last_error="ConnectionRefusedError: [Errno 111] ECONNREFUSED 127.0.0.1:8080",
    )

    with patch.object(settings, "LLM_API_KEY", None):
        async with test_engine.connect() as conn:
            res = await generate_dlq_summary(conn, dlq_id)

    assert res.category == "NETWORK_ERROR"
    assert "network" in res.summary.lower()


async def test_dlq_summary_http_5xx_fallback():
    """Heuristic categorizes 503 Service Unavailable as HTTP_5XX_SERVER_ERROR."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Upstream outage",
        last_error="HTTP 503 Service Unavailable: Server busy",
    )

    with patch.object(settings, "LLM_API_KEY", None):
        async with test_engine.connect() as conn:
            res = await generate_dlq_summary(conn, dlq_id)

    assert res.category == "HTTP_5XX_SERVER_ERROR"
    assert "5xx" in res.summary.lower()


async def test_dlq_summary_validation_error_fallback():
    """Heuristic categorizes ValidationError as VALIDATION_ERROR."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Invalid payload",
        last_error="pydantic_core._pydantic_core.ValidationError: 1 validation error for JobPayload",
    )

    with patch.object(settings, "LLM_API_KEY", None):
        async with test_engine.connect() as conn:
            res = await generate_dlq_summary(conn, dlq_id)

    assert res.category == "VALIDATION_ERROR"
    assert "validation" in res.summary.lower()


async def test_dlq_summary_database_error_fallback():
    """Heuristic categorizes IntegrityError as DATABASE_ERROR."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="DB constraint failed",
        last_error="IntegrityError: insert or update on table violates foreign key constraint",
    )

    with patch.object(settings, "LLM_API_KEY", None):
        async with test_engine.connect() as conn:
            res = await generate_dlq_summary(conn, dlq_id)

    assert res.category == "DATABASE_ERROR"
    assert "database" in res.summary.lower()


async def test_dlq_summary_json_serialization_fallback():
    """Heuristic categorizes JSONDecodeError as SERIALIZATION_ERROR."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Parse failure",
        last_error="json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
    )

    with patch.object(settings, "LLM_API_KEY", None):
        async with test_engine.connect() as conn:
            res = await generate_dlq_summary(conn, dlq_id)

    assert res.category == "SERIALIZATION_ERROR"
    assert "json" in res.summary.lower()


async def test_dlq_summary_malformed_llm_response_fallback():
    """If LLM returns unparseable content, fallback handles it cleanly."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Timeout",
        last_error="ConnectTimeout: Request timed out",
    )

    mock_choice = MagicMock()
    mock_choice.message.content = "Sorry, I cannot answer as JSON: error here"
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    mock_client_instance = MagicMock()
    mock_client_instance.chat.completions.create.return_value = mock_completion

    with patch.object(settings, "LLM_API_KEY", "mock-nvidia-key"):
        with patch("openai.OpenAI", return_value=mock_client_instance):
            async with test_engine.connect() as conn:
                res = await generate_dlq_summary(conn, dlq_id)

    # Clean fallback
    assert res.dlq_id == dlq_id
    assert res.category == "TIMEOUT_ERROR"


async def test_dlq_summary_provider_exception_fallback():
    """If LLM raises network/authentication exception, fallback handles it cleanly."""
    dlq_id = await _setup_dlq_test_fixture(
        reason="Network error",
        last_error="ConnectionRefusedError: Connection refused",
    )

    mock_client_instance = MagicMock()
    mock_client_instance.chat.completions.create.side_effect = RuntimeError("API service offline")

    with patch.object(settings, "LLM_API_KEY", "mock-nvidia-key"):
        with patch("openai.OpenAI", return_value=mock_client_instance):
            async with test_engine.connect() as conn:
                res = await generate_dlq_summary(conn, dlq_id)

    # Clean fallback
    assert res.dlq_id == dlq_id
    assert res.category == "NETWORK_ERROR"


async def test_dlq_summary_not_found_404():
    """Unknown DLQ ID raises 404 HTTPException."""
    async with test_engine.connect() as conn:
        with pytest.raises(Exception) as exc_info:
            await generate_dlq_summary(conn, uuid.uuid4())
        assert "404" in str(exc_info.value)
