import React, { useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { usePolling } from '../hooks/usePolling';
import { StatusBadge } from '../components/StatusBadge';
import { Queue } from '../api/types';

export const Queues: React.FC = () => {
  const { selectedProject } = useAuth();
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [priority, setPriority] = useState(0);
  const [maxConcurrency, setMaxConcurrency] = useState(10);
  const [actionError, setActionError] = useState<string | null>(null);

  const fetchQueues = useCallback(async () => {
    if (!selectedProject) return [];
    return api.listQueues(selectedProject.id);
  }, [selectedProject]);

  const { data: queues, loading, refresh } = usePolling(fetchQueues, 5000, !!selectedProject);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProject) return;
    setActionError(null);
    try {
      await api.createQueue(selectedProject.id, {
        name: name.trim(),
        priority: Number(priority),
        max_concurrency: Number(maxConcurrency),
      });
      setShowCreate(false);
      setName('');
      setPriority(0);
      setMaxConcurrency(10);
      refresh();
    } catch (err: any) {
      setActionError(err.message || 'Failed to create queue');
    }
  };

  const handleTogglePause = async (q: Queue) => {
    try {
      if (q.is_paused) {
        await api.resumeQueue(q.id);
      } else {
        await api.pauseQueue(q.id);
      }
      refresh();
    } catch (err: any) {
      alert(`Action failed: ${err.message}`);
    }
  };

  const handleDelete = async (q: Queue) => {
    if (!confirm(`Are you sure you want to delete queue "${q.name}"?`)) return;
    try {
      await api.deleteQueue(q.id);
      refresh();
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', margin: 0, fontWeight: 700 }}>Queues Management</h1>
          <p style={{ color: '#64748b', margin: '0.25rem 0 0 0', fontSize: '0.9rem' }}>
            Configured execution queues for {selectedProject?.name || 'project'}
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
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
          + Create Queue
        </button>
      </div>

      {actionError && (
        <div style={{ padding: '0.75rem', marginBottom: '1rem', backgroundColor: '#fee2e2', color: '#b91c1c', borderRadius: '6px', fontSize: '0.85rem' }}>
          {actionError}
        </div>
      )}

      {/* Queues Table */}
      <div style={{ backgroundColor: '#ffffff', borderRadius: '8px', border: '1px solid #e2e8f0', overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
          <thead>
            <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', color: '#475569', fontSize: '0.8rem', textTransform: 'uppercase' }}>
              <th style={{ padding: '0.75rem 1rem' }}>Queue Name</th>
              <th style={{ padding: '0.75rem 1rem' }}>Priority</th>
              <th style={{ padding: '0.75rem 1rem' }}>Max Concurrency</th>
              <th style={{ padding: '0.75rem 1rem' }}>State</th>
              <th style={{ padding: '0.75rem 1rem', textAlign: 'right' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {(queues || []).map((q) => (
              <tr key={q.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '1rem' }}>
                  <Link to={`/queues/${q.id}`} style={{ fontWeight: 600, color: '#2563eb', textDecoration: 'none' }}>
                    {q.name}
                  </Link>
                </td>
                <td style={{ padding: '1rem' }}>{q.priority}</td>
                <td style={{ padding: '1rem' }}>{q.max_concurrency} workers</td>
                <td style={{ padding: '1rem' }}>
                  {q.is_paused ? <StatusBadge status="draining" /> : <StatusBadge status="idle" />}
                </td>
                <td style={{ padding: '1rem', textAlign: 'right' }}>
                  <button
                    onClick={() => handleTogglePause(q)}
                    style={{
                      padding: '0.35rem 0.65rem',
                      marginRight: '0.5rem',
                      fontSize: '0.8rem',
                      borderRadius: '4px',
                      border: '1px solid #cbd5e1',
                      backgroundColor: '#ffffff',
                      cursor: 'pointer',
                    }}
                  >
                    {q.is_paused ? 'Resume' : 'Pause'}
                  </button>
                  <button
                    onClick={() => handleDelete(q)}
                    style={{
                      padding: '0.35rem 0.65rem',
                      fontSize: '0.8rem',
                      borderRadius: '4px',
                      border: '1px solid #fecaca',
                      backgroundColor: '#fee2e2',
                      color: '#b91c1c',
                      cursor: 'pointer',
                    }}
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {(!queues || queues.length === 0) && !loading && (
              <tr>
                <td colSpan={5} style={{ textAlign: 'center', padding: '3rem', color: '#94a3b8' }}>
                  No queues configured. Click "+ Create Queue" to create one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Create Queue Modal */}
      {showCreate && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ backgroundColor: '#ffffff', padding: '1.75rem', borderRadius: '10px', width: '420px', boxShadow: '0 10px 25px rgba(0,0,0,0.1)' }}>
            <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.15rem' }}>Create Queue</h3>
            <form onSubmit={handleCreate}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.35rem' }}>Queue Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                  placeholder="e.g. high-priority-jobs"
                />
              </div>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.35rem' }}>Priority (higher = claimed first)</label>
                <input
                  type="number"
                  value={priority}
                  onChange={(e) => setPriority(Number(e.target.value))}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                />
              </div>
              <div style={{ marginBottom: '1.25rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.35rem' }}>Max Concurrency</label>
                <input
                  type="number"
                  min={1}
                  value={maxConcurrency}
                  onChange={(e) => setMaxConcurrency(Number(e.target.value))}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: '#f8fafc', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: 'none', background: '#2563eb', color: '#ffffff', fontWeight: 500, cursor: 'pointer' }}
                >
                  Save Queue
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
