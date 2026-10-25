import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api/client';

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  /** Time of the last successful response. */
  updatedAt: Date | null;
  /** True when a refresh failed after data had already loaded. */
  stale: boolean;
  reload: () => void;
}

/**
 * Fetch `path` and optionally re-poll every `intervalMs` (the prototype's "live"
 * behaviour). Polling pauses while the window is hidden.
 */
export function useApi<T>(path: string | null, intervalMs?: number): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [tick, setTick] = useState(0);
  const pathRef = useRef(path);
  pathRef.current = path;

  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<T>(path)
      .then((result) => {
        if (cancelled || pathRef.current !== path) return;
        setData(result);
        setError(null);
        setUpdatedAt(new Date());
      })
      .catch((err: ApiError) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!path || !intervalMs) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') reload();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [path, intervalMs, reload]);

  return { data, error, loading, updatedAt, stale: !!error && !!data, reload };
}
