"""P6z — S9 physiography: per-unit zonal statistics over the rasters.* tables.

Pure part (fixture render + spec shape) runs with ``--noconftest``. The
DB-backed part exercises ``raster_zonal`` SQL against a real forest with blocks
and is skipped when no such forest / raster coverage exists.
"""

import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan import _thememap_fixture as fx  # noqa: E402
from app.services.operational_plan import raster_zonal as rz  # noqa: E402
from app.services.operational_plan.thematic_map_spec import (  # noqa: E402
    BUILTIN_THEMEMAP_SPECS,
)
from app.services.operational_plan.thematic_overlay import (
    render_from_fixture,
)  # noqa: E402

_S9_REAL = [
    "zone__elevation_mean",
    "zone__elevation_range",
    "zone__slope_mean",
    "zone__slope_dominant",
    "zone__slope_class__stackbar",
    "zone__aspect_dominant",
    "zone__aspect__rose",
    "zone__canopy_mean",
    "zone__biomass_raster_mean",
    "zone__landcover_dominant",
    "zone__landcover__pie",
    "zone__forest_type_dominant",
    "vector__slope_aspect",
]
# now wired to real vector layers (river.river84 / infrastructure.road)
_S9_WIRED = {
    "zone__accessibility": ("raster_zonal", ["roads"]),
    "forest__drainage_vectors": ("geometry", ["hydro"]),
    "zone__forest_health": ("raster_zonal", ["raster_zonal"]),
    # RUSLE soil-loss — computed raster surface, DEM + soil prereqs
    "soil__annual_loss": ("soil_grid", ["raster_zonal", "soil_data"]),
    "soil__annual_loss__user_group": (
        "soil_grid",
        ["raster_zonal", "soil_data", "user_group_extent"],
    ),
    "soil__factor_r": ("soil_grid", ["raster_zonal", "soil_data"]),
    "soil__factor_k": ("soil_grid", ["raster_zonal", "soil_data"]),
    "soil__factor_ls": ("soil_grid", ["raster_zonal", "soil_data"]),
    "soil__factor_c": ("soil_grid", ["raster_zonal", "soil_data"]),
    # P4 — landslide hazard + household vulnerability, computed surfaces
    "hazard__landslide_susceptibility": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__landslide_susceptibility__user_group": (
        "hazard_grid",
        ["raster_zonal", "geology", "user_group_extent"],
    ),
    "hazard__landslide_prone_area": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__factor_of_safety": ("hazard_grid", ["raster_zonal", "soil_data"]),
    "hazard__factor_of_safety__user_group": (
        "hazard_grid",
        ["raster_zonal", "soil_data", "user_group_extent"],
    ),
    "hazard__lsi_factor_slope": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_lithology": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_curvature_twi": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_dist_drainage": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_dist_road": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_landcover": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_landcover_change": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_aspect": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_rainfall": ("hazard_grid", ["raster_zonal", "geology"]),
    "hazard__lsi_factor_soil_texture": ("hazard_grid", ["raster_zonal", "geology"]),
    "hh__vulnerability": ("hazard_grid", ["household_data"]),
    "hh__vulnerability__user_group": (
        "hazard_grid",
        ["household_data", "user_group_extent"],
    ),
    "hh__priority_settlements": (
        "hazard_grid",
        ["household_data", "user_group_extent"],
    ),
}


def test_s9_specs_are_registered_with_the_right_source_and_section():
    for k in _S9_REAL:
        s = BUILTIN_THEMEMAP_SPECS[k]
        assert s.section == "S9", k
        assert s.source == "raster_zonal", k
        assert s.requires == ["raster_zonal"], k


def test_s9_wired_specs_have_a_real_prereq_and_source():
    from app.services.operational_plan import prereq_check

    for k, (src, reqs) in _S9_WIRED.items():
        s = BUILTIN_THEMEMAP_SPECS[k]
        assert s.section == "S9", k
        assert s.source == src, k
        assert list(s.requires) == reqs, k
        for tag in s.requires:  # every tag has a working predicate now
            assert tag in prereq_check._CHECKS, (k, tag)


@pytest.mark.parametrize("key", _S9_REAL + list(_S9_WIRED))
def test_s9_spec_renders_a_real_png_from_the_fixture(key):
    spec = BUILTIN_THEMEMAP_SPECS[key]
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)  # missing glyph → failure
        buf = render_from_fixture(spec)
    data = buf.getvalue()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", key
    assert len(data) > 4000, f"{key}: {len(data)}B"


def test_aspect_angle_deg_is_compass_to_math_convention():
    # code 1 = N → points up (90°); code 3 = E → points right (0°/360°)
    assert rz.aspect_angle_deg(1) == 90.0
    assert rz.aspect_angle_deg(3) % 360 == 0.0
    assert rz.aspect_angle_deg(5) == 270.0  # S → down


def test_fixture_carries_every_zonal_key_a_spec_reads():
    for name, v in fx.VALUES.items():
        for k in (
            "elevation_mean",
            "elevation_range",
            "slope_mean",
            "slope_dominant",
            "aspect_dominant",
            "_aspect_bins",
            "_aspect_angle_deg",
            "canopy_mean",
            "biomass_mean",
            "landcover_dominant",
            "forest_type_dominant",
        ):
            assert k in v, f"{name} missing zonal key {k}"
        assert len(v["_slope_glyph"]) == 4
        assert len(v["_aspect_glyph"]) == 8
        assert v["_landcover_glyph"]


def test_slope_class_and_forest_type_palettes_exist_and_mirror():
    from app.core import semantic_palettes as sp

    assert set(sp.CATEGORICAL["slope_class"]) == {
        "gentle",
        "moderate",
        "steep",
        "very_steep",
    }
    # forest_type is keyed by core.forest_types (the vocabulary the tile
    # renderer uses), not a local species list — owner decision 2026-09-29.
    from app.core.forest_types import FRTC_FOREST_TYPES

    assert set(sp.CATEGORICAL["forest_type"]) == {
        ft.name_en for ft in FRTC_FOREST_TYPES.values()
    }
    assert sp.CATEGORICAL["forest_type"]["Shorea robusta Forest"] == "#228B22"
    # every slope_class / forest_type hex is a reused ramp/qual hex (mirror-safe)
    reused = set()
    for stops in sp.RAMPS.values():
        reused |= {s.lower() for s in stops}
    reused |= {c.lower() for c in sp.CATEGORICAL["species_qual"].values()}
    for c in sp.CATEGORICAL["slope_class"].values():
        assert c.lower() in reused, c


# ── DB-backed: real zonal SQL against a forest with blocks ───────────────
# Self-connecting (no conftest `db` fixture) so it also runs under --noconftest;
# skips cleanly when the app DB is unreachable or has no forest with blocks.
def _live_session():
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        try:
            from app.core.config import settings

            url = settings.DATABASE_URL
        except Exception:  # noqa: BLE001
            return None
    if not url:
        return None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        eng = create_engine(url)
        s = Session(eng)
        s.execute(__import__("sqlalchemy").text("SELECT 1"))
        return s
    except Exception:  # noqa: BLE001
        return None


def test_per_unit_zonal_against_a_real_forest():
    from sqlalchemy import text

    db = _live_session()
    if db is None:
        pytest.skip("no reachable application database")

    from geoalchemy2.shape import to_shape

    from app.models.forest_block import ForestBlock

    calc_id = db.execute(
        text(
            "SELECT calculation_id FROM forest_blocks "
            "WHERE geometry IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
        )
    ).scalar()
    if calc_id is None:
        pytest.skip("no forest with blocks in this DB")

    blocks = (
        db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc_id, ForestBlock.geometry.isnot(None))
        .limit(4)
        .all()
    )
    units = [
        {"name": b.name or str(b.id)[:6], "geometry": to_shape(b.geometry)}
        for b in blocks
    ]
    if not units:
        pytest.skip("no block geometries")

    if not rz.coverage_available(db, units[0]["geometry"].wkt):
        pytest.skip("terrain rasters do not cover this forest")

    class _Spec:
        measure = "elevation_mean"

    out = rz.per_unit_zonal(db, units, _Spec())
    assert out and any(out.values())
    for rec in out.values():
        if "elevation_mean" in rec:
            assert -500 < rec["elevation_mean"] < 9000  # NoData filtered out
            assert rec["elevation_range"] >= 0

    class _Aspect:
        measure = "aspect_bins"

    ao = rz.per_unit_zonal(db, units, _Aspect())
    for rec in ao.values():
        if "_aspect_bins" in rec:
            assert set(rec["_aspect_bins"]) == set(rz.COMPASS_8)
            assert len(rec["_aspect_glyph"]) == 8
