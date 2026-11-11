import { describe, it, expect } from 'vitest';
import type { Feature } from 'geojson';
import { validateFeatureLive } from '../useLiveValidation';

describe('useLiveValidation (Task 3.4.1)', () => {
  it('validates allowed geometry per purpose', () => {
    const pointFeat: Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [85.0, 27.0] },
      properties: {},
    };
    // inventory allows Point
    const resInv = validateFeatureLive(pointFeat, 'inventory', 0);
    expect(resInv.valid).toBe(true);

    // roads only allows LineString
    const resRoad = validateFeatureLive(pointFeat, 'roads', 0);
    expect(resRoad.valid).toBe(false);
    expect(resRoad.errors[0]).toContain('not allowed for purpose');
  });

  it('detects self-intersecting polygon (bow-tie / kinks)', () => {
    const bowTiePoly: Feature = {
      type: 'Feature',
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [85.0, 27.0],
            [85.1, 27.1],
            [85.0, 27.1],
            [85.1, 27.0],
            [85.0, 27.0],
          ],
        ],
      },
      properties: {},
    };
    const res = validateFeatureLive(bowTiePoly, 'boundary', 0);
    expect(res.valid).toBe(false);
  });
});
