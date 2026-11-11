/**
 * U06 — mapOverlays reducer tests.
 */
import { describe, it, expect } from 'vitest';
import { getVisibleOverlays, getViewportTiles, tileRequestKey, MAX_CONCURRENT_TILES } from '../mapOverlays';
import { OverlayKind } from '../../store/workspaceStore';

describe('getVisibleOverlays', () => {
  it('returns treeClusters true when layer is visible', () => {
    const result = getVisibleOverlays(
      ['tree_clusters'],
      ['tree_clusters'],
      8
    );
    expect(result.treeClusters).toBe(true);
    expect(result.sampling).toBe(false);
  });

  it('returns false when layer not in visibleBuiltins', () => {
    const result = getVisibleOverlays(
      ['sampling'], // selectedLayerIds - unused in current impl
      [], // visibleBuiltins - empty
      8
    );
    expect(result.treeClusters).toBe(false);
    expect(result.sampling).toBe(false);
  });
});

describe('getViewportTiles', () => {
  it('returns tiles for small bbox', () => {
    // Small bbox around 85.05, 27.43 at z14
    const tiles = getViewportTiles([[85.05, 27.43], [85.06, 27.44]], 14);
    expect(tiles.length).toBeGreaterThan(0);
    expect(tiles[0]).toHaveProperty('z', 14);
  });

  it('returns multiple tiles for larger bbox', () => {
    // Larger bbox spanning multiple tiles at z10
    const tiles = getViewportTiles([[80, 26], [90, 30]], 10);
    expect(tiles.length).toBeGreaterThan(1);
  });

  it('handles bounds crossing antimeridian? no - web mercator clamps', () => {
    // Web Mercator doesn't handle antimeridian crossing well
    // This just tests it doesn't crash
    const tiles = getViewportTiles([[-179, -80], [179, 80]], 2);
    expect(tiles.length).toBeGreaterThan(0);
  });
});

describe('tileRequestKey', () => {
  it('generates unique key matching backend cache key shape', () => {
    const key = tileRequestKey('calc-123', 5, { z: 10, x: 42, y: 58 });
    expect(key).toBe('calc-123:5:10:42:58');
  });

  it('different params yield different keys', () => {
    const k1 = tileRequestKey('calc-1', 1, { z: 8, x: 1, y: 2 });
    const k2 = tileRequestKey('calc-1', 1, { z: 8, x: 1, y: 3 });
    const k3 = tileRequestKey('calc-2', 1, { z: 8, x: 1, y: 2 });
    const k4 = tileRequestKey('calc-1', 2, { z: 8, x: 1, y: 2 });
    expect(k1).not.toBe(k2);
    expect(k1).not.toBe(k3);
    expect(k1).not.toBe(k4);
  });
});

describe('MAX_CONCURRENT_TILES', () => {
  it('is 4 per U06 spec', () => {
    expect(MAX_CONCURRENT_TILES).toBe(4);
  });
});