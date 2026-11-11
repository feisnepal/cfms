/**
 * The bug the previous test file (useTreeClusters.test.ts) never caught:
 * fetchTile() built its URL from VITE_API_URL (an env var the rest of the app
 * doesn't use for this — services/api.ts reads VITE_API_BASE_URL, dev/prod
 * gated on import.meta.env.DEV) and sent `credentials: 'include'` with no
 * Authorization header, on an app that authenticates via JWT Bearer, not
 * cookies. Every tile request would 404 or 401 before ever reaching
 * cluster_inventory_trees, silently -- TreeClustersLayer just never gets a
 * 'ready' tile, so the layer renders nothing and looks like it "isn't
 * clustering" rather than visibly failing.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useTreeClusterTiles } from '../useTreeClusters';
import { tileFetchQueue } from '../../lib/tileQueue';

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ setQueryData: vi.fn(), prefetchQuery: vi.fn() }),
}));

describe('useTreeClusterTiles — actual request construction', () => {
  beforeEach(() => {
    tileFetchQueue.cancelPending();
    localStorage.clear();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers(),
        json: async () => ({ features: [], hasMore: false }),
      }),
    );
  });

  it('requests the real mounted backend path (.../api/calculations/.../tree-model/clusters)', async () => {
    const { result } = renderHook(() => useTreeClusterTiles({ calcId: 'calc-1', geometryVersion: 0 }));
    await result.current.getTile(10, 5, 6);
    const [url] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain('/api/calculations/calc-1/tree-model/clusters?z=10&x=5&y=6');
  });

  it('sends the stored access token as a Bearer header — the backend has no other way to authenticate it', async () => {
    localStorage.setItem('access_token', 'tok-123');
    const { result } = renderHook(() => useTreeClusterTiles({ calcId: 'calc-1', geometryVersion: 0 }));
    await result.current.getTile(10, 5, 6);
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
  });

  it('omits the header rather than sending "Bearer null" when there is no stored token', async () => {
    const { result } = renderHook(() => useTreeClusterTiles({ calcId: 'calc-1', geometryVersion: 0 }));
    await result.current.getTile(10, 5, 6);
    const [, opts] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(opts.headers).toBeUndefined();
  });
});
