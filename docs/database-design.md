# Database Design — Distributed Job Scheduler

Target: PostgreSQL 16. Full DDL: [`schema.sql`](./schema.sql). ER diagram: [`er_diagram.png`](./er_diagram.png).

## 1. Entity overview

| Table | Purpose |
|---|---|
| `organizations`, `users`, `organization_members` | Tenancy and auth. Many-to-many users↔orgs with a role. |
| `projects` | Owned by an organization; the unit that owns queues. |
| `queues` | Owned by a project; carries priority, concurrency limit, pause flag, default retry policy. |
| `retry_policies` | Reusable retry configs (fixed / linear / exponential), attachable to a queue (default) or a job (override). |
| `scheduled_jobs` | *Definitions* for recurring (cron) or one-off future jobs. The scheduler sweeps these and spawns rows in `jobs`. |
| `jobs` | The operational core — one row per unit of work, immediate or spawned. Carries status, run_at, attempt bookkeeping, claim info. |
| `job_executions` | One row per **attempt** of a job — the audit trail retries need. |
| `job_logs` | Log lines scoped to a single execution/attempt. |
| `workers` | A running worker process; current status and last heartbeat. |
| `worker_queues` | Optional explicit assignment of workers to queues. |
| `worker_heartbeats` | Time-series heartbeat history (separate from `workers.last_heartbeat_at`, which is the fast "current" pointer). |
| `dead_letter_queue` | Permanently-failed jobs, with a payload snapshot for postmortem/replay. |

## 2. Why `jobs` and `job_executions` are separate

A job can be attempted multiple times under a retry policy. Putting attempt history directly on `jobs` would mean either overwriting prior-attempt data (losing the audit trail retries and DLQ triage need) or adding unbounded repeating columns. Instead:

- `jobs` holds **current state** (status, attempt_count, claim info) — this is what the claim query and the dashboard's job explorer read, and it stays a single row per job, cheap to index and update.
- `job_executions` holds **one immutable row per attempt** (status, timing, error, result) — this is what "retry history" and "execution metrics" actually mean, and it's append-only, which keeps it cheap to write concurrently from many workers.

`job_logs` is scoped to `job_execution_id`, not `job_id`, so log lines from attempt 1 and attempt 3 of the same job are never mixed.

## 3. Why `scheduled_jobs` is separate from `jobs`

`scheduled_jobs` is a **template/definition** (cron expression, payload template, next_run_at). `jobs` is an **instance** to execute. A recurring job that fires every 5 minutes should produce a new `jobs` row on each firing, not mutate one row forever — otherwise you can't see history, can't have two firings in flight, and the atomic-claim query would be racing against the scheduler's own writes to the same row. `jobs.scheduled_job_id` links an instance back to the definition that spawned it (nullable — most jobs are submitted directly via the API, not spawned by a schedule).

## 4. Primary keys

All primary keys are UUIDs (`gen_random_uuid()`), except `job_logs` and `worker_heartbeats`, which use `BIGSERIAL`.

- **UUIDs** for everything user/API-facing: they can be generated client-side or at the API layer before the DB round-trip, they don't leak sequential counts (e.g. "how many jobs has this customer run"), and they merge cleanly if the system is ever sharded per-tenant.
- **BIGSERIAL** for `job_logs` and `worker_heartbeats` specifically: these are the two highest-write-volume, purely-internal, append-only tables in the schema. A monotonic integer PK avoids UUID's random-insertion-point index bloat on a table that is likely to receive the most writes per second in the whole system, and nothing external ever needs to reference a log row by ID.

## 5. Foreign keys and `ON DELETE` behavior

| FK | Action | Reasoning |
|---|---|---|
| `organization_members → organizations/users` | `CASCADE` | Membership has no meaning without both sides. |
| `projects → organizations` | `CASCADE` | Deleting a tenant's org should not leave orphaned projects. In a real product this would sit behind a soft-delete / confirmation flow at the application layer — the DB-level cascade is the safety net, not the primary deletion path. |
| `queues → projects` | `CASCADE` | Same reasoning as above, one level down. |
| `jobs → queues` | **`RESTRICT`** | Deliberately the odd one out. A queue can have thousands of historical jobs; silently cascading a queue deletion into deleting all job history (and DLQ entries, and logs) is exactly the kind of accidental data loss this system exists to prevent. The application must require the queue be paused and drained/archived first. |
| `job_executions → jobs`, `job_logs → job_executions` | `CASCADE` | Executions and logs have no independent meaning once the parent job is gone; this only fires when a job itself is explicitly purged (not part of normal lifecycle). |
| `dead_letter_queue → jobs` | `CASCADE` | Same reasoning — but note `payload_snapshot` on the DLQ row means the *content* needed for triage survives independently in spirit even though the row is tied to the job for referential integrity. |
| `jobs.claimed_by → workers` | `SET NULL` | If a worker process is deregistered/deleted while it "holds" a job, the job must become reclaimable by another worker, not fail or dangle. Combined with heartbeat-timeout logic, this is the basis of crash recovery. |
| `job_executions.worker_id → workers` | `SET NULL` | Preserve the execution's history even if the worker record is later cleaned up. |
| `jobs.scheduled_job_id → scheduled_jobs` | `SET NULL` | Deleting a recurring schedule shouldn't retroactively delete jobs it already spawned. |
| `queues.default_retry_policy_id`, `jobs.retry_policy_id → retry_policies` | `SET NULL` | A retry policy being retired shouldn't block deletion or orphan the queue/job — they fall back to an application-level default. |
| `worker_queues`, `worker_heartbeats → workers` | `CASCADE` | Pure child records of a worker. |

## 6. Indexing strategy

The single query that matters most for correctness and throughput is the **atomic claim**:

```sql
UPDATE jobs SET status='claimed', claimed_by=$worker, claimed_at=now()
WHERE id = (
  SELECT id FROM jobs
  WHERE queue_id = $queue AND status = 'queued' AND run_at <= now()
  ORDER BY priority DESC, run_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

`SKIP LOCKED` is what makes concurrent workers safe without an external lock manager: two workers racing this query never claim the same row, and a worker blocked on a locked row doesn't stall — it just skips to the next candidate. This is the mechanism behind the "atomic claim" and "no duplicate execution" requirements.

Supporting indexes:

- `idx_jobs_claim (queue_id, status, run_at) WHERE status IN ('queued','scheduled')` — a **partial** composite index covering exactly the claim query's filter and sort columns. Partial because completed/failed jobs (the large majority over time) never need to appear here, keeping the index small and cache-resident.
- `idx_jobs_run_at_due (run_at) WHERE status='scheduled'` — supports the scheduler's separate sweep that promotes delayed/scheduled jobs to `queued` once due.
- `idx_scheduled_jobs_due (next_run_at) WHERE is_active` — the cron/scheduler poll.
- `uq_jobs_idempotency (queue_id, idempotency_key) WHERE idempotency_key IS NOT NULL` — unique partial index; enforces idempotent submission without forcing every job to have a key.
- `idx_workers_heartbeat (last_heartbeat_at)` — the dead-worker sweep (`WHERE last_heartbeat_at < now() - interval '...'`) is a range scan on this.
- `idx_job_executions_job`, `idx_job_logs_execution_ts` — support the dashboard's job-detail and log-tail views without a sequential scan.

## 7. Normalization and deliberate denormalization

The schema is in **3NF** by default — retry policy, worker, and schedule data each live in exactly one place and are referenced, not copied. Two intentional exceptions:

1. **`jobs.max_attempts`** is copied from the retry policy at job-creation time rather than always joined live. If an operator edits a retry policy's `max_attempts`, in-flight jobs created under the old policy should keep behaving as originally configured — re-reading a live value could change the retry behavior of a job mid-flight, which is a correctness hazard, not just a performance one.
2. **`dead_letter_queue.queue_id`** is denormalized from `jobs.queue_id`. It's reachable via a join through `jobs`, but the DLQ triage view ("show me everything dead in queue X") is a common, latency-sensitive dashboard query, and this avoids a join on a table that's expected to be scanned frequently by humans, not just workers.

Both are documented trade-offs: a small amount of redundancy in exchange for correctness or read performance, in the two places where re-deriving the value live would be actively wrong or measurably slower — everywhere else, the schema stays normalized.

## 8. Performance considerations at scale

- **Table growth**: `job_logs` and `worker_heartbeats` are the fastest-growing tables. Both are designed for periodic partitioning by time (e.g. monthly `PARTITION BY RANGE` on `timestamp`/`heartbeat_at`) once volume warrants it — the schema doesn't require it on day one, but nothing in it blocks adding it later.
- **JSONB fields** (`payload`, `result`, `payload_snapshot`) are intentionally schemaless for job-type flexibility; if specific job types need to be queried by payload contents at scale, a GIN index on the relevant JSONB path can be added without a schema migration.
- **Queue statistics** (jobs pending/running/failed per queue) are computed via indexed aggregate queries against `jobs` rather than a separately maintained counters table, keeping the write path simple (one row insert/update per job transition, no counter-increment contention). If dashboard polling load on that aggregate becomes a bottleneck, it's a candidate for a materialized view refreshed on an interval — noted here as the next step, not built preemptively.
- **`FOR UPDATE SKIP LOCKED`** avoids lock contention between workers, which is what lets this design scale to many concurrent worker processes on a single Postgres instance before any sharding or external broker is needed.
