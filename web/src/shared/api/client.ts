import createClient from 'openapi-fetch';
import type { components, paths } from './schema';
import { ApiError, networkError, toApiError } from './errors';

type TokenResponse = components['schemas']['TokenResponse'];

/*
 * Session model: the access token lives only in memory (this module), the refresh token is an
 * HttpOnly cookie on /api/v1/auth that JavaScript never sees. After a page reload the session is
 * restored with POST /auth/refresh. Refresh tokens are single-use, so concurrent refreshes are
 * collapsed into one request (and serialized across tabs with the Web Locks API when available).
 */
let accessToken: string | null = null;
let refreshInFlight: Promise<TokenResponse | null> | null = null;
let onSessionExpired: (() => void) | null = null;
let onSessionRefreshed: ((session: TokenResponse) => void) | null = null;

export const tokenStore = {
  get: (): string | null => accessToken,
  set: (token: string | null): void => {
    accessToken = token;
  },
};

export function setSessionHandlers(handlers: {
  expired: () => void;
  refreshed: (session: TokenResponse) => void;
}): void {
  onSessionExpired = handlers.expired;
  onSessionRefreshed = handlers.refreshed;
}

function apiOrigin(): string {
  return typeof window !== 'undefined' ? window.location.origin : 'http://localhost';
}

async function exclusive<T>(fn: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (locks && typeof locks.request === 'function') {
    return locks.request('credit-cabinet-refresh', fn);
  }
  return fn();
}

function isTokenResponse(value: unknown): value is TokenResponse {
  return typeof value === 'object' && value !== null && typeof (value as { access_token?: unknown }).access_token === 'string';
}

/** Restores or prolongs the session; returns null when there is no valid refresh cookie. */
export function refreshSession(): Promise<TokenResponse | null> {
  if (!refreshInFlight) {
    refreshInFlight = exclusive(async () => {
      try {
        const res = await fetch(`${apiOrigin()}/api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: { Accept: 'application/json' },
        });
        if (!res.ok) return null;
        const body: unknown = await res.json();
        if (!isTokenResponse(body)) return null;
        accessToken = body.access_token;
        onSessionRefreshed?.(body);
        return body;
      } catch {
        return null;
      }
    }).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function isAuthEndpoint(url: string): boolean {
  return url.includes('/api/v1/auth/');
}

function withToken(request: Request): Request {
  const token = accessToken;
  if (token) request.headers.set('Authorization', `Bearer ${token}`);
  return request;
}

/** fetch with the in-memory bearer token and one transparent retry after a refresh on 401. */
export async function authFetch(request: Request): Promise<Response> {
  const retryCopy = request.clone();
  let response: Response;
  try {
    response = await fetch(withToken(request));
  } catch {
    setOffline(true);
    throw networkError();
  }
  setOffline(false);
  if (response.status !== 401 || isAuthEndpoint(request.url)) return response;
  const session = await refreshSession();
  if (!session) {
    accessToken = null;
    onSessionExpired?.();
    return response;
  }
  try {
    return await fetch(withToken(retryCopy));
  } catch {
    throw networkError();
  }
}

export const http = createClient<paths>({
  baseUrl: apiOrigin(),
  fetch: authFetch,
  headers: { Accept: 'application/json' },
});

interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/** Unwraps an openapi-fetch result into data or a thrown ApiError. */
export async function unwrap<T>(promise: Promise<FetchResult<T>>): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await promise;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw networkError();
  }
  const { data, error, response } = result;
  if (!response.ok) {
    throw toApiError(response.status, error, response.headers.get('X-Request-Id'));
  }
  return data as T;
}

/** Raw request for multipart uploads and binary downloads (same auth and error model). */
export async function rawRequest(path: string, init: RequestInit & { idempotencyKey?: string } = {}): Promise<Response> {
  const { idempotencyKey, ...rest } = init;
  const headers = new Headers(rest.headers);
  headers.set('Accept', headers.get('Accept') ?? 'application/json');
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey);
  const response = await authFetch(new Request(`${apiOrigin()}${path}`, { ...rest, headers }));
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    throw toApiError(response.status, body, response.headers.get('X-Request-Id'));
  }
  return response;
}

/* Connectivity flag for the "no connection" banner: set on a network failure, cleared by any response. */
let offline = false;
const connectivityListeners = new Set<() => void>();

function setOffline(value: boolean): void {
  if (offline === value) return;
  offline = value;
  connectivityListeners.forEach((l) => l());
}

export const connectivity = {
  subscribe(listener: () => void): () => void {
    connectivityListeners.add(listener);
    return () => connectivityListeners.delete(listener);
  },
  isOffline: (): boolean => offline,
  report: setOffline,
};
