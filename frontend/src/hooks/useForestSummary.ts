/** The forest summary and the plan decisions of one forest. The GET calls read stored data only; when the server says the
 *  summary is `not_collected` (nothing cached since the last change) this asks it to prepare it once, so the panel fills
 *  itself after an edit instead of staying empty. */
import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';
import type { DecisionsResponse, ForestSummary } from '../lib/forestSummary';

export type LoadStatus = 'idle' | 'loading' | 'preparing' | 'ready' | 'forbidden' | 'error';

const httpStatus = (err: unknown): number | undefined =>
  (err as { response?: { status?: number } } | null)?.response?.status;

export function useForestSummary(
  calculationId: string | null | undefined,
  area: 'forest' | 'user_group',
  lang: 'en' | 'ne',
  geometryVersion: number,
  enabled: boolean,
) {
  const [summary, setSummary] = useState<ForestSummary | null>(null);
  const [status, setStatus] = useState<LoadStatus>('idle');
  const [tick, setTick] = useState(0);
  const refreshed = useRef<string>('');

  useEffect(() => {
    if (!calculationId || !enabled) return undefined;
    let live = true;
    const base = `/api/calculations/${calculationId}/forest-summary`;
    const params = { area, lang };
    const key = `${calculationId}|${area}|${lang}|${geometryVersion}|${tick}`;
    setStatus((s) => (s === 'ready' ? s : 'loading'));
    api
      .get<ForestSummary>(base, { params })
      .then(async (r) => {
        if (!live) return;
        if (r.data.state === 'ready') {
          setSummary(r.data);
          setStatus('ready');
          return;
        }
        if (refreshed.current === key) {
          // Already asked once for this exact state; do not loop.
          setSummary(r.data);
          setStatus('ready');
          return;
        }
        refreshed.current = key;
        setStatus('preparing');
        const prepared = await api.post<ForestSummary>(`${base}/refresh`, null, { params });
        if (!live) return;
        setSummary(prepared.data);
        setStatus('ready');
      })
      .catch((err) => {
        if (live) setStatus(httpStatus(err) === 403 ? 'forbidden' : 'error');
      });
    return () => {
      live = false;
    };
  }, [calculationId, area, lang, geometryVersion, enabled, tick]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { summary, status, reload };
}

export function useDecisions(calculationId: string | null | undefined, enabled: boolean) {
  const [data, setData] = useState<DecisionsResponse | null>(null);
  const [status, setStatus] = useState<LoadStatus>('idle');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<'locked' | 'invalid' | 'error' | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!calculationId || !enabled) return undefined;
    let live = true;
    api
      .get<DecisionsResponse>(`/api/calculations/${calculationId}/decisions`)
      .then((r) => {
        if (!live) return;
        setData(r.data);
        setStatus('ready');
      })
      .catch((err) => {
        if (live) setStatus(httpStatus(err) === 403 ? 'forbidden' : 'error');
      });
    return () => {
      live = false;
    };
  }, [calculationId, enabled, tick]);

  const answer = useCallback(
    async (key: string, body: { choice: string; scope?: string | null; value?: string | null }): Promise<boolean> => {
      if (!calculationId) return false;
      setSaving(true);
      setSaveError(null);
      try {
        const r = await api.put<DecisionsResponse>(`/api/calculations/${calculationId}/decisions/${key}`, body);
        setData(r.data);
        return true;
      } catch (err) {
        const s = httpStatus(err);
        setSaveError(s === 423 ? 'locked' : s === 422 ? 'invalid' : 'error');
        setTick((n) => n + 1); // show what the server now says
        return false;
      } finally {
        setSaving(false);
      }
    },
    [calculationId],
  );

  return { data, status, saving, saveError, answer };
}
