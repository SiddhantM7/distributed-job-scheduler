import React, { useCallback } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { usePolling } from '../hooks/usePolling';
import { StatusBadge } from '../components/StatusBadge';

export const Workers: React.FC = () => {
  const { selectedProject } = useAuth();

  const fetchWorkers = useCallback(async () => {
    if (!selectedProject) return [];
    return api.listProjectWorkers(selectedProject.id);
  }, [selectedProject]);

  const { data: workers, loading } = usePolling(fetchWorkers, 5000, !!selectedProject);

  return (
    <div>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', margin: 0, fontWeight: 700 }}>Workers Fleet</h1>
          <p style={{ color: '#64748b', margin: '0.25rem 0 0 0', fontSize: '0.9rem' }}>
            Active worker processes servicing queues for <strong>{selectedProject?.name || 'project'}</strong>
          </p>
        </div>
      </div>

      {/* Workers Table */}
      <div style={{ backgroundColor: '#ffffff', borderRadius: '8px', border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', fontSize: '0.75rem', textTransform: 'uppercase' }}>
              <th style={{ padding: '0.75rem 1rem' }}>Worker Node / PID</th>
              <th style={{ padding: '0.75rem 1rem' }}>Status</th>
              <th style={{ padding: '0.75rem 1rem' }}>Concurrency Limit</th>
              <th style={{ padding: '0.75rem 1rem' }}>Assigned Queues</th>
              <th style={{ padding: '0.75rem 1rem' }}>Last Heartbeat</th>
            </tr>
          </thead>
          <tbody>
            {(workers || []).map((w) => (
              <tr key={w.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '0.75rem 1rem' }}>
                  <div style={{ fontWeight: 600, color: '#1e293b' }}>{w.hostname}</div>
                  <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>PID: {w.pid ?? '—'} · ID: {w.id.slice(0, 8)}...</div>
                </td>
                <td style={{ padding: '0.75rem 1rem' }}>
                  <StatusBadge status={w.status} />
                </td>
                <td style={{ padding: '0.75rem 1rem' }}>{w.concurrency} concurrent tasks</td>
                <td style={{ padding: '0.75rem 1rem' }}>
                  {w.assigned_queue_ids && w.assigned_queue_ids.length > 0 ? (
                    <span style={{ fontSize: '0.8rem', color: '#475569' }}>
                      {w.assigned_queue_ids.length} queue(s)
                    </span>
                  ) : (
                    <span style={{ fontSize: '0.8rem', color: '#94a3b8', fontStyle: 'italic' }}>
                      All project queues (Shared)
                    </span>
                  )}
                </td>
                <td style={{ padding: '0.75rem 1rem', color: '#64748b' }}>
                  {new Date(w.last_heartbeat_at).toLocaleTimeString()}
                </td>
              </tr>
            ))}
            {(!workers || workers.length === 0) && !loading && (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8' }}>
                  No active worker processes detected for this project.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
