"""Forest Data Workbook generator + the /uploads endpoints (UNIFIED_UPLOAD_PLAN §4.1).

Both template forms are built from the canonical schema; these tests pin that the
sheet / layer names match the schema, required columns are present, and the
download endpoints serve the right bytes with the right headers.
"""

from __future__ import annotations

import io
import os
import tempfile

from app.services.upload import schema
from app.services.upload.workbook import build_excel, build_geopackage


# ── Excel ──────────────────────────────────────────────────────────────
def test_excel_has_one_sheet_per_purpose_plus_instructions():
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(build_excel()))
    assert wb.sheetnames[0] == "Instructions"
    assert wb.sheetnames[1:] == [p.layer_name for p in schema.ordered()]


def test_excel_headers_cover_every_schema_column_and_carry_an_example():
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(build_excel()))
    for purpose in schema.ordered():
        if not purpose.columns:
            continue
        ws = wb[purpose.layer_name]
        headers = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column + 1)]
        for col in purpose.columns:
            assert any(
                h == col.name or h.startswith(col.name + " ") for h in headers
            ), f"{purpose.id}: no header for column {col.name!r} in {headers}"
        # the example row exists (row 2) and at least one required col is filled
        row2 = [ws.cell(row=2, column=i).value for i in range(1, ws.max_column + 1)]
        if any(c.example is not None for c in purpose.columns):
            assert any(v not in (None, "") for v in row2)


def test_excel_instructions_sheet_lists_every_purpose():
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(build_excel()))["Instructions"]
    text = "\n".join(
        str(c.value) for r in ws.iter_rows() for c in r if c.value is not None
    )
    assert schema.SCHEMA_VERSION in text
    for p in schema.ordered():
        assert p.layer_name in text


# ── GeoPackage ─────────────────────────────────────────────────────────
def test_geopackage_layers_match_the_spatial_purposes():
    import pyogrio

    body = build_geopackage()
    assert body[:16].startswith(b"SQLite format 3")

    d = tempfile.mkdtemp()
    path = os.path.join(d, "wb.gpkg")
    with open(path, "wb") as fh:
        fh.write(body)

    layers = {name for name, _ in pyogrio.list_layers(path).tolist()}
    expected = {p.layer_name for p in schema.spatial() if p.geometry_types}
    assert layers == expected
    # households is Excel-only
    assert "households" not in layers

    for purpose in schema.spatial():
        if not purpose.geometry_types:
            continue
        info = pyogrio.read_info(path, layer=purpose.layer_name)
        assert info["features"] == 0
        assert set(info["fields"]) == {c.name for c in purpose.columns}


def test_geopackage_geometry_types_are_sane():
    import pyogrio

    d = tempfile.mkdtemp()
    path = os.path.join(d, "wb.gpkg")
    with open(path, "wb") as fh:
        fh.write(build_geopackage())
    types = dict(pyogrio.list_layers(path).tolist())
    assert types["forest_boundary"] == "Polygon"
    assert types["blocks"] == "Polygon"
    assert types["trees"] == "Point"
    assert types["roads"] == "LineString"
    # mixed-base purposes fall back to a generic layer
    assert types["activities"] == "Unknown"


# ── endpoints ──────────────────────────────────────────────────────────
def test_workbook_endpoint_defaults_to_xlsx(client, auth_headers):
    r = client.get("/api/v1/uploads/workbook", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert (
        r.headers["content-type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert ".xlsx" in r.headers["content-disposition"]
    assert r.content[:2] == b"PK"  # zip container


def test_workbook_endpoint_gpkg(client, auth_headers):
    r = client.get(
        "/api/v1/uploads/workbook", params={"format": "gpkg"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/geopackage+sqlite3"
    assert ".gpkg" in r.headers["content-disposition"]
    assert r.content[:16].startswith(b"SQLite format 3")


def test_workbook_endpoint_rejects_unknown_format(client, auth_headers):
    r = client.get(
        "/api/v1/uploads/workbook", params={"format": "pdf"}, headers=auth_headers
    )
    assert r.status_code == 422


def test_workbook_endpoint_requires_auth(client):
    assert client.get("/api/v1/uploads/workbook").status_code == 401


def test_schema_endpoint_returns_the_canonical_schema(client, auth_headers):
    r = client.get("/api/v1/uploads/schema", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == schema.SCHEMA_VERSION
    assert body["purposes"][0]["id"] == "forest_boundary"
    assert len(body["purposes"]) == len(schema.PURPOSES)
