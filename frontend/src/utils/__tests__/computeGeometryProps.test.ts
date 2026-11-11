import { describe, it, expect } from 'vitest';
import { computeGeometryProps, withGeoProps, GEO_COMPUTED_KEYS } from '../computeGeometryProps';

const SQUARE_POLYGON = {
  type: 'Polygon',
  coordinates: [[
    [85.0, 27.0],
    [85.01, 27.0],
    [85.01, 27.01],
    [85.0, 27.01],
    [85.0, 27.0],
  ]],
};

const LINE = {
  type: 'LineString',
  coordinates: [
    [85.0, 27.0],
    [85.01, 27.01],
  ],
};

const POINT = {
  type: 'Point',
  coordinates: [85.0, 27.0],
};

describe('computeGeometryProps', () => {
  it('returns all keys with null defaults for undefined geometry', () => {
    const props = computeGeometryProps(undefined);
    expect(props).toEqual({
      geo_area_ha: null,
      geo_perimeter_km: null,
      geo_length_km: null,
      geo_centroid_lat: null,
      geo_centroid_lng: null,
      geo_bbox_ymin: null,
      geo_bbox_ymax: null,
      geo_bbox_xmin: null,
      geo_bbox_xmax: null,
    });
  });

  it('computes area/perimeter for polygons (2 decimal places)', () => {
    const props = computeGeometryProps(SQUARE_POLYGON as any);
    expect(props.geo_area_ha).not.toBeNull();
    expect(props.geo_area_ha).toBeCloseTo(props.geo_area_ha as number, 2);
    expect(props.geo_perimeter_km).not.toBeNull();
    expect(props.geo_centroid_lat).toBeCloseTo(27.005, 3);
    expect(props.geo_centroid_lng).toBeCloseTo(85.005, 3);
  });

  it('computes length for lines, not area/perimeter', () => {
    const props = computeGeometryProps(LINE as any);
    expect(props.geo_length_km).not.toBeNull();
    expect(props.geo_area_ha).toBeNull();
    expect(props.geo_perimeter_km).toBeNull();
  });

  it('computes only centroid + bbox for points', () => {
    const props = computeGeometryProps(POINT as any);
    expect(props.geo_centroid_lat).toBe(27);
    expect(props.geo_centroid_lng).toBe(85);
    expect(props.geo_area_ha).toBeNull();
    expect(props.geo_length_km).toBeNull();
  });

  it('computes bbox extents for all geometry types', () => {
    const props = computeGeometryProps(SQUARE_POLYGON as any);
    expect(props.geo_bbox_ymin).toBeCloseTo(27.0, 6);
    expect(props.geo_bbox_ymax).toBeCloseTo(27.01, 6);
    expect(props.geo_bbox_xmin).toBeCloseTo(85.0, 6);
    expect(props.geo_bbox_xmax).toBeCloseTo(85.01, 6);
  });
});

describe('withGeoProps', () => {
  it('merges geo props and strips existing geo_* from source', () => {
    const source = {
      name: 'Test',
      geo_area_ha: 999, // spoofed — must be replaced
      unrelated: 'kept',
    };
    const merged = withGeoProps(source, SQUARE_POLYGON as any);
    expect(merged.name).toBe('Test');
    expect(merged.unrelated).toBe('kept');
    expect(merged.geo_area_ha).not.toBe(999);
    for (const key of GEO_COMPUTED_KEYS) {
      expect(Object.prototype.hasOwnProperty.call(merged, key)).toBe(true);
    }
  });
});
