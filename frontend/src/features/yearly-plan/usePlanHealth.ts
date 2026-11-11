import { useCallback, useEffect, useRef, useState } from 'react';
import { yearlyPlanApi, type YearlyPlanHealth } from '../../services/api';

/**
 * The plan-health document of a forest (`GET …/yearly-plan/health`).
 *
 * Re-read on mount, whenever the window regains focus or the tab becomes visible again, and whenever
 * `refreshKey` changes (a host bumps it after it saves). The plan is edited from two screens over the
 * same tables, so what this screen last read may already be stale when the user comes back to it.
 */
export function usePlanHealth(calculationId: string | undefined, refreshKey: number | string = 0, enabled = true) {
  const [health, setHealth] = useState<YearlyPlanHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const latest = useRef(0);

  const refresh = useCallback(async () => {
    if (!calculationId || !enabled) return;
    const ticket = ++latest.current;
    setLoading(true);
    try {
      const next = await yearlyPlanApi.getHealth(calculationId);
      if (ticket === latest.current) {
        setHealth(next);
        setError(false);
      }
    } catch {
      if (ticket === latest.current) setError(true);
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, [calculationId, enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh, refreshKey]);

  useEffect(() => {
    if (!enabled) return undefined;
    const onFocus = () => void refresh();
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refresh, enabled]);

  return { health, loading, error, refresh };
}
