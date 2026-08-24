import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const Register: React.FC = () => {
  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.register({ email, name, password });
      // Auto login after register
      const loginRes = await api.login({ email, password });
      await login(loginRes.access_token);
      // Auto-create initial default org
      try {
        await api.createOrg({ name: `${name}'s Org`, slug: `org-${Date.now()}` });
      } catch (oErr) {
        console.warn('Initial org creation fallback:', oErr);
      }
      navigate('/');
    } catch (err: any) {
      setError(err.message || 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', backgroundColor: '#f8fafc', fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif' }}>
      {/* ── Left Hero Panel (Architecture & Brand) ─────────────────────────────────── */}
      <div
        className="auth-hero-panel"
        style={{
          flex: 1,
          backgroundColor: '#0b1329',
          color: '#ffffff',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '3.5rem',
          position: 'relative',
          overflow: 'hidden',
          borderRight: '1px solid #1e293b',
        }}
      >
        {/* Subtle Ambient Glows */}
        <div
          style={{
            position: 'absolute',
            top: '-10%',
            right: '-10%',
            width: '450px',
            height: '450px',
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(14, 165, 233, 0.15) 0%, rgba(15, 23, 42, 0) 70%)',
            pointerEvents: 'none',
          }}
        />
        <div
          style={{
            position: 'absolute',
            bottom: '-15%',
            left: '-10%',
            width: '500px',
            height: '500px',
            borderRadius: '50%',
            background: 'radial-gradient(circle, rgba(99, 102, 241, 0.12) 0%, rgba(15, 23, 42, 0) 70%)',
            pointerEvents: 'none',
          }}
        />

        {/* Top Branding */}
        <div style={{ position: 'relative', zIndex: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '2.5rem' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '10px',
                backgroundColor: 'rgba(56, 189, 248, 0.15)',
                border: '1px solid rgba(56, 189, 248, 0.3)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: '#38bdf8',
                fontSize: '1.25rem',
                fontWeight: 700,
              }}
            >
              ⚡
            </div>
            <span style={{ fontSize: '1.15rem', fontWeight: 700, letterSpacing: '-0.02em', color: '#f8fafc' }}>
              Distributed Job Scheduler
            </span>
          </div>

          <h1 style={{ fontSize: '2.5rem', fontWeight: 800, lineHeight: 1.15, letterSpacing: '-0.03em', margin: '0 0 1.25rem 0', color: '#ffffff' }}>
            Distributed Job Scheduler
          </h1>
          <p style={{ fontSize: '1.05rem', color: '#94a3b8', lineHeight: 1.6, maxWidth: '480px', margin: 0 }}>
            Reliable job execution, retries, workers and observability — in one place.
          </p>
        </div>

        {/* Conceptual Architecture Flow */}
        <div
          style={{
            position: 'relative',
            zIndex: 10,
            backgroundColor: 'rgba(15, 23, 42, 0.65)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '14px',
            padding: '1.75rem',
            backdropFilter: 'blur(8px)',
            maxWidth: '520px',
            margin: '2.5rem 0',
          }}
        >
          <div style={{ fontSize: '0.75rem', fontFamily: 'monospace', color: '#64748b', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '1.25rem' }}>
            Core Pipeline Architecture
          </div>

          {/* Primary Pipeline Tier */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
            {/* Queue Node */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.4rem' }}>
              <div
                style={{
                  padding: '0.65rem 0.9rem',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  color: '#e2e8f0',
                }}
              >
                <span>📥</span> Queue
              </div>
              <span style={{ fontSize: '0.65rem', fontFamily: 'monospace', color: '#64748b' }}>SKIP LOCKED</span>
            </div>

            <span style={{ color: '#475569', fontSize: '1rem' }}>→</span>

            {/* Worker Node */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.4rem' }}>
              <div
                style={{
                  padding: '0.65rem 0.9rem',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid rgba(255, 255, 255, 0.12)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  color: '#e2e8f0',
                }}
              >
                <span>⚙️</span> Worker
              </div>
              <span style={{ fontSize: '0.65rem', fontFamily: 'monospace', color: '#64748b' }}>CONCURRENCY</span>
            </div>

            <span style={{ color: '#475569', fontSize: '1rem' }}>→</span>

            {/* Execution Node */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.4rem' }}>
              <div
                style={{
                  padding: '0.65rem 0.9rem',
                  borderRadius: '8px',
                  backgroundColor: 'rgba(56, 189, 248, 0.15)',
                  border: '1px solid rgba(56, 189, 248, 0.4)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.4rem',
                  fontSize: '0.8rem',
                  fontWeight: 600,
                  color: '#38bdf8',
                }}
              >
                <span>▶</span> Execute
              </div>
              <span style={{ fontSize: '0.65rem', fontFamily: 'monospace', color: '#38bdf8' }}>AUDIT LOGS</span>
            </div>
          </div>

          {/* Secondary Fault-Tolerance Tier */}
          <div
            style={{
              marginTop: '1.25rem',
              paddingTop: '1rem',
              borderTop: '1px solid rgba(255, 255, 255, 0.08)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: '0.75rem',
              fontFamily: 'monospace',
              color: '#94a3b8',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span style={{ color: '#fbbf24' }}>↻</span>
              <span>Backoff Retries</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <span style={{ color: '#f87171' }}>⚠</span>
              <span style={{ color: '#fca5a5' }}>Dead Letter Queue (DLQ)</span>
            </div>
          </div>
        </div>

        {/* Footer Tag */}
        <div style={{ position: 'relative', zIndex: 10, fontSize: '0.8rem', color: '#64748b', fontFamily: 'monospace' }}>
          PostgreSQL Atomic State Machine · Zero External Broker Required
        </div>
      </div>

      {/* ── Right Form Panel ──────────────────────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '2.5rem 1.5rem',
          backgroundColor: '#ffffff',
        }}
      >
        <div style={{ width: '100%', maxWidth: '420px' }}>
          {/* Header */}
          <div style={{ marginBottom: '2rem' }}>
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
                padding: '0.2rem 0.6rem',
                borderRadius: '6px',
                backgroundColor: '#f1f5f9',
                border: '1px solid #e2e8f0',
                fontSize: '0.75rem',
                fontFamily: 'monospace',
                color: '#475569',
                marginBottom: '1rem',
                fontWeight: 600,
              }}
            >
              <span>●</span> REGISTRATION
            </div>
            <h2 style={{ fontSize: '1.85rem', fontWeight: 800, letterSpacing: '-0.025em', color: '#0f172a', margin: '0 0 0.4rem 0' }}>
              Create your account
            </h2>
            <p style={{ color: '#64748b', fontSize: '0.95rem', margin: 0 }}>
              Start scheduling and executing background jobs in minutes
            </p>
          </div>

          {/* Error Banner */}
          {error && (
            <div
              style={{
                padding: '0.85rem 1rem',
                marginBottom: '1.5rem',
                backgroundColor: '#fef2f2',
                border: '1px solid #fecaca',
                color: '#991b1b',
                borderRadius: '8px',
                fontSize: '0.85rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <span>⚠</span>
              <span>{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div>
              <label
                htmlFor="register-name"
                style={{
                  display: 'block',
                  fontSize: '0.75rem',
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  letterSpacing: '0.04em',
                  color: '#475569',
                  textTransform: 'uppercase',
                  marginBottom: '0.4rem',
                }}
              >
                Full Name
              </label>
              <input
                id="register-name"
                type="text"
                required
                placeholder="Jane Doe"
                value={name}
                onChange={(e) => setName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#ffffff',
                  fontSize: '0.95rem',
                  color: '#0f172a',
                  outline: 'none',
                  boxSizing: 'border-box',
                  transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = '#0284c7';
                  e.target.style.boxShadow = '0 0 0 3px rgba(2, 132, 199, 0.15)';
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = '#cbd5e1';
                  e.target.style.boxShadow = 'none';
                }}
              />
            </div>

            <div>
              <label
                htmlFor="register-email"
                style={{
                  display: 'block',
                  fontSize: '0.75rem',
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  letterSpacing: '0.04em',
                  color: '#475569',
                  textTransform: 'uppercase',
                  marginBottom: '0.4rem',
                }}
              >
                Work Email
              </label>
              <input
                id="register-email"
                type="email"
                required
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#ffffff',
                  fontSize: '0.95rem',
                  color: '#0f172a',
                  outline: 'none',
                  boxSizing: 'border-box',
                  transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = '#0284c7';
                  e.target.style.boxShadow = '0 0 0 3px rgba(2, 132, 199, 0.15)';
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = '#cbd5e1';
                  e.target.style.boxShadow = 'none';
                }}
              />
            </div>

            <div>
              <label
                htmlFor="register-password"
                style={{
                  display: 'block',
                  fontSize: '0.75rem',
                  fontFamily: 'monospace',
                  fontWeight: 600,
                  letterSpacing: '0.04em',
                  color: '#475569',
                  textTransform: 'uppercase',
                  marginBottom: '0.4rem',
                }}
              >
                Password (min 8 chars)
              </label>
              <input
                id="register-password"
                type="password"
                required
                minLength={8}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: '100%',
                  padding: '0.65rem 0.85rem',
                  borderRadius: '8px',
                  border: '1px solid #cbd5e1',
                  backgroundColor: '#ffffff',
                  fontSize: '0.95rem',
                  color: '#0f172a',
                  outline: 'none',
                  boxSizing: 'border-box',
                  transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
                }}
                onFocus={(e) => {
                  e.target.style.borderColor = '#0284c7';
                  e.target.style.boxShadow = '0 0 0 3px rgba(2, 132, 199, 0.15)';
                }}
                onBlur={(e) => {
                  e.target.style.borderColor = '#cbd5e1';
                  e.target.style.boxShadow = 'none';
                }}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                marginTop: '0.5rem',
                width: '100%',
                padding: '0.75rem 1rem',
                backgroundColor: '#0f172a',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                fontSize: '0.9rem',
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                transition: 'background-color 0.15s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
              }}
              onMouseEnter={(e) => {
                if (!loading) e.currentTarget.style.backgroundColor = '#1e293b';
              }}
              onMouseLeave={(e) => {
                if (!loading) e.currentTarget.style.backgroundColor = '#0f172a';
              }}
            >
              {loading ? (
                <>
                  <span style={{ display: 'inline-block', animation: 'spin 1s linear infinite' }}>⟳</span>
                  <span>Registering...</span>
                </>
              ) : (
                'Register Account'
              )}
            </button>
          </form>

          {/* Login Link */}
          <div style={{ marginTop: '2rem', textAlign: 'center', fontSize: '0.9rem', color: '#64748b' }}>
            Already have an account?{' '}
            <Link
              to="/login"
              style={{
                color: '#0284c7',
                fontWeight: 600,
                textDecoration: 'none',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.textDecoration = 'underline')}
              onMouseLeave={(e) => (e.currentTarget.style.textDecoration = 'none')}
            >
              Sign in here
            </Link>
          </div>
        </div>
      </div>

      {/* Responsive Stylesheet */}
      <style>{`
        @media (max-width: 900px) {
          .auth-hero-panel {
            display: none !important;
          }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};
