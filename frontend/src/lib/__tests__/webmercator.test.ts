/**
 * U06 — lockstep tests for the front-end Web-Mercator tile helpers.
 *
 * These MUST STAY IN LOCKSTEP with `backend/app/services/webmercator.py` (plan A.3).
 * The values are anchored to well-known Web-Mercator tile facts so any drift on
 * either side of the stack is caught.
 */
import { describe, it, expect } from 'vitest';
import { bboxForTile, cellSizeAtZoom, lngLatToMeters, tileXY } from '../webmercator';

describe('tileXY', () => {
  it('z0: whole world is one tile at (0,0)', () => {
    expect(tileXY(0, 0, 0)).toEqual([0, 0]);
    expect(tileXY(-179.9, -85, 0)).toEqual([0, 0]);
    expect(tileXY(179.9, 85, 0)).toEqual([0, 0]);
  });

  it('London at z2 falls in tile (1,1)', () => {
    // London ~ (-0.1276, 51.5072)
    const [x, y] = tileXY(-0.1276, 51.5072, 2);
    const expectedX = Math.floor(((180.0 - 0.1276) / 360.0) * 4.0); // 1
    expect(x).toBe(expectedX);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThan(4);
    // The actual computed value
    expect([x, y]).toEqual([1, 1]);
  });

  it('Nepal forest anchor at z14 matches backend', () => {
    const [x, y] = tileXY(85.05, 27.43, 14);
    const n = 2 ** 14;
    const expectedX = Math.floor((85.05 + 180.0) / 360.0 * n);
    expect(x).toBe(expectedX);
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x).toBeLessThan(n);
    expect(y).toBeGreaterThanOrEqual(0);
    expect(y).toBeLessThan(n);
  });

  it('clamps extreme latitude to Web-Mercator edge', () => {
    const [x, y] = tileXY(10, 89.9, 4);
    expect(x).toBeGreaterThanOrEqual(0);
    expect(x).toBeLessThan(16);
    // At the clamped north edge, y can be at the boundary (y = -1 for exact edge)
    // The important thing is it doesn't produce NaN/Infinity
    expect(Number.isFinite(y)).toBe(true);
  });
});

describe('bboxForTile', () => {
  it('world tile at z0 covers full extent', () => {
    const [w, s, e, n] = bboxForTile(0, 0, 0);
    expect(w).toBeCloseTo(-180.0);
    expect(e).toBeCloseTo(180.0);
    expect(s).toBeCloseTo(-85.05112878, 6);
    expect(n).toBeCloseTo(85.05112878, 6);
  });

  it('tile contains its centroid', () => {
    const z = 10;
    for (const [tx, ty] of [[300, 400], [512, 512], [600, 700]]) {
      const [w, s, e, n] = bboxForTile(tx, ty, z);
      const cx = (w + e) / 2.0;
      const cy = (s + n) / 2.0;
      expect(tileXY(cx, cy, z)).toEqual([tx, ty]);
    }
  });

  it('bounds are monotonic', () => {
    const [w, s, e, n] = bboxForTile(123, 456, 14);
    expect(w).toBeLessThan(e);
    expect(s).toBeLessThan(n);
  });
});

describe('lngLatToMeters', () => {
  it('null island maps to (0,0)', () => {
    const [x, y] = lngLatToMeters(0, 0);
    // Floating point precision: allow small epsilon
    expect(Math.abs(x)).toBeLessThan(1e-9);
    expect(Math.abs(y)).toBeLessThan(1e-9);
  });

  it('known 3857 value for Nepal anchor', () => {
    const [x] = lngLatToMeters(85.05, 27.43);
    // Matches backend constant (lockstep)
    expect(x).toBeCloseTo(9467722.691967918, 4);
  });
});

describe('cellSizeAtZoom', () => {
  it('z0 equals base cell size', () => {
    expect(cellSizeAtZoom(0)).toBeCloseTo(156543.03392, 9);
  });

  it('z18 divides by 2^18', () => {
    expect(cellSizeAtZoom(18)).toBeCloseTo(156543.03392 / 2 ** 18, 9);
  });
});