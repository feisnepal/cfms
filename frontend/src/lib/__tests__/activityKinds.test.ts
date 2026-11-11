import { describe, it, expect } from 'vitest';
import {
  ACTIVITY_KINDS,
  ACTIVITY_KIND_IDS,
  activityKindCountKey,
  activityKindLabel,
  activityKindMarker,
  activityKindPathStyle,
} from '../activityKinds';
import { ACTIVITY_KIND_ICONS } from '../activityKindIcons';

describe('the kind table', () => {
  it('gives every kind a colour, both labels and an icon that exists', () => {
    for (const id of ACTIVITY_KIND_IDS) {
      const k = ACTIVITY_KINDS[id];
      expect(k.color, id).toMatch(/^#[0-9a-f]{6}$/i);
      expect(k.ne.length, id).toBeGreaterThan(0);
      expect(k.en.length, id).toBeGreaterThan(0);
      expect(ACTIVITY_KIND_ICONS[k.icon], `${id} -> ${k.icon}`).toBeTruthy();
    }
  });

  it('gives kinds that share a geometry different looks, so two symbols are never confused', () => {
    // Same-coloured pairs must at least differ in icon (points) or dash/weight (lines).
    const look = (id: string) => {
      const k = ACTIVITY_KINDS[id];
      return k.geom === 'point' ? `${k.color}|${k.icon}` : `${k.color}|${k.dash}|${k.weight}|${k.icon}`;
    };
    const seen = new Map<string, string>();
    for (const id of ACTIVITY_KIND_IDS) {
      const key = `${ACTIVITY_KINDS[id].geom}|${look(id)}`;
      expect(seen.get(key), `${id} looks like ${seen.get(key)}`).toBeUndefined();
      seen.set(key, id);
    }
  });

  it('covers all three geometries', () => {
    const geoms = new Set(ACTIVITY_KIND_IDS.map((id) => ACTIVITY_KINDS[id].geom));
    expect(geoms).toEqual(new Set(['point', 'line', 'polygon']));
  });
});

describe('activityKindPathStyle — lines and polygons', () => {
  it('a native line keeps its own colour, dash and weight', () => {
    expect(activityKindPathStyle('trail', 'LineString')).toMatchObject({ color: '#8d5524', dashArray: '8 6', weight: 1.6 });
    expect(activityKindPathStyle('road', 'LineString')).toMatchObject({ color: '#8d5524', dashArray: undefined, weight: 2.6 });
    expect(activityKindPathStyle('fire_line', 'LineString')?.color).toBe('#c62828');
  });

  it('a native polygon is a tinted fill in the kind colour', () => {
    const s = activityKindPathStyle('plantation', 'Polygon');
    expect(s).toMatchObject({ color: '#10b981', fillColor: '#10b981', fillOpacity: 0.35 });
  });

  it('a kind drawn as a different geometry still takes its colour (a nursery drawn as an area)', () => {
    expect(activityKindPathStyle('nursery', 'Polygon')).toMatchObject({ fillColor: '#2e7d32', fillOpacity: 0.3 });
    expect(activityKindPathStyle('nursery', 'LineString')).toMatchObject({ color: '#2e7d32', weight: 3 });
  });

  it('an outline-only kind (encroachment) stays visible', () => {
    const s = activityKindPathStyle('encroachment', 'Polygon');
    expect(s?.fillOpacity).toBeGreaterThanOrEqual(0.15);
    expect(s?.dashArray).toBe('4 4');
  });

  it('no kind, an unknown kind or a point returns null, so the generic style applies', () => {
    expect(activityKindPathStyle('', 'Polygon')).toBeNull();
    expect(activityKindPathStyle(undefined, 'LineString')).toBeNull();
    expect(activityKindPathStyle('not_a_kind', 'Polygon')).toBeNull();
    expect(activityKindPathStyle('nursery', 'Point')).toBeNull();
  });
});

describe('activityKindMarker — points', () => {
  it('is a coloured badge with an SVG icon', () => {
    const { html, size } = activityKindMarker('nursery');
    expect(size).toBe(28);
    expect(html).toContain('background:#2e7d32');
    expect(html).toContain('<svg');
    expect(html).toContain('<path');
  });

  it('different kinds get different badges', () => {
    expect(activityKindMarker('nursery').html).not.toBe(activityKindMarker('fire_tower').html);
  });

  it('an unknown or missing kind gets a smaller neutral pin', () => {
    const generic = activityKindMarker('');
    expect(generic.size).toBe(22);
    expect(generic.html).toContain('background:#616161');
    expect(activityKindMarker('not_a_kind').html).toBe(generic.html);
  });
});

describe('labels and count keys', () => {
  it('labels a kind in the requested language', () => {
    expect(activityKindLabel('nursery', 'en')).toBe('Nursery');
    expect(activityKindLabel('nursery', 'ne')).toBe('नर्सरी');
    expect(activityKindLabel('', 'en')).toBe('');
    expect(activityKindLabel('nope', 'en')).toBe('');
  });

  it('keys the legend tally per kind', () => {
    expect(activityKindCountKey('road')).toBe('activity_features:kind:road');
  });
});
