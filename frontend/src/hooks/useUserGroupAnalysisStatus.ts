import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';

export interface UserGroupAnalysisStatus {
  hasAnalysis: boolean;
  loading: boolean;
  refetch: () => void;
}

/**
 * Analysis-existence gate for the workspace user-group section (BG-2).
 * Mirrors the call in `UserGroupMapTab` (`GET /user-group/results`); an
 * analysis exists when a non-null `extent_id` comes back. Keyed on
 * `geometryVersion` (bumped after analyse/delete in UG-5) so a fresh modal
 * analyse/delete refreshes the section without a reload.
 */
export function useUserGroupAnalysisStatus(calculationId?: string | null): UserGroupAnalysisStatus {
  const geometryVersion = useWorkspaceStore((s) => s.geometryVersion);
  const [hasAnalysis, setHasAnalysis] = useState(false);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let cancelled = false;
    if (!calculationId) {
      setHasAnalysis(false);
      return;
    }
    setLoading(true);
    api
      .get(`/api/calculations/${calculationId}/user-group/results`)
      .then((res) => {
        if (cancelled) return;
        const r = res.data;
        setHasAnalysis(!!r && !!r.extent_id);
      })
      .catch(() => { if (!cancelled) setHasAnalysis(false); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [calculationId, geometryVersion, tick]);

  return { hasAnalysis, loading, refetch };
}