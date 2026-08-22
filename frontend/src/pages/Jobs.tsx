import React, { useState, useCallback, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { usePolling } from '../hooks/usePolling';
import { StatusBadge } from '../components/StatusBadge';
import { Job, Queue } from '../api/types';

export const Jobs: React.FC = () => {
  const { selectedProject } = useAuth();
  const [searchParams] = useSearchParams();
  const initialQueueId = searchParams.get('queue_id') || '';

  const [queues, setQueues] = useState<Queue[]>([]);
  const [selectedQueueId, setSelectedQueueId] = useState<string>(initialQueueId);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [page, setPage] = useState<number>(1);

  // Submit Job Modal State
  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [jobType, setJobType] = useState('process_data');
  const [jobKind, setJobKind] = useState<'immediate' | 'delayed' | 'recurring'>('immediate');
  const [jobPayload, setJobPayload] = useState('{\n  "key": "value"\n}');
  const [jobPriority, setJobPriority] = useState(0);
  const [runAt, setRunAt] = useState('');
  const [cronExp, setCronExp] = useState('0 * * * *');
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Load project queues
  useEffect(() => {
    if (!selectedProject) return;
    api.listQueues(selectedProject.id).then((qList) => {
      setQueues(qList);
      if (!selectedQueueId && qList.length > 0) {
        setSelectedQueueId(qList[0].id);
      }
    });
  }, [selectedProject]);

  const fetchJobs = useCallback(async () => {
    if (!selectedQueueId) return { items: [], total: 0, page: 1, page_size: 20 };
    return api.listJobs(selectedQueueId, {
      status: statusFilter || undefined,
      type: typeFilter.trim() || undefined,
      page,
      page_size: 20,
    });
  }, [selectedQueueId, statusFilter, typeFilter, page]);

  const { data: paginatedJobs, loading, refresh } = usePolling(fetchJobs, 5000, !!selectedQueueId);

  const handleSubmitJob = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedQueueId) return;
    setSubmitError(null);
    try {
      let parsedPayload = {};
      try {
        parsedPayload = JSON.parse(jobPayload);
      } catch (pErr) {
        throw new Error('Invalid JSON payload');
      }

      const body: any = {
        type: jobType.trim(),
        payload: parsedPayload,
        kind: jobKind,
        priority: Number(jobPriority),
      };

      if (jobKind === 'delayed') {
        if (!runAt) throw new Error('run_at date/time is required for delayed jobs');
        body.run_at = new Date(runAt).toISOString();
      } else if (jobKind === 'recurring') {
        if (!cronExp) throw new Error('cron_expression is required for recurring jobs');
        body.cron_expression = cronExp.trim();
      }

      await api.createJob(selectedQueueId, body);
      setShowSubmitModal(false);
      refresh();
    } catch (err: any) {
      setSubmitError(err.message || 'Failed to create job');
    }
  };

  const handleCancel = async (job: Job) => {
    try {
      await api.cancelJob(job.id);
      refresh();
    } catch (err: any) {
      alert(`Cancel failed: ${err.message}`);
    }
  };

  const handleRetry = async (job: Job) => {
    try {
      await api.retryJob(job.id);
      refresh();
    } catch (err: any) {
      alert(`Retry failed: ${err.message}`);
    }
  };

  return (
    <div>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', margin: 0, fontWeight: 700 }}>Jobs Explorer</h1>
          <p style={{ color: '#64748b', margin: '0.25rem 0 0 0', fontSize: '0.9rem' }}>
            Query, inspect, and submit execution workloads
          </p>
        </div>
        <button
          onClick={() => setShowSubmitModal(true)}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#2563eb',
            color: '#ffffff',
            border: 'none',
            borderRadius: '6px',
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          + Submit Job
        </button>
      </div>

      {/* Filter Bar */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem', marginBottom: '1rem', backgroundColor: '#ffffff', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <div>
          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem' }}>QUEUE</label>
          <select
            value={selectedQueueId}
            onChange={(e) => {
              setSelectedQueueId(e.target.value);
              setPage(1);
            }}
            style={{ padding: '0.4rem 0.65rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
          >
            {queues.map((q) => (
              <option key={q.id} value={q.id}>
                {q.name}
              </option>
            ))}
            {queues.length === 0 && <option value="">No queues available</option>}
          </select>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem' }}>STATUS</label>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            style={{ padding: '0.4rem 0.65rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
          >
            <option value="">All Statuses</option>
            <option value="queued">Queued</option>
            <option value="scheduled">Scheduled</option>
            <option value="claimed">Claimed</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="dead_letter">Dead Letter</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem' }}>JOB TYPE</label>
          <input
            type="text"
            placeholder="Filter by type..."
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter(e.target.value);
              setPage(1);
            }}
            style={{ padding: '0.4rem 0.65rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
          />
        </div>
      </div>

      {/* Jobs Table */}
      <div style={{ backgroundColor: '#ffffff', borderRadius: '8px', border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', fontSize: '0.75rem', textTransform: 'uppercase' }}>
              <th style={{ padding: '0.75rem 1rem' }}>Job ID / Type</th>
              <th style={{ padding: '0.75rem 1rem' }}>Kind</th>
              <th style={{ padding: '0.75rem 1rem' }}>Status</th>
              <th style={{ padding: '0.75rem 1rem' }}>Priority</th>
              <th style={{ padding: '0.75rem 1rem' }}>Attempts</th>
              <th style={{ padding: '0.75rem 1rem' }}>Created At</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(paginatedJobs?.items || []).map((j) => (
              <tr key={j.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '0.75rem 1rem' }}>
                  <Link to={`/jobs/${j.id}`} style={{ fontWeight: 600, color: '#2563eb', textDecoration: 'none', display: 'block' }}>
                    {j.type}
                  </Link>
                  <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>{j.id.slice(0, 8)}...</span>
                </td>
                <td style={{ padding: '0.75rem 1rem' }}>{j.kind}</td>
                <td style={{ padding: '0.75rem 1rem' }}>
                  <StatusBadge status={j.status} />
                </td>
                <td style={{ padding: '0.75rem 1rem' }}>{j.priority}</td>
                <td style={{ padding: '0.75rem 1rem' }}>
                  {j.attempt_count} / {j.max_attempts}
                </td>
                <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>
                  {new Date(j.created_at).toLocaleTimeString()}
                </td>
                <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                  {['queued', 'scheduled'].includes(j.status) && (
                    <button
                      onClick={() => handleCancel(j)}
                      style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: '1px solid #cbd5e1', background: '#ffffff', cursor: 'pointer' }}
                    >
                      Cancel
                    </button>
                  )}
                  {['failed', 'dead_letter'].includes(j.status) && (
                    <button
                      onClick={() => handleRetry(j)}
                      style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: '1px solid #bbf7d0', background: '#dcfce7', color: '#15803d', cursor: 'pointer' }}
                    >
                      Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {(!paginatedJobs || paginatedJobs.items.length === 0) && !loading && (
              <tr>
                <td colSpan={7} style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8' }}>
                  No jobs found matching criteria.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {/* Pagination Bar */}
        {paginatedJobs && paginatedJobs.total > 0 && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.75rem 1rem', borderTop: '1px solid #f1f5f9', fontSize: '0.85rem' }}>
            <span style={{ color: '#64748b' }}>
              Showing {paginatedJobs.items.length} of {paginatedJobs.total} jobs
            </span>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                style={{ padding: '0.25rem 0.65rem', borderRadius: '4px', border: '1px solid #cbd5e1', background: '#ffffff', cursor: page <= 1 ? 'not-allowed' : 'pointer' }}
              >
                Previous
              </button>
              <button
                disabled={page * 20 >= paginatedJobs.total}
                onClick={() => setPage(page + 1)}
                style={{ padding: '0.25rem 0.65rem', borderRadius: '4px', border: '1px solid #cbd5e1', background: '#ffffff', cursor: page * 20 >= paginatedJobs.total ? 'not-allowed' : 'pointer' }}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Submit Job Modal */}
      {showSubmitModal && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ backgroundColor: '#ffffff', padding: '1.75rem', borderRadius: '10px', width: '460px', maxHeight: '90vh', overflowY: 'auto' }}>
            <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.15rem' }}>Submit New Job</h3>
            {submitError && (
              <div style={{ padding: '0.5rem', marginBottom: '1rem', backgroundColor: '#fee2e2', color: '#b91c1c', borderRadius: '6px', fontSize: '0.8rem' }}>
                {submitError}
              </div>
            )}
            <form onSubmit={handleSubmitJob}>
              <div style={{ marginBottom: '0.75rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem' }}>Job Type</label>
                <input
                  type="text"
                  required
                  value={jobType}
                  onChange={(e) => setJobType(e.target.value)}
                  style={{ width: '100%', padding: '0.45rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
                />
              </div>

              <div style={{ marginBottom: '0.75rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem' }}>Kind</label>
                <select
                  value={jobKind}
                  onChange={(e) => setJobKind(e.target.value as any)}
                  style={{ width: '100%', padding: '0.45rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
                >
                  <option value="immediate">Immediate</option>
                  <option value="delayed">Delayed</option>
                  <option value="recurring">Recurring (Cron)</option>
                </select>
              </div>

              {jobKind === 'delayed' && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem' }}>Run At (Date/Time)</label>
                  <input
                    type="datetime-local"
                    required
                    value={runAt}
                    onChange={(e) => setRunAt(e.target.value)}
                    style={{ width: '100%', padding: '0.45rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
                  />
                </div>
              )}

              {jobKind === 'recurring' && (
                <div style={{ marginBottom: '0.75rem' }}>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem' }}>Cron Expression</label>
                  <input
                    type="text"
                    required
                    value={cronExp}
                    onChange={(e) => setCronExp(e.target.value)}
                    placeholder="*/5 * * * *"
                    style={{ width: '100%', padding: '0.45rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
                  />
                </div>
              )}

              <div style={{ marginBottom: '0.75rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem' }}>Priority</label>
                <input
                  type="number"
                  value={jobPriority}
                  onChange={(e) => setJobPriority(Number(e.target.value))}
                  style={{ width: '100%', padding: '0.45rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
                />
              </div>

              <div style={{ marginBottom: '1.25rem' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem' }}>Payload (JSON)</label>
                <textarea
                  rows={4}
                  value={jobPayload}
                  onChange={(e) => setJobPayload(e.target.value)}
                  style={{ width: '100%', padding: '0.45rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontFamily: 'monospace', fontSize: '0.8rem' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setShowSubmitModal(false)}
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: '#f8fafc', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: 'none', background: '#2563eb', color: '#ffffff', fontWeight: 500, cursor: 'pointer' }}
                >
                  Submit Job
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
