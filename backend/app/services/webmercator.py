"""
Web-Mercator (EPSG:3857) tile helpers — U05/U06 cluster grid.

MUST STAY IN LOCKSTEP with `frontend/src/lib/webmercator.ts` (plan A.3).
All tile math is Web Mercator (metres), NOT decimal degrees — grid spacing is
uniform at any latitude only in EPSG:3857 (a decimal-degree cell_m/111320
approach distorts east-west away from the equator and is wrong).
"""

from __future__ import annotations

import math

# Web Mercator world circumference (2 * pi * R, R = 6378137 m).
EARTH_RADIUS_M = 6378137.0
WORLD_CIRCUMFERENCE_M = 2.0 * math.pi * EARTH_RADIUS_M
ORIGIN_SHIFT_M = WORLD_CIRCUMFERENCE_M / 2.0  # half-world (max |x| or |y| in 3857)


def _clamp_lat(lat: float) -> float:
    """Clamp to Web Mercator's valid latitude range [-85.05112878, 85.05112878]."""
    return max(-85.05112878, min(85.05112878, lat))


def tile_xy(lng: float, lat: float, z: int) -> tuple[int, int]:
    """Web-Mercator tile x,y for a lon/lat at zoom z.

    Standard rule: n = 2**z; x = (lng+180)/360*n; y follows the Mercator formula.
    MUST STAY IN LOCKSTEP with frontend/src/lib/webmercator.ts.
    """
    n = float(2 ** z)
    lat = _clamp_lat(lat)
    lat_rad = math.radians(lat)
    x = (lng + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n
    return int(math.floor(x)), int(math.floor(y))


def bbox_for_tile(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Web-Mercator lon/lat bbox (w, s, e, n) for a tile. Must stay in lockstep.

    Uses the standard tile→lat/lng inverse: y uses atan(sinh(pi*(1-2y/n))).
    """
    n = float(2 ** z)
    w = x / n * 360.0 - 180.0
    e = (x + 1) / n * 360.0 - 180.0
    n0 = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    s = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * (y + 1) / n))))
    return w, s, e, n0


def lnglat_to_meters(lng: float, lat: float) -> tuple[float, float]:
    """Convert EPSG:4326 lon/lat to EPSG:3857 metres."""
    x = lng * ORIGIN_SHIFT_M / 180.0
    y = math.log(math.tan((90.0 + _clamp_lat(lat)) * math.pi / 360.0)) / (math.pi / 180.0)
    y = y * ORIGIN_SHIFT_M / 180.0
    return x, y


def webmercator_extent(w: float, s: float, e: float, n: float) -> tuple[float, float, float, float]:
    """Transform a 4326 bbox (w,s,e,n) into EPSG:3857 (x_min, y_min, x_max, y_max)."""
    x_min, _ = lnglat_to_meters(w, s)
    _, y_min = lnglat_to_meters(w, s)
    x_max, _ = lnglat_to_meters(e, n)
    _, y_max = lnglat_to_meters(e, n)
    return x_min, y_min, x_max, y_max


def cell_size_at_zoom(z: int) -> float:
    """Web-Mercator cell size in metres for one tile-step at zoom z.

    cell_m = tile_world_size / 2**z, where tile world size (one tile, zoom 0) is
    156543.03392804097 m. This is the bucket cell size for z<18 clustering.
    """
    return 156543.03392 / (2.0 ** z)