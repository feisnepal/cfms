/**
 * coordinateMath.ts — CRS-aware bearing, distance, and destination math (Gap 5.1).
 *
 * Dispatches between great-circle calculations (via @turf/turf for EPSG:4326)
 * and planar calculations (for projected CRSs). Never mixes the two.
 */
import * as turf from '@turf/turf';
import type { CrsDefinition, LatLngPoint } from './displayCrs';

export interface PointTuple {
  lng: number;
  lat: number;
}

/** Calculate distance between two points in meters (great-circle for 4326). */
export function distanceBetween(a: LatLngPoint, b: LatLngPoint, crs: CrsDefinition = { epsg: 4326 } as any): number {
  if (crs.epsg === 4326) {
    const from = turf.point([a.lng, a.lat]);
    const to = turf.point([b.lng, b.lat]);
    return turf.distance(from, to, { units: 'meters' });
  }
  // Planar Euclidean fallback for projected systems
  const dx = b.lng - a.lng;
  const dy = b.lat - a.lat;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Calculate initial bearing from point a to point b in degrees (0–360). */
export function bearingBetween(a: LatLngPoint, b: LatLngPoint, crs: CrsDefinition = { epsg: 4326 } as any): number {
  if (crs.epsg === 4326) {
    const from = turf.point([a.lng, a.lat]);
    const to = turf.point([b.lng, b.lat]);
    return turf.bearing(from, to);
  }
  const dx = b.lng - a.lng;
  const dy = b.lat - a.lat;
  return (Math.atan2(dx, dy) * (180 / Math.PI) + 360) % 360;
}

/** Calculate destination point given start point, bearing in degrees, and distance in meters. */
export function destinationPoint(start: LatLngPoint, bearingDeg: number, distanceMeters: number, crs: CrsDefinition = { epsg: 4326 } as any): LatLngPoint {
  if (crs.epsg === 4326) {
    const pt = turf.point([start.lng, start.lat]);
    const options = { units: 'meters' as const };
    const dest = turf.destination(pt, distanceMeters, bearingDeg, options);
    const coords = dest.geometry.coordinates;
    return { lng: coords[0], lat: coords[1] };
  }
  // Planar fallback
  const rad = (bearingDeg * Math.PI) / 180;
  const lng = start.lng + distanceMeters * Math.sin(rad);
  const lat = start.lat + distanceMeters * Math.cos(rad);
  return { lng, lat };
}
