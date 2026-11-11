import { describe, it, expect } from 'vitest';
import { matchFeature, filterForMap, dropHiddenFeatures, type AttributeFilter } from '../attributeFilter';

const f = (props: Record<string, unknown>) =>
  ({ type: 'Feature' as const, geometry: null as never, properties: props });

describe('matchFeature (WORKSPACE_LAYER_STYLING_PLAN.md P4.6)', () => {
  it('a blank field or value matches everything', () => {
    expect(matchFeature(f({ a: 1 }), '', 'eq', '5')).toBe(true);
    expect(matchFeature(f({ a: 1 }), 'a', 'eq', '')).toBe(true);
  });

  it('eq / ne are case-insensitive string compares', () => {
    expect(matchFeature(f({ wc: 'Protection' }), 'wc', 'eq', 'protection')).toBe(true);
    expect(matchFeature(f({ wc: 'Protection' }), 'wc', 'ne', 'protection')).toBe(false);
  });

  it('contains is a substring test', () => {
    expect(matchFeature(f({ name: 'North Block' }), 'name', 'contains', 'block')).toBe(true);
    expect(matchFeature(f({ name: 'North Block' }), 'name', 'contains', 'south')).toBe(false);
  });

  it('numeric ops coerce; non-numeric operands fail closed', () => {
    expect(matchFeature(f({ area: 12 }), 'area', 'gt', '5')).toBe(true);
    expect(matchFeature(f({ area: 12 }), 'area', 'lte', '12')).toBe(true);
    expect(matchFeature(f({ area: 12 }), 'area', 'gte', '20')).toBe(false);
    expect(matchFeature(f({ area: 'n/a' }), 'area', 'gt', '5')).toBe(false);
  });
});

describe('filterForMap', () => {
  const filter: AttributeFilter = { layerId: 'blocks', field: 'wc', op: 'eq', value: 'protection' };

  it('filters only the target layer, passes others through by reference', () => {
    const feats = [f({ wc: 'production' }), f({ wc: 'protection' })];
    expect(filterForMap(feats, filter, 'blocks')).toHaveLength(1);
    expect(filterForMap(feats, filter, 'compartments')).toBe(feats);
  });

  it('null / undefined features → null; no filter → passthrough', () => {
    expect(filterForMap(null, filter, 'blocks')).toBeNull();
    expect(filterForMap(undefined, filter, 'blocks')).toBeNull();
    const feats = [f({ wc: 'x' })];
    expect(filterForMap(feats, null, 'blocks')).toBe(feats);
  });
});

describe('dropHiddenFeatures (P5.1)', () => {
  it('removes features whose id is hidden; empty / missing list → passthrough', () => {
    const feats = [f({ id: 'a' }), f({ id: 'b' }), f({ id: 'c' })];
    expect(dropHiddenFeatures(feats, ['b'])!.map((x) => x.properties!.id)).toEqual(['a', 'c']);
    expect(dropHiddenFeatures(feats, [])).toBe(feats);
    expect(dropHiddenFeatures(feats, undefined)).toBe(feats);
    expect(dropHiddenFeatures(null, ['b'])).toBeNull();
  });
});

import { suggestFilterValues } from '../attributeFilter';
describe('suggestFilterValues', () => {
  const f = (species: any, dbh = 1) => ({ type: 'Feature', geometry: null, properties: { species, dbh } } as any);
  const feats = [f('Sal'), f('Sal'), f('Simal'), f(''), f(null), f('-')];
  it('lists distinct values by frequency, skipping blanks', () => {
    expect(suggestFilterValues(feats, 'species', 'eq', '')).toEqual([{ value: 'Sal', count: 2 }, { value: 'Simal', count: 1 }]);
  });
  it('narrows by typed text and is empty for numeric comparisons', () => {
    expect(suggestFilterValues(feats, 'species', 'eq', 'sim').map((s) => s.value)).toEqual(['Simal']);
    expect(suggestFilterValues(feats, 'dbh', 'gt', '')).toEqual([]);
  });
});
