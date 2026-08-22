# System Architecture — Distributed Job Scheduler

Diagram: [`architecture.png`](./architecture.png)

## 1. Components

**Web Dashboard (React SPA)**
Talks only to the REST API, never the database directly. Polls for live status (see §3) — queue health, worker status, job explorer, execution logs, throughput.

**API Service (FastAPI)**
Stateless, horizontally scalable. Owns:
- Auth (JWT-based; org/project scoping enforced per-request)
- CRUD for organizations/projects/queues/retry policies
- Job submission (immediate/delayed/scheduled/recurring/batch) and querying (pagination, filtering)
- Read-side aggregate endpoints for dashboard metrics
It never claims or executes jobs itself — that's the workers' job. This keeps the API's request/response cycle fast and predictable regardless of worker load.

**Scheduler Process**
A single lightweight background process (can run leader-elected/HA later, but one instance is sufficient for the core requirement) with two responsibilities on a short interval (e.g. every 1s):
1. Promote due jobs: `UPDATE jobs SET status='queued' WHERE status='scheduled' AND run_at <= now()`.
2. Sweep `scheduled_jobs` where `is_active AND next_run_at <= now()`, insert a new `jobs` row from the template, and advance `next_run_at` (cron parsing via a standard cron library).
It also runs the dead-worker sweep: workers whose `last_heartbeat_at` is older than a timeout get their in-flight jobs' `claimed_by` cleared and status reset to `queued` (via the `SET NULL` FK behavior plus an explicit status reset), so a crashed worker's jobs aren't lost.

**Worker Pool**
Any number of independent worker processes, each running a loop:
`poll → atomically claim (SELECT ... FOR UPDATE SKIP LOCKED) → execute handler → record job_execution + job_logs → mark completed, or apply retry policy, or move to DLQ on exhaustion → heartbeat`.
Workers are stateless with respect to each other — they coordinate only through row-level locks in Postgres, which is what makes adding or removing workers a purely operational action (no rebalancing protocol needed).

**PostgreSQL**
The single source of truth for everything: queue config, job state, execution history, logs, worker registry, DLQ. See §2 for why this replaces a separate message broker.

## 2. Key design decision: the database *is* the queue

A common alternative architecture puts a broker (Redis, RabbitMQ, Kafka) in front of a separate results database. This design deliberately uses Postgres for both, via `SELECT ... FOR UPDATE SKIP LOCKED` as the claim primitive.

**Why:**
- **Transactional consistency for free.** A job's state transition and its execution record are written in the same database as everything else that needs to stay consistent with it (retry counts, DLQ entries) — no dual-write problem between a broker and a database.
- **Fewer moving parts.** One system to operate, back up, and reason about failure modes for, appropriate for a project evaluated on engineering quality and reliability rather than raw throughput.
- **Sufficient throughput for the target scale.** `SKIP LOCKED` avoids the classic "SELECT then UPDATE" race and lock-contention collapse; a single well-indexed Postgres instance comfortably handles thousands of claims/sec, well beyond what a "production-inspired" project of this scope needs to demonstrate.

**Trade-off, stated honestly:** this would not be the right choice at extreme scale (hundreds of thousands of jobs/sec across a fleet), where a dedicated broker's purpose-built delivery guarantees and horizontal partitioning outweigh the operational simplicity of one database. That threshold is well beyond this assignment's scope, so it's noted here as the boundary of the design rather than solved for.

## 3. Live updates: polling over WebSockets (for the core scope)

The assignment allows either. Polling was chosen for the core implementation because it needs no additional infrastructure (no pub/sub broker, no connection-state management) and is trivially horizontally scalable — every API replica can answer a poll independently. WebSocket live updates are listed as a bonus feature and would layer on top of this (e.g. via Postgres `LISTEN/NOTIFY` fanned out to connected clients) without changing the underlying data model.

## 4. Reliability mechanisms, summarized

| Concern | Mechanism |
|---|---|
| Duplicate execution | `FOR UPDATE SKIP LOCKED` atomic claim — a row can only be claimed once |
| Worker crash mid-job | Heartbeat timeout detected by the scheduler; job's claim is released back to `queued` |
| Transient failure | Retry policy (fixed/linear/exponential) re-queues with a computed delay, up to `max_attempts` |
| Permanent failure | Job moves to `dead_letter_queue` with a payload snapshot for triage/replay |
| Idempotent submission | Unique `(queue_id, idempotency_key)` index rejects/dedupes duplicate submissions |
| Audit trail | Every attempt is an immutable `job_executions` row; every log line is scoped to that attempt |

## 5. Scaling out (beyond core scope, noted for completeness)

- **API**: stateless, scale horizontally behind a load balancer.
- **Workers**: scale horizontally by running more processes; `max_concurrency` per queue and `SKIP LOCKED` mean adding workers requires no coordination.
- **Database**: the eventual bottleneck at very high volume. Vertical scaling and read replicas (for dashboard reads) go a long way; beyond that, queue sharding (listed as a bonus feature) or migrating high-volume queues to a dedicated broker are the natural next steps.
