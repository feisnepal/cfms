/**
 * useResolvedParams — load / patch / reset a forest's resolved parameter set
 * (RUSLE or hazard/vulnerability). Shared by the Hazard & Erosion parameter
 * panel and the two Maps-tab `…ParamsButton` shortcuts.
 *
 * The API trio is passed in so the hook is agnostic to which parameter family
 * it is driving:
 *   get(id)            -> { params, provenance, customised }
 *   patch(id, partial) -> same, after merging `partial` onto the stored override
 *   reset(id)          -> same, after dropping the per-forest override
 *
 * `patch` state is a sparse object the caller edits; `save()` sends it and
 * `reset()` clears both it and the stored override.
 */
import { useCallback, useEffect, useState } from 'react';

export interface ResolvedParamsResponse {
  params: Record<string, unknown>;
  provenance: Record<string, 'default' | 'profile' | 'forest'>;
  customised: boolean;
}

export interface ParamsApi<TPatch> {
  get: (id: string) => Promise<ResolvedParamsResponse>;
  patch: (id: string, partial: TPatch) => Promise<ResolvedParamsResponse>;
  reset: (id: string) => Promise<ResolvedParamsResponse>;
}

export interface UseResolvedParams<TPatch> {
  resp: ResolvedParamsResponse | null;
  loading: boolean;
  saving: boolean;
  error: boolean;
  patch: TPatch;
  setPatch: React.Dispatch<React.SetStateAction<TPatch>>;
  dirty: boolean;
  reload: () => Promise<void>;
  /** PATCH the current sparse patch; resolves to the new response or throws. */
  save: () => Promise<ResolvedParamsResponse>;
  /** DELETE the per-forest override and clear the patch. */
  reset: () => Promise<ResolvedParamsResponse>;
  customised: boolean;
}

/** True when the sparse patch has no leaf overrides (nested-empty groups count as empty). */
const isEmpty = (p: unknown): boolean =>
  !p ||
  typeof p !== 'object' ||
  Object.keys(p as Record<string, unknown>).every((k) => {
    const v = (p as Record<string, unknown>)[k];
    return v && typeof v === 'object' && !Array.isArray(v)
      ? Object.keys(v as Record<string, unknown>).length === 0
      : false;
  });

export function useResolvedParams<TPatch extends object>(
  api: ParamsApi<TPatch>,
  calculationId: string,
  empty: () => TPatch,
): UseResolvedParams<TPatch> {
  const [resp, setResp] = useState<ResolvedParamsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const [patch, setPatch] = useState<TPatch>(empty);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setResp(await api.get(calculationId));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const r = await api.patch(calculationId, patch);
      setResp(r);
      return r;
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId, patch]);

  const reset = useCallback(async () => {
    setSaving(true);
    try {
      const r = await api.reset(calculationId);
      setResp(r);
      setPatch(empty());
      return r;
    } finally {
      setSaving(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [calculationId]);

  return {
    resp,
    loading,
    saving,
    error,
    patch,
    setPatch,
    dirty: !isEmpty(patch),
    reload,
    save,
    reset,
    customised: !!resp?.customised,
  };
}
