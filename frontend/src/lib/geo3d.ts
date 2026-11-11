/**
 * geo3d.ts — Z-coordinate tolerance + geo3d wrappers (Gap 5.3).
 */
import * as turf from '@turf/turf';
import type { GeoJSON, Feature } from 'geojson';

export function stripZ<T extends GeoJSON>(geojson: T): T {
  if (!geojson || typeof geojson !== 'object') return geojson;
  const clone = JSON.parse(JSON.stringify(geojson));

  function cleanCoords(coords: unknown): unknown {
    if (!Array.isArray(coords)) return coords;
    if (coords.length > 0 && typeof coords[0] === 'number') {
      return coords.slice(0, 2);
    }
    return coords.map(cleanCoords);
  }

  const anyObj = clone as any;
  if (anyObj.geometry && typeof anyObj.geometry === 'object' && anyObj.geometry.coordinates) {
    anyObj.geometry.coordinates = cleanCoords(anyObj.geometry.coordinates);
  }
  if (Array.isArray(anyObj.coordinates)) {
    anyObj.coordinates = cleanCoords(anyObj.coordinates);
  }
  if (Array.isArray(anyObj.features)) {
    anyObj.features = anyObj.features.map(stripZ);
  }

  return clone;
}

export function area3d(geojson: GeoJSON): number {
  const flattened = stripZ(geojson);
  return turf.area(flattened as any);
}

export function length3d(geojson: GeoJSON): number {
  const flattened = stripZ(geojson);
  return turf.length(flattened as any, { units: 'meters' });
}
