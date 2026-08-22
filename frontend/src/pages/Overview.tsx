import React, { useState, useCallback } from 'react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { usePolling } from '../hooks/usePolling';
import { StatusBadge } from '../components/StatusBadge';

export const Overview: React.FC = () => {
  const { selectedProject } = useAuth();
  const [window, setWindow] = useState<'1h' | '24h' | '7d'>('1h');

  // Fetch overview metrics
  const fetchOverview = useCallback(async () => {
    if (!selectedProject) return null;
    return api.getMetricsOverview(selectedProject.id);
  }, [selectedProject]);

  // Fetch throughput metrics
  const fetchThroughput = useCallback(async () => {
    if (!selectedProject) return null;
    return api.getThroughputMetrics(selectedProject.id, window);
  }, [selectedProject, window]);

  const { data: overview, loading: overviewLoading } = usePolling(fetchOverview, 5000, !!selectedProject);
  const { data: throughput, loading: throughputLoading } = usePolling(fetchThroughput, 5000, !!selectedProject);

  if (!selectedProject) {
    return (
      <div style={{ textAlign: 'center', padding: '4rem', backgroundColor: '#ffffff', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <h2>No Project Selected</h2>
        <p style={{ color: '#64748b' }}>Please select or create a project from the top navbar to view metrics.</p>
      </div>
    );
  }

  // Format chart data
  const chartData = (throughput?.buckets || []).map((b) => ({
    time: new Date(b.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    completed: b.completed,
    failed: b.failed,
  }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.5rem', margin: 0, fontWeight: 700 }}>Project Overview</h1>
          <p style={{ color: '#64748b', margin: '0.25rem 0 0 0', fontSize: '0.9rem' }}>
            Real-time cross-queue health & telemetry for <strong>{selectedProject.name}</strong>
          </p>
        </div>
        <span style={{ fontSize: '0.75rem', color: '#64748b', backgroundColor: '#f1f5f9', padding: '0.35rem 0.65rem', borderRadius: '9999px', border: '1px solid #e2e8f0' }}>
          ● Live polling (5s)
        </span>
      </div>

      {/* Metric Cards Row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Active Workers</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '0.25rem', color: '#2563eb' }}>
            {overview?.active_workers ?? (overviewLoading ? '...' : 0)}
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Total Queues</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '0.25rem' }}>
            {overview?.total_queues ?? (overviewLoading ? '...' : 0)}
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Total Jobs</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '0.25rem' }}>
            {overview?.total_jobs ?? (overviewLoading ? '...' : 0)}
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Failure Rate</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '0.25rem', color: (overview?.failure_rate || 0) > 0.05 ? '#ef4444' : '#16a34a' }}>
            {overview ? `${(overview.failure_rate * 100).toFixed(1)}%` : '0%'}
          </div>
        </div>

        <div style={{ backgroundColor: '#ffffff', padding: '1.25rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
          <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Avg Duration</div>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, marginTop: '0.25rem', color: '#475569' }}>
            {overview?.avg_duration_ms ? `${Math.round(overview.avg_duration_ms)}ms` : '—'}
          </div>
        </div>
      </div>

      {/* Status Breakdown Grid */}
      <div style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1rem', fontWeight: 600 }}>Job Status Breakdown</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '0.75rem' }}>
          {overview?.job_status_counts &&
            Object.entries(overview.job_status_counts).map(([status, count]) => (
              <div key={status} style={{ padding: '0.75rem', borderRadius: '6px', backgroundColor: '#f8fafc', border: '1px solid #f1f5f9' }}>
                <StatusBadge status={status} />
                <div style={{ fontSize: '1.3rem', fontWeight: 700, marginTop: '0.5rem' }}>{count}</div>
              </div>
            ))}
        </div>
      </div>

      {/* Throughput Chart */}
      <div style={{ backgroundColor: '#ffffff', padding: '1.5rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 600 }}>Execution Throughput</h3>
            <span style={{ fontSize: '0.8rem', color: '#64748b' }}>
              Completed vs Failed executions ({throughput?.jobs_per_minute || 0} jobs/min)
            </span>
          </div>

          {/* Window Toggle */}
          <div style={{ display: 'flex', gap: '0.25rem', backgroundColor: '#f1f5f9', padding: '0.25rem', borderRadius: '6px' }}>
            {(['1h', '24h', '7d'] as const).map((w) => (
              <button
                key={w}
                onClick={() => setWindow(w)}
                style={{
                  padding: '0.25rem 0.65rem',
                  fontSize: '0.8rem',
                  borderRadius: '4px',
                  border: 'none',
                  backgroundColor: window === w ? '#ffffff' : 'transparent',
                  fontWeight: window === w ? 600 : 400,
                  boxShadow: window === w ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
                  cursor: 'pointer',
                }}
              >
                {w}
              </button>
            ))}
          </div>
        </div>

        <div style={{ height: '280px', width: '100%' }}>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="time" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
                <Tooltip />
                <Area type="monotone" dataKey="completed" stackId="1" stroke="#16a34a" fill="#dcfce7" name="Completed" />
                <Area type="monotone" dataKey="failed" stackId="1" stroke="#dc2626" fill="#fee2e2" name="Failed" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: '0.9rem' }}>
              No execution telemetry recorded in this time window.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
