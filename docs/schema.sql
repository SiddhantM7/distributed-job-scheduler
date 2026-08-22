-- =====================================================================
-- Distributed Job Scheduler — PostgreSQL Schema
-- =====================================================================
-- Conventions:
--   * Surrogate PKs are UUID (gen_random_uuid()) except high-volume,
--     append-only log tables which use BIGSERIAL (cheaper to index,
--     no random-UUID write amplification on the btree).
--   * created_at / updated_at are timestamptz, defaulted server-side.
--   * All FKs declare an explicit ON DELETE action — see
--     database-design.md for the reasoning behind each choice.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

CREATE TYPE member_role       AS ENUM ('owner', 'admin', 'member');
CREATE TYPE retry_strategy    AS ENUM ('fixed', 'linear', 'exponential');
CREATE TYPE job_kind          AS ENUM ('immediate', 'delayed', 'scheduled', 'recurring', 'batch');
CREATE TYPE job_status        AS ENUM ('queued', 'scheduled', 'claimed', 'running',
                                        'completed', 'failed', 'dead_letter', 'cancelled');
CREATE TYPE execution_status  AS ENUM ('running', 'completed', 'failed');
CREATE TYPE worker_status     AS ENUM ('idle', 'busy', 'draining', 'offline');
CREATE TYPE log_level         AS ENUM ('debug', 'info', 'warn', 'error');

-- ---------------------------------------------------------------------
-- Identity & tenancy
-- ---------------------------------------------------------------------

CREATE TABLE organizations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    name           TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE organization_members (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id          UUID NOT NULL REFERENCES users(id)         ON DELETE CASCADE,
    role             member_role NOT NULL DEFAULT 'member',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, user_id)
);
CREATE INDEX idx_org_members_user ON organization_members(user_id);

CREATE TABLE projects (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    description      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name)
);
CREATE INDEX idx_projects_org ON projects(organization_id);

-- ---------------------------------------------------------------------
-- Queue configuration
-- ---------------------------------------------------------------------

CREATE TABLE retry_policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL,
    strategy            retry_strategy NOT NULL DEFAULT 'exponential',
    base_delay_seconds  INT NOT NULL DEFAULT 5 CHECK (base_delay_seconds >= 0),
    max_delay_seconds   INT CHECK (max_delay_seconds IS NULL OR max_delay_seconds >= base_delay_seconds),
    multiplier          NUMERIC(4,2) DEFAULT 2.0 CHECK (multiplier IS NULL OR multiplier > 0),
    max_attempts        INT NOT NULL DEFAULT 5 CHECK (max_attempts >= 1),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE queues (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id                UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    default_retry_policy_id   UUID REFERENCES retry_policies(id) ON DELETE SET NULL,
    name                      TEXT NOT NULL,
    priority                  INT NOT NULL DEFAULT 0,
    max_concurrency           INT NOT NULL DEFAULT 10 CHECK (max_concurrency >= 1),
    is_paused                 BOOLEAN NOT NULL DEFAULT false,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);
CREATE INDEX idx_queues_project ON queues(project_id);

-- Recurring / cron & one-off scheduled job *definitions*.
-- Each due definition spawns a row in `jobs`.
CREATE TABLE scheduled_jobs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    queue_id          UUID NOT NULL REFERENCES queues(id) ON DELETE CASCADE,
    retry_policy_id   UUID REFERENCES retry_policies(id) ON DELETE SET NULL,
    name              TEXT NOT NULL,
    job_type          TEXT NOT NULL,
    payload_template  JSONB NOT NULL DEFAULT '{}',
    cron_expression   TEXT,                      -- NULL for one-off scheduled jobs
    is_recurring      BOOLEAN NOT NULL DEFAULT false,
    is_active         BOOLEAN NOT NULL DEFAULT true,
    next_run_at       TIMESTAMPTZ NOT NULL,
    last_run_at       TIMESTAMPTZ,
    created_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (is_recurring = false OR cron_expression IS NOT NULL)
);
-- Scheduler's core sweep query: WHERE is_active AND next_run_at <= now()
CREATE INDEX idx_scheduled_jobs_due ON scheduled_jobs(next_run_at) WHERE is_active;

-- ---------------------------------------------------------------------
-- Jobs — the operational core
-- ---------------------------------------------------------------------

CREATE TABLE jobs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    queue_id          UUID NOT NULL REFERENCES queues(id) ON DELETE RESTRICT,
    scheduled_job_id  UUID REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    retry_policy_id   UUID REFERENCES retry_policies(id) ON DELETE SET NULL,
    claimed_by        UUID,   -- FK added below, after `workers` exists (see fk_jobs_claimed_by)
    batch_id          UUID,
    type              TEXT NOT NULL,
    payload           JSONB NOT NULL DEFAULT '{}',
    kind              job_kind NOT NULL DEFAULT 'immediate',
    status            job_status NOT NULL DEFAULT 'queued',
    priority          INT NOT NULL DEFAULT 0,
    run_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempt_count     INT NOT NULL DEFAULT 0,
    max_attempts      INT NOT NULL DEFAULT 5,          -- resolved from retry policy at creation time
    idempotency_key   TEXT,
    claimed_at        TIMESTAMPTZ,
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    result            JSONB,
    error             TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The single most important index in the system: the atomic-claim query
-- filters by queue + status + eligibility, then orders by priority.
CREATE INDEX idx_jobs_claim ON jobs(queue_id, status, run_at)
    WHERE status IN ('queued', 'scheduled');
-- Global sweep used by the scheduler to promote delayed/scheduled jobs.
CREATE INDEX idx_jobs_run_at_due ON jobs(run_at) WHERE status = 'scheduled';
CREATE INDEX idx_jobs_batch ON jobs(batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX idx_jobs_scheduled_job ON jobs(scheduled_job_id) WHERE scheduled_job_id IS NOT NULL;
-- Idempotent submission: same key within a queue is rejected/returned, not duplicated.
CREATE UNIQUE INDEX uq_jobs_idempotency ON jobs(queue_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE workers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname          TEXT NOT NULL,
    pid               INT,
    status            worker_status NOT NULL DEFAULT 'idle',
    concurrency       INT NOT NULL DEFAULT 5 CHECK (concurrency >= 1),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata          JSONB NOT NULL DEFAULT '{}'
);
-- Dead-worker detection sweep: WHERE last_heartbeat_at < now() - interval '...'
CREATE INDEX idx_workers_heartbeat ON workers(last_heartbeat_at);

-- Optional assignment of specific workers to specific queues (else a
-- worker polls every queue it's authorized for via project scope).
CREATE TABLE worker_queues (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id  UUID NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    queue_id   UUID NOT NULL REFERENCES queues(id)  ON DELETE CASCADE,
    UNIQUE (worker_id, queue_id)
);

-- Now that `workers` exists, attach the FK from jobs.claimed_by.
ALTER TABLE jobs
    ADD CONSTRAINT fk_jobs_claimed_by
    FOREIGN KEY (claimed_by) REFERENCES workers(id) ON DELETE SET NULL;

CREATE TABLE job_executions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    worker_id       UUID REFERENCES workers(id) ON DELETE SET NULL,
    attempt_number  INT NOT NULL,
    status          execution_status NOT NULL DEFAULT 'running',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    duration_ms     INT,
    error           TEXT,
    result          JSONB,
    UNIQUE (job_id, attempt_number)
);
CREATE INDEX idx_job_executions_job ON job_executions(job_id);
CREATE INDEX idx_job_executions_worker ON job_executions(worker_id);

CREATE TABLE job_logs (
    id                  BIGSERIAL PRIMARY KEY,
    job_execution_id    UUID NOT NULL REFERENCES job_executions(id) ON DELETE CASCADE,
    "timestamp"         TIMESTAMPTZ NOT NULL DEFAULT now(),
    level               log_level NOT NULL DEFAULT 'info',
    message             TEXT NOT NULL
);
CREATE INDEX idx_job_logs_execution_ts ON job_logs(job_execution_id, "timestamp");

CREATE TABLE worker_heartbeats (
    id                BIGSERIAL PRIMARY KEY,
    worker_id         UUID NOT NULL REFERENCES workers(id) ON DELETE CASCADE,
    heartbeat_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    active_job_count  INT NOT NULL DEFAULT 0,
    cpu_pct           NUMERIC(5,2),
    mem_mb            INT
);
CREATE INDEX idx_worker_heartbeats_worker_ts ON worker_heartbeats(worker_id, heartbeat_at);

CREATE TABLE dead_letter_queue (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                 UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    queue_id               UUID NOT NULL REFERENCES queues(id) ON DELETE CASCADE,  -- denormalized for filtering
    reason                 TEXT NOT NULL,
    last_error             TEXT,
    payload_snapshot       JSONB NOT NULL,
    failed_attempt_count   INT NOT NULL,
    moved_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved               BOOLEAN NOT NULL DEFAULT false,
    resolved_at            TIMESTAMPTZ
);
CREATE INDEX idx_dlq_queue ON dead_letter_queue(queue_id) WHERE NOT resolved;

-- ---------------------------------------------------------------------
-- updated_at trigger (applied to every table that has the column)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_orgs_updated        BEFORE UPDATE ON organizations     FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_users_updated       BEFORE UPDATE ON users             FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_projects_updated    BEFORE UPDATE ON projects          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_queues_updated      BEFORE UPDATE ON queues            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_sched_jobs_updated  BEFORE UPDATE ON scheduled_jobs    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_jobs_updated        BEFORE UPDATE ON jobs              FOR EACH ROW EXECUTE FUNCTION set_updated_at();
