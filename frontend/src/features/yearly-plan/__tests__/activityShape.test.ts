/** The shape belongs to the activity (owner, 2026-10-15): its own shape wins, else its kind's, never its unit. */
import { describe, expect, it } from 'vitest';
import { toCatalogueActivity } from '../../../lib/activitySearch';
import { mapPhrase } from '../activityCatalogue';
import { drawGeomOf } from '../wizard/wizardMachine';

const raw = (over: Record<string, unknown> = {}) => ({ id: 1, activity: 'x', unit: 'हेक्टर', requires_map: true, ...over });

describe('the shape of an activity', () => {
  it('is its kind\'s shape by default', () => {
    expect(drawGeomOf(toCatalogueActivity(raw({ map_kind: 'trail' })))).toBe('line');
    expect(drawGeomOf(toCatalogueActivity(raw({ map_kind: 'coupe', unit: 'चट्टा' })))).toBe('polygon');
    expect(drawGeomOf(toCatalogueActivity(raw({ map_kind: 'nursery' })))).toBe('point');
  });

  it('is the activity\'s own shape when it has one (signboard kind, block marking: a line)', () => {
    const a = toCatalogueActivity(raw({ map_kind: 'signboard', map_geom: 'line', unit: 'कि.मि.' }));
    expect(a.mapGeom).toBe('line');
    expect(drawGeomOf(a)).toBe('line');
    expect(mapPhrase(a)).toBe('line');
  });

  it('can be given to an activity that has no kind at all (land use: a polygon)', () => {
    const a = toCatalogueActivity(raw({ map_kind: null, map_geom: 'polygon', unit: 'स्थान' }));
    expect(drawGeomOf(a)).toBe('polygon');
    expect(mapPhrase(a)).toBe('area');
  });

  it('is never taken from the unit', () => {
    // a point kind measured in hectares stays a point; a polygon kind measured in trees stays a polygon
    expect(drawGeomOf(toCatalogueActivity(raw({ map_kind: 'signboard', unit: 'हेक्टर' })))).toBe('point');
    expect(drawGeomOf(toCatalogueActivity(raw({ map_kind: 'silviculture_area', unit: 'रुख संख्या' })))).toBe('polygon');
  });

  it('ignores a value that is not a shape', () => {
    expect(toCatalogueActivity(raw({ map_geom: 'circle' })).mapGeom).toBeNull();
  });
});
