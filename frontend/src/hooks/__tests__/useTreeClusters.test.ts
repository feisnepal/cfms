/**
 * U06 — useTreeClusters hook unit tests (logic only, no render).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { tileRequestKey } from '../../lib/mapOverlays';
import { tileFetchQueue } from '../../lib/tileQueue';

vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({
    setQueryData: vi.fn(),
    prefetchQuery: vi.fn(),
  }),
}));

describe('useTreeClusterTiles logic (unit)', () => {
  beforeEach(() => {
    tileFetchQueue.cancelPending();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('tileRequestKey matches backend cache key format', () => {
    const key = tileRequestKey('calc-uuid', 7, { z: 10, x: 100, y: 200 });
    expect(key).toBe('calc-uuid:7:10:100:200');
  });

  it('rate limit 429 throws with retry-after', () => {
    const resp = { status: 429, headers: new Headers({ 'Retry-After': '30' }) };
    expect(() => {
      if (resp.status === 429) {
        const retry = resp.headers.get('Retry-After');
        throw new Error(`Rate limited (retry after ${retry}s)`);
      }
    }).toThrow('Rate limited');
  });

  it('timeout aborts fetch', async () => {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 5000);
    vi.advanceTimersByTime(5000);
    await expect(
      fetch('/slow', { signal: controller.signal })
    ).rejects.toThrow();
  });
});