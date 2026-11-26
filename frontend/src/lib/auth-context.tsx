"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, refreshSession, setAccessToken } from "./api";
import type { TokenResponse, User, Workspace } from "./types";

const WS_KEY = "meetmind.workspace";

interface AuthState {
  user: User | null;
  workspaces: Workspace[];
  workspace: Workspace | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  acceptToken: (token: string) => Promise<void>;
  selectWorkspace: (id: string) => void;
  reloadWorkspaces: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

function storedWorkspace(): string | null {
  try {
    return window.localStorage.getItem(WS_KEY);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadSession = useCallback(async () => {
    const [me, wss] = await Promise.all([api.me(), api.workspaces()]);
    setUser(me);
    setWorkspaces(wss);
    const preferred = storedWorkspace();
    setWorkspaceId(wss.find((w) => w.id === preferred)?.id ?? wss[0]?.id ?? null);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await refreshSession();
      if (token && !cancelled) {
        try {
          await loadSession();
        } catch {
          setAccessToken(null);
        }
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSession]);

  const accept = useCallback(
    async (data: TokenResponse | string) => {
      setAccessToken(typeof data === "string" ? data : data.access_token);
      await loadSession();
    },
    [loadSession],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      workspaces,
      workspace: workspaces.find((w) => w.id === workspaceId) ?? null,
      loading,
      login: async (email, password) => accept(await api.login(email, password)),
      register: async (name, email, password) => accept(await api.register(name, email, password)),
      acceptToken: async (token) => accept(token),
      logout: async () => {
        try {
          await api.logout();
        } finally {
          setAccessToken(null);
          setUser(null);
          setWorkspaces([]);
        }
      },
      selectWorkspace: (id) => {
        setWorkspaceId(id);
        try {
          window.localStorage.setItem(WS_KEY, id);
        } catch {
          /* storage unavailable */
        }
      },
      reloadWorkspaces: async () => setWorkspaces(await api.workspaces()),
    }),
    [user, workspaces, workspaceId, loading, accept],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function canEdit(ws: Workspace | null): boolean {
  return !!ws && ws.role !== "viewer";
}

export function isAdmin(ws: Workspace | null): boolean {
  return !!ws && (ws.role === "admin" || ws.role === "owner");
}
