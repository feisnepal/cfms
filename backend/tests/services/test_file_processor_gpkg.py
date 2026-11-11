"""Phase U-3 tests — GeoPackage reader (Task 3.1).

Covers:
- Task 3.0: pyogrio preferred backend chosen (documented in plan).
- Task 3.1: .gpkg parses layers -> geometries + attributes + CRS;
  magic-byte check rejects non-GPKG files; empty geometry rows skipped.
"""
import os
import tempfile

import geopandas
import pytest
from shapely.geometry import Polygon, Point, LineString

from app.services.file_processor import (
    read_geopackage,
    _is_geopackage,
)


def _write_gpkg(layer_name, gdf, filepath):
    gdf.to_file(filepath, layer=layer_name, driver="GPKG")
    return filepath


def test_gpkg_read_polygon_layer():
    """Task 3.1: a polygon GPKG layer reads into (geoms, attrs, CRS)."""
    gdf = geopandas.GeoDataFrame(
        {
            "name": ["A", "B"],
            "area_ha": [1.0, 2.5],
            "geometry": [
                Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                Polygon([(2, 2), (2, 3), (3, 3), (3, 2)]),
            ],
        },
        crs="EPSG:4326",
    )
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "test.gpkg")
        _write_gpkg("polygons", gdf, p)

        geoms, attrs, crs = read_geopackage(p)
        assert len(geoms) == 2
        assert all(isinstance(g, Polygon) for g in geoms)
        assert attrs[0]["name"] == "A"
        assert attrs[1]["area_ha"] == 2.5
        assert crs.to_epsg() == 4326


def test_gpkg_read_point_and_line_layer():
    """Task 3.1: point and line GPKG layers parse correctly."""
    gdf = geopandas.GeoDataFrame(
        {
            "geometry": [
                Point(10, 20),
                Point(30, 40),
            ]
        },
        crs="EPSG:4326",
    )
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "pts.gpkg")
        _write_gpkg("points", gdf, p)
        geoms, attrs, crs = read_geopackage(p)
        assert len(geoms) == 2
        assert all(isinstance(g, Point) for g in geoms)
        assert crs.to_epsg() == 4326

    gdf_l = geopandas.GeoDataFrame(
        {"geometry": [LineString([(0, 0), (1, 1), (2, 0)])]},
        crs="EPSG:4326",
    )
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "lines.gpkg")
        _write_gpkg("lines", gdf_l, p)
        geoms, _, _ = read_geopackage(p)
        assert len(geoms) == 1
        assert isinstance(geoms[0], LineString)


def test_gpkg_magic_byte_rejects_non_gpkg():
    """Task 3.1: non-GPKG file fails the magic-byte check."""
    assert not _is_geopackage(__file__)  # a .py file is not a GPKG


def test_gpkg_read_skips_empty_geometries():
    """Task 3.1: rows with empty/missing geometry are skipped, not errored."""
    gdf = geopandas.GeoDataFrame(
        {
            "name": ["ok", "bad", "ok2"],
            "geometry": [
                Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]),
                None,
                Point(5, 5),
            ],
        },
        crs="EPSG:4326",
    )
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "mixed.gpkg")
        _write_gpkg("mixed", gdf, p)
        geoms, attrs, _ = read_geopackage(p)
        assert len(geoms) == 2
        assert attrs[0]["name"] == "ok"
        assert attrs[1]["name"] == "ok2"


def test_gpkg_read_empty_file_raises():
    """Task 3.1: a GPKG with no readable features raises a clear error."""
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "empty.gpkg")
        with open(p, "wb") as f:
            f.write(b"SQLite format 3\x00")
            f.write(b"\x00" * 52)
            f.write(b"GPKG")
        with pytest.raises(ValueError, match="no readable features"):
            read_geopackage(p)
