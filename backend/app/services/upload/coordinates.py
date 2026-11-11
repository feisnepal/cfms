"""Work out what a set of coordinates is (UPLOAD_EXPERIENCE_PLAN.md, UP-3.1).

A file's coordinates are wrong in a handful of recognisable ways: in UTM metres instead of degrees, or longitude and latitude swapped. Telling the
user "verify the coordinates, EPSG code..." leaves them guessing; naming the mistake (and, for UTM, the zone) lets them fix it, or lets us fix it.

The existing ``CoordinateDetector.detect_crs`` picks UTM 44N or 45N from overlapping numeric bounds alone, so 343500 east always reads as zone 44
even where it can only be zone 45. Here each candidate zone is TRANSFORMED and kept only if it lands inside Nepal (and, when a reference box such
as the forest boundary is given, near it).
"""
from __future__ import annotations

import logging

from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

# longitude min, latitude min, longitude max, latitude max
NEPAL_BBOX = (80.0, 26.3, 88.3, 30.5)
UTM_ZONES = {32644: 44, 32645: 45}  # Nepal spans zones 44N (78 to 84 E) and 45N (84 to 90 E)

logger = logging.getLogger(__name__)


def _usable(xs: Iterable, ys: Iterable) -> Tuple[np.ndarray, np.ndarray]:
    x = np.asarray(list(xs) if not isinstance(xs, np.ndarray) else xs, dtype=float).ravel()
    y = np.asarray(list(ys) if not isinstance(ys, np.ndarray) else ys, dtype=float).ravel()
    ok = np.isfinite(x) & np.isfinite(y)
    return x[ok], y[ok]


def in_nepal(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> bool:
    b = NEPAL_BBOX
    return b[0] <= lon_min and lon_max <= b[2] and b[1] <= lat_min and lat_max <= b[3]


def _bbox_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], pad: float = 0.5) -> bool:
    return not (a[2] < b[0] - pad or a[0] > b[2] + pad or a[3] < b[1] - pad or a[1] > b[3] + pad)


def utm_to_lonlat(xs, ys, epsg: int) -> Tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(np.asarray(xs, dtype=float), np.asarray(ys, dtype=float))
    return np.asarray(lon), np.asarray(lat)


EASTING_RANGE = (100_000.0, 1_000_000.0)  # UTM easting: 6 digits
NORTHING_RANGE = (2_500_000.0, 3_800_000.0)  # UTM northing in Nepal: 7 digits (about 2.9 to 3.4 million)
# in-Nepal forms first, so a tie in a file with several forms resolves toward the one we can use
_KIND_ORDER = ("degrees", "utm", "swapped", "swapped_utm", "outside_nepal", "unknown")


_KIND_LABEL = {"degrees": "degrees (latitude / longitude)", "utm": "UTM metres", "swapped": "latitude and longitude swapped",
               "swapped_utm": "easting and northing swapped", "outside_nepal": "degrees outside Nepal", "unknown": "an unrecognised form"}


def point_kind(x, y) -> str:
    """What one coordinate pair is, judged by its size and not by the column names it came in.

    ``degrees`` | ``utm`` | ``swapped`` (latitude in X, longitude in Y) | ``swapped_utm`` (northing in X, easting in Y) |
    ``outside_nepal`` (degrees-shaped but outside the Nepal box) | ``unknown`` | ``missing`` (blank / not a number) | ``zero`` (0 in both).
    """
    try:
        x, y = float(x), float(y)
    except (TypeError, ValueError):
        return "missing"
    if not (np.isfinite(x) and np.isfinite(y)):
        return "missing"
    if x == 0 and y == 0:
        return "zero"
    lon0, lat0, lon1, lat1 = NEPAL_BBOX
    if lon0 <= x <= lon1 and lat0 <= y <= lat1:
        return "degrees"
    if lat0 <= x <= lat1 and lon0 <= y <= lon1:
        return "swapped"
    if EASTING_RANGE[0] <= x <= EASTING_RANGE[1] and NORTHING_RANGE[0] <= y <= NORTHING_RANGE[1]:
        return "utm"
    if NORTHING_RANGE[0] <= x <= NORTHING_RANGE[1] and EASTING_RANGE[0] <= y <= EASTING_RANGE[1]:
        return "swapped_utm"
    if abs(x) <= 180 and abs(y) <= 90:
        return "outside_nepal"
    return "unknown"


def _row_numbers(xs, n: int):
    """Spreadsheet row numbers (row 1 is the header): index + 2 for a pandas Series, else position + 2."""
    idx = getattr(xs, "index", None)
    try:
        return [int(i) + 2 for i in idx] if idx is not None and len(idx) == n else [i + 2 for i in range(n)]
    except (TypeError, ValueError):
        return [i + 2 for i in range(n)]


def point_report(xs, ys) -> Dict[str, Any]:
    """Judge every point separately: the form most of the file is in (``dominant``), the rows with no usable coordinates, and the rows in a
    different form from the rest (``strays``). One mistyped point therefore no longer turns the whole file into 'unknown'."""
    x_list = list(xs.tolist() if hasattr(xs, "tolist") else xs)
    y_list = list(ys.tolist() if hasattr(ys, "tolist") else ys)
    n = min(len(x_list), len(y_list))
    rows = _row_numbers(xs, n)
    kinds = [point_kind(x_list[i], y_list[i]) for i in range(n)]
    counts: Dict[str, int] = {}
    for k in kinds:
        if k not in ("missing", "zero"):
            counts[k] = counts.get(k, 0) + 1
    dominant = min(counts, key=lambda k: (-counts[k], _KIND_ORDER.index(k))) if counts else None
    return {
        "kinds": kinds,
        "rows": rows,
        "dominant": dominant,
        "missing_rows": [r for r, k in zip(rows, kinds) if k in ("missing", "zero")],
        "strays": [(r, k) for r, k in zip(rows, kinds) if k not in ("missing", "zero") and k != dominant],
    }


def diagnose(xs, ys, *, reference_bbox: Optional[Tuple[float, float, float, float]] = None) -> Dict[str, Any]:
    """What the numbers are. ``kind`` is one of:

    ``ok`` (degrees inside Nepal) | ``swapped`` (longitude and latitude the wrong way round) | ``utm`` (one zone fits: ``epsg``, ``zone``) |
    ``utm_ambiguous`` (both zones land in Nepal and no reference box decides) | ``unknown`` | ``empty``.
    ``reference_bbox`` is (lon_min, lat_min, lon_max, lat_max), e.g. the forest boundary: it picks between two UTM zones.
    """
    rep = point_report(xs, ys)
    x, y = _usable(xs, ys)
    if not len(x):
        return {"kind": "empty", "missing_rows": rep["missing_rows"], "strays": rep["strays"]}
    if rep["dominant"] is not None:  # judge the form most of the file is in; the rows in another form are reported as strays, not averaged in
        keep = [k == rep["dominant"] for k in rep["kinds"]]
        xa, ya = np.asarray(list(xs.tolist() if hasattr(xs, "tolist") else xs), dtype=float), np.asarray(list(ys.tolist() if hasattr(ys, "tolist") else ys), dtype=float)
        m = np.asarray(keep) & np.isfinite(xa[: len(keep)]) & np.isfinite(ya[: len(keep)])
        if m.any():
            x, y = xa[: len(keep)][m], ya[: len(keep)][m]
    out = _diagnose_form(x, y, reference_bbox, rep["dominant"])
    out["missing_rows"], out["strays"], out["dominant"] = rep["missing_rows"], rep["strays"], rep["dominant"]
    return out


def _diagnose_form(x, y, reference_bbox, dominant) -> Dict[str, Any]:
    xmin, xmax, ymin, ymax = float(x.min()), float(x.max()), float(y.min()), float(y.max())
    if dominant == "swapped_utm":
        return {"kind": "swapped_utm", "bbox": (xmin, ymin, xmax, ymax)}
    if in_nepal(xmin, ymin, xmax, ymax):
        return {"kind": "ok", "bbox": (xmin, ymin, xmax, ymax)}
    # longitude where latitude should be and the reverse: x looks like a latitude (26 to 31), y like a longitude (80 to 89)
    if in_nepal(ymin, xmin, ymax, xmax):
        return {"kind": "swapped", "bbox": (xmin, ymin, xmax, ymax)}
    if 100_000 <= xmin and xmax <= 1_000_000 and 2_500_000 <= ymin and ymax <= 3_800_000:
        fits = []
        for epsg, zone in UTM_ZONES.items():
            lon, lat = utm_to_lonlat([xmin, xmax], [ymin, ymax], epsg)
            box = (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
            if in_nepal(*box):
                fits.append({"epsg": epsg, "zone": zone, "bbox": box})
        if reference_bbox is not None and len(fits) > 1:
            near = [f for f in fits if _bbox_overlap(f["bbox"], reference_bbox)]
            fits = near or fits
        if len(fits) == 1:
            return {"kind": "utm", **fits[0]}
        if len(fits) > 1:
            return {"kind": "utm_ambiguous", "candidates": fits}
    return {"kind": "unknown", "bbox": (xmin, ymin, xmax, ymax)}


def forest_bbox(db, calculation_id) -> Optional[Tuple[float, float, float, float]]:
    """(lon_min, lat_min, lon_max, lat_max) of the forest boundary, used to tell UTM zone 44 from 45; None without a boundary."""
    from sqlalchemy import text

    if not calculation_id:
        return None
    row = db.execute(
        text("SELECT ST_XMin(boundary_geom), ST_YMin(boundary_geom), ST_XMax(boundary_geom), ST_YMax(boundary_geom) FROM calculations WHERE id = :c"),
        {"c": str(calculation_id)},
    ).first()
    return tuple(float(v) for v in row) if row and row[0] is not None else None


def coordinate_findings(xs, ys, *, reference_bbox=None, file: Optional[str] = None):
    """Findings for a file whose coordinates are not degrees inside Nepal: name the mistake and say what to do (nothing for the OK case).

    Used by the uploads that SUGGEST rather than convert (field inventory, stem mapping): the user fixes the file or chooses the projection."""
    from app.services.upload.findings import finding

    d = diagnose(xs, ys, reference_bbox=reference_bbox)
    out = []
    if d["kind"] == "swapped":
        out.append(finding("coordinates.looks_swapped", file=file))
    elif d["kind"] == "swapped_utm":
        out.append(finding("coordinates.looks_swapped_utm", file=file))
    elif d["kind"] == "utm":
        out.append(finding("coordinates.looks_like_utm", found=d["zone"], expected=f"EPSG:{d['epsg']}", file=file))
    elif d["kind"] == "utm_ambiguous":
        zones = " or ".join(str(c["zone"]) for c in d["candidates"])
        epsgs = " or ".join(f"EPSG:{c['epsg']}" for c in d["candidates"])
        out.append(finding("coordinates.looks_like_utm", found=zones, expected=epsgs, file=file))
    if d.get("missing_rows"):  # name the rows: a count alone sends the user hunting through the sheet
        out.append(finding("coordinates.rows_missing", rows=d["missing_rows"][:50], count=len(d["missing_rows"]), file=file))
    strays = d.get("strays") or []
    if strays:
        out.append(finding("coordinates.stray_points", rows=[r for r, _ in strays][:50], count=len(strays),
                           found=" / ".join(sorted({_KIND_LABEL[k] for _, k in strays})), expected=_KIND_LABEL.get(d.get("dominant"), ""), file=file))
    return out


def preview_payload(db, calculation_id, xs, ys, *, max_points: int = 300) -> Dict[str, Any]:
    """What to draw so the user can SEE where a file's points fall: a sample of the points, the forest boundary (simplified), and how the numbers
    were read. UTM metres are drawn converted (``assumed`` says which zone), so the picture shows where the points WOULD be; swapped columns are
    drawn corrected. ``assumed`` is ``as_is`` | ``utm_zone_44`` | ``utm_zone_45`` | ``swapped``."""
    import json

    from sqlalchemy import text

    x, y = _usable(xs, ys)
    boundary = None
    if calculation_id:
        row = db.execute(
            text("SELECT ST_AsGeoJSON(ST_Simplify(boundary_geom, 0.0003)) FROM calculations WHERE id = :c AND boundary_geom IS NOT NULL"),
            {"c": str(calculation_id)},
        ).scalar()
        boundary = json.loads(row) if row else None
    d = diagnose(x, y, reference_bbox=forest_bbox(db, calculation_id))
    assumed = "as_is"
    if d["kind"] == "utm":
        x, y = utm_to_lonlat(x, y, d["epsg"])
        assumed = f"utm_zone_{d['zone']}"
    elif d["kind"] == "swapped":
        x, y = y, x
        assumed = "swapped"
    if len(x) > max_points:
        idx = np.linspace(0, len(x) - 1, max_points).astype(int)
        x, y = x[idx], y[idx]
    return {"points": [[round(float(a), 6), round(float(b), 6)] for a, b in zip(x, y)], "assumed": assumed, "boundary": boundary}


FAR_FROM_FOREST_M = 2000.0  # a user group beside its forest may touch or lie near it; kilometres away is almost always a wrong file or projection


def distance_to_forest_m(db, calculation_id) -> Optional[float]:
    """Metres from the saved user group (union of its polygons) to the forest boundary; 0 when they touch; None when either is missing."""
    from sqlalchemy import text

    row = db.execute(
        text(
            "SELECT ST_Distance(geography(ST_Union(e.extent_geometry)), geography(c.boundary_geom)) "
            "FROM public.user_group_extents e JOIN public.calculations c ON c.id = e.calculation_id "
            "WHERE e.calculation_id = :c AND e.extent_geometry IS NOT NULL AND c.boundary_geom IS NOT NULL GROUP BY c.boundary_geom"
        ),
        {"c": str(calculation_id)},
    ).first()
    return float(row[0]) if row and row[0] is not None else None


def far_from_forest_findings(db, calculation_id, file=None) -> list:
    """A warning when the saved user group is far from the forest (never a block: the group is saved as uploaded)."""
    from app.services.upload.findings import finding

    try:
        d = distance_to_forest_m(db, calculation_id)
    except Exception:  # noqa: BLE001 -- advisory check; the upload itself must not fail because of it
        logger.warning("far-from-forest check failed for %s", calculation_id, exc_info=True)
        db.rollback()
        return []
    if d is None or d <= FAR_FROM_FOREST_M:
        return []
    return [finding("user_group.far_from_forest", found=f"{d / 1000:.1f}", file=file)]


# ── which coordinate system? (VALIDATION_TRACKER.md, step C2) ───────────────────────────────────────────────────────────
# Degrees and the two UTM zones that cover Nepal. Modified UTM (Everest 1830) is a later step; a file in it is handled as "unrecognised": the
# user gives the EPSG code. The user's choice is the authority; detection pre-selects it and checks it against where the points land.
SYSTEM_LABELS = {4326: "Degrees (WGS 84)", 32644: "UTM zone 44N", 32645: "UTM zone 45N"}
INSIDE_NEPAL_OK = 0.95  # a system "fits" when at least this share of the points land inside the real outline of Nepal


def inside_nepal_flags(db, lons, lats):
    """For each point, is it inside Nepal's real outline (``admin.province``), not the bounding rectangle? NaN is False."""
    from sqlalchemy import text

    lo = [float(v) if np.isfinite(v) else None for v in lons]
    la = [float(v) if np.isfinite(v) else None for v in lats]
    if not lo:
        return []
    rows = db.execute(
        text(
            "SELECT p.i, (p.lon IS NOT NULL AND p.lat IS NOT NULL AND EXISTS (SELECT 1 FROM admin.province pr "
            "WHERE ST_Intersects(pr.shape, ST_SetSRID(ST_MakePoint(p.lon, p.lat), 4326)))) "
            "FROM unnest(cast(:lo AS float8[]), cast(:la AS float8[])) WITH ORDINALITY AS p(lon, lat, i) ORDER BY p.i"
        ),
        {"lo": lo, "la": la},
    ).fetchall()
    return [bool(r[1]) for r in rows]


def _fraction(flags, mask) -> float:
    sel = [f for f, m in zip(flags, mask) if m]
    return (sum(sel) / len(sel)) if sel else 0.0


def detect_systems(db, xs, ys, *, reference_bbox=None) -> Dict[str, Any]:
    """Which coordinate system the numbers are in, as candidates the dialog can pre-select from.

    ``candidates`` lists each system that could explain the dominant form of the file, best first, with the share of points that land inside
    Nepal under it. ``suggested_epsg`` is set only when one candidate clearly fits (and, when it is a tie, the forest boundary breaks it); otherwise
    ``ambiguous`` is True and the user is asked. Rows in another form, and rows with no coordinates, are returned by number.
    """
    rep = point_report(xs, ys)
    dom = rep["dominant"]
    base: Dict[str, Any] = {"dominant": dom, "missing_rows": rep["missing_rows"], "strays": rep["strays"], "candidates": [],
                            "suggested_epsg": None, "ambiguous": False, "point_count": len(rep["kinds"])}
    if dom is None:
        return base
    xa = np.asarray(list(xs.tolist() if hasattr(xs, "tolist") else xs), dtype=float)
    ya = np.asarray(list(ys.tolist() if hasattr(ys, "tolist") else ys), dtype=float)
    n = len(rep["kinds"])
    xa, ya = xa[:n], ya[:n]
    mask = np.asarray([k == dom for k in rep["kinds"]])

    def candidate(epsg: int, lon, lat) -> Dict[str, Any]:
        flags = inside_nepal_flags(db, lon, lat)
        box = (float(np.nanmin(lon[mask])), float(np.nanmin(lat[mask])), float(np.nanmax(lon[mask])), float(np.nanmax(lat[mask]))) if mask.any() else None
        return {"epsg": epsg, "zone": UTM_ZONES.get(epsg), "label": SYSTEM_LABELS[epsg], "inside_fraction": round(_fraction(flags, mask), 3),
                "near_forest": bool(reference_bbox is not None and box is not None and _bbox_overlap(box, reference_bbox))}

    cands: List[Dict[str, Any]] = []
    if dom == "degrees":
        cands.append(candidate(4326, xa, ya))
    elif dom == "swapped":
        cands.append(candidate(4326, ya, xa))  # the columns are the wrong way round; the system itself is degrees
    elif dom == "utm":
        for epsg in UTM_ZONES:
            ok = np.isfinite(xa) & np.isfinite(ya)
            lon = np.full(n, np.nan)
            lat = np.full(n, np.nan)
            lon[ok & mask], lat[ok & mask] = utm_to_lonlat(xa[ok & mask], ya[ok & mask], epsg)
            cands.append(candidate(epsg, lon, lat))
    # dominant "swapped_utm" / "outside_nepal" / "unknown": no candidate can be offered; the user names the system (custom EPSG)
    cands.sort(key=lambda c: (-c["inside_fraction"], not c["near_forest"], c["epsg"]))
    fitting = [c for c in cands if c["inside_fraction"] >= INSIDE_NEPAL_OK]
    if len(fitting) > 1 and reference_bbox is not None:
        near = [c for c in fitting if c["near_forest"]]
        fitting = near or fitting
    base["candidates"] = cands
    base["none_fit"] = bool(cands) and not fitting  # numbers that land inside Nepal under no system we offer: the user names the system
    if len(fitting) == 1:
        base["suggested_epsg"] = fitting[0]["epsg"]
    elif len(fitting) > 1:
        base["ambiguous"] = True
    return base


def apply_system(df, epsg: Optional[int], columns=("longitude", "latitude")):
    """Convert the coordinate columns from the chosen UTM zone to degrees. ``(df, converted_row_count)``; the input frame is not modified.

    Only rows that are in UTM form are converted, so a stray row typed in degrees is left for the validator to name. Degrees (4326) and None change nothing."""
    if epsg not in UTM_ZONES or any(c not in df.columns for c in columns):
        return df, 0
    import pandas as pd

    xc, yc = columns
    x = pd.to_numeric(df[xc], errors="coerce")
    y = pd.to_numeric(df[yc], errors="coerce")
    rows = [point_kind(a, b) == "utm" for a, b in zip(x, y)]
    if not any(rows):
        return df, 0
    sel = np.asarray(rows)
    lon, lat = utm_to_lonlat(x.to_numpy()[sel], y.to_numpy()[sel], epsg)
    out = df.copy()
    out[xc], out[yc] = x.astype(float), y.astype(float)  # a cell that was not a number is a blank now; the validator names the row
    out.loc[sel, xc] = lon
    out.loc[sel, yc] = lat
    return out, int(sel.sum())


def apply_chosen_system(db, df, epsg: Optional[int], *, file: Optional[str] = None, columns=("longitude", "latitude")):
    """``(df, findings)`` for the system the user chose. UTM is converted (and reported once, as before); if the converted points do not land in
    Nepal the mismatch is named with its rows and the system the numbers look like. Degrees / None: the frame is returned as it is."""
    from app.services.upload.findings import finding

    if epsg not in UTM_ZONES:
        return df, []
    out, converted = apply_system(df, epsg, columns)
    if not converted:
        return df, []
    import pandas as pd

    lon = pd.to_numeric(out[columns[0]], errors="coerce").to_numpy()
    lat = pd.to_numeric(out[columns[1]], errors="coerce").to_numpy()
    flags = inside_nepal_flags(db, lon, lat)
    kinds = [point_kind(a, b) for a, b in zip(pd.to_numeric(df[columns[0]], errors="coerce"), pd.to_numeric(df[columns[1]], errors="coerce"))]
    rows = _row_numbers(df[columns[0]], len(kinds))
    outside = [r for r, k, f in zip(rows, kinds, flags) if k == "utm" and not f]
    findings = [finding("coordinates.utm_converted", found=UTM_ZONES[epsg], file=file)]
    if outside:
        best = detect_systems(db, df[columns[0]], df[columns[1]])
        alt = next((c["label"] for c in best["candidates"] if c["epsg"] != epsg and c["inside_fraction"] >= INSIDE_NEPAL_OK), "another system")
        findings.append(finding("coordinates.system_mismatch", rows=outside[:50], count=len(outside), found=SYSTEM_LABELS[epsg], expected=alt, file=file))
    return out, findings


def boundary_check_points(xs, ys, *, projection_epsg: Optional[int] = None, reference_bbox=None) -> List[Tuple[float, float, int]]:
    """``[(longitude, latitude, 1-based row)]`` for the quick boundary check of a stem-mapping file.

    The check compares points with the forest boundary in degrees. A file in UTM metres used to be compared as if its numbers were degrees, so every
    tree was reported outside the forest whatever the user chose. Rows in UTM form are converted with the zone the user chose; with no choice, with the
    one zone that fits Nepal (the forest boundary breaks a tie between two). Degrees, and anything we cannot place, are passed on unchanged.
    """
    x = np.asarray(list(xs.tolist() if hasattr(xs, "tolist") else xs), dtype=float)
    y = np.asarray(list(ys.tolist() if hasattr(ys, "tolist") else ys), dtype=float)
    epsg = projection_epsg if projection_epsg in UTM_ZONES else None
    if epsg is None:
        d = diagnose(x, y, reference_bbox=reference_bbox)
        if d.get("kind") == "utm":
            epsg = d["epsg"]
    is_utm = np.asarray([point_kind(a, b) == "utm" for a, b in zip(x, y)])
    lon, lat = x.copy(), y.copy()
    if epsg is not None and is_utm.any():
        lon[is_utm], lat[is_utm] = utm_to_lonlat(x[is_utm], y[is_utm], epsg)
    return [(float(a), float(b), i + 1) for i, (a, b) in enumerate(zip(lon, lat)) if np.isfinite(a) and np.isfinite(b)]


# ── the coordinate system a template declares (VALIDATION_TRACKER.md, "Download data template") ──────────────────────────
CRS_COLUMN_NAMES = ("coordinate_system_epsg", "crs_epsg", "epsg", "crs", "coordinate_system")


def declared_system(df) -> Dict[str, Any]:
    """The coordinate system a file declares in its ``coordinate_system_epsg`` column (the templates make it required on every row).

    ``{"column", "epsg", "values", "mixed", "unsupported", "blank_rows"}``: ``epsg`` is the single supported code when every filled row says the same; ``mixed``
    is True when the rows disagree; ``unsupported`` lists codes we cannot read yet (Modified UTM among them); ``blank_rows`` are the spreadsheet rows that
    carry coordinates but no declaration. A file without the column gives ``column=None`` and the Add data dialog asks instead.
    """
    import re

    import pandas as pd

    from app.utils.number_format import normalize_nepali_digits

    out: Dict[str, Any] = {"column": None, "epsg": None, "values": [], "mixed": False, "unsupported": [], "blank_rows": []}
    lowered = {str(c).strip().lower(): c for c in df.columns}
    column = next((lowered[n] for n in CRS_COLUMN_NAMES if n in lowered), None)
    if column is None:
        return out
    out["column"] = str(column)
    codes: List[int] = []
    for cell in df[column].tolist():
        text = normalize_nepali_digits(cell).strip() if cell is not None and not (isinstance(cell, float) and np.isnan(cell)) else ""
        m = re.search(r"(\d{4,5})", text)
        codes.append(int(m.group(1)) if m else 0)
    filled = sorted({c for c in codes if c})
    out["values"] = filled
    out["mixed"] = len(filled) > 1
    out["unsupported"] = [c for c in filled if c not in SYSTEM_LABELS]
    if len(filled) == 1 and filled[0] in SYSTEM_LABELS:
        out["epsg"] = filled[0]
    lon_col, lat_col = None, None
    from app.services.upload.column_synonyms import coordinate_columns

    lon_col, lat_col = coordinate_columns(df.columns, "trees")
    if lon_col is not None and lat_col is not None:
        x, y = pd.to_numeric(df[lon_col], errors="coerce"), pd.to_numeric(df[lat_col], errors="coerce")
        out["blank_rows"] = [i + 2 for i, (a, b, c) in enumerate(zip(x, y, codes)) if pd.notna(a) and pd.notna(b) and not c][:50]
    return out
