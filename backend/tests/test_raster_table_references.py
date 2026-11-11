"""Raster-table references must resolve, and slope/aspect must come from the
cooked class rasters — never from the DEM.

Why this file exists
--------------------
`rasters.slope` was dropped (owner notice, 2026-09-29) while five call sites
still named it, so the raster-click query, the steep-slope mask, two
`analysis.py` slope histograms and `map_generator` all began to fail — and
every existing test stayed green, because none of them touched a live raster.

Owner rules encoded here (2026-09-29):
  * `rasters.slope_regulation` is the only slope-class table.
  * `rasters.aspect` is the aspect table.
  * Slope and aspect are read from those prepared rasters. Do **not** derive a
    slope surface from the DEM with `ST_Slope` in the raster-display path.

`rasters.slope_regulation` is 1-band 8BUI with nodata 0 holding class codes
1-4 (bands in `core/constants.py`), so a `ST_Value` on it is a CLASS. It is not
a degree value and must never be reported as one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.core.database import engine

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# FROM/JOIN rasters.<ident>
_SQL_REF = re.compile(r"\b(?:FROM|JOIN)\s+rasters\.([a-z0-9_]+)", re.IGNORECASE)

# Real rasters.* tables that are deliberately outside the tile catalog. Adding
# an entry here is a deliberate act; every other table must be in the catalog.
_EXTRA_KNOWN = {"hansen2000_classified"}


def _sql_refs() -> dict[str, list[str]]:
    """Table references only — `rasters.some_function(...)` is a PostGIS set-
    returning function (user_group_analysis.py), not a table."""
    found: dict[str, list[str]] = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        for i, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for m in _SQL_REF.finditer(line):
                if line[m.end() :].lstrip().startswith("("):
                    continue
                found.setdefault(m.group(1), []).append(f"{path.name}:{i}")
    return found


def test_every_sql_raster_reference_is_a_known_table():
    """A FROM/JOIN on rasters.X must name the catalog or a documented extra.

    Ratchet: introducing a raster table reference means adding it to
    `_EXTRA_KNOWN` in the same commit, so a dropped or misspelt table cannot
    reach production quietly.
    """
    from app.services.tile_service import TileService

    catalog = {v.split(".")[-1] for v in TileService.RASTER_TABLES.values()}
    refs = _sql_refs()
    unknown = sorted(set(refs) - catalog - _EXTRA_KNOWN)
    assert not unknown, (
        "SQL references rasters.<table> that is neither in TileService."
        "RASTER_TABLES nor _EXTRA_KNOWN: " + ", ".join(unknown)
    )


def test_the_deleted_slope_table_is_never_referenced():
    """rasters.slope is gone; any surviving SQL reference is dead code."""
    offenders = _sql_refs().get("slope", [])
    assert not offenders, f"rasters.slope referenced in SQL: {offenders}"


def test_slope_and_aspect_come_from_the_cooked_rasters():
    """Owner rule: read the prepared class rasters, do not derive from the DEM."""
    tiles_src = (APP_ROOT / "api" / "tiles.py").read_text(encoding="utf-8")
    assert "rasters.slope_regulation" in tiles_src
    assert "rasters.aspect" in tiles_src
    assert "ST_Slope(" not in tiles_src, (
        "api/tiles.py must not derive slope from the DEM (owner decision "
        "2026-09-29); read rasters.slope_regulation"
    )


def test_click_info_does_not_report_a_class_as_degrees():
    """The click payload used to send `slope_degrees` holding a 1-4 class code,
    which the UI rendered with a degree sign."""
    tiles_src = (APP_ROOT / "api" / "tiles.py").read_text(encoding="utf-8")
    assert '"slope_degrees"' not in tiles_src
    for field in ("slope_class", "slope_class_label", "slope_class_range", "slope_is_nodata"):
        assert f'"{field}"' in tiles_src, f"{field} missing from the click payload"


def test_slope_class_names_and_zonal_keys_agree():
    """constants owns the display names; raster_zonal owns the lowercase data
    keys. They must not drift into two different orderings."""
    from app.core.constants import SLOPE_CLASS_BANDS, SLOPE_CLASS_NAMES
    from app.services.operational_plan.raster_zonal import SLOPE_LABELS

    assert sorted(SLOPE_CLASS_NAMES) == [1, 2, 3, 4]
    assert sorted(SLOPE_CLASS_BANDS) == [1, 2, 3, 4]
    assert sorted(SLOPE_LABELS) == [1, 2, 3, 4]
    for code, (en, _np) in SLOPE_CLASS_NAMES.items():
        # data keys use underscores, display names use spaces
        assert en.lower().replace(" ", "_") == SLOPE_LABELS[code]
        assert SLOPE_CLASS_BANDS[code]


def test_slope_class_bands_follow_the_documented_thresholds():
    from app.core.constants import (
        SLOPE_CLASS_BANDS,
        SLOPE_GENTLE_MAX_DEG,
        SLOPE_MODERATE_MAX_DEG,
        SLOPE_STEEP_MAX_DEG,
    )

    assert SLOPE_CLASS_BANDS[1].startswith("0-")
    assert SLOPE_CLASS_BANDS[1].endswith(f"{SLOPE_GENTLE_MAX_DEG:g}°")
    assert SLOPE_CLASS_BANDS[2].startswith(f"{SLOPE_GENTLE_MAX_DEG:g}-")
    assert SLOPE_CLASS_BANDS[2].endswith(f"{SLOPE_MODERATE_MAX_DEG:g}°")
    assert SLOPE_CLASS_BANDS[3].startswith(f"{SLOPE_MODERATE_MAX_DEG:g}-")
    assert SLOPE_CLASS_BANDS[3].endswith(f"{SLOPE_STEEP_MAX_DEG:g}°")
    assert SLOPE_CLASS_BANDS[4] == f">{SLOPE_STEEP_MAX_DEG:g}°"


# ── live metadata gate (skipped where the rasters schema is absent) ─────
def _live_raster_tables() -> set[str] | None:
    with engine.connect() as cx:
        rows = cx.execute(
            sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='rasters' AND table_type='BASE TABLE'"
            )
        ).fetchall()
    return {r[0] for r in rows} or None


def test_catalog_tables_exist_and_metadata_is_as_documented():
    live = _live_raster_tables()
    if live is None:
        pytest.skip("no rasters schema in this database (test DB)")
    with engine.connect() as cx:
        row = cx.execute(
            sa.text(
                "SELECT num_bands, pixel_types, nodata_values FROM raster_columns "
                "WHERE r_table_schema='rasters' AND r_table_name='slope_regulation'"
            )
        ).first()
        assert row is not None, "rasters.slope_regulation is not registered"
        num_bands, pixel_types, nodata_values = row
        assert num_bands == 1
        assert "8BUI" in pixel_types[0], f"expected a uint8 class raster, got {pixel_types}"
        assert float(nodata_values[0]) == 0.0

        vals = cx.execute(
            sa.text(
                "SELECT DISTINCT (pvc).value::int FROM ("
                "  SELECT ST_ValueCount(rast,1) pvc FROM rasters.slope_regulation"
                ") s WHERE (pvc).value IS NOT NULL ORDER BY 1"
            )
        ).fetchall()
    assert {v[0] for v in vals} == {1, 2, 3, 4}, (
        "slope_regulation is no longer a 1-4 class raster — every "
        "'this is a class, not degrees' assumption in the codebase needs review"
    )

    from app.services.tile_service import TileService

    missing = sorted(
        t for t in TileService.RASTER_TABLES.values() if t.split(".")[-1] not in live
    )
    assert not missing, f"catalog keys with no table: {missing}"
