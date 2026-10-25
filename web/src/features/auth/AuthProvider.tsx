import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { refreshSession, setSessionHandlers, tokenStore } from '@/shared/api/client';
import { api } from '@/shared/api/endpoints';
import { clearSessionDrafts } from '@/shared/lib/sessionDrafts';
import type { Role, TokenResponse, UserInfo } from '@/shared/api/types';

type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous'; reason?: 'expired' | 'logout' }
  | { status: 'authenticated'; user: UserInfo };

interface AuthContextValue {
  state: AuthState;
  login: (login: string, password: string) => Promise<UserInfo>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// One boot refresh per page load (React StrictMode mounts effects twice; refresh tokens are single-use).
let bootPromise: Promise<TokenResponse | null> | null = null;
function bootSession(): Promise<TokenResponse | null> {
  bootPromise ??= refreshSession();
  return bootPromise;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<AuthState>({ status: 'loading' });

  useEffect(() => {
    setSessionHandlers({
      expired: () => {
        tokenStore.set(null);
        queryClient.clear();
        setState({ status: 'anonymous', reason: 'expired' });
      },
      refreshed: (session) => {
        setState((prev) =>
          prev.status === 'authenticated' && prev.user.id === session.user.id ? prev : { status: 'authenticated', user: session.user },
        );
      },
    });
    let active = true;
    void bootSession().then((session) => {
      if (!active) return;
      setState(session ? { status: 'authenticated', user: session.user } : { status: 'anonymous' });
    });
    return () => {
      active = false;
    };
  }, [queryClient]);

  const login = useCallback(
    async (loginValue: string, password: string) => {
      const session = await api.login(loginValue, password);
      tokenStore.set(session.access_token);
      queryClient.clear();
      setState({ status: 'authenticated', user: session.user });
      return session.user;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // the cookie is cleared server-side when possible; locally we forget the session anyway
    }
    tokenStore.set(null);
    queryClient.clear();
    clearSessionDrafts();
    setState({ status: 'anonymous', reason: 'logout' });
  }, [queryClient]);

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}

export function useUser(): UserInfo {
  const { state } = useAuth();
  if (state.status !== 'authenticated') throw new Error('useUser requires an authenticated session');
  return state.user;
}

export function homeFor(role: Role): string {
  if (role === 'CLIENT') return '/client/applications';
  if (role === 'RISK_MANAGER') return '/bank/applications';
  return '/bank/queue';
}

/** Only same-origin application paths of the user's own workspace are accepted as a return target. */
export function safeReturnPath(raw: unknown, role: Role): string | null {
  if (typeof raw !== 'string' || !raw.startsWith('/') || raw.startsWith('//') || raw.includes('\\')) return null;
  const area = role === 'CLIENT' ? '/client/' : '/bank/';
  return raw.startsWith(area) ? raw : null;
}
