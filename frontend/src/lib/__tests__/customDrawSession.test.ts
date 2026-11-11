import { describe, it, expect } from 'vitest';
import { measureLatLngCoords } from '../customDrawSession';

describe('measureLatLngCoords', () => {
  it('Point: no area, no length', () => {
    const r = measureLatLngCoords('Point', [[85.3, 27.7]]);
    expect(r.areaHa).toBeNull();
    expect(r.lengthM).toBeNull();
  });

  it('Line: null area, positive length once >=2 points', () => {
    const under = measureLatLngCoords('Line', [[85.3, 27.7]]);
    expect(under.lengthM).toBeNull();

    const r = measureLatLngCoords('Line', [[85.30, 27.70], [85.31, 27.70]]);
    expect(r.areaHa).toBeNull();
    expect(r.lengthM).toBeGreaterThan(0);
    // ~0.01 deg longitude at this latitude is roughly 990m — sanity bound, not exact.
    expect(r.lengthM).toBeGreaterThan(500);
    expect(r.lengthM).toBeLessThan(1500);
  });

  it('Polygon: null area under 3 points, positive area at 3+', () => {
    const under = measureLatLngCoords('Polygon', [[0, 0], [0, 1]]);
    expect(under.areaHa).toBeNull();

    const r = measureLatLngCoords('Polygon', [[0, 0], [0, 1], [1, 1], [1, 0]]);
    expect(r.lengthM).toBeNull();
    expect(r.areaHa).toBeGreaterThan(0);
  });

  it('does not require the ring to be pre-closed (closes it internally)', () => {
    const open = measureLatLngCoords('Polygon', [[0, 0], [0, 1], [1, 1], [1, 0]]);
    const closed = measureLatLngCoords('Polygon', [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]);
    expect(open.areaHa).toBeCloseTo(closed.areaHa!, 6);
  });
});
