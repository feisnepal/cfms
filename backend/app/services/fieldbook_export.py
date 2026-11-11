"""Field book exports: CSV, Excel, GPX and GeoJSON -- one row definition, four ways to show it.

Every value comes from ``fieldbook_record.point_record`` (and the nearest ridge/river from ``topography_for``), so the
four files cannot disagree: the same label, the same remark, the same numbers to the same decimals. A format only
decides how a value is displayed (a CSV cell, an Excel cell, a GeoJSON property, a line of GPX text) and what it can
hold (GPX has no UTM columns; CSV has no geometry).

``services/export.py`` re-exports these, so existing imports keep working.
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List
from uuid import UUID
from xml.etree import ElementTree as ET

from sqlalchemy.orm import Session

from app.models.fieldbook import Fieldbook
from app.services.fieldbook_lines import lines_from_points
from app.services.fieldbook_record import COLUMNS, HEADERS, KEYS, PLACES, csv_text, point_label, point_record, topography_for


def _load(db: Session, calculation_id: UUID) -> List[Fieldbook]:
    from app.services.export import _rollback_quietly

    _rollback_quietly(db)   # a failed earlier query must not poison this export
    points = (
        db.query(Fieldbook).filter(Fieldbook.calculation_id == calculation_id).order_by(Fieldbook.point_number).all()
    )
    if not points:
        raise ValueError("No fieldbook points found for this calculation")
    return points


def _records(db: Session, calculation_id: UUID, points: List[Fieldbook]) -> List[Dict[str, Any]]:
    topo = topography_for(db, calculation_id, points)
    return [point_record(p, topo.get(p.id)) for p in points]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def export_fieldbook_csv(db: Session, calculation_id: UUID) -> bytes:
    """One row per point, the canonical columns in reading order."""
    from app.services.export import _safe_string

    points = _load(db, calculation_id)
    records = _records(db, calculation_id, points)

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADERS)
    for rec in records:
        writer.writerow([
            _safe_string(csv_text(k, rec[k])) if isinstance(rec[k], str) else csv_text(k, rec[k]) for k in KEYS
        ])
    return out.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------

def export_fieldbook_excel(db: Session, calculation_id: UUID) -> bytes:
    """Sheets: Summary | Points | Lines | Junctions (the last two only when there is something to list)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from app.services.export import _safe_string

    points = _load(db, calculation_id)
    records = _records(db, calculation_id, points)

    def header_row(ws, headers, fill):
        for col, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color=fill, end_color=fill, fill_type="solid")
            cell.alignment = Alignment(horizontal="center")

    def cell_value(key, value):
        if value is None:
            return ""
        return _safe_string(value) if isinstance(value, str) else value

    wb = Workbook()

    # ---- Summary
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Fieldbook Summary"
    ws["A1"].font = Font(size=14, bold=True)
    outer = [p for p in points if p.boundary_class == "outer"]
    elevations = [float(p.elevation) for p in points if p.elevation is not None]
    summary = [
        ["Total Points", len(points)],
        ["Outer boundary points (O)", len(outer)],
        ["Internal boundary points (I)", sum(1 for p in points if p.boundary_class == "internal")],
        ["Junction points", sum(1 for p in points if p.is_junction)],
        ["Vertices", sum(1 for p in points if p.point_type == "vertex")],
        ["Interpolated Points", sum(1 for p in points if p.point_type == "interpolated")],
        # The forest's outer boundary length. (Summing every point's distance_to_next would also count each internal
        # edge, and the old per-unit total counted every shared edge twice.)
        ["Outer Perimeter (m)", sum(float(p.distance_to_next or 0) for p in (outer or points))],
        ["Min Elevation (m)", min(elevations) if elevations else None],
        ["Max Elevation (m)", max(elevations) if elevations else None],
        ["Avg Elevation (m)", sum(elevations) / len(elevations) if elevations else None],
        ["Verified Points", sum(1 for p in points if p.is_verified)],
    ]
    for i, (label, value) in enumerate(summary, start=3):
        ws[f"A{i}"] = label
        ws[f"A{i}"].font = Font(bold=True)
        if value is not None:
            ws[f"B{i}"] = round(value, 2) if isinstance(value, float) else value

    # ---- Points
    ws_points = wb.create_sheet("Points")
    header_row(ws_points, HEADERS, "CCCCCC")
    for row, (p, rec) in enumerate(zip(points, records), start=2):
        for col, key in enumerate(KEYS, start=1):
            ws_points.cell(row=row, column=col, value=cell_value(key, rec[key]))
        # verified = green, a junction = amber, an outer-boundary point = pale blue
        fill = "C6EFCE" if p.is_verified else "FFE699" if p.is_junction else "DDEBF7" if p.boundary_class == "outer" else None
        if fill:
            for col in range(1, len(KEYS) + 1):
                ws_points.cell(row=row, column=col).fill = PatternFill(start_color=fill, end_color=fill, fill_type="solid")
    for col in range(1, len(KEYS) + 1):
        ws_points.column_dimensions[get_column_letter(col)].width = 15
    ws_points.column_dimensions[get_column_letter(KEYS.index("remarks") + 1)].width = 40
    ws_points.freeze_panes = "B2"
    ws_points.auto_filter.ref = f"A1:{get_column_letter(len(KEYS))}{len(points) + 1}"

    # ---- Lines: how the points group. An outer ring is CLOSED (it draws as a polygon outline); every internal edge is
    # OPEN -- never closed, never joined to another edge, even though the I-numbers run on from one edge to the next.
    book_lines = lines_from_points(points)
    if book_lines:
        ws_l = wb.create_sheet("Lines")
        l_headers = [
            "रेखा (Line)", "प्रकार (Kind)", "बन्द / खुला (Closed / Open)", "बिन्दु संख्या (Points)",
            "लम्बाइ मि. (Length m)", "पहिलो (First)", "अन्तिम (Last)", "बिन्दुक्रम (Point sequence)",
        ]
        header_row(ws_l, l_headers, "DDEBF7")
        for r, ln in enumerate(book_lines, start=2):
            seq = " → ".join(ln["labels"] + ([ln["labels"][0]] if ln["closed"] and ln["labels"] else []))
            for col, value in enumerate([
                ln["id"], "outer ring" if ln["kind"] == "outer" else "internal",
                "closed (polygon outline)" if ln["closed"] else "open (not closed)",
                len(ln["labels"]), ln["length_m"],
                ln["labels"][0] if ln["labels"] else "", ln["labels"][-1] if ln["labels"] else "", seq,
            ], start=1):
                ws_l.cell(row=r, column=col, value=value)
        for col in range(1, len(l_headers) + 1):
            ws_l.column_dimensions[get_column_letter(col)].width = 80 if col == len(l_headers) else 22
        ws_l.freeze_panes = "A2"

    # ---- Junctions: only the points where three or more regions meet -- the ones a surveyor most wants to find
    junction_idx = [i for i, p in enumerate(points) if p.is_junction]
    if junction_idx:
        ws_j = wb.create_sheet("Junctions")
        j_keys = ["point", "boundary", "junction", "remarks", "latitude", "longitude"]
        header_row(ws_j, [dict(COLUMNS)[k] for k in j_keys], "FFE699")
        for r, i in enumerate(junction_idx, start=2):
            for col, key in enumerate(j_keys, start=1):
                ws_j.cell(row=r, column=col, value=cell_value(key, records[i][key]))
        for col in range(1, len(j_keys) + 1):
            ws_j.column_dimensions[get_column_letter(col)].width = 40 if j_keys[col - 1] == "remarks" else 16

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out.read()


# ---------------------------------------------------------------------------
# GPX
# ---------------------------------------------------------------------------

def _gpx_description(rec: Dict[str, Any]) -> str:
    """The point's record as one line of text (GPX has a name, an elevation and a free-text description)."""
    parts: List[str] = []
    if rec["remarks"]:
        parts.append(rec["remarks"])
    if rec["sub_area"]:
        parts.append(f"Sub-area: {rec['sub_area']}")
        if rec["sub_area_category"]:
            parts.append(f"Category: {rec['sub_area_category']}")
        if rec["excluded"] == "Yes":
            parts.append("Type: Excluded Zone (Private Land)")
    if rec["line"]:
        parts.append(f"Line: {rec['line']}")
    if rec["next_point"]:
        parts.append(f"Next: {rec['next_point']}")
    if rec["azimuth"] is not None:
        parts.append(f"Azimuth: {rec['azimuth']:.2f}°")
    if rec["distance"] is not None:
        parts.append(f"Distance: {rec['distance']:.2f}m")
    if rec["nearest_feature"]:
        near = f"Nearest: {rec['nearest_feature']}"
        if rec["nearest_feature_type"]:
            near += f" ({rec['nearest_feature_type']})"
        if rec["nearest_feature_distance_m"] is not None:
            near += f", {rec['nearest_feature_distance_m']}m"
        if rec["nearest_feature_direction"]:
            near += f" {rec['nearest_feature_direction']}"
        parts.append(near)
    if rec["verified"] == "Yes":
        parts.append("Verified")
    return " | ".join(parts)


def export_fieldbook_gpx(db: Session, calculation_id: UUID) -> bytes:
    """Waypoints (one per point) then one route per line. A closed line repeats its first point at the end so a GPS app
    draws the outline closed; an internal edge is left open."""
    points = _load(db, calculation_id)
    records = _records(db, calculation_id, points)

    gpx = ET.Element("gpx", {
        "version": "1.1",
        "creator": "Community Forest Management System",
        "xmlns": "http://www.topografix.com/GPX/1/1",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd",
    })
    metadata = ET.SubElement(gpx, "metadata")
    ET.SubElement(metadata, "name").text = f"Fieldbook - Calculation {calculation_id}"
    ET.SubElement(metadata, "desc").text = f"Boundary fieldbook with {len(points)} points"

    for rec in records:
        if rec["latitude"] is None or rec["longitude"] is None:
            continue
        wpt = ET.SubElement(gpx, "wpt", {"lat": f"{rec['latitude']:.{PLACES['latitude']}f}", "lon": f"{rec['longitude']:.{PLACES['longitude']}f}"})
        ET.SubElement(wpt, "name").text = rec["point"]
        ET.SubElement(wpt, "type").text = rec["type"]
        if rec["elevation"] is not None:
            ET.SubElement(wpt, "ele").text = f"{rec['elevation']:.2f}"
        desc = _gpx_description(rec)
        if desc:
            ET.SubElement(wpt, "desc").text = desc

    for ln in lines_from_points(points):
        rte = ET.SubElement(gpx, "rte")
        ET.SubElement(rte, "name").text = ln["id"]
        kind = "outer ring (closed)" if ln["kind"] == "outer" else "loop (closed)" if ln["closed"] else "internal edge (open)"
        ET.SubElement(rte, "desc").text = f"{kind} - {len(ln['labels'])} points, {ln['length_m']:.0f} m"
        for lon, lat in ln["coordinates"]:
            ET.SubElement(rte, "rtept", {"lat": f"{lat:.7f}", "lon": f"{lon:.7f}"})

    out = io.BytesIO()
    ET.ElementTree(gpx).write(out, encoding="utf-8", xml_declaration=True)
    out.seek(0)
    return out.read()


# ---------------------------------------------------------------------------
# GeoJSON
# ---------------------------------------------------------------------------

def export_fieldbook_geojson(db: Session, calculation_id: UUID) -> Dict[str, Any]:
    """Point features carrying the canonical row as properties, then the lines joining them.

    ``properties.layer`` tells them apart: ``"point"`` or ``"line"``. An outer ring is a CLOSED LineString (first
    coordinate repeated last): it draws as a polygon outline. An internal edge is an OPEN LineString.
    Coordinates are [longitude, latitude] (RFC 7946).
    """
    points = _load(db, calculation_id)
    records = _records(db, calculation_id, points)

    features: List[Dict[str, Any]] = []
    for p, rec in zip(points, records):
        if rec["latitude"] is None or rec["longitude"] is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [rec["longitude"], rec["latitude"]]},
            "properties": {"layer": "point", "point_number": p.point_number, **{k: rec[k] for k in KEYS}},
        })

    for ln in lines_from_points(points):
        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": ln["coordinates"]},
            "properties": {
                "layer": "line",
                "line_id": ln["id"],
                "kind": ln["kind"],
                "closed": ln["closed"],
                "point_labels": ln["labels"],
                "length_m": ln["length_m"],
            },
        })

    return {"type": "FeatureCollection", "features": features}
