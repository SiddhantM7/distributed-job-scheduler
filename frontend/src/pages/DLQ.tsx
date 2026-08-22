import React, { useState, useCallback, useEffect } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { usePolling } from '../hooks/usePolling';
import { DLQEntry, Queue } from '../api/types';

export const DLQ: React.FC = () => {
  const { selectedProject } = useAuth();
  const [queues, setQueues] = useState<Queue[]>([]);
  const [selectedQueueId, setSelectedQueueId] = useState<string>('');
  const [resolvedFilter, setResolvedFilter] = useState<string>('false');
  const [page, setPage] = useState<number>(1);
  const [selectedPayload, setSelectedPayload] = useState<Record<string, any> | null>(null);

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

  const fetchDLQ = useCallback(async () => {
    if (!selectedQueueId) return { items: [], total: 0, page: 1, page_size: 20 };
    const resolvedParam = resolvedFilter === '' ? undefined : resolvedFilter === 'true';
    return api.listDLQ(selectedQueueId, {
      resolved: resolvedParam,
      page,
      page_size: 20,
    });
  }, [selectedQueueId, resolvedFilter, page]);

  const { data: paginatedDLQ, loading, refresh } = usePolling(fetchDLQ, 5000, !!selectedQueueId);

  const handleRetry = async (entry: DLQEntry) => {
    try {
      await api.retryDLQ(entry.id);
      refresh();
    } catch (err: any) {
      alert(`Retry failed: ${err.message}`);
    }
  };

  const handleResolve = async (entry: DLQEntry) => {
    try {
      await api.resolveDLQ(entry.id);
      refresh();
    } catch (err: any) {
      alert(`Resolve failed: ${err.message}`);
    }
  };

  return (
    <div>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', margin: 0, fontWeight: 700 }}>Dead Letter Queue (DLQ)</h1>
          <p style={{ color: '#64748b', margin: '0.25rem 0 0 0', fontSize: '0.9rem' }}>
            Triage permanently failed jobs and replay payload snapshots
          </p>
        </div>
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
          <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', marginBottom: '0.25rem' }}>TRIAGE STATUS</label>
          <select
            value={resolvedFilter}
            onChange={(e) => {
              setResolvedFilter(e.target.value);
              setPage(1);
            }}
            style={{ padding: '0.4rem 0.65rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem' }}
          >
            <option value="false">Unresolved Only (Action Required)</option>
            <option value="true">Resolved Only</option>
            <option value="">All DLQ Entries</option>
          </select>
        </div>
      </div>

      {/* DLQ Table */}
      <div style={{ backgroundColor: '#ffffff', borderRadius: '8px', border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', fontSize: '0.75rem', textTransform: 'uppercase' }}>
              <th style={{ padding: '0.75rem 1rem' }}>Reason / Error</th>
              <th style={{ padding: '0.75rem 1rem' }}>Job ID</th>
              <th style={{ padding: '0.75rem 1rem' }}>Failed Attempts</th>
              <th style={{ padding: '0.75rem 1rem' }}>Moved At</th>
              <th style={{ padding: '0.75rem 1rem' }}>Status</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(paginatedDLQ?.items || []).map((entry) => (
              <tr key={entry.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '0.75rem 1rem', maxWidth: '300px' }}>
                  <div style={{ fontWeight: 600, color: '#b91c1c' }}>{entry.reason}</div>
                  {entry.last_error && (
                    <div style={{ fontSize: '0.75rem', color: '#64748b', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {entry.last_error}
                    </div>
                  )}
                  <button
                    onClick={() => setSelectedPayload(entry.payload_snapshot)}
                    style={{ marginTop: '0.25rem', padding: '0.15rem 0.4rem', fontSize: '0.7rem', borderRadius: '4px', border: '1px solid #cbd5e1', background: '#f8fafc', cursor: 'pointer' }}
                  >
                    🔍 View Payload
                  </button>
                </td>
                <td style={{ padding: '0.75rem 1rem', fontFamily: 'monospace', fontSize: '0.75rem', color: '#64748b' }}>
                  {entry.job_id.slice(0, 8)}...
                </td>
                <td style={{ padding: '0.75rem 1rem' }}>{entry.failed_attempt_count} attempts</td>
                <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>
                  {new Date(entry.moved_at).toLocaleString()}
                </td>
                <td style={{ padding: '0.75rem 1rem' }}>
                  {entry.resolved ? (
                    <span style={{ color: '#16a34a', fontWeight: 600, fontSize: '0.75rem' }}>✓ Resolved</span>
                  ) : (
                    <span style={{ color: '#dc2626', fontWeight: 600, fontSize: '0.75rem' }}>● Unresolved</span>
                  )}
                </td>
                <td style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>
                  {!entry.resolved && (
                    <div style={{ display: 'flex', gap: '0.35rem', justifyContent: 'flex-end' }}>
                      <button
                        onClick={() => handleRetry(entry)}
                        style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: '1px solid #bbf7d0', background: '#dcfce7', color: '#15803d', cursor: 'pointer', fontWeight: 600 }}
                      >
                        Re-Submit
                      </button>
                      <button
                        onClick={() => handleResolve(entry)}
                        style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem', borderRadius: '4px', border: '1px solid #cbd5e1', background: '#ffffff', cursor: 'pointer' }}
                      >
                        Acknowledge
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {(!paginatedDLQ || paginatedDLQ.items.length === 0) && !loading && (
              <tr>
                <td colSpan={6} style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8' }}>
                  No dead letter queue entries found matching criteria.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Payload Modal */}
      {selectedPayload && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '10px', width: '500px', maxHeight: '80vh', overflowY: 'auto' }}>
            <h3 style={{ marginTop: 0, marginBottom: '0.75rem', fontSize: '1.1rem' }}>Payload Snapshot</h3>
            <pre style={{ backgroundColor: '#f8fafc', padding: '1rem', borderRadius: '6px', fontSize: '0.85rem', overflowX: 'auto' }}>
              {JSON.stringify(selectedPayload, null, 2)}
            </pre>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1rem' }}>
              <button
                onClick={() => setSelectedPayload(null)}
                style={{ padding: '0.45rem 0.9rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: '#f8fafc', cursor: 'pointer' }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
