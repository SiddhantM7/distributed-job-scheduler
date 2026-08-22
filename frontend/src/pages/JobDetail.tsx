import React, { useCallback, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { StatusBadge } from '../components/StatusBadge';
import { JobExecution, JobLog } from '../api/types';

export const JobDetail: React.FC = () => {
  const { jobId } = useParams<{ jobId: string }>();
  const [selectedExecId, setSelectedExecId] = useState<string | null>(null);
  const [logs, setLogs] = useState<JobLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  const fetchJob = useCallback(async () => {
    if (!jobId) return null;
    return api.getJob(jobId);
  }, [jobId]);

  const fetchExecutions = useCallback(async () => {
    if (!jobId) return [];
    return api.getJobExecutions(jobId);
  }, [jobId]);

  const { data: job, loading: jobLoading, refresh } = usePolling(fetchJob, 5000, !!jobId);
  const { data: executions } = usePolling(fetchExecutions, 5000, !!jobId);

  const handleSelectExecution = async (exec: JobExecution) => {
    if (!jobId) return;
    setSelectedExecId(exec.id);
    setLogsLoading(true);
    try {
      const l = await api.getExecutionLogs(jobId, exec.id);
      setLogs(l);
    } catch (err) {
      console.error('Failed to load logs:', err);
    } finally {
      setLogsLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!jobId) return;
    try {
      await api.cancelJob(jobId);
      refresh();
    } catch (err: any) {
      alert(`Cancel failed: ${err.message}`);
    }
  };

  const handleRetry = async () => {
    if (!jobId) return;
    try {
      await api.retryJob(jobId);
      refresh();
    } catch (err: any) {
      alert(`Retry failed: ${err.message}`);
    }
  };

  if (jobLoading && !job) {
    return <div style={{ padding: '2rem' }}>Loading job details...</div>;
  }

  if (!job) {
    return <div style={{ padding: '2rem' }}>Job not found.</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Link to="/jobs" style={{ color: '#2563eb', fontSize: '0.85rem', textDecoration: 'none' }}>
            ← Back to Jobs
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginTop: '0.25rem' }}>
            <h1 style={{ fontSize: '1.4rem', margin: 0, fontWeight: 700 }}>Job: {job.type}</h1>
            <StatusBadge status={job.status} />
          </div>
        </div>

        <div style={{ display: 'flex', gap: '0.5rem' }}>
          {['queued', 'scheduled'].includes(job.status) && (
            <button
              onClick={handleCancel}
              style={{ padding: '0.45rem 0.85rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: '#ffffff', cursor: 'pointer', fontWeight: 500 }}
            >
              Cancel Job
            </button>
          )}
          {['failed', 'dead_letter'].includes(job.status) && (
            <button
              onClick={handleRetry}
              style={{ padding: '0.45rem 0.85rem', borderRadius: '6px', border: '1px solid #bbf7d0', background: '#dcfce7', color: '#15803d', cursor: 'pointer', fontWeight: 600 }}
            >
              Retry Job
            </button>
          )}
        </div>
      </div>

      {/* Metadata Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
        <div style={{ backgroundColor: '#ffffff', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>Job ID</div>
          <div style={{ fontSize: '0.85rem', fontFamily: 'monospace', marginTop: '0.25rem', wordBreak: 'break-all' }}>{job.id}</div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>Kind / Priority</div>
          <div style={{ fontSize: '0.9rem', marginTop: '0.25rem' }}>
            {job.kind} (Priority: {job.priority})
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>Attempt Count</div>
          <div style={{ fontSize: '0.9rem', marginTop: '0.25rem' }}>
            {job.attempt_count} of {job.max_attempts} max attempts
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.75rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>Created At</div>
          <div style={{ fontSize: '0.85rem', marginTop: '0.25rem' }}>{new Date(job.created_at).toLocaleString()}</div>
        </div>
      </div>

      {/* Payload & Result Section */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '0.9rem', fontWeight: 600 }}>Payload Snapshot</h3>
          <pre style={{ margin: 0, padding: '0.75rem', backgroundColor: '#f8fafc', borderRadius: '6px', fontSize: '0.8rem', overflowX: 'auto' }}>
            {JSON.stringify(job.payload, null, 2)}
          </pre>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '0.9rem', fontWeight: 600 }}>Result / Error Output</h3>
          {job.error ? (
            <div style={{ padding: '0.75rem', backgroundColor: '#fee2e2', color: '#b91c1c', borderRadius: '6px', fontSize: '0.8rem', fontFamily: 'monospace' }}>
              {job.error}
            </div>
          ) : job.result ? (
            <pre style={{ margin: 0, padding: '0.75rem', backgroundColor: '#f8fafc', borderRadius: '6px', fontSize: '0.8rem', overflowX: 'auto' }}>
              {JSON.stringify(job.result, null, 2)}
            </pre>
          ) : (
            <div style={{ color: '#94a3b8', fontSize: '0.85rem', fontStyle: 'italic' }}>No result or error recorded yet.</div>
          )}
        </div>
      </div>

      {/* Execution Attempts Timeline */}
      <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 600 }}>Execution History</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {(executions || []).map((exec) => (
            <div
              key={exec.id}
              onClick={() => handleSelectExecution(exec)}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '0.75rem',
                borderRadius: '6px',
                border: selectedExecId === exec.id ? '1px solid #2563eb' : '1px solid #e2e8f0',
                backgroundColor: selectedExecId === exec.id ? '#eff6ff' : '#f8fafc',
                cursor: 'pointer',
              }}
            >
              <div>
                <span style={{ fontWeight: 600, fontSize: '0.85rem', marginRight: '0.75rem' }}>
                  Attempt #{exec.attempt_number}
                </span>
                <StatusBadge status={exec.status} />
              </div>
              <div style={{ fontSize: '0.8rem', color: '#64748b' }}>
                {exec.duration_ms ? `${exec.duration_ms}ms` : 'In-flight'} · {new Date(exec.started_at).toLocaleTimeString()}
              </div>
            </div>
          ))}
          {(!executions || executions.length === 0) && (
            <div style={{ color: '#94a3b8', fontSize: '0.85rem' }}>No execution attempts yet.</div>
          )}
        </div>

        {/* Selected Execution Logs */}
        {selectedExecId && (
          <div style={{ marginTop: '1.25rem', borderTop: '1px solid #e2e8f0', paddingTop: '1rem' }}>
            <h4 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', fontWeight: 600 }}>
              Execution Logs (Attempt #{executions?.find((e) => e.id === selectedExecId)?.attempt_number})
            </h4>
            {logsLoading ? (
              <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Loading logs...</div>
            ) : logs.length > 0 ? (
              <div style={{ backgroundColor: '#0f172a', color: '#f8fafc', padding: '0.75rem', borderRadius: '6px', fontFamily: 'monospace', fontSize: '0.8rem', maxHeight: '200px', overflowY: 'auto' }}>
                {logs.map((l) => (
                  <div key={l.id} style={{ marginBottom: '0.25rem' }}>
                    <span style={{ color: '#94a3b8' }}>[{new Date(l.timestamp).toLocaleTimeString()}]</span>{' '}
                    <span style={{ color: l.level === 'error' ? '#f87171' : '#4ade80', fontWeight: 600 }}>[{l.level.toUpperCase()}]</span>{' '}
                    {l.message}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: '#94a3b8', fontSize: '0.8rem' }}>No log lines recorded for this execution.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
