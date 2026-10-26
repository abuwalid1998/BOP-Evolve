/**
 * Thin fetch wrapper. In the browser the UI and API share an origin (nginx or the
 * Vite proxy forwards /api). Inside the Electron shell the server URL comes from
 * the desktop settings exposed by the preload bridge.
 */

export interface DesktopBridge {
  platform: string;
  appVersion: string;
  getServerUrl: () => Promise<string>;
  setServerUrl: (url: string) => Promise<string>;
  testServer: (url: string) => Promise<{ ok: boolean; status?: number; error?: string }>;
}

declare global {
  interface Window {
    bopDesktop?: DesktopBridge;
  }
}

const TOKEN_KEY = 'bop-evolve.token';
let apiBase = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export const isDesktop = () => typeof window !== 'undefined' && !!window.bopDesktop;

export async function initApiBase(): Promise<void> {
  if (window.bopDesktop) apiBase = (await window.bopDesktop.getServerUrl()).replace(/\/+$/, '');
}

export const getApiBase = () => apiBase;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** The server's structured `detail` payload, when it is not a plain message. */
    public detail?: unknown,
  ) {
    super(message);
  }
}

type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();
export const onUnauthorized = (fn: UnauthorizedListener) => {
  unauthorizedListeners.add(fn);
  return () => unauthorizedListeners.delete(fn);
};

export const tokenStore = {
  get: () => {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string | null) => {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, 'network');
  }
  if (response.status === 401 && token) {
    tokenStore.set(null);
    unauthorizedListeners.forEach((fn) => fn());
  }
  if (!response.ok) {
    let message = response.statusText;
    let detail: unknown;
    try {
      const payload = await response.json();
      detail = payload.detail;
      if (typeof payload.detail === 'string') message = payload.detail;
      else if (Array.isArray(payload.detail)) message = payload.detail.map((d: { msg: string }) => d.msg).join('; ');
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(response.status, message, detail);
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
};

/** Download a CSV export with the bearer token (plain links cannot send headers). */
export async function downloadCsv(path: string, filename: string): Promise<void> {
  const token = tokenStore.get();
  const response = await fetch(`${apiBase}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

/** POST and save the CSV the server returns (used for one-time activation codes). Returns the response headers. */
export async function postDownload(path: string, filename: string): Promise<Headers> {
  const token = tokenStore.get();
  const response = await fetch(`${apiBase}${path}`, {
    method: 'POST',
    headers: { Accept: 'text/csv', 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: '{}',
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* non-JSON error */
    }
    throw new ApiError(response.status, response.statusText, detail);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return response.headers;
}
