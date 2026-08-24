/**
 * API Type Definitions matching Backend Schemas
 */

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
  memberships: OrgMembership[];
}

export interface OrgMembership {
  organization_id: string;
  organization_name: string;
  role: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  organization_id: string;
  created_by?: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
}

export interface QueueLiveStats {
  queued: number;
  scheduled: number;
  claimed: number;
  running: number;
  completed: number;
  failed: number;
  dead_letter: number;
  cancelled: number;
}

export interface Queue {
  id: string;
  project_id: string;
  default_retry_policy_id?: string | null;
  name: string;
  priority: number;
  max_concurrency: number;
  is_paused: boolean;
  created_at: string;
  updated_at: string;
  stats?: QueueLiveStats;
}

export interface Job {
  id: string;
  queue_id: string;
  scheduled_job_id?: string | null;
  retry_policy_id?: string | null;
  claimed_by?: string | null;
  batch_id?: string | null;
  type: string;
  payload: Record<string, any>;
  kind: string;
  status: 'queued' | 'scheduled' | 'claimed' | 'running' | 'completed' | 'failed' | 'dead_letter' | 'cancelled';
  priority: number;
  run_at: string;
  attempt_count: number;
  max_attempts: number;
  idempotency_key?: string | null;
  claimed_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  result?: Record<string, any> | null;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobExecution {
  id: string;
  job_id: string;
  worker_id?: string | null;
  attempt_number: number;
  status: 'running' | 'completed' | 'failed';
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  error?: string | null;
  result?: Record<string, any> | null;
}

export interface JobLog {
  id: number;
  job_execution_id: string;
  timestamp: string;
  level: string;
  message: string;
}

export interface Worker {
  id: string;
  hostname: string;
  pid?: number | null;
  status: 'idle' | 'busy' | 'draining' | 'offline';
  concurrency: number;
  started_at: string;
  last_heartbeat_at: string;
  metadata: Record<string, any>;
  assigned_queue_ids: string[];
  active_job_count: number;
}

export interface DLQEntry {
  id: string;
  job_id: string;
  queue_id: string;
  reason: string;
  last_error?: string | null;
  payload_snapshot: Record<string, any>;
  failed_attempt_count: number;
  moved_at: string;
  resolved: boolean;
  resolved_at?: string | null;
}

export interface DLQSummary {
  dlq_id: string;
  job_id: string;
  job_type: string;
  category: string;
  summary: string;
  root_cause: string;
  suggested_action: string;
  generated_at: string;
}

export interface ProjectMetricsOverview {
  project_id: string;
  total_queues: number;
  active_workers: number;
  job_status_counts: {
    queued: number;
    scheduled: number;
    claimed: number;
    running: number;
    completed: number;
    failed: number;
    dead_letter: number;
    cancelled: number;
  };
  total_jobs: number;
  total_completed: number;
  total_failed: number;
  failure_rate: number;
  avg_duration_ms?: number | null;
}

export interface ThroughputBucket {
  timestamp: string;
  completed: number;
  failed: number;
  avg_duration_ms?: number | null;
}

export interface ProjectThroughputMetrics {
  project_id: string;
  window: string;
  bucket_size: string;
  buckets: ThroughputBucket[];
  total_completed: number;
  total_failed: number;
  jobs_per_minute: number;
  overall_failure_rate: number;
}

export interface Paginated<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
