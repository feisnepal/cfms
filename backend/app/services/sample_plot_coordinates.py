"""Typing a sample plot's coordinates: WGS84 latitude / longitude, or UTM easting / northing.

Plots are STORED as WGS84 (EPSG:4326). UTM is a second way of writing the same place, in a metre grid whose zone depends on where the
plot is (Nepal is zone 44 west of 84 degrees E and zone 45 east of it). The zone is never typed: it is worked out from the plot itself,
so a forest that crosses the 84 degree line simply has plots in both zones, each shown in its own. A UTM value typed for a plot is read in
THAT plot's current zone (the zone shown in its own row).

One value may be changed at a time (a single cell): the other value of its pair is taken from the plot as it is now.

Pure and database-free; the endpoint does the boundary check and the saving.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from pyproj import Transformer

LAT_RANGE = (-90.0, 90.0)
LON_RANGE = (-180.0, 180.0)
EASTING_RANGE = (0.0, 1_000_000.0)
NORTHING_RANGE = (0.0, 10_000_000.0)


class CoordinateError(ValueError):
    """A typed coordinate that cannot be used. ``code`` is the i18n message key (``sampling.<code>``); ``fields`` fill its placeholders."""

    def __init__(self, code: str, **fields):
        super().__init__(code)
        self.code = code
        self.fields = fields


@dataclass(frozen=True)
class Resolved:
    longitude: float
    latitude: float
    system: str  # "wgs84" | "utm"
    zone: int
    easting: float
    northing: float
    #: the user typed one value of a pair (rather than a whole dragged position)
    typed: bool

    def describe(self) -> str:
        """The point as the system understood it, language-neutral (digits and symbols only) for the error message."""
        wgs = f"lat {self.latitude:.6f}, lon {self.longitude:.6f}"
        if self.system == "utm":
            return f"UTM {self.zone}N E {self.easting:.2f} N {self.northing:.2f} ({wgs})"
        return wgs


def utm_zone_for(longitude: float) -> int:
    """The UTM zone a longitude falls in (Nepal: 44 up to 84 degrees E, 45 from 84 degrees E)."""
    return int((float(longitude) + 180.0) // 6.0) + 1


def to_utm(longitude: float, latitude: float, zone: Optional[int] = None) -> tuple[int, float, float]:
    """``(zone, easting, northing)`` of a WGS84 point; ``zone`` defaults to the point's own."""
    z = zone if zone is not None else utm_zone_for(longitude)
    e, n = Transformer.from_crs("EPSG:4326", f"EPSG:326{z:02d}", always_xy=True).transform(longitude, latitude)
    return z, float(e), float(n)


def from_utm(zone: int, easting: float, northing: float) -> tuple[float, float]:
    """``(longitude, latitude)`` of a UTM point (northern hemisphere) in the given zone."""
    lon, lat = Transformer.from_crs(f"EPSG:326{zone:02d}", "EPSG:4326", always_xy=True).transform(easting, northing)
    return float(lon), float(lat)


def _number(value, field: str) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise CoordinateError("coordinate_not_a_number", field=field)
    if not math.isfinite(v):
        raise CoordinateError("coordinate_not_a_number", field=field)
    return v


def resolve_new_location(
    current_lon: float,
    current_lat: float,
    *,
    longitude=None,
    latitude=None,
    utm_easting=None,
    utm_northing=None,
) -> Resolved:
    """The plot's new WGS84 position from whatever the user typed. Raises :class:`CoordinateError` (friendly, translated by the caller)."""
    lon, lat = _number(longitude, "longitude"), _number(latitude, "latitude")
    east, north = _number(utm_easting, "utm_easting"), _number(utm_northing, "utm_northing")
    wgs_given = lon is not None or lat is not None
    utm_given = east is not None or north is not None
    if wgs_given and utm_given:
        raise CoordinateError("coordinate_both")
    if not wgs_given and not utm_given:
        raise CoordinateError("coordinate_none")

    if wgs_given:
        new_lon = current_lon if lon is None else lon
        new_lat = current_lat if lat is None else lat
        if not (LAT_RANGE[0] <= new_lat <= LAT_RANGE[1]):
            raise CoordinateError("coordinate_lat_range", value=f"{new_lat:g}")
        if not (LON_RANGE[0] <= new_lon <= LON_RANGE[1]):
            raise CoordinateError("coordinate_lon_range", value=f"{new_lon:g}")
        zone, e, n = to_utm(new_lon, new_lat)
        # a typed pair of both lon+lat is a whole new position (a drag); a single value is a typed cell
        return Resolved(new_lon, new_lat, "wgs84", zone, e, n, typed=not (lon is not None and lat is not None))

    zone, cur_e, cur_n = to_utm(current_lon, current_lat)  # read in the zone of the plot as it is now
    e = cur_e if east is None else east
    n = cur_n if north is None else north
    if not (EASTING_RANGE[0] < e < EASTING_RANGE[1]):
        raise CoordinateError("coordinate_easting_range", value=f"{e:,.2f}", zone=zone)
    if not (NORTHING_RANGE[0] <= n < NORTHING_RANGE[1]):
        raise CoordinateError("coordinate_northing_range", value=f"{n:,.2f}", zone=zone)
    new_lon, new_lat = from_utm(zone, e, n)
    if not (math.isfinite(new_lon) and math.isfinite(new_lat)):
        raise CoordinateError("coordinate_easting_range", value=f"{e:,.2f}", zone=zone)
    return Resolved(new_lon, new_lat, "utm", zone, e, n, typed=True)
