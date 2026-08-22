import { useEffect, useRef, useState, useCallback } from 'react';

export function usePolling<T>(
  fetchFn: () => Promise<T>,
  intervalMs: number = 5000,
  enabled: boolean = true
) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const isMounted = useRef<boolean>(true);

  const execute = useCallback(async (showLoading: boolean = false) => {
    if (showLoading) setLoading(true);
    try {
      const result = await fetchFn();
      if (isMounted.current) {
        setData(result);
        setError(null);
      }
    } catch (err: any) {
      if (isMounted.current) {
        setError(err.message || 'An error occurred');
      }
    } finally {
      if (isMounted.current && showLoading) {
        setLoading(false);
      }
    }
  }, [fetchFn]);

  useEffect(() => {
    isMounted.current = true;
    if (!enabled) {
      setLoading(false);
      return;
    }

    execute(true);

    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        execute(false);
      }
    }, intervalMs);

    return () => {
      isMounted.current = false;
      clearInterval(timer);
    };
  }, [execute, intervalMs, enabled]);

  return { data, loading, error, refresh: () => execute(true) };
}
