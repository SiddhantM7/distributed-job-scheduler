"""AI and heuristic failure analysis service for Dead Letter Queue (DLQ) entries."""
import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import settings
from app.models.tables import dead_letter_queue, job_executions, job_logs, jobs
from app.schemas.dlq import DLQSummaryResponse

logger = logging.getLogger(__name__)


# ─── Heuristic Rule-Based Fallback ────────────────────────────────────────────

def _classify_error_pattern(combined_text: str) -> tuple[str, str, str, str]:
    """Deterministic classification of failure patterns based on error text."""
    lower = combined_text.lower()

    # 1. Timeout errors (Precedence 1)
    if any(k in lower for k in ("timeout", "timed out", "deadline exceeded", "connecttimeout", "readtimeout")):
        category = "TIMEOUT_ERROR"
        summary = "Job execution timed out while awaiting a response or task completion."
        root_cause = "Operation exceeded the allocated time limit during execution or network request."
        suggested_action = "Check downstream service latency, increase queue/job timeout, or verify network stability."

    # 2. HTTP 5xx Server errors (Precedence 2)
    elif any(k in lower for k in (
        "503 service unavailable",
        "502 bad gateway",
        "504 gateway",
        "500 internal",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "status code 5",
        "503 service",
    )):
        category = "HTTP_5XX_SERVER_ERROR"
        summary = "External HTTP service responded with 5xx server-side error."
        root_cause = "Downstream server crashed, overloaded, or gateway proxy failed to route."
        suggested_action = "Verify external dependency health status and consider delaying re-submission."

    # 3. HTTP 4xx Client errors (Precedence 3)
    elif any(k in lower for k in (
        "429 too many",
        "rate limit",
        "400 bad request",
        "401 unauthorized",
        "403 forbidden",
        "404 not found",
        "422 unprocessable",
        "http 400",
        "http 401",
        "http 403",
        "http 404",
        "http 422",
        "http 429",
        "status code 4",
    )):
        category = "HTTP_4XX_CLIENT_ERROR"
        summary = "Upstream HTTP request rejected with client-side 4xx error."
        root_cause = "Authentication failure, invalid payload parameters, rate limiting, or requested resource does not exist."
        suggested_action = "Inspect request headers, API credentials, and payload parameters before retrying."

    # 4. Data validation / Schema errors (Precedence 4)
    elif any(k in lower for k in (
        "validationerror",
        "pydantic",
        "valueerror",
        "invalid input",
        "missing required field",
        "schema mismatch",
        "invalid payload",
    )):
        category = "VALIDATION_ERROR"
        summary = "Task payload failed schema or data validation constraints."
        root_cause = "Input data structure violates required schema, types, or business validation rules."
        suggested_action = "Correct the input payload structure before submitting a new job."

    # 5. Database / Query errors (Precedence 5)
    elif any(k in lower for k in (
        "integrityerror",
        "foreign key",
        "foreignkey",
        "unique constraint",
        "deadlock",
        "violates foreign key",
        "violates unique",
        "relation does not exist",
        "psycopg",
        "asyncpg",
    )):
        category = "DATABASE_ERROR"
        summary = "Database operation failed due to a constraint violation or query error."
        root_cause = "Foreign key mismatch, unique constraint collision, or invalid relational state."
        suggested_action = "Ensure dependent database entities exist and inspect database constraint rules."

    # 6. JSON / Serialization errors (Precedence 6)
    elif any(k in lower for k in (
        "jsondecodeerror",
        "json.decoder",
        "serializationerror",
        "invalid json",
        "decode error",
    )):
        category = "SERIALIZATION_ERROR"
        summary = "Failed to serialize or deserialize JSON data during processing."
        root_cause = "Malformed JSON string or unsupported serialization data type."
        suggested_action = "Validate JSON formatting and payload encoding."

    # 7. Network / Connection errors (Precedence 7)
    elif any(k in lower for k in (
        "econnrefused",
        "connectionrefused",
        "connection reset",
        "failed to connect",
        "getaddrinfo",
        "dns resolution",
        "network is unreachable",
        "host unreachable",
    )):
        category = "NETWORK_ERROR"
        summary = "Network connection failed during task execution."
        root_cause = "Target host unreachable, port closed, or network transport interrupted."
        suggested_action = "Verify downstream host availability, firewall/DNS rules, and network connectivity."

    # 8. Unknown / Generic fallback (Precedence 8)
    else:
        category = "UNKNOWN_ERROR"
        summary = "Job encountered an unclassified execution failure."
        root_cause = combined_text.strip() or "No specific error trace available."
        suggested_action = "Inspect execution logs and payload snapshot to diagnose the failure."

    return category, summary, root_cause, suggested_action


def _build_heuristic_summary(
    dlq_id: uuid.UUID,
    job_id: uuid.UUID,
    job_type: str,
    reason: str,
    last_error: str | None,
    execution_errors: List[str],
    log_snippets: List[str],
) -> DLQSummaryResponse:
    """Produce deterministic fallback summary without calling external AI services."""
    combined_parts = [reason]
    if last_error:
        combined_parts.append(last_error)
    combined_parts.extend(execution_errors)
    combined_parts.extend(log_snippets)
    combined_text = " | ".join(filter(None, combined_parts))

    category, summary, root_cause, suggested_action = _classify_error_pattern(combined_text)

    return DLQSummaryResponse(
        dlq_id=dlq_id,
        job_id=job_id,
        job_type=job_type,
        category=category,
        summary=summary,
        root_cause=root_cause,
        suggested_action=suggested_action,
        generated_at=datetime.now(tz=timezone.utc),
    )


# ─── Context Gathering ────────────────────────────────────────────────────────

async def _gather_dlq_context(
    db: AsyncConnection,
    dlq_id: uuid.UUID,
) -> Dict[str, Any]:
    """Gather relevant failure context without leaking complete raw payloads."""
    # 1. Fetch DLQ row
    dlq_res = await db.execute(
        select(dead_letter_queue).where(dead_letter_queue.c.id == dlq_id)
    )
    dlq_row = dlq_res.mappings().first()
    if dlq_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "DLQ_ENTRY_NOT_FOUND", "message": "DLQ entry not found", "details": {}},
        )

    # 2. Fetch Job row
    job_res = await db.execute(
        select(jobs).where(jobs.c.id == dlq_row["job_id"])
    )
    job_row = job_res.mappings().first()
    job_type = job_row["type"] if job_row else "unknown"

    # 3. Fetch execution attempt errors
    exec_res = await db.execute(
        select(job_executions.c.attempt_number, job_executions.c.status, job_executions.c.error, job_executions.c.duration_ms)
        .where(job_executions.c.job_id == dlq_row["job_id"])
        .order_by(job_executions.c.attempt_number.asc())
    )
    executions = exec_res.mappings().all()
    execution_errors = [e["error"] for e in executions if e["error"]]

    # 4. Fetch error/warn logs (limit to 10 most recent)
    logs_res = await db.execute(
        select(job_logs.c.level, job_logs.c.message)
        .join(job_executions, job_executions.c.id == job_logs.c.job_execution_id)
        .where(
            job_executions.c.job_id == dlq_row["job_id"],
            job_logs.c.level.in_(("error", "warn")),
        )
        .order_by(job_logs.c.id.desc())
        .limit(10)
    )
    log_snippets = [f"[{r['level'].upper()}] {r['message']}" for r in logs_res.mappings().all()]

    # Extract schema keys only (avoid sending sensitive user payload data to external AI)
    payload_snapshot = dlq_row["payload_snapshot"] or {}
    payload_keys = list(payload_snapshot.keys()) if isinstance(payload_snapshot, dict) else []

    return {
        "dlq_id": dlq_row["id"],
        "job_id": dlq_row["job_id"],
        "job_type": job_type,
        "reason": dlq_row["reason"],
        "last_error": dlq_row["last_error"],
        "failed_attempt_count": dlq_row["failed_attempt_count"],
        "execution_errors": execution_errors,
        "log_snippets": log_snippets,
        "payload_keys": payload_keys,
    }


# ─── AI Failure Analysis Service ──────────────────────────────────────────────

async def generate_dlq_summary(
    db: AsyncConnection,
    dlq_id: uuid.UUID,
) -> DLQSummaryResponse:
    """Analyze DLQ entry failure using NVIDIA NIM / OpenAI-compatible LLM with deterministic fallback."""
    context = await _gather_dlq_context(db, dlq_id)

    # If no LLM API key configured, use deterministic heuristic analyzer
    if not settings.LLM_API_KEY:
        return _build_heuristic_summary(
            dlq_id=context["dlq_id"],
            job_id=context["job_id"],
            job_type=context["job_type"],
            reason=context["reason"],
            last_error=context["last_error"],
            execution_errors=context["execution_errors"],
            log_snippets=context["log_snippets"],
        )

    # Attempt AI analysis via OpenAI-compatible SDK (e.g. NVIDIA NIM)
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
            timeout=15.0,
        )

        prompt_data = {
            "job_type": context["job_type"],
            "dlq_reason": context["reason"],
            "last_error": context["last_error"],
            "failed_attempts": context["failed_attempt_count"],
            "attempt_errors": context["execution_errors"],
            "recent_error_logs": context["log_snippets"],
            "payload_fields": context["payload_keys"],
        }

        system_instruction = (
            "You are an expert distributed systems reliability engineer. "
            "Analyze the provided Dead Letter Queue (DLQ) failure data. "
            "Respond ONLY with a valid JSON object containing exactly four string keys: "
            "'category' (e.g. TIMEOUT_ERROR, NETWORK_ERROR, VALIDATION_ERROR, HTTP_4XX_CLIENT_ERROR, HTTP_5XX_SERVER_ERROR, DATABASE_ERROR, or SERIALIZATION_ERROR), "
            "'summary' (a concise 1-2 sentence executive overview of what failed), "
            "'root_cause' (technical root cause analysis based on the error trace and logs), and "
            "'suggested_action' (concrete recommendation for the operator/developer to resolve the issue)."
        )

        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": json.dumps(prompt_data)},
            ],
            temperature=0.2,
            max_tokens=500,
        )

        raw_content = response.choices[0].message.content or ""
        # Clean potential markdown wrappers
        clean_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_content.strip())
        parsed = json.loads(clean_json)

        # Validate required fields
        if all(k in parsed and isinstance(parsed[k], str) and parsed[k].strip() for k in ("category", "summary", "root_cause", "suggested_action")):
            return DLQSummaryResponse(
                dlq_id=context["dlq_id"],
                job_id=context["job_id"],
                job_type=context["job_type"],
                category=parsed["category"].strip().upper(),
                summary=parsed["summary"].strip(),
                root_cause=parsed["root_cause"].strip(),
                suggested_action=parsed["suggested_action"].strip(),
                generated_at=datetime.now(tz=timezone.utc),
            )

    except Exception as exc:
        logger.warning(f"LLM failure analysis encountered error, using fallback: {exc}")

    # Graceful fallback on any provider error or malformed response
    return _build_heuristic_summary(
        dlq_id=context["dlq_id"],
        job_id=context["job_id"],
        job_type=context["job_type"],
        reason=context["reason"],
        last_error=context["last_error"],
        execution_errors=context["execution_errors"],
        log_snippets=context["log_snippets"],
    )
