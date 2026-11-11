/**
 * displayCrs.ts — Precision Display CRS helpers (Gap 2).
 *
 * SSOT Reference: backend/app/core/geo.py (`calculate_utm_epsg`),
 * backend/app/core/constants.py (UTM zones 44N/45N).
 *
 * Storage is always EPSG:4326 GeoJSON; DISPLAY_CRS controls presentation only.
 */

export interface CrsDefinition {
  epsg: number;
  name: string;
  unit: 'degrees' | 'meters';
}

export const DISPLAY_CRS: CrsDefinition = {
  epsg: 4326,
  name: 'WGS 84 (Lat/Lon)',
  unit: 'degrees',
};

export interface LatLngPoint {
  lat: number;
  lng: number;
}

/** Format lat/lng coordinates for status bar / numeric entry display (6 decimal places). */
export function formatCoords(latlng: LatLngPoint, _crs: CrsDefinition = DISPLAY_CRS): string {
  const lat = Number(latlng.lat);
  const lng = Number(latlng.lng);
  if (Number.isNaN(lat) || Number.isNaN(lng)) return '—, —';
  return `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
}

/** Parse coordinate text (e.g. "27.5, 83.5" or "27.5 83.5") into LatLngPoint. */
export function parseCoords(text: string, _crs: CrsDefinition = DISPLAY_CRS): LatLngPoint | null {
  if (!text || typeof text !== 'string') return null;
  const parts = text.trim().split(/[\s,]+/);
  if (parts.length < 2) return null;
  const lat = parseFloat(parts[0]);
  const lng = parseFloat(parts[1]);
  if (Number.isNaN(lat) || Number.isNaN(lng)) return null;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return null;
  return { lat, lng };
}
