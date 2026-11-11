"""Regression tests for the `metadata['blocks']` payload produced by
`process_geometry_list` for polygon/purpose-first imports.

These blocks are embedded in a `layer_metadata` JSONB column on the
`workspace_layers` table and in `result_data` JSONB on calculations. They
therefore MUST be fully JSON-serializable — a shapely object left bare inside
`geometry`/`centroid` raises `Object of type Polygon is not JSON serializable`
on flush (bug report 2026-08-05).
"""
import io
import json
import zipfile

import pytest
import shapefile
from fastapi import UploadFile
from shapely.geometry import Point, Polygon

from app.services.file_processor import process_uploaded_file, process_geometry_list
from app.core.constants import IMPORT_PURPOSE_BLOCKS


def _build_shp_zip_bytes(poly_coords) -> bytes:
    """Build an in-memory zipped ESRI shapefile (shp+shx+dbf) from one polygon."""
    shp_buf, shx_buf, dbf_buf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(
        shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shapefile.POLYGON
    ) as w:
        w.autoBalance = 1
        w.field("DELETION", "C")
        w.field("NAME", "C")
        w.record("N", "Block A")
        w.poly([poly_coords])

    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("block_a.shp", shp_buf.getvalue())
        zf.writestr("block_a.shx", shx_buf.getvalue())
        zf.writestr("block_a.dbf", dbf_buf.getvalue())
    return zbuf.getvalue()


def _assert_blocks_json_serializable(metadata: dict) -> None:
    assert "blocks" in metadata and isinstance(metadata["blocks"], list) and metadata["blocks"]
    # The defining regression: every block must round-trip through json.
    parsed = json.loads(json.dumps({"blocks": metadata["blocks"]}))
    block = parsed["blocks"][0]
    assert set(block) >= {"index", "name", "geometry", "area_sqm", "area_hectares", "centroid"}
    assert block["geometry"]["type"] == "Polygon"
    assert {"lon", "lat"} == set(block["centroid"])


def test_blocks_metadata_json_serializable_from_polygon():
    """Polygon purpose=blocks → metadata['blocks'] must be JSON-serializable."""
    poly = Polygon([(85.30, 27.60), (85.40, 27.60), (85.40, 27.70), (85.30, 27.70), (85.30, 27.60)])
    _, metadata = process_geometry_list([poly], [{"NAME": "Block A"}], purpose=IMPORT_PURPOSE_BLOCKS)
    _assert_blocks_json_serializable(metadata)


def test_blocks_metadata_json_serializable_from_point_auto_buffer():
    """Single point → auto-buffer polygon → JSON-serializable blocks."""
    _, metadata = process_geometry_list([Point(85.35, 27.65)], [{}], purpose=IMPORT_PURPOSE_BLOCKS)
    assert metadata.get("auto_buffered") is True
    _assert_blocks_json_serializable(metadata)


@pytest.mark.asyncio
async def test_shapefile_in_zip_yields_json_serializable_blocks():
    """End-to-end-ish: a zipped shapefile imported with purpose=blocks produces
    JSON-serializable block metadata (the exact regression from the bug report)."""
    poly_coords = [
        (85.30, 27.60), (85.40, 27.60), (85.40, 27.70), (85.30, 27.70), (85.30, 27.60),
    ]
    content = _build_shp_zip_bytes(poly_coords)
    upload = UploadFile(filename="sundar.zip", file=io.BytesIO(content))
    geometries, attributes, metadata = await process_uploaded_file(upload, purpose=IMPORT_PURPOSE_BLOCKS)
    _assert_blocks_json_serializable(metadata)
