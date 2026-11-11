import { describe, it, expect } from 'vitest';
import { computeNewDrawPreview } from '../newDrawPreview';

const boundary = [{
  type: 'Feature',
  properties: {},
  geometry: {
    type: 'Polygon',
    coordinates: [[
      [0, 0], [0, 100], [100, 100], [100, 0], [0, 0],
    ]],
  },
}];

function poly(coords: Array<[number, number]>) {
  return [{
    type: 'Feature',
    properties: {},
    geometry: {
      type: 'Polygon',
      coordinates: [coords],
    },
  }];
}

describe('computeNewDrawPreview', () => {
  it('returns 0/drawn-state with fewer than 3 points', () => {
    const r = computeNewDrawPreview([[0, 0], [10, 10]], boundary, []);
    expect(r.drawnHa).toBe(0);
    expect(r.warnings.join(' ')).toContain('least 3');
  });

  it('computes drawn area for a square inside the boundary', () => {
    const r = computeNewDrawPreview(
      [[10, 10], [90, 10], [90, 90], [10, 90]],
      boundary,
      [],
    );
    // turf uses geodesic area for lon/lat coords — verify drawn == clipped (fully inside)
    expect(r.drawnHa).toBeGreaterThan(0);
    expect(r.clippedHa).toBeCloseTo(r.drawnHa, 5);
    expect(r.outsideHa).toBeLessThan(0.0001);
    expect(r.outsideBoundary).toBe(false);
    expect(r.overlapsExisting).toBe(false);
  });

  it('flags overlap against an existing feature', () => {
    const r = computeNewDrawPreview(
      [[10, 10], [90, 10], [90, 90], [10, 90]],
      boundary,
      poly([[20, 20], [40, 20], [40, 40], [20, 40]]),
    );
    expect(r.overlapsExisting).toBe(true);
    expect(r.warnings.join(' ')).toContain('overlaps');
  });

  it('flags a polygon fully outside the boundary', () => {
    const r = computeNewDrawPreview(
      [[200, 200], [300, 200], [300, 300], [200, 300]],
      boundary,
      [],
    );
    expect(r.outsideBoundary).toBe(true);
    expect(r.clippedHa).toBeCloseTo(0, 5);
    expect(r.warnings.join(' ')).toContain('outside');
  });
});
