"""SFM per-block species assemblage → SfmBlockInputs (P1).

Pure helpers (``group_for``, ``_dominant_and_codominant``,
``_ge40_from_breakdown``, ``_shares_from_counts``) are unit-tested directly;
the three source resolvers run against the test DB with hand-inserted rows.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from sqlalchemy import text
from shapely.geometry import Point, Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.sustainable_fm import species_assemblage as sa
from app.services.sustainable_fm.sfm_config import DEFAULT_PARAMS
from app.services.sustainable_fm.species_assemblage import (
    SfmBlockInputs,
    SpeciesShare,
    group_for,
    resolve_block_inputs,
)


# ── pure: group_for ─────────────────────────────────────────────────────
def test_group_for():
    assert group_for("Shorea robusta") == "SAL"
    assert group_for("Pinus roxburghii") == "PINE_ROX"
    assert group_for("Pinus wallichiana") == "PINE_WALL"
    assert group_for("Pinus patula") == "PINE_PATULA"
    assert group_for("Pinus something-else") == "PINE_ROX"  # unlisted pine
    assert group_for("Dalbergia sissoo") == "SISSOO_KHAIR"
    assert group_for("Acacia catechu") == "SISSOO_KHAIR"
    assert group_for("Schima wallichii") == "HILL_BROADLEAF"
    assert group_for("Quercus semecarpifolia") == "TEMPERATE_BROADLEAF"
    assert group_for("Abies spectabilis") == "TEMPERATE_CONIFER"
    assert group_for("Random unknownus") == "OTHER"
    assert group_for(None) == "OTHER"
    assert group_for("robusta", genus="Shorea") == "SAL"


# ── pure: dominant / codominant ────────────────────────────────────────
def _sh(sci, group, pct):
    return SpeciesShare(sci, None, sci.split()[0].lower(), group, pct)


def test_dominant_and_codominant():
    shares = [
        _sh("Shorea robusta", "SAL", 72.0),
        _sh("Schima wallichii", "HILL_BROADLEAF", 20.0),
    ]
    assert sa._dominant_and_codominant(shares) == ("SAL", None, [])

    shares = [
        _sh("Pinus roxburghii", "PINE_ROX", 55.0),
        _sh("Schima wallichii", "HILL_BROADLEAF", 35.0),
    ]
    dom, co, unmapped = sa._dominant_and_codominant(shares)
    assert (dom, co, unmapped) == ("PINE_ROX", "HILL_BROADLEAF", [])

    # a second group under 30 % is not co-dominant
    shares = [
        _sh("Pinus roxburghii", "PINE_ROX", 80.0),
        _sh("Schima wallichii", "HILL_BROADLEAF", 20.0),
    ]
    assert sa._dominant_and_codominant(shares)[1] is None

    # all OTHER → no dominant, names collected
    shares = [_sh("Weirdus treeus", "OTHER", 60.0), _sh("Oddus plantus", "OTHER", 40.0)]
    assert sa._dominant_and_codominant(shares) == (
        None,
        None,
        ["Weirdus treeus", "Oddus plantus"],
    )


# ── pure: >=40 cm ratio from the DBH breakdown ─────────────────────────
def test_ge40_from_breakdown():
    bd = {
        "10_20": {"timber": 5.0},
        "30_40": {"timber": 10.0},
        "40_50": {"timber": 6.0},
        "50_60": {"timber": 4.0},
    }
    # ratio = (6+4) / (5+10+6+4) = 0.4 ; * 100 m3/ha = 40 ; * 20 ha = 800
    per_ha, absol = sa._ge40_from_breakdown(bd, gs_per_ha=100.0, area_ha=20.0)
    assert per_ha == 40.0
    assert absol == 800.0

    assert sa._ge40_from_breakdown(None, 100.0, 10.0) == (None, None)
    assert sa._ge40_from_breakdown({}, 100.0, 10.0) == (None, None)
    assert sa._ge40_from_breakdown(bd, None, 10.0) == (None, None)


def test_shares_rank_by_volume_then_count():
    counts = {
        "Shorea robusta": {"local": "Sal", "vol": 30.0, "n": 3},
        "Schima wallichii": {"local": "Chilaune", "vol": 10.0, "n": 7},
    }
    by_vol = sa._shares_from_counts(counts, by="vol")
    assert by_vol[0].scientific == "Shorea robusta" and by_vol[0].share_pct == 75.0
    by_n = sa._shares_from_counts(counts, by="n")
    assert by_n[0].scientific == "Schima wallichii" and by_n[0].share_pct == 70.0


# ── DB fixtures ───────────────────────────────────────────────────────
def _user(db):
    u = User(
        email=f"sfm{uuid.uuid4().hex[:8]}@t.com",
        full_name="SFM P1",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    return u


def _calc_with_block(db):
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=_user(db).id,
        uploaded_filename="p1.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    poly = Polygon([(84, 27), (84.02, 27), (84.02, 27.02), (84, 27.02)])
    block = ForestBlock(
        calculation_id=calc.id,
        name="Block-1",
        block_name="Block-1",
        geometry=from_shape(poly, srid=4326),
        area_hectares=100.0,
        area_sqm=1_000_000.0,
        index=1,
        division_level=1,
    )
    db.add(block)
    db.flush()
    return calc, block


def _add_stem_inventory(db, calc, trees):
    """trees: list of (species, dia_cm, net_volume, stand_type, remark)."""
    ic_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO inventory_calculations "
            "(id, calculation_id, user_id, uploaded_filename, grid_spacing_meters, "
            " projection_epsg, status) "
            "VALUES (:id, :cid, :uid, 'sm.csv', 20.0, 32644, 'completed')"
        ),
        {"id": ic_id, "cid": str(calc.id), "uid": str(calc.user_id)},
    )
    for sp, dia, vol, stype, remark in trees:
        db.execute(
            text(
                "INSERT INTO inventory_trees "
                "(id, inventory_calculation_id, species, dia_cm, net_volume, "
                " stand_type, remark, block_name, location, was_corrected) "
                "VALUES (:id, :ic, :sp, :dia, :vol, :st, :rm, 'Block-1', "
                " ST_GeogFromText('SRID=4326;POINT(84.01 27.01)'), false)"
            ),
            {
                "id": str(uuid.uuid4()),
                "ic": ic_id,
                "sp": sp,
                "dia": dia,
                "vol": vol,
                "st": stype,
                "rm": remark,
            },
        )
    db.flush()


def test_stem_mapping_source(db):
    calc, block = _calc_with_block(db)
    trees = (
        [("Shorea robusta", 45.0, 1.2, "Tree", None)] * 7
        + [("Shorea robusta", 12.0, 0.05, "Pole", None)] * 3
        + [("Schima wallichii", 50.0, 1.0, "Tree", None)] * 3
        + [("Shorea robusta", 2.0, 0.0, "Regeneration", None)] * 400
        + [("Shorea robusta", 60.0, 2.0, "Tree", "Mother Tree")] * 2
    )
    _add_stem_inventory(db, calc, trees)

    inp = resolve_block_inputs(calc, block, DEFAULT_PARAMS, db)
    # Stem mapping is done in ONE block, chosen from the plot inventory, so it must never be the basis of a forest
    # type (owner, 2026-10-06): with no sample plots the block gets only the raster prior, and no plots counted.
    assert inp.source == "prior"
    assert inp.plot_count == 0
    assert inp.dominant_group is None  # the census was NOT read for the species group


def test_field_inventory_source(db):
    calc, block = _calc_with_block(db)
    fic_id = str(uuid.uuid4())
    db.execute(
        text(
            "INSERT INTO field_inventory_calculations "
            "(id, calculation_id, user_id, uploaded_filename, regeneration_area_sqm, "
            " sapling_area_sqm, pole_area_sqm, tree_area_sqm, status) "
            "VALUES (:id, :cid, :uid, 'fi.csv', 10, 25, 100, 500, 'completed')"
        ),
        {"id": fic_id, "cid": str(calc.id), "uid": str(calc.user_id)},
    )
    db.execute(
        text(
            "INSERT INTO field_inventory_block_summary "
            "(id, field_inventory_calculation_id, block_name, total_sample_plots, "
            " regeneration_per_ha, sapling_per_ha, total_growing_stock_m3_per_ha, "
            " dbh_class_breakdown) "
            "VALUES (:id, :fic, 'Block-1', 10, 6000, 2500, 120.0, "
            ' \'{"30_40": {"timber": 60}, "40_50": {"timber": 30}, '
            '   "50_60": {"timber": 10}}\'::jsonb)'
        ),
        {"id": str(uuid.uuid4()), "fic": fic_id},
    )
    db.flush()

    inp = resolve_block_inputs(calc, block, DEFAULT_PARAMS, db)
    assert inp.source == "field_inventory"
    assert inp.growing_stock_m3_per_ha == pytest.approx(120.0)
    # ratio (30+10)/(60+30+10) = 0.4 → 48 m3/ha ; * 100 ha = 4800
    assert inp.gs_ge40_m3_per_ha == pytest.approx(48.0, abs=1e-6)
    assert inp.gs_ge40_m3 == pytest.approx(4800.0, abs=1e-3)
    assert inp.regen_adequate is True  # 6000 >= 5000 and 2500 >= 2000
    assert inp.mother_trees_per_ha is None


def test_prior_source_when_no_inventory(db):
    calc, block = _calc_with_block(db)
    inp = resolve_block_inputs(calc, block, DEFAULT_PARAMS, db)
    assert inp.source == "prior"
    assert inp.gs_ge40_m3 is None
    assert inp.regen_adequate is None
    assert inp.dominant_group is None  # no FRTC raster in the test DB
    assert inp.origin == "natural"  # no OP plan → metadata default
    assert inp.crown_density_pct == DEFAULT_PARAMS.crown_density_default


def test_metadata_form_drives_origin_and_crown(db):
    calc, block = _calc_with_block(db)
    db.execute(
        text(
            "INSERT INTO operational_plans (id, calculation_id, plan_metadata) "
            "VALUES (:id, :cid, "
            ' \'{"user_inputs": {"forest_type": "वृक्षारोपण", '
            '   "avg_crown_density_pct": 15}}\'::jsonb)'
        ),
        {"id": str(uuid.uuid4()), "cid": str(calc.id)},
    )
    db.flush()
    inp = resolve_block_inputs(calc, block, DEFAULT_PARAMS, db)
    assert inp.origin == "plantation"
    assert inp.crown_density_pct == 15


def test_plot_count_and_species_come_from_the_blocks_own_plots(db):
    from tests.sfm_field_fixture import add_field_inventory

    calc, block = _calc_with_block(db)
    add_field_inventory(db, calc, "Block-1", species="Shorea robusta", plots=4)
    inp = resolve_block_inputs(calc, block, DEFAULT_PARAMS, db)
    assert inp.source == "field_inventory"
    assert inp.plot_count == 4
    assert inp.dominant_group == "SAL"
