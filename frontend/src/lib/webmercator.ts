/**
 * Web-Mercator (EPSG:3857) tile helpers — U05/U06 cluster grid.
 *
 * MUST STAY IN LOCKSTEP with `backend/app/services/webmercator.py` (plan A.3).
 * All tile math is Web Mercator (metres), NOT decimal degrees — grid spacing is
 * uniform at any latitude only in EPSG:3857 (a decimal-degree cell_m/111320
 * approach distorts east-west away from the equator and is wrong).
 */

const EARTH_RADIUS_M = 6378137.0;
const WORLD_CIRCUMFERENCE_M = 2.0 * Math.PI * EARTH_RADIUS_M;
const ORIGIN_SHIFT_M = WORLD_CIRCUMFERENCE_M / 2.0; // half-world (max |x| or |y| in 3857)

function _clampLat(lat: number): number {
  return Math.max(-85.05112878, Math.min(85.05112878, lat));
}

/**
 * Web-Mercator tile x,y for a lon/lat at zoom z.
 *
 * Standard rule: n = 2**z; x = (lng+180)/360*n; y follows the Mercator formula.
 * MUST STAY IN LOCKSTEP with backend/app/services/webmercator.py.
 */
export function tileXY(lng: number, lat: number, z: number): [number, number] {
  const n = 2 ** z;
  lat = _clampLat(lat);
  const latRad = (lat * Math.PI) / 180;
  const x = ((lng + 180.0) / 360.0) * n;
  const y = (1.0 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2.0 * n;
  return [Math.floor(x), Math.floor(y)];
}

/**
 * Web-Mercator lon/lat bbox (w, s, e, n) for a tile.
 * Must stay in lockstep with backend/app/services/webmercator.py.
 */
export function bboxForTile(x: number, y: number, z: number): [number, number, number, number] {
  const n = 2 ** z;
  const w = (x / n) * 360.0 - 180.0;
  const e = ((x + 1) / n) * 360.0 - 180.0;
  const n0 = Math.atan(Math.sinh(Math.PI * (1.0 - 2.0 * y / n))) * 180.0 / Math.PI;
  const s = Math.atan(Math.sinh(Math.PI * (1.0 - 2.0 * (y + 1) / n))) * 180.0 / Math.PI;
  return [w, s, e, n0];
}

/** Convert EPSG:4326 lon/lat to EPSG:3857 metres. */
export function lngLatToMeters(lng: number, lat: number): [number, number] {
  const x = lng * ORIGIN_SHIFT_M / 180.0;
  let y = Math.log(Math.tan((90.0 + _clampLat(lat)) * Math.PI / 360.0)) / (Math.PI / 180.0);
  y = y * ORIGIN_SHIFT_M / 180.0;
  return [x, y];
}

/** Cell size in metres for one tile-step at zoom z. */
export function cellSizeAtZoom(z: number): number {
  return 156543.03392 / (2 ** z);
}