import { describe, it, expect } from 'vitest';
import type { Feature } from 'geojson';
import { copyFeature, pasteFeature } from '../copyPaste';

describe('copyPaste (Task 3.5.1)', () => {
  const feat: Feature = {
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [85.0, 27.0] },
    properties: { featureId: 'old-1', geo_area_ha: 5, species: 'Sal' },
  };

  it('copyFeature deep-copies without reference sharing', () => {
    const cp = copyFeature(feat);
    expect(cp).toEqual(feat);
    expect(cp).not.toBe(feat);
  });

  it('pasteFeature strips featureId and geo_* fields and applies offset', () => {
    const pasted = pasteFeature(feat, 'inventory');
    const props = pasted.properties as any;
    expect(props.featureId).toBeUndefined();
    expect(props.geo_area_ha).toBeUndefined();
    expect(props.species).toBe('Sal'); // preserved custom property
    const coords = (pasted.geometry as any).coordinates;
    expect(coords[0]).toBeCloseTo(85.0005, 2);
    expect(coords[1]).toBeCloseTo(27.0005, 2);
  });
});
