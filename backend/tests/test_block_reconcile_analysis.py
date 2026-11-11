"""BA-3: the analysis engine (`analyze_forest_boundary`) must run on the
DB-authoritative `forest_blocks` set even when the JSONB `result_data.blocks`
snapshot is stale (the 1-vs-5 defect), while legacy upload-mode calcs with no
`forest_blocks` rows keep analysing over their JSONB snapshot unchanged.
"""
from __future__ import annotations

import asyncio
import uuid

from shapely.geometry import box
from shapely.wkt import dumps as wkt_dumps

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.models.user import User

# Disable every optional heavy whole-forest analysis so the test only exercises
# the block loop + cheap geometry-only bookkeeping (same harness as
# test_analysis_debug_hook.py).
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


def _seed(db, with_blocks=True):
    user = User(
        email=f"rec-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Reconcile Analysis",
    )
    db.add(user)
    db.flush()

    stale = {
        "total_blocks": 1,
        "blocks": [{
            "block_index": 0,
            "block_name": "simpani",
            "area_hectares": 100.0,
            "geometry": {"type": "Polygon",
                         "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
        }],
    }
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name=f"Rec CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(2, 2, 6, 6)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
        result_data=stale,
    )
    db.add(calc)
    db.flush()

    if with_blocks:
        for i in range(1, 6):
            db.add(ForestBlock(
                id=uuid.uuid4(),
                calculation_id=calc.id,
                name=f"blocks-{i}",
                geometry=wkt_dumps(box(2 + i / 10.0, 2, 4 + i / 10.0, 4)),
                area_hectares=i * 10.0,
                index=i,
                natural_name=None,
                division_level=1,
            ))
    db.commit()
    db.refresh(calc)
    return calc


def test_analysis_runs_over_five_db_blocks_not_stale_jsonb(db, monkeypatch):
    from app.services import analysis as analysis_mod
    from app.services.analysis import analyze_forest_boundary

    calc = _seed(db, with_blocks=True)

    monkeypatch.setattr(analysis_mod, "get_administrative_location", lambda wkt, db: {})

    result, _ = asyncio.run(analyze_forest_boundary(calc.id, db, dict(OPTIONS)))

    blocks = result["blocks"]
    assert len(blocks) == 5
    assert [b["block_name"] for b in blocks] == [
        "blocks-1", "blocks-2", "blocks-3", "blocks-4", "blocks-5",
    ]


def test_legacy_no_db_rows_analysis_still_runs_over_single_jsonb_block(db, monkeypatch):
    from app.services import analysis as analysis_mod
    from app.services.analysis import analyze_forest_boundary

    calc = _seed(db, with_blocks=False)

    monkeypatch.setattr(analysis_mod, "get_administrative_location", lambda wkt, db: {})

    result, _ = asyncio.run(analyze_forest_boundary(calc.id, db, dict(OPTIONS)))

    blocks = result["blocks"]
    assert len(blocks) == 1
    assert blocks[0]["block_name"] == "simpani"


def _seed_with_compartments(db, n_compartments=3):
    """1 block (division_level 0) divided into N compartments (division_level 1,
    is_compartment=True) — the workspace 'divide into compartments' shape. The
    stale JSONB carries only the single block; result_data['compartments'] is
    empty, mirroring the छिमेकी defect."""
    user = User(
        email=f"rec-cmp-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="not-a-real-hash",
        full_name="Reconcile Compartments",
    )
    db.add(user)
    db.flush()

    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name=f"Cmp CF {uuid.uuid4().hex[:6]}",
        boundary_geom=wkt_dumps(box(2, 2, 6, 6)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
        result_data={
            "total_blocks": 1,
            "polygon_type": "compartment",  # divide flips this, but never fills compartments[]
            "blocks": [{
                "block_index": 0,
                "block_name": "छिमेकी Block 1",
                "area_hectares": 228.0,
                "geometry": {"type": "Polygon",
                             "coordinates": [[[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]]]},
            }],
        },
    )
    db.add(calc)
    db.flush()

    parent = ForestBlock(
        id=uuid.uuid4(), calculation_id=calc.id, name="छिमेकी Block 1",
        geometry=wkt_dumps(box(2, 2, 6, 6)), area_hectares=228.0, index=0,
        division_level=1, is_compartment=False,
    )
    db.add(parent)
    db.flush()

    for i in range(1, n_compartments + 1):
        db.add(ForestBlock(
            id=uuid.uuid4(), calculation_id=calc.id, name=f"C{i}",
            block_name=f"C{i}",
            geometry=wkt_dumps(box(2 + (i - 1), 2, 3 + (i - 1), 4)),
            area_hectares=10.0 * i, index=i,
            division_level=1, is_compartment=True, parent_block_id=parent.id,
        ))
    db.commit()
    db.refresh(calc)
    return calc


def test_reconcile_compartments_populates_result_data(db):
    from app.services.block_reconcile_service import reconcile_compartments_from_db
    from app.services.analysis_polygon_source import PolygonSource

    calc = _seed_with_compartments(db, n_compartments=4)
    assert calc.result_data.get("compartments", []) == []

    changed = reconcile_compartments_from_db(db, calc)
    assert changed is True

    comps = calc.result_data["compartments"]
    assert [c["block_name"] for c in comps] == ["C1", "C2", "C3", "C4"]
    assert calc.result_data["total_compartments"] == 4
    assert all(c.get("geometry") for c in comps)

    # PolygonSource now routes analysis to the compartments, not the 1 block.
    src = PolygonSource.for_result_data(calc.result_data)
    assert src.get_metadata_key() == "compartments"
    assert len(src.get_polygons()) == 4

    # Idempotent.
    assert reconcile_compartments_from_db(db, calc) is False


def test_reconcile_compartments_noop_when_no_compartment_rows(db):
    from app.services.block_reconcile_service import reconcile_compartments_from_db

    calc = _seed(db, with_blocks=True)  # 5 blocks, division_level 0, no compartments
    assert reconcile_compartments_from_db(db, calc) is False
    assert "compartments" not in (calc.result_data or {})


def test_analysis_runs_over_compartments_not_the_single_block(db, monkeypatch):
    from app.services import analysis as analysis_mod
    from app.services.analysis import analyze_forest_boundary

    calc = _seed_with_compartments(db, n_compartments=3)
    monkeypatch.setattr(analysis_mod, "get_administrative_location", lambda wkt, db: {})

    result, _ = asyncio.run(analyze_forest_boundary(calc.id, db, dict(OPTIONS)))

    assert "compartments" in result
    assert len(result["compartments"]) == 3
    assert [c["block_name"] for c in result["compartments"]] == ["C1", "C2", "C3"]
