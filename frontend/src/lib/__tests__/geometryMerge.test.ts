import { describe, it, expect } from 'vitest';
import { applyImportedMerge, featureIdOf } from '../geometryMerge';

const feat = (featureId: string, name = featureId): GeoJSON.Feature =>
  ({
    type: 'Feature',
    id: featureId,
    geometry: { type: 'Polygon', coordinates: [] },
    properties: { featureId, name },
  }) as GeoJSON.Feature;

describe('applyImportedMerge', () => {
  it('removes the source featureIds and appends the merged feature', () => {
    const cur = [feat('imported-0', 'imp-sel-a'), feat('imported-1', 'imp-sel-b')];
    const merged = feat('imported-0-merged', 'imp-sel-a_merged');
    const next = applyImportedMerge(cur, ['imported-0', 'imported-1'], merged);
    expect(next).toHaveLength(1);
    expect(featureIdOf(next[0])).toBe('imported-0-merged');
    expect(next[0].properties?.name).toBe('imp-sel-a_merged');
  });

  it('keeps unrelated features untouched', () => {
    const cur = [feat('imp-a'), feat('imp-b')];
    const next = applyImportedMerge(cur, ['imp-b'], feat('imp-b-merged'));
    expect(next.map(featureIdOf)).toEqual(['imp-a', 'imp-b-merged']);
  });

  it('returns the SAME array reference when the merged feature has no geometry', () => {
    const cur = [feat('imp-a')];
    const next = applyImportedMerge(cur, ['imp-a'], { properties: {} });
    expect(next).toBe(cur);
  });

  it('returns the SAME array reference when there is no merged feature at all', () => {
    const cur = [feat('imp-a')];
    expect(applyImportedMerge(cur, ['imp-a'], null)).toBe(cur);
  });

  it('tolerates server responses shaped { merged } / { feature } / bare', () => {
    const cur = [feat('imp-a'), feat('imp-b')];
    for (const body of [
      { merged: feat('m') },
      { feature: feat('m') },
      feat('m'),
    ]) {
      const merged = (body as { merged?: GeoJSON.Feature; feature?: GeoJSON.Feature })?.merged
        ?? (body as { feature?: GeoJSON.Feature })?.feature
        ?? (body as GeoJSON.Feature);
      const next = applyImportedMerge(cur, ['imp-a'], merged);
      expect(next.map(featureIdOf)).toEqual(['imp-b', 'm']);
    }
  });
});

describe('featureIdOf (UE-4.1 import identity resolution)', () => {
  it('prefers properties.featureId over properties.id', () => {
    expect(featureIdOf({ type: 'Feature', properties: { featureId: 'a', id: 'b' }, geometry: { type: 'Point', coordinates: [] } } as GeoJSON.Feature))
      .toBe('a');
  });

  it('falls back to properties.id when featureId is absent', () => {
    expect(featureIdOf({ type: 'Feature', properties: { id: 'row-9' }, geometry: { type: 'Point', coordinates: [] } } as GeoJSON.Feature))
      .toBe('row-9');
  });

  it('falls back to the top-level GeoJSON id', () => {
    expect(featureIdOf({ id: 42, geometry: { type: 'Point', coordinates: [] } } as unknown as GeoJSON.Feature))
      .toBe('42');
  });

  it('returns an empty string when no id is available', () => {
    expect(featureIdOf({ type: 'Feature' } as GeoJSON.Feature)).toBe('');
  });

  it('coerces numeric ids to strings for stable array lookups', () => {
    const numeric = [{ properties: { featureId: 7 }, geometry: { type: 'Point', coordinates: [] } } as unknown as GeoJSON.Feature];
    const next = applyImportedMerge(numeric, ['7'], feat('m'));
    expect(next.map(featureIdOf)).toEqual(['m']);
  });
});