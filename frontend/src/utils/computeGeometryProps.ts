/**
 * Frontend geometry computation — mirrors the backend SSOT (compute_geometry_properties).
 *
 * Computes derived geo_* fields from a GeoJSON geometry. Used to guarantee the
 * values exist in the UI even if a feature predates the backend auto-computation,
 * or while a feature is being drawn before it is persisted.
 */
import * as turf from '@turf/turf';
import type { Geometry } from 'geojson';

export interface GeoComputedProps {
  geo_area_ha: number | null;
  geo_perimeter_km: number | null;
  geo_length_km: number | null;
  geo_centroid_lat: number | null;
  geo_centroid_lng: number | null;
  geo_bbox_ymin: number | null;
  geo_bbox_ymax: number | null;
  geo_bbox_xmin: number | null;
  geo_bbox_xmax: number | null;
}

export const GEO_COMPUTED_KEYS: (keyof GeoComputedProps)[] = [
  'geo_area_ha',
  'geo_perimeter_km',
  'geo_length_km',
  'geo_centroid_lat',
  'geo_centroid_lng',
  'geo_bbox_ymin',
  'geo_bbox_ymax',
  'geo_bbox_xmin',
  'geo_bbox_xmax',
];

const EMPTY: GeoComputedProps = {
  geo_area_ha: null,
  geo_perimeter_km: null,
  geo_length_km: null,
  geo_centroid_lat: null,
  geo_centroid_lng: null,
  geo_bbox_ymin: null,
  geo_bbox_ymax: null,
  geo_bbox_xmin: null,
  geo_bbox_xmax: null,
};

const round = (v: number, decimals: number): number =>
  Number(v.toFixed(decimals));

export function computeGeometryProps(geometry: Geometry | undefined | null): GeoComputedProps {
  if (!geometry) return EMPTY;
  try {
    const result: GeoComputedProps = { ...EMPTY };

    // Centroid (all geometry types)
    try {
      const c = turf.centroid(geometry as any);
      if (c.geometry?.coordinates) {
        const [lng, lat] = c.geometry.coordinates;
        result.geo_centroid_lat = round(lat, 6);
        result.geo_centroid_lng = round(lng, 6);
      }
    } catch { /* ignore */ }

    // Bounding box (all geometry types)
    try {
      const bbox = turf.bbox(geometry as any);
      if (Array.isArray(bbox) && bbox.length === 4) {
        const [minX, minY, maxX, maxY] = bbox;
        result.geo_bbox_xmin = round(minX, 6);
        result.geo_bbox_ymin = round(minY, 6);
        result.geo_bbox_xmax = round(maxX, 6);
        result.geo_bbox_ymax = round(maxY, 6);
      }
    } catch { /* ignore */ }

    const type = geometry.type;
    if (type === 'Polygon' || type === 'MultiPolygon') {
      try {
        const areaM2 = turf.area(geometry as any);
        result.geo_area_ha = round(areaM2 / 10000, 2);
      } catch { /* ignore */ }
      try {
        const lengthM = turf.length(turf.feature(geometry) as any, { units: 'kilometers' });
        result.geo_perimeter_km = round(lengthM, 2);
      } catch { /* ignore */ }
    } else if (type === 'LineString' || type === 'MultiLineString') {
      try {
        const lengthKm = turf.length(geometry as any, { units: 'kilometers' });
        result.geo_length_km = round(lengthKm, 2);
      } catch { /* ignore */ }
    }

    return result;
  } catch {
    return EMPTY;
  }
}

/** Merge geo_* into a feature's properties, overriding any existing values. */
export function withGeoProps(properties: Record<string, any>, geometry?: Geometry | null): Record<string, any> {
  const geo = computeGeometryProps(geometry);
  const clean: Record<string, any> = {};
  for (const [k, v] of Object.entries(properties || {})) {
    if (GEO_COMPUTED_KEYS.includes(k as any)) continue;
    clean[k] = v;
  }
  return { ...clean, ...geo };
}
