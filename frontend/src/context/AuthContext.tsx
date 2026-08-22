import React, { createContext, useContext, useEffect, useState } from 'react';
import { api, getAuthToken, setAuthToken } from '../api/client';
import { Organization, Project, User } from '../api/types';

interface AuthContextType {
  user: User | null;
  orgs: Organization[];
  projects: Project[];
  selectedOrg: Organization | null;
  selectedProject: Project | null;
  loading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
  selectOrg: (org: Organization) => Promise<void>;
  selectProject: (proj: Project) => void;
  refreshProjects: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<Organization | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);

  const initAuth = async () => {
    const token = getAuthToken();
    if (!token) {
      setLoading(false);
      return;
    }
    try {
      const u = await api.getMe();
      setUser(u);
      const oList = await api.listOrgs();
      setOrgs(oList);
      if (oList.length > 0) {
        const firstOrg = oList[0];
        setSelectedOrg(firstOrg);
        const pRes = await api.listProjects(firstOrg.id);
        setProjects(pRes.items || []);
        if (pRes.items && pRes.items.length > 0) {
          setSelectedProject(pRes.items[0]);
        }
      }
    } catch (err) {
      console.error('Failed to init auth:', err);
      setAuthToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    initAuth();
  }, []);

  const login = async (token: string) => {
    setAuthToken(token);
    setLoading(true);
    await initAuth();
  };

  const logout = () => {
    setAuthToken(null);
    setUser(null);
    setOrgs([]);
    setProjects([]);
    setSelectedOrg(null);
    setSelectedProject(null);
  };

  const selectOrg = async (org: Organization) => {
    setSelectedOrg(org);
    try {
      const pRes = await api.listProjects(org.id);
      setProjects(pRes.items || []);
      if (pRes.items && pRes.items.length > 0) {
        setSelectedProject(pRes.items[0]);
      } else {
        setSelectedProject(null);
      }
    } catch (err) {
      console.error('Failed to fetch projects for org:', err);
    }
  };

  const selectProject = (proj: Project) => {
    setSelectedProject(proj);
  };

  const refreshProjects = async () => {
    if (!selectedOrg) return;
    const pRes = await api.listProjects(selectedOrg.id);
    setProjects(pRes.items || []);
    if (!selectedProject && pRes.items && pRes.items.length > 0) {
      setSelectedProject(pRes.items[0]);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        orgs,
        projects,
        selectedOrg,
        selectedProject,
        loading,
        login,
        logout,
        selectOrg,
        selectProject,
        refreshProjects,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
