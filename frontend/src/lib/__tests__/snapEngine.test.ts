import { describe, it, expect } from 'vitest';
import type { Feature } from 'geojson';
import { SnapEngine } from '../snapEngine';

describe('SnapEngine (Gap 4.1–4.3, 7.1)', () => {
  const lineFeature: Feature = {
    type: 'Feature',
    geometry: {
      type: 'LineString',
      coordinates: [
        [85.0, 27.0],
        [85.1, 27.1],
        [85.2, 27.0],
      ],
    },
    properties: { featureId: 'l1' },
  };

  it('snaps to vertices and endpoints with priority', () => {
    const engine = new SnapEngine([lineFeature]);
    // Cursor very close to vertex [85.1, 27.1]
    const res = engine.snapToNearest({ lat: 27.1001, lng: 85.1 }, 20, 1.0);
    expect(res).not.toBeNull();
    expect(res?.targetType).toBe('vertex');
    expect(res?.point[0]).toBeCloseTo(85.1, 4);
    expect(res?.point[1]).toBeCloseTo(27.1, 4);
  });

  it('returns null when outside tolerance', () => {
    const engine = new SnapEngine([lineFeature]);
    const res = engine.snapToNearest({ lat: 29.0, lng: 90.0 }, 10, 1.0);
    expect(res).toBeNull();
  });
});
