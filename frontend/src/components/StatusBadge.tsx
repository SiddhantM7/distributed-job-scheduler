import React from 'react';

interface StatusBadgeProps {
  status: string;
}

const statusColors: Record<string, { bg: string; text: string; border: string }> = {
  queued: { bg: '#e0f2fe', text: '#0369a1', border: '#bae6fd' },
  scheduled: { bg: '#fef3c7', text: '#b45309', border: '#fde68a' },
  claimed: { bg: '#f3e8ff', text: '#7e22ce', border: '#e9d5ff' },
  running: { bg: '#dbeafe', text: '#1d4ed8', border: '#bfdbfe' },
  completed: { bg: '#dcfce7', text: '#15803d', border: '#bbf7d0' },
  failed: { bg: '#fee2e2', text: '#b91c1c', border: '#fecaca' },
  dead_letter: { bg: '#fce7f3', text: '#be185d', border: '#fbcfe8' },
  cancelled: { bg: '#f3f4f6', text: '#4b5563', border: '#e5e7eb' },
  idle: { bg: '#dcfce7', text: '#15803d', border: '#bbf7d0' },
  busy: { bg: '#fef3c7', text: '#b45309', border: '#fde68a' },
  draining: { bg: '#ffedd5', text: '#c2410c', border: '#fed7aa' },
  offline: { bg: '#f3f4f6', text: '#6b7280', border: '#e5e7eb' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const colors = statusColors[status.toLowerCase()] || { bg: '#f3f4f6', text: '#374151', border: '#e5e7eb' };

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '0.2rem 0.55rem',
        borderRadius: '9999px',
        fontSize: '0.75rem',
        fontWeight: 600,
        backgroundColor: colors.bg,
        color: colors.text,
        border: `1px solid ${colors.border}`,
        textTransform: 'uppercase',
        letterSpacing: '0.03em',
      }}
    >
      {status}
    </span>
  );
};
