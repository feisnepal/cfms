"""Forest Data Workbook — the one downloadable template.

Two forms, one contract: both are generated from the canonical :mod:`.schema`,
so the template a user fills and the validator that checks it can never drift.

    build_geopackage() -> bytes   # empty, correctly-typed layers, one per spatial purpose
    build_excel()      -> bytes   # one sheet per purpose + Instructions + a grey example row

UNIFIED_UPLOAD_PLAN.md §4.1.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

from . import schema
from .excel_rules import apply_workbook_validations

# ── pandas dtype for a schema column ───────────────────────────────────
_PANDAS_DTYPE = {
    "text": "object",
    "date": "object",
    "integer": "Int64",  # nullable — an empty template column has no rows anyway
    "number": "float64",
    "boolean": "object",
}

# ── schema geometry token → OGR geometry-type name pyogrio understands ──
_OGR_GEOM = {
    "POINT": "Point",
    "MULTIPOINT": "MultiPoint",
    "LINESTRING": "LineString",
    "MULTILINESTRING": "MultiLineString",
    "POLYGON": "Polygon",
    "MULTIPOLYGON": "MultiPolygon",
}
_GEOM_BASE = {
    "POINT": "point",
    "MULTIPOINT": "point",
    "LINESTRING": "line",
    "MULTILINESTRING": "line",
    "POLYGON": "polygon",
    "MULTIPOLYGON": "polygon",
}


def _ogr_geometry_type(purpose: schema.Purpose) -> str:
    """One concrete OGR type for the layer. A purpose that spans more than one
    base geometry (activities, water) gets an 'Unknown' generic layer."""
    bases = {_GEOM_BASE.get(t) for t in purpose.geometry_types}
    if len(bases) == 1:
        return _OGR_GEOM.get(purpose.geometry_types[0], "Unknown")
    return "Unknown"


def _header(col: schema.Column) -> str:
    """Column header for the Excel sheet — the name, with its unit appended when
    the name does not already carry it."""
    if col.unit and col.unit.lower() not in col.name.lower():
        short = col.unit.split("(")[0].strip()
        return f"{col.name} ({short})"
    return col.name


# ══════════════════════════════════════════════════════════════════════════
# GeoPackage
# ══════════════════════════════════════════════════════════════════════════
def build_geopackage() -> bytes:
    """An empty .gpkg: one correctly-typed layer per spatial purpose, named for
    its purpose. Households / field inventory are Excel-only (non-spatial / PII).
    """
    import geopandas as gpd  # noqa: PLC0415 — heavy, import on use
    import pandas as pd  # noqa: PLC0415
    import pyogrio  # noqa: PLC0415

    spatial = [p for p in schema.spatial() if p.geometry_types]
    tmpdir = tempfile.mkdtemp(prefix="fdw_")
    path = os.path.join(tmpdir, "Forest_Data_Workbook.gpkg")
    try:
        for i, purpose in enumerate(spatial):
            cols = {
                c.name: pd.Series([], dtype=_PANDAS_DTYPE.get(c.dtype, "object"))
                for c in purpose.columns
            }
            gdf = gpd.GeoDataFrame(
                {**cols, "geometry": gpd.GeoSeries([], crs="EPSG:4326")},
                crs="EPSG:4326",
            )
            pyogrio.write_dataframe(
                gdf,
                path,
                layer=purpose.layer_name,
                driver="GPKG",
                geometry_type=_ogr_geometry_type(purpose),
                append=i > 0,
            )
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════
# Excel workbook
# ══════════════════════════════════════════════════════════════════════════
_HEADER_FILL = "FF2E7D32"  # forest green
_REQUIRED_FILL = "FF1B5E20"  # darker green — a required column
_EXAMPLE_FILL = "FFEEEEEE"  # grey — the delete-me example row
_TITLE_FILL = "FFF4F3EF"


def build_excel() -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415
    from openpyxl.comments import Comment  # noqa: PLC0415
    from openpyxl.styles import Alignment, Font, PatternFill  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    wb = Workbook()
    wb.remove(wb.active)  # drop the default sheet

    _instructions_sheet(wb, Font, PatternFill, Alignment)

    for purpose in schema.ordered():
        ws = wb.create_sheet(title=purpose.layer_name[:31])
        cols = list(purpose.columns) or [
            schema.Column(
                "geometry_wkt", "text", description_en="Geometry as WKT (EPSG:4326)."
            )
        ]
        req_names = {
            r for rule in purpose.rules for r in rule.params.get("columns", [])
        }

        for c_idx, col in enumerate(cols, start=1):
            required = col.required or col.name in req_names
            cell = ws.cell(row=1, column=c_idx, value=_header(col))
            cell.font = Font(bold=True, color="FFFFFFFF", size=11)
            cell.fill = PatternFill(
                "solid", fgColor=_REQUIRED_FILL if required else _HEADER_FILL
            )
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.comment = Comment(_column_help(col, required), "Forest Data Workbook")
            ws.column_dimensions[get_column_letter(c_idx)].width = max(
                14, len(_header(col)) + 4
            )

            ex = "" if col.example is None else col.example
            ecell = ws.cell(row=2, column=c_idx, value=ex)
            ecell.fill = PatternFill("solid", fgColor=_EXAMPLE_FILL)
            ecell.font = Font(italic=True, color="FF888888")

        # the same limits the server refuses at: schema ranges / lists, and the shared rule table for the field-inventory sheet
        apply_workbook_validations(ws, purpose)

        ws.freeze_panes = "A2"
        ws.cell(
            row=4, column=1, value="↑ row 2 is an example — delete it before uploading"
        )
        ws.cell(row=4, column=1).font = Font(italic=True, color="FFAA0000", size=9)

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _column_help(col: schema.Column, required: bool) -> str:
    lines = [col.description_en or col.name]
    if col.description_ne:
        lines.append(col.description_ne)
    lines.append("Required" if required else "Optional")
    if col.enum:
        lines.append("Allowed: " + ", ".join(col.enum))
    if col.minimum is not None or col.maximum is not None:
        lo = "" if col.minimum is None else col.minimum
        hi = "" if col.maximum is None else col.maximum
        lines.append(f"Range: {lo}–{hi}" + (f" {col.unit}" if col.unit else ""))
    return "\n".join(str(x) for x in lines)


def _instructions_sheet(wb, Font, PatternFill, Alignment) -> None:
    ws = wb.create_sheet(title="Instructions")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 26
    ws.column_dimensions["C"].width = 60

    def row(r, *vals, bold=False, fill=None):
        for i, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=i, value=v)
            if bold:
                c.font = Font(bold=True)
            if fill:
                c.fill = PatternFill("solid", fgColor=fill)
            c.alignment = Alignment(vertical="top", wrap_text=(i == 3))

    row(1, "Forest Data Workbook", bold=True, fill=_TITLE_FILL)
    row(2, f"schema version {schema.SCHEMA_VERSION}")
    row(
        3,
        "How to use",
        "",
        "Fill in the sheets you have data for — you do not need them all. "
        "Row 2 of each sheet is a grey example; delete it before uploading. "
        "Upload the whole file back through “Add data”. The system sorts each "
        "sheet to its purpose by the sheet name.",
    )
    row(
        4,
        "Boundary first",
        "",
        "A forest must have a boundary before anything else can be attached. "
        "Fill the forest_boundary sheet (or upload a boundary) first; every "
        "other sheet is checked against it.",
    )
    row(
        5,
        "Errors vs warnings",
        "",
        "An error blocks that sheet from being saved; a warning is flagged on "
        "the row but lets it through. The review screen shows both before "
        "anything is committed.",
    )
    row(7, "Sheet", "Data", "Required columns", bold=True, fill=_TITLE_FILL)

    r = 8
    for p in schema.ordered():
        req = [c.name for c in p.columns if c.required] or ["—"]
        row(r, p.layer_name, p.label_en, ", ".join(req))
        r += 1

    ws.freeze_panes = "A8"
