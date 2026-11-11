/**
 * useDraftSync — GD 1.3.4 buffered feature write / auto-save (review #3, Gap 3.1).
 *
 * Flushes `digitizeDraftFeatures[layerId]` to the backend via the bulk endpoint
 * (Task 1.2.3, chunks of 25) on: (a) explicit Finish & Save, (b) mode switch away
 * from the layer, (c) 30s debounce while drawing, (d) beforeunload.
 *
 * Sync state machine (Gap 3.1): 'idle' | 'syncing' | 'error' | 'recovery'.
 * Undo/redo is disabled while `syncing`; the buffer is locked during flush.
 * On success → clear buffer, rehydrate from server; on failure → stay 'error',
 * buffer retained for retry (Task 1.3.5).
 *
 * IndexedDB backing store (Gap 9.1): every enqueue persists the buffer to
 * browserCache (`digitizeDrafts` store); rehydrate from IndexedDB on mount
 * BEFORE the server fetch so a crashed/closed browser draft survives.
 */
import { useEffect, useRef, useCallback } from 'react';
import type { GeoJSON } from 'geojson';
import { useWorkspaceStore } from '../store/workspaceStore';
import { browserCache } from '../services/browserCache';
import i18n from '../i18n';

export const CHUNK_SIZE = 25;
export const AUTO_SAVE_DEBOUNCE_MS = 30_000;

export function featureIdOf(feature: GeoJSON.Feature): string | undefined {
  const props = (feature.properties as Record<string, unknown>) || {};
  return (props.featureId as string) ?? (props.id as string) ?? ((feature as { id?: unknown }).id as string);
}

export function chunkBy<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

function buildBaseUrl(): string {
  return (import.meta as any).env?.VITE_API_URL ?? '';
}

async function authHeaders(): Promise<Record<string, string>> {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

/** GD 1.3.5: vector-clock fields injected on each buffered feature (Gap 9.2). */
export interface VectorClock {
  deviceId: string;
  timestamp: number;
  sequence: number;
}

function makeDeviceId(): string {
  const stored = localStorage.getItem('cf_device_id');
  if (stored) return stored;
  const id =
    (crypto as any)?.randomUUID?.() ??
    `dev-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  localStorage.setItem('cf_device_id', id);
  return id;
}

let vectorSequence = 0;

export function withVectorClock(feature: GeoJSON.Feature): GeoJSON.Feature {
  const clock: VectorClock = {
    deviceId: makeDeviceId(),
    timestamp: Date.now(),
    sequence: ++vectorSequence,
  };
  return {
    ...feature,
    properties: { ...(feature.properties || {}), _vectorClock: clock },
  };
}

export function readVectorClock(feature: GeoJSON.Feature): VectorClock | undefined {
  return (feature.properties as Record<string, unknown>)?._vectorClock as VectorClock | undefined;
}

/**
 * Core flush routine — extracted so it can be unit-tested without a DOM renderer.
 * Sends the buffer as upserts in chunks of 25, one Idempotency-Key per flush.
 * Throws on the first non-ok response; the caller maps failure to 'error' state.
 *
 * GD 1.3.5:
 * - retries reuse the SAME idempotency key (server returns cached response, no dupes)
 * - per-feature `_vectorClock` (LWW) attached to each upsert
 * - throws a distinguishable `ConflictFlushError` on 409 (optimistic-concurrency)
 */
export class ConflictFlushError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`Bulk flush conflict (${status})`);
    this.name = 'ConflictFlushError';
    this.status = status;
    this.detail = detail;
  }
}

export interface FlushOptions {
  fetchImpl?: typeof fetch;
  idempotencyKey?: string;
  /** when set, LWW vector clocks are injected onto the sent copies (default true) */
  useVectorClock?: boolean;
  /** GD 2.4: 'append' targets an existing non-draft layer (finalized/legacy import). Defaults to 'draft'. */
  mode?: 'draft' | 'append';
}

export async function flushDigitizeBuffer(
  calcId: string,
  layerId: number,
  buffer: GeoJSON.Feature[],
  options?: FlushOptions,
): Promise<{ mapping: Record<string, string>; featureCount: number }> {
  const fetchImpl = options?.fetchImpl ?? fetch;
  const idempotencyKey =
    options?.idempotencyKey ??
    (crypto as any)?.randomUUID?.() ??
    `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const baseUrl = buildBaseUrl();
  const headers = await authHeaders();
  const mapping: Record<string, string> = {};
  let featureCount = 0;

  for (const chunk of chunkBy(buffer, CHUNK_SIZE)) {
    const payload = {
      features: chunk.map((f) => {
        const feature = (options?.useVectorClock ?? true) ? withVectorClock(f) : f;
        return {
          clientTempId: featureIdOf(f) ?? f.id ?? '',
          feature,
          operation: 'upsert' as const,
        };
      }),
      idempotency_key: idempotencyKey,
      mode: options?.mode ?? 'draft',
    };
    const res = await fetchImpl(
      `${baseUrl}/api/v1/workspace/${calcId}/digitize-layers/${layerId}/features/bulk`,
      {
        method: 'POST',
        headers: { ...headers, 'Idempotency-Key': idempotencyKey },
        credentials: 'include',
        body: JSON.stringify(payload),
      },
    );
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      if (res.status === 409) throw new ConflictFlushError(res.status, detail);
      throw new Error(`Bulk flush failed (${res.status})`);
    }
    const data = await res.json();
    if (data?.mapping) Object.assign(mapping, data.mapping);
    featureCount = data?.feature_count ?? featureCount;
  }
  return { mapping, featureCount };
}

const RETRY_DELAYS_MS = [1_000, 2_000, 4_000];

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Resilient flush wrapper (GD 1.3.5): 3 attempts with exponential backoff
 * (1s → 2s → 4s) reusing the SAME idempotency key. A fresh key is only minted
 * when the previous key's cached response is >5 min old (TTL window) — i.e. a
 * brand-new logical flush.
 */
export async function flushDigitizeBufferWithRetry(
  calcId: string,
  layerId: number,
  buffer: GeoJSON.Feature[],
  options?: FlushOptions & { maxAttempts?: number },
): Promise<{ mapping: Record<string, string>; featureCount: number }> {
  const maxAttempts = options?.maxAttempts ?? 3;
  const key =
    options?.idempotencyKey ??
    (crypto as any)?.randomUUID?.() ??
    `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let lastError: unknown;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    if (attempt > 0) {
      const backoff = RETRY_DELAYS_MS[Math.min(attempt - 1, RETRY_DELAYS_MS.length - 1)];
      await delay(backoff);
    }
    try {
      return await flushDigitizeBuffer(calcId, layerId, buffer, {
        ...options,
        idempotencyKey: key,
      });
    } catch (err) {
      lastError = err;
      if (err instanceof ConflictFlushError) throw err; // do not retry conflicts
    }
  }
  throw lastError;
}

export interface UseDraftSyncOptions {
  calcId: string | undefined;
  layerId: number | undefined;
  /** when true the layer is active in the workspace (drawing) — drives debounce + mode-switch flush */
  active: boolean;
  /** GD 2.4: 'append' flushes into an existing non-draft layer (no draft lifecycle). Defaults to 'draft'. */
  mode?: 'draft' | 'append';
  /** GD 2.4: invoked after a successful append flush with the persisted feature count (toast hook). */
  onAppendFlushed?: (count: number, layerId: number) => void;
}

export function useDraftSync({ calcId, layerId, active, mode = 'draft', onAppendFlushed }: UseDraftSyncOptions) {
  const store = useWorkspaceStore();
  const flushingRef = useRef(false);
  const lockRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRef = useRef(active);
  activeRef.current = active;
  const modeRef = useRef(mode);
  modeRef.current = mode;

  const draftKey = calcId && layerId != null ? `${calcId}:${layerId}` : null;

  const rehydrateFromServer = useCallback(async () => {
    if (!calcId || layerId == null) return;
    try {
      const baseUrl = buildBaseUrl();
      const headers = await authHeaders();
      const res = await fetch(
        `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${layerId}/features`,
        { headers, credentials: 'include' },
      );
      if (!res.ok) return;
      const data = await res.json();
      const features: GeoJSON.Feature[] = data.features || [];
      useWorkspaceStore.getState().setImportedLayerFeatures(layerId, features);
      // GD 2.4: append mode keeps the finalized layer's authoritative list in
      // importedLayerFeatures only — never repopulate the draft buffer (there is none).
      if (modeRef.current !== 'append') {
        useWorkspaceStore.getState().setDigitizeDraftFeatures(layerId, features);
      }
    } catch (err) {
      console.error('useDraftSync rehydrate failed:', err);
    }
  }, [calcId, layerId]);

  const flush = useCallback(async (): Promise<boolean> => {
    if (!calcId || layerId == null) return false;
    if (flushingRef.current) return false;
    if (lockRef.current) return false;

    const buffer = useWorkspaceStore.getState().digitizeDraftFeatures[layerId] || [];
    if (buffer.length === 0) return true;

    flushingRef.current = true;
    lockRef.current = true;
    useWorkspaceStore.getState().setDigitizeSyncState('syncing');

    try {
      const result = await flushDigitizeBufferWithRetry(calcId, layerId, buffer, {
        mode: modeRef.current,
      });

      // Success: clear buffer, rehydrate from server, resume idle.
      useWorkspaceStore.getState().clearDigitizeDraftFeatures(layerId);
      await rehydrateFromServer();
      useWorkspaceStore.getState().setDigitizeSyncState('idle');
      // GD 2.4: toast hook fires only in append mode (finalized-layer appends).
      if (modeRef.current === 'append' && result.featureCount > 0) {
        onAppendFlushed?.(result.featureCount, layerId);
      }
      return true;
    } catch (err) {
      console.error('useDraftSync flush failed:', err);
      if (err instanceof ConflictFlushError) {
        // Optimistic-concurrency conflict (409): server updated_at newer than the
        // client's — never silently overwrite. Force rehydration + review required.
        useWorkspaceStore.getState().setDigitizeSyncState('recovery');
        await rehydrateFromServer();
        useWorkspaceStore.getState().setDigitizeSyncState('idle');
        try {
          const antd = await import('antd');
          antd.message.warning(i18n.t('workspace.draftServerMerge'));
        } catch {
          /* antd not available */
        }
        return false;
      }
      useWorkspaceStore.getState().setDigitizeSyncState('error');
      return false;
    } finally {
      flushingRef.current = false;
      lockRef.current = false;
    }
  }, [calcId, layerId, rehydrateFromServer, onAppendFlushed]);

  // IndexedDB backing store: persist buffer on every change (Gap 9.1).
  useEffect(() => {
    if (!draftKey || layerId == null) return;
    const buffer = store.digitizeDraftFeatures[layerId];
    if (buffer) {
      browserCache.setDigitizeDraft(calcId as string, layerId, buffer).catch(() => {});
    }
  }, [store.digitizeDraftFeatures, draftKey, layerId, calcId]);

  // Rehydrate from IndexedDB on mount BEFORE the server fetch.
  useEffect(() => {
    if (!draftKey || layerId == null) return;
    let cancelled = false;
    (async () => {
      try {
        const cached = (await browserCache.getDigitizeDraft(calcId as string, layerId)) as
          GeoJSON.Feature[] | null;
        if (cancelled || !cached || cached.length === 0) return;
        const current = useWorkspaceStore.getState().digitizeDraftFeatures[layerId];
        if (!current || current.length === 0) {
          useWorkspaceStore.getState().setDigitizeDraftFeatures(layerId, cached);
        }
      } catch (err) {
        console.error('useDraftSync IndexedDB rehydrate failed:', err);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey, layerId, calcId]);

  // 30s debounce while drawing (active layer).
  useEffect(() => {
    if (!active || !draftKey || layerId == null) return;
    const buffer = store.digitizeDraftFeatures[layerId];
    if (!buffer || buffer.length === 0) return;
    if (store.digitizeSyncState === 'syncing' || lockRef.current) return;

    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      flush();
    }, AUTO_SAVE_DEBOUNCE_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [active, draftKey, layerId, store.digitizeDraftFeatures, store.digitizeSyncState, flush]);

  // beforeunload flush (best-effort).
  useEffect(() => {
    if (!draftKey || layerId == null) return;
    const handler = (e: BeforeUnloadEvent) => {
      const buffer = useWorkspaceStore.getState().digitizeDraftFeatures[layerId];
      if (buffer && buffer.length > 0) {
        flush();
      }
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [draftKey, layerId, flush]);

  // Mode switch away from the layer → flush (when not active anymore but had a draft).
  const prevActiveRef = useRef(active);
  useEffect(() => {
    if (prevActiveRef.current && !active && draftKey && layerId != null) {
      const st = useWorkspaceStore.getState();
      const buffer = st.digitizeDraftFeatures[layerId];
      if (buffer && buffer.length > 0 && st.digitizeSyncState === 'idle') {
        flush();
      }
    }
    prevActiveRef.current = active;
  }, [active, draftKey, layerId, flush]);

  // GD 1.3.5: persistent-failure toast + auto-retry on reconnect.
  useEffect(() => {
    if (!draftKey || layerId == null) return;
    const st = useWorkspaceStore.getState();
    const buffer = st.digitizeDraftFeatures[layerId];
    if (st.digitizeSyncState === 'error' && buffer && buffer.length > 0) {
      (async () => {
        try {
          const antd = await import('antd');
          antd.message.error(i18n.t('workspace.draftSyncFailed'));
        } catch {
          /* antd not available in tests */
        }
      })();
    }
  }, [draftKey, layerId, store.digitizeSyncState, store.digitizeDraftFeatures]);

  useEffect(() => {
    if (!draftKey || layerId == null) return;
    const onOnline = () => {
      const st = useWorkspaceStore.getState();
      const buffer = st.digitizeDraftFeatures[layerId];
      if (buffer && buffer.length > 0 && st.digitizeSyncState === 'error') {
        flush();
      }
    };
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
  }, [draftKey, layerId, flush]);

  return { flush };
}
