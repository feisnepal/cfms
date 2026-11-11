"""One definition of a field book row -- so every output says the same thing.

CSV, Excel, GeoJSON, GPX, the OP document table and the Field Book tab used to each build their own row, so they
drifted: a different search buffer for the nearest ridge/river (100 m in the tab, 200 m in the files), a distance
truncated in one place and rounded in another, GeoJSON and GPX without the nearby feature, a ``Block``, a ``Separates``
and a ``Remark`` column that all said the same thing.

``point_record`` is the row. The exporters format it (a CSV cell, an Excel cell, a GeoJSON property, a GPX
description); they never recompute it. ``topography_for`` is the one place the nearest ridge/river is looked up.

The remark is the one human-readable statement of what a point is, and it already names the units
(``outer: ब्लक १, ब्लक २``, ``internal (junction of 3): A, B, C``). There is deliberately no separate "Block" or
"Separates" column: they would repeat it. The structured fields stay in the database and the API for code that
needs them (``adjacent_units``, ``block_name``, ``lines``).
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Dict, Iterable, Optional

logger = logging.getLogger(__name__)

# (key, header). The header is the bilingual one the CSV and Excel files carry; GeoJSON uses the key.
# Order is the reading order: what the point is, then where, then how to get to the next one.
COLUMNS = [
    ("point", "क्र.सं. (Point No)"),
    ("type", "प्रकार (Type)"),
    ("boundary", "सीमा (Outer/Internal)"),
    ("junction", "जंक्सन (Junction)"),
    ("remarks", "कैफियत (Remarks)"),
    ("next_point", "अर्को बिन्दु (Next Point)"),
    ("line", "रेखा (Line)"),
    ("sub_area", "उप-क्षेत्रको नाम (Sub-area Name)"),
    ("sub_area_category", "उप-क्षेत्रको प्रकार (Sub-area Category)"),
    ("excluded", "बहिस्कृत क्षेत्र हो (Is Excluded Zone)"),
    ("latitude", "अक्षांश (Latitude)"),
    ("longitude", "देशान्तर (Longitude)"),
    ("easting_utm", "UTM इस्टिङ (Easting UTM)"),
    ("northing_utm", "UTM नर्दिङ (Northing UTM)"),
    ("utm_zone", "UTM जोन (UTM Zone)"),
    ("azimuth", "दिगंश / Azimuth (deg)"),
    ("distance", "दूरी / Distance (m)"),
    ("elevation", "उचाइ / Elevation (m)"),
    ("nearest_feature", "नजिकको फिचर (Nearest Feature)"),
    ("nearest_feature_type", "फिचरको प्रकार (Feature Type)"),
    ("nearest_feature_distance_m", "फिचरसम्मको दूरी / Distance to Feature (m)"),
    ("nearest_feature_direction", "फिचरतर्फको दिशा (Direction to Feature)"),
    ("verified", "प्रमाणित (Verified)"),
]
KEYS = [k for k, _ in COLUMNS]
HEADERS = [h for _, h in COLUMNS]

# decimal places a numeric value is rounded to -- once, here, so no format shows more or less than another
PLACES = {
    "latitude": 7, "longitude": 7, "easting_utm": 2, "northing_utm": 2,
    "azimuth": 2, "distance": 2, "elevation": 2,
}

TOPO_KEYS = ("nearest_feature", "nearest_feature_type", "nearest_feature_distance_m", "nearest_feature_direction")
_EMPTY_TOPO: Dict[str, Any] = {k: None for k in TOPO_KEYS}


def _num(value, places: int) -> Optional[float]:
    """Rounded float; None stays None and a real 0 stays 0 (a falsy test used to blank it)."""
    return None if value is None else round(float(value), places)


def point_label(point) -> str:
    """What people read and quote: O1.. / I1..; P<n> for a field book made before outer/internal existed."""
    return point.point_label or f"P{point.point_number}"


def point_record(point, topo: Optional[Dict[str, Any]] = None) -> "OrderedDict[str, Any]":
    """The canonical row for one saved point. Values are final (rounded); formatting is the exporter's job."""
    topo = topo or _EMPTY_TOPO
    return OrderedDict(
        point=point_label(point),
        type=point.point_type,
        boundary=point.boundary_class or None,
        junction=point.junction_degree if point.is_junction else None,
        remarks=point.remarks or None,
        next_point=point.next_point_label or None,
        line=point.line_id or None,
        sub_area=point.sub_area_name or None,
        sub_area_category=point.sub_area_category or None,
        excluded=(("Yes" if point.is_excluded else "No") if point.sub_area_name else None),
        latitude=_num(point.latitude, PLACES["latitude"]),
        longitude=_num(point.longitude, PLACES["longitude"]),
        easting_utm=_num(point.easting_utm, PLACES["easting_utm"]),
        northing_utm=_num(point.northing_utm, PLACES["northing_utm"]),
        utm_zone=point.utm_zone,
        azimuth=_num(point.azimuth_to_next, PLACES["azimuth"]),
        distance=_num(point.distance_to_next, PLACES["distance"]),
        elevation=_num(point.elevation, PLACES["elevation"]),
        nearest_feature=topo.get("nearest_feature"),
        nearest_feature_type=topo.get("nearest_feature_type"),
        nearest_feature_distance_m=topo.get("nearest_feature_distance_m"),
        nearest_feature_direction=topo.get("nearest_feature_direction"),
        verified="Yes" if point.is_verified else "No",
    )


def csv_text(key: str, value: Any) -> str:
    """A record value as CSV text: fixed decimals for measurements, blank for None (but 0 stays '0.00')."""
    if value is None:
        return ""
    if key in PLACES:
        return f"{value:.{PLACES[key]}f}"
    return str(value)


# ---------------------------------------------------------------------------
# nearest ridge / river
# ---------------------------------------------------------------------------

# One set of parameters for every output. The tab used a 100 m pre-clip buffer and the files 200 m, so the same
# point could name a different nearby feature depending on where you looked.
TOPO_PRECLIP_BUFFER_M = 200.0
TOPO_SEARCH_RADIUS_M = 100.0
TOPO_MIN_DISTANCE_M = 20.0


def topography_for(db, calculation_id, points: Iterable[Any]) -> Dict[Any, Dict[str, Any]]:
    """``{point.id: {nearest_feature, nearest_feature_type, nearest_feature_distance_m, nearest_feature_direction}}``.

    Pre-clips the ridge/river data to the forest boundary ONCE (20-100x faster than querying per point). Any failure
    degrades to "no nearby feature" rather than failing the export; it is logged with the call site.
    """
    from sqlalchemy import text

    points = list(points)
    out: Dict[Any, Dict[str, Any]] = {p.id: dict(_EMPTY_TOPO) for p in points}
    try:
        from app.utils.geospatial_vector_optimized import (
            find_nearest_topographic_feature_optimized,
            preclip_topographic_features,
        )

        row = db.execute(
            text("SELECT ST_AsText(boundary_geom) AS wkt FROM public.calculations WHERE id = :calc_id"),
            {"calc_id": str(calculation_id)},
        ).first()
        if not row or not row.wkt:
            return out
        clipped = preclip_topographic_features(db=db, boundary_wkt=row.wkt, buffer_meters=TOPO_PRECLIP_BUFFER_M)
        if not clipped:
            logger.warning("Pre-clipping returned nothing - nearest ridge/river columns will be empty")
            return out
        for p in points:
            if p.longitude is None or p.latitude is None:
                continue
            try:
                found = find_nearest_topographic_feature_optimized(
                    db=db,
                    longitude=float(p.longitude),
                    latitude=float(p.latitude),
                    clipped_features=clipped,
                    search_radius_meters=TOPO_SEARCH_RADIUS_M,
                    prefer_rivers=True,
                    min_distance_threshold=TOPO_MIN_DISTANCE_M,
                )
            except Exception:
                logger.warning("nearest ridge/river lookup failed for point %s", p.point_number, exc_info=True)
                continue
            if found:
                out[p.id] = {
                    "nearest_feature": found.get("feature_name") or None,
                    "nearest_feature_type": found.get("feature_type") or None,
                    "nearest_feature_distance_m": int(round(float(found.get("distance_meters") or 0))),
                    "nearest_feature_direction": found.get("direction") or None,
                }
    except Exception:
        logger.error("Failed to look up nearest ridge/river features", exc_info=True)
        try:
            db.rollback()
        except Exception:
            logger.warning("rollback failed after a topography error", exc_info=True)
    return out


# ---------------------------------------------------------------------------
# the remark
# ---------------------------------------------------------------------------

def generated_remark(point) -> str:
    """What the generator wrote for this point: ``outer: ब्लक १, ब्लक २`` / ``internal (junction of 3): A, B, C``.
    Empty for a point from a field book made before outer/internal existed."""
    if not point.boundary_class:
        return ""
    from app.services.fieldbook_sequence import remark_text

    return remark_text(point.boundary_class, list(point.adjacent_units or []), point.junction_degree or 0, point.sub_area_name)


def merge_remark(point, note: Optional[str]) -> Optional[str]:
    """A surveyor's note added to a point. The generated text (which names the units) is always kept in front, so a note
    in the field can never remove the one statement of what the point separates. Clearing the note restores the generated
    text; a note that already begins with it (an edited copy of the whole remark) is kept as written."""
    note = (note or "").strip()
    base = generated_remark(point)
    if not base:
        return note or None
    if not note:
        return base
    if note.startswith(base):
        return note
    return f"{base}; {note}"
