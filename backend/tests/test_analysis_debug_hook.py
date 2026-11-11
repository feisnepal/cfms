"""H4.2 / H3.5: cover the DEBUG-gated forced-failure hook in
`analyze_forest_boundary` (analysis.py:323-325).

The hook only exists so the fail-fast gate can crash a single block during
development. It reads `settings.DEBUG` and the `CFMS_FORCE_BLOCK_FAILURE` env
var; when set it raises, and the enclosing except handler tags the block with
`analysis_error` instead of aborting the whole calculation.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from shapely.geometry import box, mapping
from shapely.wkt import dumps as wkt_dumps

from app.models.calculation import Calculation
from app.models.user import User

# Disable every optional heavy whole-forest analysis so the test only exercises
# the block loop (the forced raise happens before block geometry analysis) and
# the cheap, geometry-only bookkeeping that follows it.
OPTIONS = {
    "run_raster_analysis": False,
    "run_proximity": False,
    "run_landcover_1984": False,
    "run_hansen2000": False,
    "run_temperature": False,
    "run_precipitation": False,
    "run_elevation": False,
    "run_slope": False,
    "run_aspect": False,
    "run_canopy": False,
    "run_biomass": False,
    "run_forest_health": False,
    "run_forest_type": False,
    "run_landcover": False,
    "run_forest_loss": False,
    "run_forest_gain": False,
    "run_fire_loss": False,
    "run_soil": False,
}


def _seed_calculation_with_blocks(db):
    user = User(
        email=f"dbg-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Debug Hook",
    )
    db.add(user)
    db.flush()

    geojson = mapping(box(2, 2, 6, 6))
    calc = Calculation(
        user_id=user.id,
        forest_name=f"Debug CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(2, 2, 6, 6)),
        result_data={
            "blocks": [
                {
                    "block_index": 0,
                    "block_name": "Block 1",
                    "area_hectares": 16.0,
                    "geometry": geojson,
                }
            ]
        },
    )
    db.add(calc)
    db.commit()
    return calc


def test_debug_forced_block_failure_tags_the_block(db, monkeypatch):
    from app.core.config import settings
    from app.services import analysis as analysis_mod
    from app.services.analysis import analyze_forest_boundary

    calc = _seed_calculation_with_blocks(db)

    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setenv("CFMS_FORCE_BLOCK_FAILURE", "*")
    # The whole-forest tail calls get_administrative_location without a guard;
    # the admin.admin_nepal table is not part of the test schema, so stub it.
    monkeypatch.setattr(analysis_mod, "get_administrative_location", lambda wkt, db: {})

    result, _ = asyncio.run(analyze_forest_boundary(calc.id, db, dict(OPTIONS)))

    blocks = result["blocks"]
    assert len(blocks) == 1
    assert "analysis_error" in blocks[0]
    assert "forced analysis failure" in blocks[0]["analysis_error"]


def test_debug_hook_is_inert_when_env_is_blank(db, monkeypatch):
    from app.core.config import settings
    from app.services import analysis as analysis_mod
    from app.services.analysis import analyze_forest_boundary

    calc = _seed_calculation_with_blocks(db)

    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.delenv("CFMS_FORCE_BLOCK_FAILURE", raising=False)
    monkeypatch.setattr(analysis_mod, "get_administrative_location", lambda wkt, db: {})

    result, _ = asyncio.run(analyze_forest_boundary(calc.id, db, dict(OPTIONS)))

    blocks = result["blocks"]
    assert len(blocks) == 1
    assert "analysis_error" not in blocks[0]
