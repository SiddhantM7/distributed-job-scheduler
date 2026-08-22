"""Initial schema from docs/schema.sql

Revision ID: 001
Revises:
Create Date: 2026-08-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Enum types
    op.execute("CREATE TYPE member_role AS ENUM ('owner', 'admin', 'member')")
    op.execute("CREATE TYPE retry_strategy AS ENUM ('fixed', 'linear', 'exponential')")
    op.execute(
        "CREATE TYPE job_kind AS ENUM ('immediate', 'delayed', 'scheduled', 'recurring', 'batch')"
    )
    op.execute(
        "CREATE TYPE job_status AS ENUM "
        "('queued', 'scheduled', 'claimed', 'running', 'completed', 'failed', 'dead_letter', 'cancelled')"
    )
    op.execute("CREATE TYPE execution_status AS ENUM ('running', 'completed', 'failed')")
    op.execute("CREATE TYPE worker_status AS ENUM ('idle', 'busy', 'draining', 'offline')")
    op.execute("CREATE TYPE log_level AS ENUM ('debug', 'info', 'warn', 'error')")

    # ─── Identity & tenancy ───────────────────────────────────────────

    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "organization_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", ENUM("owner", "admin", "member", name="member_role", create_type=False), nullable=False, server_default=sa.text("'member'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "user_id"),
    )
    op.create_index("idx_org_members_user", "organization_members", ["user_id"])

    op.create_table(
        "projects",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("organization_id", UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("organization_id", "name"),
    )
    op.create_index("idx_projects_org", "projects", ["organization_id"])

    # ─── Queue configuration ─────────────────────────────────────────

    # retry_policies — added project_id FK (not in original schema.sql)
    op.create_table(
        "retry_policies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "strategy",
            ENUM("fixed", "linear", "exponential", name="retry_strategy", create_type=False),
            nullable=False,
            server_default=sa.text("'exponential'"),
        ),
        sa.Column("base_delay_seconds", sa.Integer, nullable=False, server_default="5"),
        sa.Column("max_delay_seconds", sa.Integer),
        sa.Column("multiplier", sa.Numeric(4, 2), server_default="2.0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("base_delay_seconds >= 0", name="chk_retry_base_delay"),
        sa.CheckConstraint("max_delay_seconds IS NULL OR max_delay_seconds >= base_delay_seconds", name="chk_retry_max_delay"),
        sa.CheckConstraint("multiplier IS NULL OR multiplier > 0", name="chk_retry_multiplier"),
        sa.CheckConstraint("max_attempts >= 1", name="chk_retry_max_attempts"),
    )
    op.create_index("idx_retry_policies_project", "retry_policies", ["project_id"])

    op.create_table(
        "queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("default_retry_policy_id", UUID(as_uuid=True), sa.ForeignKey("retry_policies.id", ondelete="SET NULL")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_concurrency", sa.Integer, nullable=False, server_default="10"),
        sa.Column("is_paused", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("project_id", "name"),
        sa.CheckConstraint("max_concurrency >= 1", name="chk_queues_max_concurrency"),
    )
    op.create_index("idx_queues_project", "queues", ["project_id"])

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retry_policy_id", UUID(as_uuid=True), sa.ForeignKey("retry_policies.id", ondelete="SET NULL")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("job_type", sa.Text, nullable=False),
        sa.Column("payload_template", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("cron_expression", sa.Text),
        sa.Column("is_recurring", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("is_recurring = false OR cron_expression IS NOT NULL", name="chk_scheduled_jobs_cron"),
    )
    op.create_index("idx_scheduled_jobs_due", "scheduled_jobs", ["next_run_at"], postgresql_where=sa.text("is_active"))

    # ─── Jobs — the operational core ─────────────────────────────────

    # workers first, because jobs.claimed_by references workers
    op.create_table(
        "workers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("hostname", sa.Text, nullable=False),
        sa.Column("pid", sa.Integer),
        sa.Column("status", ENUM("idle", "busy", "draining", "offline", name="worker_status", create_type=False), nullable=False, server_default=sa.text("'idle'")),
        sa.Column("concurrency", sa.Integer, nullable=False, server_default="5"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.CheckConstraint("concurrency >= 1", name="chk_workers_concurrency"),
    )
    op.create_index("idx_workers_heartbeat", "workers", ["last_heartbeat_at"])

    op.create_table(
        "jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("scheduled_job_id", UUID(as_uuid=True), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL")),
        sa.Column("retry_policy_id", UUID(as_uuid=True), sa.ForeignKey("retry_policies.id", ondelete="SET NULL")),
        sa.Column("claimed_by", UUID(as_uuid=True), sa.ForeignKey("workers.id", ondelete="SET NULL")),
        sa.Column("batch_id", UUID(as_uuid=True)),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("kind", ENUM("immediate", "delayed", "scheduled", "recurring", "batch", name="job_kind", create_type=False), nullable=False, server_default=sa.text("'immediate'")),
        sa.Column("status", ENUM("queued", "scheduled", "claimed", "running", "completed", "failed", "dead_letter", "cancelled", name="job_status", create_type=False), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("attempt_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("idempotency_key", sa.Text),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("result", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    # The critical claim index (partial)
    op.create_index(
        "idx_jobs_claim", "jobs", ["queue_id", "status", "run_at"],
        postgresql_where=sa.text("status IN ('queued', 'scheduled')"),
    )
    op.create_index(
        "idx_jobs_run_at_due", "jobs", ["run_at"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index(
        "idx_jobs_batch", "jobs", ["batch_id"],
        postgresql_where=sa.text("batch_id IS NOT NULL"),
    )
    op.create_index(
        "idx_jobs_scheduled_job", "jobs", ["scheduled_job_id"],
        postgresql_where=sa.text("scheduled_job_id IS NOT NULL"),
    )
    op.create_index(
        "uq_jobs_idempotency", "jobs", ["queue_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "worker_queues",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("worker_id", UUID(as_uuid=True), sa.ForeignKey("workers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("worker_id", "queue_id"),
    )

    op.create_table(
        "job_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("worker_id", UUID(as_uuid=True), sa.ForeignKey("workers.id", ondelete="SET NULL")),
        sa.Column("attempt_number", sa.Integer, nullable=False),
        sa.Column("status", ENUM("running", "completed", "failed", name="execution_status", create_type=False), nullable=False, server_default=sa.text("'running'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("result", JSONB),
        sa.UniqueConstraint("job_id", "attempt_number"),
    )
    op.create_index("idx_job_executions_job", "job_executions", ["job_id"])
    op.create_index("idx_job_executions_worker", "job_executions", ["worker_id"])

    op.create_table(
        "job_logs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("job_execution_id", UUID(as_uuid=True), sa.ForeignKey("job_executions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("level", ENUM("debug", "info", "warn", "error", name="log_level", create_type=False), nullable=False, server_default=sa.text("'info'")),
        sa.Column("message", sa.Text, nullable=False),
    )
    op.create_index("idx_job_logs_execution_ts", "job_logs", ["job_execution_id", "timestamp"])

    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("worker_id", UUID(as_uuid=True), sa.ForeignKey("workers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("active_job_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cpu_pct", sa.Numeric(5, 2)),
        sa.Column("mem_mb", sa.Integer),
    )
    op.create_index("idx_worker_heartbeats_worker_ts", "worker_heartbeats", ["worker_id", "heartbeat_at"])

    op.create_table(
        "dead_letter_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("last_error", sa.Text),
        sa.Column("payload_snapshot", JSONB, nullable=False),
        sa.Column("failed_attempt_count", sa.Integer, nullable=False),
        sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_dlq_queue", "dead_letter_queue", ["queue_id"], postgresql_where=sa.text("NOT resolved"))

    # ─── updated_at trigger ──────────────────────────────────────────

    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
        BEGIN
          NEW.updated_at = now();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table, trigger_name in [
        ("organizations", "trg_orgs_updated"),
        ("users", "trg_users_updated"),
        ("projects", "trg_projects_updated"),
        ("queues", "trg_queues_updated"),
        ("scheduled_jobs", "trg_sched_jobs_updated"),
        ("jobs", "trg_jobs_updated"),
    ]:
        op.execute(
            f"CREATE TRIGGER {trigger_name} BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("dead_letter_queue")
    op.drop_table("worker_heartbeats")
    op.drop_table("job_logs")
    op.drop_table("job_executions")
    op.drop_table("worker_queues")
    op.drop_table("jobs")
    op.drop_table("workers")
    op.drop_table("scheduled_jobs")
    op.drop_table("queues")
    op.drop_table("retry_policies")
    op.drop_table("projects")
    op.drop_table("organization_members")
    op.drop_table("users")
    op.drop_table("organizations")

    # Drop function
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    # Drop enums
    for enum_name in [
        "log_level", "worker_status", "execution_status",
        "job_status", "job_kind", "retry_strategy", "member_role",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
