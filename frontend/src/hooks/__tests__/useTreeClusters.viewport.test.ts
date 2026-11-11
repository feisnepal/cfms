/**
 * The render snapshot from `useVisibleTreeClusterTiles` must contain ONLY the
 * tiles covering the current viewport at the current zoom.
 *
 * The bug this pins: tiles were cached for the whole session and the snapshot
 * iterated every one of them, so as the user zoomed/panned, a z18 tile plus
 * the z19/z20 tiles over the same ground all stayed "ready" and the consumer
 * summed trees across all of them — 14,239 real trees were reported as 35,394.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useVisibleTreeClusterTiles } from '../useTreeClusters';
import { tileFetchQueue } from '../../lib/tileQueue';

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ setQueryData: vi.fn(), prefetchQuery: vi.fn() }),
}));

// getViewportTiles is the (bounds, zoom) -> tile list mapping; stub it so each
// "viewport" resolves to a known, disjoint tile set.
const getViewportTiles = vi.fn();
vi.mock('../../lib/mapOverlays', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../lib/mapOverlays')>();
  return { ...actual, getViewportTiles: (...a: unknown[]) => getViewportTiles(...a) };
});

type Bounds = [[number, number], [number, number]];
const VIEW_A: Bounds = [[0, 0], [1, 1]];
const VIEW_B: Bounds = [[5, 5], [6, 6]];

beforeEach(() => {
  tileFetchQueue.cancelPending();
  localStorage.clear();
  getViewportTiles.mockReset().mockImplementation((bounds: Bounds) =>
    bounds[0][0] === 0
      ? [{ z: 18, x: 10, y: 10 }, { z: 18, x: 11, y: 10 }] // VIEW_A → 2 tiles
      : [{ z: 19, x: 100, y: 100 }],                        // VIEW_B → 1 tile
  );
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      // one tree per tile, so tiles.size and the total tree count track 1:1
      json: async () => ({ features: [{ type: 'Feature', properties: { id: 'x' } }], hasMore: false }),
    }),
  );
});

const totalFeatures = (tiles: Map<string, { data: { features?: unknown[] } | null }>) =>
  [...tiles.values()].reduce((n, t) => n + (t.data?.features?.length ?? 0), 0);

describe('useVisibleTreeClusterTiles — the snapshot is scoped to the current view', () => {
  it('drops the previous viewport/zoom tiles instead of accumulating them', async () => {
    const { result, rerender } = renderHook(
      ({ bounds, zoom }: { bounds: Bounds; zoom: number }) =>
        useVisibleTreeClusterTiles('calc-1', 0, bounds, zoom, true),
      { initialProps: { bounds: VIEW_A, zoom: 18 } },
    );

    await waitFor(() => expect(result.current.tiles.size).toBe(2));
    expect(totalFeatures(result.current.tiles)).toBe(2);

    // Move to a different viewport at a different zoom.
    rerender({ bounds: VIEW_B, zoom: 19 });

    await waitFor(() => expect(result.current.tiles.size).toBe(1));
    // NOT 3 — the two VIEW_A tiles are gone from the render set.
    expect(totalFeatures(result.current.tiles)).toBe(1);
    expect([...result.current.tiles.keys()]).toEqual(['calc-1:0:19:100:100']);
  });

  it('re-uses cached tile data when the viewport returns to old ground (no refetch)', async () => {
    const { result, rerender } = renderHook(
      ({ bounds, zoom }: { bounds: Bounds; zoom: number }) =>
        useVisibleTreeClusterTiles('calc-1', 0, bounds, zoom, true),
      { initialProps: { bounds: VIEW_A, zoom: 18 } },
    );
    await waitFor(() => expect(result.current.tiles.size).toBe(2));
    const callsAfterA = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length;

    rerender({ bounds: VIEW_B, zoom: 19 });
    await waitFor(() => expect(result.current.tiles.size).toBe(1));

    rerender({ bounds: VIEW_A, zoom: 18 });
    await waitFor(() => expect(result.current.tiles.size).toBe(2));

    // VIEW_A tiles came from cache — only the single VIEW_B fetch was added.
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(callsAfterA + 1);
  });
});
