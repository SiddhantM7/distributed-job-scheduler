import React, { useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';

export const Layout: React.FC = () => {
  const { user, orgs, projects, selectedOrg, selectedProject, selectOrg, selectProject, logout, refreshProjects } = useAuth();
  const navigate = useNavigate();
  const [showCreateProject, setShowCreateProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectDesc, setNewProjectDesc] = useState('');

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOrg || !newProjectName.trim()) return;
    try {
      const proj = await api.createProject(selectedOrg.id, {
        name: newProjectName.trim(),
        description: newProjectDesc.trim() || undefined,
      });
      await refreshProjects();
      selectProject(proj);
      setShowCreateProject(false);
      setNewProjectName('');
      setNewProjectDesc('');
    } catch (err: any) {
      alert(`Error creating project: ${err.message}`);
    }
  };

  const navLinks = [
    { to: '/', label: 'Overview' },
    { to: '/queues', label: 'Queues' },
    { to: '/jobs', label: 'Jobs Explorer' },
    { to: '/workers', label: 'Workers Fleet' },
    { to: '/dlq', label: 'Dead Letter Queue' },
  ];

  return (
    <div style={{ minHeight: '100vh', backgroundColor: '#f8fafc', fontFamily: 'Inter, system-ui, sans-serif', color: '#0f172a' }}>
      {/* Top Navbar */}
      <header style={{ backgroundColor: '#ffffff', borderBottom: '1px solid #e2e8f0', padding: '0.75rem 2rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '1.4rem' }}>⚡</span>
            <span style={{ fontWeight: 700, fontSize: '1.1rem', letterSpacing: '-0.02em', color: '#1e293b' }}>
              Job Scheduler
            </span>
          </div>

          {/* Org & Project Selectors */}
          {user && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <select
                value={selectedOrg?.id || ''}
                onChange={(e) => {
                  const org = orgs.find((o) => o.id === e.target.value);
                  if (org) selectOrg(org);
                }}
                style={{ padding: '0.35rem 0.65rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem', backgroundColor: '#ffffff' }}
              >
                {orgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    Org: {o.name}
                  </option>
                ))}
              </select>

              <select
                value={selectedProject?.id || ''}
                onChange={(e) => {
                  const proj = projects.find((p) => p.id === e.target.value);
                  if (proj) selectProject(proj);
                }}
                style={{ padding: '0.35rem 0.65rem', borderRadius: '6px', border: '1px solid #cbd5e1', fontSize: '0.85rem', backgroundColor: '#ffffff' }}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    Project: {p.name}
                  </option>
                ))}
                {projects.length === 0 && <option value="">No projects</option>}
              </select>

              <button
                onClick={() => setShowCreateProject(true)}
                style={{ padding: '0.35rem 0.65rem', fontSize: '0.8rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: '#f1f5f9', cursor: 'pointer' }}
              >
                + Project
              </button>
            </div>
          )}
        </div>

        {/* User profile & Logout */}
        {user ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <span style={{ fontSize: '0.85rem', color: '#475569' }}>
              👤 <strong>{user.name}</strong> ({user.email})
            </span>
            <button
              onClick={() => {
                logout();
                navigate('/login');
              }}
              style={{
                padding: '0.35rem 0.75rem',
                fontSize: '0.8rem',
                borderRadius: '6px',
                border: '1px solid #cbd5e1',
                backgroundColor: '#ffffff',
                cursor: 'pointer',
                color: '#ef4444',
                fontWeight: 500,
              }}
            >
              Log Out
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <NavLink to="/login" style={{ fontSize: '0.85rem', textDecoration: 'none', color: '#2563eb' }}>
              Log In
            </NavLink>
          </div>
        )}
      </header>

      {/* Navigation Sub-bar */}
      {user && (
        <nav style={{ backgroundColor: '#ffffff', borderBottom: '1px solid #e2e8f0', padding: '0 2rem', display: 'flex', gap: '1.5rem' }}>
          {navLinks.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              style={({ isActive }) => ({
                padding: '0.75rem 0',
                fontSize: '0.9rem',
                fontWeight: isActive ? 600 : 500,
                color: isActive ? '#2563eb' : '#64748b',
                textDecoration: 'none',
                borderBottom: isActive ? '2px solid #2563eb' : '2px solid transparent',
              })}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      )}

      {/* Main Content Area */}
      <main style={{ padding: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
        <Outlet />
      </main>

      {/* Create Project Modal */}
      {showCreateProject && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ backgroundColor: '#ffffff', padding: '1.75rem', borderRadius: '10px', width: '400px', boxShadow: '0 10px 25px rgba(0,0,0,0.1)' }}>
            <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.15rem' }}>Create New Project</h3>
            <form onSubmit={handleCreateProject}>
              <div style={{ marginBottom: '1rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.35rem' }}>Project Name</label>
                <input
                  type="text"
                  required
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                  placeholder="e.g. production-backend"
                />
              </div>
              <div style={{ marginBottom: '1.25rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.35rem' }}>Description (optional)</label>
                <textarea
                  value={newProjectDesc}
                  onChange={(e) => setNewProjectDesc(e.target.value)}
                  style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', border: '1px solid #cbd5e1' }}
                  placeholder="Description of workloads..."
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                <button
                  type="button"
                  onClick={() => setShowCreateProject(false)}
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: '1px solid #cbd5e1', background: '#f8fafc', cursor: 'pointer' }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{ padding: '0.5rem 1rem', borderRadius: '6px', border: 'none', background: '#2563eb', color: '#ffffff', fontWeight: 500, cursor: 'pointer' }}
                >
                  Create Project
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
