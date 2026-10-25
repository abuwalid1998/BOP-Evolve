import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, onUnauthorized, tokenStore } from '../api/client';

export interface RoleGrant {
  code: string;
  scope_type: string;
  scope_id: string | null;
}

export interface CurrentUser {
  id: string;
  username: string;
  display_name: string;
  display_name_ar: string | null;
  employee_id: string | null;
  roles: RoleGrant[];
  permissions: string[];
}

interface AuthValue {
  user: CurrentUser | null;
  ready: boolean;
  expired: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (...permissions: string[]) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [ready, setReady] = useState(false);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    const off = onUnauthorized(() => {
      setUser(null);
      setExpired(true);
    });
    if (!tokenStore.get()) {
      setReady(true);
      return () => {
        off();
      };
    }
    api
      .get<CurrentUser>('/api/auth/me')
      .then(setUser)
      .catch(() => tokenStore.set(null))
      .finally(() => setReady(true));
    return () => {
      off();
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const result = await api.post<{ access_token: string; user: CurrentUser }>('/api/auth/login', {
      username,
      password,
    });
    tokenStore.set(result.access_token);
    setExpired(false);
    setUser(result.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/api/auth/logout');
    } catch {
      /* session may already be gone */
    }
    tokenStore.set(null);
    setUser(null);
  }, []);

  const can = useCallback(
    (...permissions: string[]) => !!user && permissions.some((p) => user.permissions.includes(p)),
    [user],
  );

  return (
    <AuthContext.Provider value={{ user, ready, expired, login, logout, can }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
