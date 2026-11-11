"""Geospatial helpers — single source of truth for UTM zone selection.

The UTM zone MUST be computed automatically from latitude/longitude rather than
hardcoded (e.g. 32645). Previously the codebase used a mix of hardcoded 32645,
a Nepal-binary `lon<84 -> 32644 else 32645`, and duplicate global formulas
(see SSOT_audit_Report.md D10-B). All area/ST_Transform calls should derive the
SRID from calculate_utm_epsg(lon, lat).

The original implementation lived in app.utils.geometry_utils; it is re-exported
there to avoid breaking the Shapely geodesic util that imports it.
"""

from typing import Tuple


def calculate_utm_epsg(lon: float, lat: float) -> int:
    """Calculate the appropriate UTM EPSG code for given coordinates.

    Uses standard UTM zone calculation that works globally:
    - Zone number = floor((longitude + 180) / 6) + 1
    - Northern hemisphere: EPSG 326XX (where XX is zone number)
    - Southern hemisphere: EPSG 327XX (where XX is zone number)

    Args:
        lon: Longitude in decimal degrees (WGS84)
        lat: Latitude in decimal degrees (WGS84)

    Returns:
        EPSG code for the appropriate UTM zone

    Examples:
        >>> calculate_utm_epsg(85.3, 27.7)  # Kathmandu, Nepal
        32645  # UTM Zone 45N
        >>> calculate_utm_epsg(-122.4, 37.8)  # San Francisco, USA
        32610  # UTM Zone 10N
        >>> calculate_utm_epsg(151.2, -33.9)  # Sydney, Australia
        32756  # UTM Zone 56S
    """
    # Calculate UTM zone number (1-60)
    zone = int((lon + 180) / 6) + 1
    if zone > 60:
        zone = 60

    # Determine hemisphere and calculate EPSG code
    if lat >= 0:
        # Northern hemisphere: 32601-32660
        epsg = 32600 + zone
    else:
        # Southern hemisphere: 32701-32760
        epsg = 32700 + zone

    return epsg


def utm_epsg_for_geometry_wkt(wkt_4326: str) -> int:
    """Compute UTM EPSG from the centroid of a WGS84 WKT geometry.

    Convenience for SQL/Python paths that hold a geometry as WKT in EPSG:4326.
    """
    from shapely import wkt as shapely_wkt

    centroid = shapely_wkt.loads(wkt_4326).centroid
    return calculate_utm_epsg(centroid.x, centroid.y)


def utm_epsg_for_lonlat_tuple(centroid: Tuple[float, float]) -> int:
    """Compute UTM EPSG from a (lon, lat) tuple."""
    lon, lat = centroid
    return calculate_utm_epsg(lon, lat)
