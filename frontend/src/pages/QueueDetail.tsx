import React, { useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '../api/client';
import { usePolling } from '../hooks/usePolling';
import { StatusBadge } from '../components/StatusBadge';

export const QueueDetail: React.FC = () => {
  const { queueId } = useParams<{ queueId: string }>();

  const fetchQueue = useCallback(async () => {
    if (!queueId) return null;
    return api.getQueue(queueId);
  }, [queueId]);

  const { data: queue, loading } = usePolling(fetchQueue, 5000, !!queueId);

  if (loading && !queue) {
    return <div style={{ padding: '2rem' }}>Loading queue details...</div>;
  }

  if (!queue) {
    return <div style={{ padding: '2rem' }}>Queue not found.</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Link to="/queues" style={{ color: '#2563eb', fontSize: '0.85rem', textDecoration: 'none' }}>
            ← Back to Queues
          </Link>
          <h1 style={{ fontSize: '1.5rem', margin: '0.25rem 0 0 0', fontWeight: 700 }}>
            Queue: {queue.name}
          </h1>
        </div>
        <Link
          to={`/jobs?queue_id=${queue.id}`}
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: '#2563eb',
            color: '#ffffff',
            borderRadius: '6px',
            textDecoration: 'none',
            fontWeight: 600,
            fontSize: '0.85rem',
          }}
        >
          View Jobs in this Queue →
        </Link>
      </div>

      {/* Overview Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>State</div>
          <div style={{ marginTop: '0.5rem' }}>
            {queue.is_paused ? <StatusBadge status="draining" /> : <StatusBadge status="idle" />}
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>Priority</div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, marginTop: '0.25rem' }}>{queue.priority}</div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600, textTransform: 'uppercase' }}>Max Concurrency</div>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, marginTop: '0.25rem' }}>{queue.max_concurrency}</div>
        </div>
      </div>

      {/* Live Job Counts */}
      {queue.stats && (
        <div style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 600 }}>Live Job Stats</h3>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: '0.75rem' }}>
            {Object.entries(queue.stats).map(([status, count]) => (
              <div key={status} style={{ padding: '0.75rem', borderRadius: '6px', backgroundColor: '#f8fafc', border: '1px solid #f1f5f9' }}>
                <StatusBadge status={status} />
                <div style={{ fontSize: '1.3rem', fontWeight: 700, marginTop: '0.5rem' }}>{count}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
