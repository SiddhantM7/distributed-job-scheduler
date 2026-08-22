# API Specification — Distributed Job Scheduler

Base path: `/api/v1`. Auth: `Authorization: Bearer <JWT>` on every route except `/auth/*`.
Once the backend is built, this hand-written spec is superseded by FastAPI's
auto-generated OpenAPI schema at `/docs` — this document is the design-time contract.

## Conventions

- **Pagination**: `?page=1&page_size=20` (default 20, max 100). Responses wrap lists as:
  ```json
  { "items": [...], "page": 1, "page_size": 20, "total": 137 }
  ```
- **Filtering**: resource-specific query params, e.g. `GET /jobs?status=failed&queue_id=...`.
- **Errors**: consistent envelope on every non-2xx response:
  ```json
  { "error": { "code": "JOB_NOT_FOUND", "message": "Job abc123 does not exist", "details": {} } }
  ```
- **Idempotent job creation**: clients may send an `Idempotency-Key` header (or `idempotency_key` in the body) on `POST /queues/{id}/jobs`; a repeat with the same key returns the original job (200) instead of creating a duplicate (201).

## Auth

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create a user account. |
| POST | `/auth/login` | Exchange credentials for an access + refresh token. |
| POST | `/auth/refresh` | Exchange a refresh token for a new access token. |
| GET | `/auth/me` | Current user profile + org memberships. |

## Organizations & Projects

| Method | Path | Description |
|---|---|---|
| POST | `/organizations` | Create an organization (creator becomes `owner`). |
| GET | `/organizations` | List organizations the user belongs to. |
| POST | `/organizations/{org_id}/members` | Invite/add a member with a role. |
| POST | `/organizations/{org_id}/projects` | Create a project. |
| GET | `/organizations/{org_id}/projects` | List projects (paginated). |
| GET | `/projects/{project_id}` | Project detail. |
| PATCH | `/projects/{project_id}` | Update name/description. |
| DELETE | `/projects/{project_id}` | Delete (cascades to queues — see database-design.md §5). |

## Queues

| Method | Path | Description |
|---|---|---|
| POST | `/projects/{project_id}/queues` | Create a queue: `{ name, priority, max_concurrency, default_retry_policy_id? }`. |
| GET | `/projects/{project_id}/queues` | List queues for a project. |
| GET | `/queues/{queue_id}` | Queue detail including live stats (pending/running/completed/failed/dlq counts). |
| PATCH | `/queues/{queue_id}` | Update priority, max_concurrency, retry policy. |
| POST | `/queues/{queue_id}/pause` | Pause — no new jobs get claimed. |
| POST | `/queues/{queue_id}/resume` | Resume. |
| GET | `/queues/{queue_id}/stats` | Throughput/health metrics for dashboards (jobs/min, avg duration, failure rate). |
| DELETE | `/queues/{queue_id}` | Delete — `409 Conflict` if the queue has any non-terminal jobs (see `RESTRICT`, database-design.md §5). |

## Retry Policies

| Method | Path | Description |
|---|---|---|
| POST | `/projects/{project_id}/retry-policies` | Create `{ name, strategy, base_delay_seconds, max_delay_seconds?, multiplier?, max_attempts }`. |
| GET | `/projects/{project_id}/retry-policies` | List. |
| PATCH | `/retry-policies/{id}` | Update (does not affect already-created jobs — see database-design.md §7). |

## Jobs

| Method | Path | Description |
|---|---|---|
| POST | `/queues/{queue_id}/jobs` | Create a job. `kind` determines required fields (see below). |
| GET | `/queues/{queue_id}/jobs` | List jobs, filterable by `status`, `type`, `batch_id`, date range; paginated. |
| GET | `/jobs/{job_id}` | Job detail, including current status and attempt count. |
| GET | `/jobs/{job_id}/executions` | Full attempt history for the job. |
| GET | `/jobs/{job_id}/executions/{execution_id}/logs` | Log lines for one attempt. |
| POST | `/jobs/{job_id}/cancel` | Cancel a job that hasn't started running. |
| POST | `/jobs/{job_id}/retry` | Manually re-queue a `failed` or `dead_letter` job. |
| POST | `/queues/{queue_id}/jobs/batch` | Submit many jobs sharing a `batch_id` in one call. |

**Create-job request body by kind:**
```jsonc
// immediate
{ "type": "send_email", "payload": {...}, "kind": "immediate", "priority": 0 }

// delayed
{ "type": "send_email", "payload": {...}, "kind": "delayed", "run_at": "2026-08-23T10:00:00Z" }

// scheduled (one-off, via scheduled_jobs)
{ "type": "generate_report", "payload_template": {...}, "kind": "scheduled", "scheduled_for": "2026-09-01T00:00:00Z" }

// recurring (cron, via scheduled_jobs)
{ "type": "nightly_cleanup", "payload_template": {...}, "kind": "recurring", "cron_expression": "0 2 * * *" }

// batch
{ "type": "resize_image", "items": [{"payload": {...}}, {"payload": {...}}] }
```

## Scheduled Job Definitions

| Method | Path | Description |
|---|---|---|
| GET | `/queues/{queue_id}/scheduled-jobs` | List cron/scheduled definitions. |
| PATCH | `/scheduled-jobs/{id}` | Update cron expression / active flag / payload template. |
| DELETE | `/scheduled-jobs/{id}` | Deactivate/delete (existing spawned jobs are unaffected — `SET NULL`). |

## Workers

| Method | Path | Description |
|---|---|---|
| GET | `/projects/{project_id}/workers` | List registered workers, status, current load. |
| POST | `/workers/register` | Called by a worker process on startup. |
| POST | `/workers/{worker_id}/heartbeat` | Called by a worker on its heartbeat interval; body includes `active_job_count`. |
| POST | `/workers/{worker_id}/deregister` | Graceful shutdown. |

## Dead Letter Queue

| Method | Path | Description |
|---|---|---|
| GET | `/queues/{queue_id}/dlq` | List DLQ entries for a queue, filterable by `resolved`. |
| POST | `/dlq/{id}/retry` | Re-submit the job (creates a fresh `jobs` row from `payload_snapshot`) and mark `resolved`. |
| POST | `/dlq/{id}/resolve` | Mark resolved without retrying (acknowledged/ignored). |

## Dashboard/metrics

| Method | Path | Description |
|---|---|---|
| GET | `/projects/{project_id}/metrics/overview` | Cross-queue summary: totals by status, throughput, failure rate. |
| GET | `/projects/{project_id}/metrics/throughput?window=1h` | Time-bucketed completed/failed counts for charts. |

## Status codes used

`200` OK · `201` Created · `202` Accepted (async action) · `204` No Content (delete) ·
`400` validation error · `401` unauthenticated · `403` unauthorized (wrong org/role) ·
`404` not found · `409` conflict (e.g. delete-with-children, duplicate idempotency key on a *changed* payload) · `422` semantically invalid (e.g. bad cron expression) · `500` unexpected.
