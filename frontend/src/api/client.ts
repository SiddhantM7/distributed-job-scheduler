/**
 * Typed API Client for Distributed Job Scheduler
 */
import {
  DLQEntry,
  DLQSummary,
  Job,
  JobExecution,
  JobLog,
  Organization,
  Paginated,
  Project,
  ProjectMetricsOverview,
  ProjectThroughputMetrics,
  Queue,
  User,
  Worker,
} from './types';

const API_BASE = '/api/v1';

let authToken: string | null = localStorage.getItem('access_token');

export const setAuthToken = (token: string | null) => {
  authToken = token;
  if (token) {
    localStorage.setItem('access_token', token);
  } else {
    localStorage.removeItem('access_token');
  }
};

export const getAuthToken = () => authToken;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set('Content-Type', 'application/json');

  if (authToken) {
    headers.set('Authorization', `Bearer ${authToken}`);
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 204) {
    return {} as T;
  }

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({}));
    const message = errorBody?.detail?.message || errorBody?.detail || `HTTP Error ${res.status}`;
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }

  return res.json();
}

export const api = {
  // Auth
  login: (body: { email: string; password: string }) =>
    request<{ access_token: string; refresh_token: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  register: (body: { email: string; password: string; name: string }) =>
    request<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getMe: () => request<User>('/auth/me'),

  // Organizations & Projects
  listOrgs: () => request<Organization[]>('/organizations'),
  createOrg: (body: { name: string; slug: string }) =>
    request<Organization>('/organizations', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  listProjects: (orgId: string) =>
    request<Paginated<Project>>(`/organizations/${orgId}/projects`),
  createProject: (orgId: string, body: { name: string; description?: string }) =>
    request<Project>(`/organizations/${orgId}/projects`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getProject: (projectId: string) => request<Project>(`/projects/${projectId}`),

  // Queues
  listQueues: (projectId: string) => request<Queue[]>(`/projects/${projectId}/queues`),
  getQueue: (queueId: string) => request<Queue>(`/queues/${queueId}`),
  createQueue: (projectId: string, body: { name: string; priority?: number; max_concurrency?: number }) =>
    request<Queue>(`/projects/${projectId}/queues`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  pauseQueue: (queueId: string) =>
    request<Queue>(`/queues/${queueId}/pause`, { method: 'POST' }),
  resumeQueue: (queueId: string) =>
    request<Queue>(`/queues/${queueId}/resume`, { method: 'POST' }),
  deleteQueue: (queueId: string) =>
    request<void>(`/queues/${queueId}`, { method: 'DELETE' }),

  // Jobs
  listJobs: (queueId: string, params: { status?: string; type?: string; page?: number; page_size?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.status) query.set('status', params.status);
    if (params.type) query.set('type', params.type);
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));
    return request<Paginated<Job>>(`/queues/${queueId}/jobs?${query.toString()}`);
  },
  getJob: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  createJob: (queueId: string, body: any) =>
    request<Job>(`/queues/${queueId}/jobs`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  cancelJob: (jobId: string) =>
    request<Job>(`/jobs/${jobId}/cancel`, { method: 'POST' }),
  retryJob: (jobId: string) =>
    request<Job>(`/jobs/${jobId}/retry`, { method: 'POST' }),
  getJobExecutions: (jobId: string) =>
    request<JobExecution[]>(`/jobs/${jobId}/executions`),
  getExecutionLogs: (jobId: string, execId: string) =>
    request<JobLog[]>(`/jobs/${jobId}/executions/${execId}/logs`),

  // Workers
  listProjectWorkers: (projectId: string) =>
    request<Worker[]>(`/projects/${projectId}/workers`),
  getWorker: (workerId: string) => request<Worker>(`/workers/${workerId}`),

  // Dead Letter Queue
  listDLQ: (queueId: string, params: { resolved?: boolean; page?: number; page_size?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.resolved !== undefined) query.set('resolved', String(params.resolved));
    if (params.page) query.set('page', String(params.page));
    if (params.page_size) query.set('page_size', String(params.page_size));
    return request<Paginated<DLQEntry>>(`/queues/${queueId}/dlq?${query.toString()}`);
  },
  getDLQEntry: (dlqId: string) => request<DLQEntry>(`/dlq/${dlqId}`),
  getDLQSummary: (dlqId: string) =>
    request<DLQSummary>(`/dlq/${dlqId}/summary`, { method: 'POST' }),
  retryDLQ: (dlqId: string) => request<Job>(`/dlq/${dlqId}/retry`, { method: 'POST' }),
  resolveDLQ: (dlqId: string) => request<DLQEntry>(`/dlq/${dlqId}/resolve`, { method: 'POST' }),

  // Metrics
  getMetricsOverview: (projectId: string) =>
    request<ProjectMetricsOverview>(`/projects/${projectId}/metrics/overview`),
  getThroughputMetrics: (projectId: string, window: string = '1h') =>
    request<ProjectThroughputMetrics>(`/projects/${projectId}/metrics/throughput?window=${window}`),
};
