"""SFM P10 — crown-density estimate from the canopy / ESA raster (follow-on).

``source="none"`` (the default) is byte-identical to P1: the estimator is never
called and ``crown_density_pct`` is ``crown_density_default``. ``"esa"`` on a
bare test DB (no ``rasters.esa_world_cover``) degrades to ``None`` inside a
SAVEPOINT — no exception, the caller's transaction survives. ``"canopy"`` maths
are unit-tested against a synthetic pixel array.
"""

from __future__ import annotations

import uuid

import numpy as np
import pytest
from sqlalchemy import text

from app.services.sustainable_fm import crown_density as cd
from app.services.sustainable_fm.sfm_config import (
    DEFAULT_PARAMS,
    SfmParams,
    SfmParamsPatch,
)

_WKT = "POLYGON((84 27, 84.02 27, 84.02 27.02, 84 27.02, 84 27))"


# ── schema ─────────────────────────────────────────────────────────────────
def test_param_field_default_and_validation():
    assert DEFAULT_PARAMS.crown_density_estimate_source == "none"
    assert (
        SfmParams(crown_density_estimate_source="esa").crown_density_estimate_source
        == "esa"
    )
    with pytest.raises(Exception):
        SfmParams(crown_density_estimate_source="lidar")
    # the sparse patch accepts it too
    assert SfmParamsPatch(crown_density_estimate_source="canopy") is not None
    with pytest.raises(Exception):
        SfmParamsPatch(crown_density_estimate_source="nope")


# ── estimator dispatch ─────────────────────────────────────────────────────
def test_none_source_never_estimates(db):
    assert cd.estimate_crown_density(_WKT, "none", db) is None
    assert cd.estimate_crown_density("", "esa", db) is None  # no geometry


def test_esa_missing_raster_is_none_and_savepoint_safe(db):
    # bare test DB has no rasters.esa_world_cover
    assert cd.estimate_crown_density(_WKT, "esa", db) is None
    # the request transaction is still usable
    assert db.execute(text("SELECT 1")).scalar() == 1


def test_canopy_pixel_fraction_maths(monkeypatch):
    # 100 pixels: 30 NoData(0), 20 non-forest(1), 50 woody(≥2 m)
    arr = np.array([0] * 30 + [1] * 20 + [4] * 25 + [18] * 25, dtype="uint8").reshape(
        10, 10
    )

    class _Src:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cd, "CANOPY_TIF_PATH", "ignored.tif")
    import rasterio

    monkeypatch.setattr(rasterio, "open", lambda _p: _Src())
    monkeypatch.setattr(
        "rasterio.mask.mask", lambda src, shapes, crop: (arr[None, :, :], None)
    )

    # valid = 70 pixels (drop the 30 NoData); 50 are woody → 71 %
    assert cd._canopy_crown_pct({"type": "Polygon", "coordinates": []}) == 71


def test_canopy_all_nodata_is_none(monkeypatch):
    arr = np.zeros((4, 4), dtype="uint8")

    class _Src:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    import rasterio

    monkeypatch.setattr(rasterio, "open", lambda _p: _Src())
    monkeypatch.setattr("rasterio.mask.mask", lambda *a, **k: (arr[None, :, :], None))
    assert cd._canopy_crown_pct({"type": "Polygon", "coordinates": []}) is None


# ── integration through resolve_block_inputs ───────────────────────────────
def _calc_with_block(db):
    from app.models.calculation import Calculation
    from app.models.forest_block import ForestBlock
    from app.models.user import User, UserRole
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Polygon

    u = User(
        email=f"cd{uuid.uuid4().hex[:8]}@t.com",
        full_name="CD",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="cd.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    poly = Polygon([(84, 27), (84.02, 27), (84.02, 27.02), (84, 27.02)])
    blk = ForestBlock(
        calculation_id=calc.id,
        name="Block-1",
        block_name="Block-1",
        geometry=from_shape(poly, srid=4326),
        area_hectares=100.0,
        area_sqm=1_000_000.0,
        index=1,
        division_level=1,
    )
    db.add(blk)
    db.flush()
    return calc, blk


def test_default_source_matches_p1(db):
    from app.services.sustainable_fm.species_assemblage import resolve_block_inputs

    calc, blk = _calc_with_block(db)
    p = SfmParams()  # source="none"
    inp = resolve_block_inputs(calc, blk, p, db)
    assert inp.crown_density_pct == p.crown_density_default  # 50


def test_esa_source_falls_back_to_default_when_no_raster(db):
    from app.services.sustainable_fm.species_assemblage import resolve_block_inputs

    calc, blk = _calc_with_block(db)
    p = SfmParams(crown_density_estimate_source="esa")
    inp = resolve_block_inputs(calc, blk, p, db)
    # no rasters.esa_world_cover in the test DB → estimator None → default
    assert inp.crown_density_pct == p.crown_density_default


def test_estimated_value_is_used_when_available(db, monkeypatch):
    from app.services.sustainable_fm import species_assemblage as sa
    from app.services.sustainable_fm.species_assemblage import resolve_block_inputs

    calc, blk = _calc_with_block(db)
    monkeypatch.setattr(
        "app.services.sustainable_fm.crown_density.estimate_crown_density",
        lambda wkt, src, db: 12,
    )
    p = SfmParams(crown_density_estimate_source="canopy")
    inp = resolve_block_inputs(calc, blk, p, db)
    assert inp.crown_density_pct == 12  # the < 20 % सि.नं. 6 trigger can now fire
    _ = sa  # keep the import referenced
