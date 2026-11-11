"""P1 integration — zone_classifier + species_assemblage over a real forest.

Opt-in: set ``SFM_INTEGRATION_CALC_ID`` to a calculation id in the live ``cf_db``
(a stem-mapped forest such as बृन्दाबन). Skipped otherwise, so it never runs in
the normal test-DB suite.

    SFM_INTEGRATION_CALC_ID=<uuid> pytest tests/services/test_sfm_p1_integration.py
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.forest_block import ForestBlock
from app.services.sustainable_fm.sfm_config import resolve_params
from app.services.sustainable_fm.species_assemblage import resolve_block_inputs
from app.services.sustainable_fm.zone_classifier import SFM_ZONES, classify_block

_CALC_ID = os.environ.get("SFM_INTEGRATION_CALC_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _CALC_ID, reason="set SFM_INTEGRATION_CALC_ID to run"),
]


@pytest.fixture(scope="module")
def live_db():
    url = os.environ.get(
        "DATABASE_URL", "postgresql://postgres:admin123@localhost:5432/cf_db"
    )
    engine = create_engine(url, pool_pre_ping=True)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_every_block_classifies_and_resolves(live_db):
    from app.models.calculation import Calculation

    calc = live_db.get(Calculation, _CALC_ID)
    assert calc is not None, f"calc {_CALC_ID} not found in the live DB"
    params = resolve_params(live_db, calc.id)

    blocks = (
        live_db.query(ForestBlock)
        .filter(ForestBlock.calculation_id == calc.id, ForestBlock.division_level == 1)
        .all()
    )
    assert blocks, "forest has no level-0 blocks"

    sources = set()
    for block in blocks:
        wkt = live_db.execute(
            text("SELECT ST_AsText(geometry) FROM forest_blocks WHERE id = :id"),
            {"id": str(block.id)},
        ).scalar()
        zone = classify_block(wkt, live_db, params)
        assert zone.sfm_zone in SFM_ZONES
        assert zone.slope_band in (1, 2, 3, 4)
        assert abs(sum(zone.slope_band_area_pct.values()) - 100.0) < 1.0

        inp = resolve_block_inputs(calc, block, params, live_db, zone=zone)
        assert inp.block_name
        assert inp.source in ("stem_mapping", "field_inventory", "prior")
        sources.add(inp.source)
        if inp.source == "stem_mapping":
            assert inp.gs_ge40_m3 is not None
            assert inp.dominant_group is not None

    # a real forest that has been inventoried should not be all-prior
    assert sources != {"prior"}, "expected at least one inventoried block"
