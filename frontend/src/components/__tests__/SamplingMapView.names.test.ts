import { describe, expect, it } from 'vitest';
import { buildUnitNameByKey } from '../SamplingMapView';

describe('sampling map: unit names are the workspace attribute names', () => {
  it('translates the key a plot is filed under back to the unit name', () => {
    const features = [
      { properties: { name: 'North slope', unit_key: 'SC1' } },
      { properties: { name: 'SC2', unit_key: 'SC2' } },
      { properties: { name: 'No key' } },
      { properties: { unit_key: 'X' } },
    ];
    expect(buildUnitNameByKey(features)).toEqual({ SC1: 'North slope', SC2: 'SC2' });
  });

  it('copes with a layer that has not loaded', () => {
    expect(buildUnitNameByKey(undefined)).toEqual({});
  });
});
