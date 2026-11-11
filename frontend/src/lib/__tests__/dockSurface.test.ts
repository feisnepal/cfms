import { describe, it, expect } from 'vitest';
import { toFeatureParam, parseFeatureParam } from '../dockSurface';

describe('dockSurface', () => {
  it('round-trips a plain built-in layer id', () => {
    const ref = { layerId: 'sample_plots', featureId: '42' };
    expect(parseFeatureParam(toFeatureParam(ref))).toEqual(ref);
  });

  it('round-trips an imported-layer id (which itself contains a colon)', () => {
    const ref = { layerId: 'imported:9c1e-abcd', featureId: 'row-7' };
    expect(parseFeatureParam(toFeatureParam(ref))).toEqual(ref);
  });

  it('splits on the LAST colon, not the first', () => {
    expect(parseFeatureParam('imported:9c1e-abcd:row-7')).toEqual({
      layerId: 'imported:9c1e-abcd',
      featureId: 'row-7',
    });
  });

  it('rejects a missing, empty, or colon-less value', () => {
    expect(parseFeatureParam(null)).toBeNull();
    expect(parseFeatureParam(undefined)).toBeNull();
    expect(parseFeatureParam('')).toBeNull();
    expect(parseFeatureParam('no-colon-here')).toBeNull();
  });

  it('rejects a value with nothing on one side of the colon', () => {
    expect(parseFeatureParam(':42')).toBeNull();
    expect(parseFeatureParam('sample_plots:')).toBeNull();
  });
});
