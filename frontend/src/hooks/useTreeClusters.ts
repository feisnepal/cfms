/**
 * Tree cluster tile fetch hook — U06.
 * Uses react-query with tile-keyed queryKey, MAX_CONCURRENT_TILES queue,
 * and AbortController for viewport changes.
 */

import { useQuery, useQueryClient, UseQueryOptions } from '@tanstack/react-query';
import { useCallback, useMemo, useRef, useState, useEffect } from 'react';
import { tileRequestKey, TreeClusterTileRequest, MAX_CONCURRENT_TILES } from '../lib/mapOverlays';
import { tileFetchQueue } from '../lib/tileQueue';
import { API_BASE_URL } from '../services/api';

// Mirrors services/api.ts's own dev/prod base-URL rule (refreshTokenOnce,
// ~line 212): in dev, Vite's proxy serves /api on the same origin, so an
// absolute base would bypass it; VITE_API_URL (this file's previous, unused
// variable) isn't even the env var the rest of the app reads for this.
const API_BASE = import.meta.env.DEV ? '' : API_BASE_URL;

interface UseTreeClustersOptions {
  calcId: string | null;
  geometryVersion: number;
  enabled?: boolean;
}

export interface TreeClusterTileData {
  features: GeoJSON.Feature[];
  hasMore: boolean;
}

const FETCH_TIMEOUT_MS = 5000;

export function useTreeClusterTiles({ calcId, geometryVersion, enabled = true }: UseTreeClustersOptions) {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  // Reset queue when calcId or geometryVersion changes (new epoch)
  useEffect(() => {
    if (calcId && geometryVersion >= 0) {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      tileFetchQueue.cancelPending();
    }
  }, [calcId, geometryVersion]);

  const fetchTile = useCallback(
    async (z: number, x: number, y: number): Promise<TreeClusterTileData> => {
      if (!calcId) throw new Error('No calcId');
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

      try {
        const url = `${API_BASE}/api/calculations/${calcId}/tree-model/clusters?z=${z}&x=${x}&y=${y}`;
        // This app authenticates via a JWT Bearer header, not cookies (see
        // services/api.ts's own comment on X-Requested-With) — `credentials:
        // 'include'` alone sent no credential the backend's
        // get_current_active_user dependency would accept, so every tile
        // request 401'd before the URL fix even mattered.
        const token = localStorage.getItem('access_token');
        const resp = await fetch(url, {
          signal: controller.signal,
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        if (resp.status === 429) {
          const retryAfter = resp.headers.get('Retry-After');
          throw new Error(`Rate limited (retry after ${retryAfter || '60'}s)`);
        }
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        return resp.json();
      } finally {
        clearTimeout(timeoutId);
      }
    },
    [calcId]
  );

  /** Fetch a single tile via the queue. */
  const getTile = useCallback(
    async (z: number, x: number, y: number): Promise<TreeClusterTileData> => {
      const key = tileRequestKey(calcId!, geometryVersion, { z, x, y });
      return tileFetchQueue.enqueue(key, () => fetchTile(z, x, y), abortRef.current!);
    },
    [calcId, geometryVersion, fetchTile]
  );

  /** Prefetch a tile (for adjacent tiles). */
  const prefetchTile = useCallback(
    (z: number, x: number, y: number) => {
      const key = tileRequestKey(calcId!, geometryVersion, { z, x, y });
      queryClient.prefetchQuery({
        queryKey: ['treeClusters', key],
        queryFn: () => fetchTile(z, x, y),
        staleTime: 30_000,
      });
    },
    [calcId, geometryVersion, fetchTile, queryClient]
  );

  return { getTile, prefetchTile, cancelAll: () => tileFetchQueue.cancelPending() };
}

/**
 * Hook to fetch all visible tiles for the current viewport.
 * Returns a map of tileKey -> { data, fetchState }.
 */
export function useVisibleTreeClusterTiles(
  calcId: string | null,
  geometryVersion: number,
  viewportBounds: [[number, number], [number, number]] | null,
  mapZoom: number,
  enabled = true
) {
  const queryClient = useQueryClient();
  const { getTile } = useTreeClusterTiles({ calcId, geometryVersion, enabled });

  // A session-long cache of every tile ever fetched — reused when the user pans
  // back over old ground. It is NOT the render set (see `wantedKeys`).
  const tilesRef = useRef<Map<string, TreeClusterTileData>>(new Map());
  const fetchStatesRef = useRef<Map<string, 'idle' | 'loading' | 'error' | 'ready'>>(new Map());
  // Tile data lives in refs (no re-render per tile), but the consumer needs a
  // NEW `tiles` object only when something actually changed. Before this, the
  // snapshot Map was rebuilt on every render and returned by identity, so
  // `TreeClustersLayer`'s `useMemo([tiles])` never held — it re-flattened every
  // tile and re-rendered every marker on each unrelated store tick, which is
  // what froze the tab when the "show only matches on map" filter was toggled.
  // A `tick` bumped on real state transitions gates both the rebuild and (via
  // useMemo) the returned identity — and makes freshly loaded tiles actually
  // appear without waiting for an incidental parent re-render.
  const [tick, setTick] = useState(0);
  const bump = useCallback(() => setTick((t) => t + 1), []);
  // The tiles that cover the CURRENT viewport at the CURRENT zoom. Only these
  // go into the render snapshot — otherwise the consumer sums trees across
  // every tile ever fetched, at every zoom level panned through, and a z18
  // tile plus the z19/z20 tiles over the same ground triple-count (reported:
  // 14,239 real trees shown as 35,394).
  const [wantedKeys, setWantedKeys] = useState<string[]>([]);

  useEffect(() => {
    if (!calcId || !viewportBounds || !enabled || mapZoom < 0) {
      setWantedKeys((prev) => (prev.length ? [] : prev));
      return;
    }

    // Import dynamically to avoid circular deps
    import('../lib/mapOverlays').then(({ getViewportTiles }) => {
      const wanted = getViewportTiles(viewportBounds, mapZoom);
      const keys = wanted.map((t) => tileRequestKey(calcId, geometryVersion, t));
      setWantedKeys((prev) =>
        prev.length === keys.length && prev.every((k, i) => k === keys[i]) ? prev : keys,
      );

      // Fetch each tile
      let started = false;
      for (const tile of wanted) {
        const key = tileRequestKey(calcId, geometryVersion, tile);
        if (tilesRef.current.get(key)) continue;                    // already have data
        if (fetchStatesRef.current.get(key) === 'loading') continue; // already in flight

        fetchStatesRef.current.set(key, 'loading');
        started = true;

        getTile(tile.z, tile.x, tile.y)
          .then((data) => {
            tilesRef.current.set(key, data);
            fetchStatesRef.current.set(key, 'ready');
            // Also prime react-query cache
            queryClient.setQueryData(['treeClusters', key], data);
            bump();
          })
          .catch((err) => {
            if (err.name !== 'AbortError') {
              fetchStatesRef.current.set(key, 'error');
              bump();
            }
          });
      }
      if (started) bump();
    });
  }, [calcId, geometryVersion, viewportBounds, mapZoom, enabled, getTile, queryClient, bump]);

  // Snapshot for rendering — ONLY the current viewport's tiles, rebuilt (and
  // re-identified) when `tick` (a tile finished) or `wantedKeys` (the viewport
  // moved) changes.
  const tiles = useMemo(() => {
    const snapshot = new Map<string, { data: TreeClusterTileData | null; state: 'idle' | 'loading' | 'error' | 'ready' }>();
    for (const key of wantedKeys) {
      snapshot.set(key, {
        data: tilesRef.current.get(key) || null,
        state: fetchStatesRef.current.get(key) ?? 'loading',
      });
    }
    return snapshot;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick, wantedKeys]);

  return { tiles };
}