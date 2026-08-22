from sqlalchemy import (
    MetaData, Table, Column, String, Text, Integer, Boolean, Numeric,
    DateTime, ForeignKey, UniqueConstraint, CheckConstraint, Index, text, BigInteger
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ENUM

metadata = MetaData()

# Enums
member_role = ENUM('owner', 'admin', 'member', name='member_role', create_type=False)
retry_strategy = ENUM('fixed', 'linear', 'exponential', name='retry_strategy', create_type=False)
job_kind = ENUM('immediate', 'delayed', 'scheduled', 'recurring', 'batch', name='job_kind', create_type=False)
job_status = ENUM('queued', 'scheduled', 'claimed', 'running',
                  'completed', 'failed', 'dead_letter', 'cancelled', name='job_status', create_type=False)
execution_status = ENUM('running', 'completed', 'failed', name='execution_status', create_type=False)
worker_status = ENUM('idle', 'busy', 'draining', 'offline', name='worker_status', create_type=False)
log_level = ENUM('debug', 'info', 'warn', 'error', name='log_level', create_type=False)

# Organizations
organizations = Table(
    'organizations', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('name', Text, nullable=False),
    Column('slug', Text, nullable=False, unique=True),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
)

# Users
users = Table(
    'users', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('email', Text, nullable=False, unique=True),
    Column('password_hash', Text, nullable=False),
    Column('name', Text, nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
)

# Organization Members
organization_members = Table(
    'organization_members', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('organization_id', UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
    Column('user_id', UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
    Column('role', member_role, nullable=False, server_default=text("'member'")),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    UniqueConstraint('organization_id', 'user_id', name='uq_org_members'),
    Index('idx_org_members_user', 'user_id'),
)

# Projects
projects = Table(
    'projects', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('organization_id', UUID(as_uuid=True), ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
    Column('created_by', UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL')),
    Column('name', Text, nullable=False),
    Column('description', Text),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    UniqueConstraint('organization_id', 'name', name='uq_projects_org_name'),
    Index('idx_projects_org', 'organization_id'),
)

# Retry Policies
retry_policies = Table(
    'retry_policies', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('project_id', UUID(as_uuid=True), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
    Column('name', Text, nullable=False),
    Column('strategy', retry_strategy, nullable=False, server_default=text("'exponential'")),
    Column('base_delay_seconds', Integer, nullable=False, server_default='5'),
    Column('max_delay_seconds', Integer),
    Column('multiplier', Numeric(4, 2), server_default='2.0'),
    Column('max_attempts', Integer, nullable=False, server_default='5'),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    CheckConstraint('base_delay_seconds >= 0', name='chk_retry_base_delay'),
    CheckConstraint('max_delay_seconds IS NULL OR max_delay_seconds >= base_delay_seconds', name='chk_retry_max_delay'),
    CheckConstraint('multiplier IS NULL OR multiplier > 0', name='chk_retry_multiplier'),
    CheckConstraint('max_attempts >= 1', name='chk_retry_max_attempts'),
    Index('idx_retry_policies_project', 'project_id'),
)

# Queues
queues = Table(
    'queues', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('project_id', UUID(as_uuid=True), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
    Column('default_retry_policy_id', UUID(as_uuid=True), ForeignKey('retry_policies.id', ondelete='SET NULL')),
    Column('name', Text, nullable=False),
    Column('priority', Integer, nullable=False, server_default='0'),
    Column('max_concurrency', Integer, nullable=False, server_default='10'),
    Column('is_paused', Boolean, nullable=False, server_default='false'),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    UniqueConstraint('project_id', 'name', name='uq_queues_project_name'),
    CheckConstraint('max_concurrency >= 1', name='chk_queues_max_concurrency'),
    Index('idx_queues_project', 'project_id'),
)

# Scheduled Jobs
scheduled_jobs = Table(
    'scheduled_jobs', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('queue_id', UUID(as_uuid=True), ForeignKey('queues.id', ondelete='CASCADE'), nullable=False),
    Column('retry_policy_id', UUID(as_uuid=True), ForeignKey('retry_policies.id', ondelete='SET NULL')),
    Column('name', Text, nullable=False),
    Column('job_type', Text, nullable=False),
    Column('payload_template', JSONB, nullable=False, server_default=text("'{}'")),
    Column('cron_expression', Text),
    Column('is_recurring', Boolean, nullable=False, server_default='false'),
    Column('is_active', Boolean, nullable=False, server_default='true'),
    Column('next_run_at', DateTime(timezone=True), nullable=False),
    Column('last_run_at', DateTime(timezone=True)),
    Column('created_by', UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL')),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    CheckConstraint('is_recurring = false OR cron_expression IS NOT NULL', name='chk_scheduled_jobs_cron'),
    Index('idx_scheduled_jobs_due', 'next_run_at', postgresql_where=text("is_active")),
)

# Workers
workers = Table(
    'workers', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('hostname', Text, nullable=False),
    Column('pid', Integer),
    Column('status', worker_status, nullable=False, server_default=text("'idle'")),
    Column('concurrency', Integer, nullable=False, server_default='5'),
    Column('started_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('last_heartbeat_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('metadata', JSONB, nullable=False, server_default=text("'{}'")),
    CheckConstraint('concurrency >= 1', name='chk_workers_concurrency'),
    Index('idx_workers_heartbeat', 'last_heartbeat_at'),
)

# Worker Queues
worker_queues = Table(
    'worker_queues', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('worker_id', UUID(as_uuid=True), ForeignKey('workers.id', ondelete='CASCADE'), nullable=False),
    Column('queue_id', UUID(as_uuid=True), ForeignKey('queues.id', ondelete='CASCADE'), nullable=False),
    UniqueConstraint('worker_id', 'queue_id', name='uq_worker_queues'),
)

# Jobs
jobs = Table(
    'jobs', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('queue_id', UUID(as_uuid=True), ForeignKey('queues.id', ondelete='RESTRICT'), nullable=False),
    Column('scheduled_job_id', UUID(as_uuid=True), ForeignKey('scheduled_jobs.id', ondelete='SET NULL')),
    Column('retry_policy_id', UUID(as_uuid=True), ForeignKey('retry_policies.id', ondelete='SET NULL')),
    Column('claimed_by', UUID(as_uuid=True), ForeignKey('workers.id', ondelete='SET NULL')),
    Column('batch_id', UUID(as_uuid=True)),
    Column('type', Text, nullable=False),
    Column('payload', JSONB, nullable=False, server_default=text("'{}'")),
    Column('kind', job_kind, nullable=False, server_default=text("'immediate'")),
    Column('status', job_status, nullable=False, server_default=text("'queued'")),
    Column('priority', Integer, nullable=False, server_default='0'),
    Column('run_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('attempt_count', Integer, nullable=False, server_default='0'),
    Column('max_attempts', Integer, nullable=False, server_default='5'),
    Column('idempotency_key', Text),
    Column('claimed_at', DateTime(timezone=True)),
    Column('started_at', DateTime(timezone=True)),
    Column('completed_at', DateTime(timezone=True)),
    Column('result', JSONB),
    Column('error', Text),
    Column('created_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('updated_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Index('idx_jobs_claim', 'queue_id', 'status', 'run_at', postgresql_where=text("status IN ('queued', 'scheduled')")),
    Index('idx_jobs_run_at_due', 'run_at', postgresql_where=text("status = 'scheduled'")),
    Index('idx_jobs_batch', 'batch_id', postgresql_where=text("batch_id IS NOT NULL")),
    Index('idx_jobs_scheduled_job', 'scheduled_job_id', postgresql_where=text("scheduled_job_id IS NOT NULL")),
    Index('uq_jobs_idempotency', 'queue_id', 'idempotency_key', unique=True, postgresql_where=text("idempotency_key IS NOT NULL")),
)

# Job Executions
job_executions = Table(
    'job_executions', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('job_id', UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
    Column('worker_id', UUID(as_uuid=True), ForeignKey('workers.id', ondelete='SET NULL')),
    Column('attempt_number', Integer, nullable=False),
    Column('status', execution_status, nullable=False, server_default=text("'running'")),
    Column('started_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('completed_at', DateTime(timezone=True)),
    Column('duration_ms', Integer),
    Column('error', Text),
    Column('result', JSONB),
    UniqueConstraint('job_id', 'attempt_number', name='uq_job_executions_attempt'),
    Index('idx_job_executions_job', 'job_id'),
    Index('idx_job_executions_worker', 'worker_id'),
)

# Job Logs
job_logs = Table(
    'job_logs', metadata,
    Column('id', BigInteger, primary_key=True, autoincrement=True),
    Column('job_execution_id', UUID(as_uuid=True), ForeignKey('job_executions.id', ondelete='CASCADE'), nullable=False),
    Column('timestamp', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('level', log_level, nullable=False, server_default=text("'info'")),
    Column('message', Text, nullable=False),
    Index('idx_job_logs_execution_ts', 'job_execution_id', 'timestamp'),
)

# Worker Heartbeats
worker_heartbeats = Table(
    'worker_heartbeats', metadata,
    Column('id', BigInteger, primary_key=True, autoincrement=True),
    Column('worker_id', UUID(as_uuid=True), ForeignKey('workers.id', ondelete='CASCADE'), nullable=False),
    Column('heartbeat_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('active_job_count', Integer, nullable=False, server_default='0'),
    Column('cpu_pct', Numeric(5, 2)),
    Column('mem_mb', Integer),
    Index('idx_worker_heartbeats_worker_ts', 'worker_id', 'heartbeat_at'),
)

# Dead Letter Queue
dead_letter_queue = Table(
    'dead_letter_queue', metadata,
    Column('id', UUID(as_uuid=True), primary_key=True, server_default=text('gen_random_uuid()')),
    Column('job_id', UUID(as_uuid=True), ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
    Column('queue_id', UUID(as_uuid=True), ForeignKey('queues.id', ondelete='CASCADE'), nullable=False),
    Column('reason', Text, nullable=False),
    Column('last_error', Text),
    Column('payload_snapshot', JSONB, nullable=False),
    Column('failed_attempt_count', Integer, nullable=False),
    Column('moved_at', DateTime(timezone=True), nullable=False, server_default=text('now()')),
    Column('resolved', Boolean, nullable=False, server_default='false'),
    Column('resolved_at', DateTime(timezone=True)),
    Index('idx_dlq_queue', 'queue_id', postgresql_where=text("NOT resolved")),
)
