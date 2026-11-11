"""The compartment export must produce a real GeoPackage, not a quiet GeoJSON.

`fiona` carried a CRITICAL (CVE-2023-45853, bundled MiniZip) and a HIGH, and
this endpoint was its only use anywhere in the codebase. It is now written with
`pyogrio` -- geopandas' default engine, already a dependency, same GDAL
underneath -- and fiona is gone from requirements.in entirely. That removes the
finding permanently rather than chasing the next advisory.

Why this file exists at all
---------------------------
The endpoint wraps the write in `except Exception` and falls back to writing
GeoJSON with a `.geojson` name. That fallback is deliberate and worth keeping --
a degraded export beats a 500 -- but it means a broken writer does NOT surface
as an error. The caller still gets 200. They simply receive a different file
format than the one they asked for, and the only signal is the extension.

So the risky option here was the obvious one: bumping fiona to 1.10.x. Its
`fiona.crs.from_epsg` was already deprecated, and had it been removed the call
would have raised straight into that fallback and every GPKG export would have
silently become GeoJSON, with a green test suite throughout. There was no test
covering this endpoint at all.

These tests exercise `write_blocks_gpkg` directly, deliberately bypassing the
fallback, so a failure is a failure rather than a format change.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.api.compartments import GPKG_FIELDS, write_blocks_gpkg


def _feature(**overrides):
    props = {
        "id": "11111111-1111-1111-1111-111111111111",
        "block_name": "Block 1",
        "parent_block_name": "",
        "is_compartment": 0,
        "compartment_code": "",
        "area_sqm": 123456.75,
        "area_hectares": 12.345675,
        "perimeter_m": 1420.5,
        "tree_count": 12,
        "mother_tree": 3,
        "felling_tree": 1,
        "regeneration": 40,
        "sapling": 22,
        "small_pole": 5,
        "large_pole": 6,
        "small_tree": 7,
        "medium_tree": 8,
        "large_tree": 9,
        "very_large_tree": 2,
        "index": 1,
        "created_at": "2026-08-25T00:00:00",
    }
    props.update(overrides)
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [85.30, 27.70], [85.31, 27.70],
                [85.31, 27.71], [85.30, 27.71], [85.30, 27.70],
            ]],
        },
        "properties": props,
    }


def test_the_file_is_actually_a_geopackage(tmp_path: Path) -> None:
    """The whole point. A GeoPackage is a SQLite database with a known
    application_id; a GeoJSON fallback would start with '{'."""
    out = tmp_path / "blocks.gpkg"
    write_blocks_gpkg([_feature()], str(out))

    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:16].startswith(b"SQLite format 3"), (
        "Not a SQLite container -- the GeoJSON fallback probably ran"
    )

    with sqlite3.connect(out) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "gpkg_contents" in tables, f"No GeoPackage metadata table: {sorted(tables)}"


def test_every_declared_column_survives_the_write(tmp_path: Path) -> None:
    """The short names are the export's public contract."""
    import geopandas as gpd

    out = tmp_path / "blocks.gpkg"
    write_blocks_gpkg([_feature()], str(out))

    written = gpd.read_file(out, engine="pyogrio")
    for column, _key, _cast in GPKG_FIELDS:
        assert column in written.columns, f"{column} missing from the export"


def test_integer_columns_do_not_become_floats(tmp_path: Path) -> None:
    """A None in an integer column makes pandas widen the whole column to
    float, so `tree_count` comes back as 12.0. fiona could not do this because
    its schema declared the types; the explicit coercion replaces that."""
    import geopandas as gpd

    out = tmp_path / "blocks.gpkg"
    write_blocks_gpkg([_feature(), _feature(tree_count=None, mother_tree=None)], str(out))

    written = gpd.read_file(out, engine="pyogrio")
    assert str(written["tree_count"].dtype).startswith("int"), (
        f"tree_count came back as {written['tree_count'].dtype}"
    )
    assert written["tree_count"].tolist() == [12, 0]


def test_geometry_and_crs_are_preserved(tmp_path: Path) -> None:
    import geopandas as gpd

    out = tmp_path / "blocks.gpkg"
    write_blocks_gpkg([_feature()], str(out))

    written = gpd.read_file(out, engine="pyogrio")
    assert written.crs is not None and written.crs.to_epsg() == 4326
    assert written.geometry.iloc[0].geom_type == "Polygon"
    # Coordinates are lon/lat around Kathmandu; a swapped axis order would
    # put this in the Indian Ocean.
    minx, miny, _maxx, _maxy = written.total_bounds
    assert 85.0 < minx < 86.0 and 27.0 < miny < 28.0


def test_fiona_is_not_imported_anywhere_in_the_app() -> None:
    """The dependency is removed, so an import of it would break the build
    rather than fall back -- and would reintroduce the CVE if re-added."""
    import ast

    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[0] == "fiona" for a in node.names):
                    offenders.append(f"{path.name}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == "fiona":
                    offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        "fiona is imported again: " + ", ".join(offenders)
        + ". It was removed for CVE-2023-45853; use pyogrio."
    )
