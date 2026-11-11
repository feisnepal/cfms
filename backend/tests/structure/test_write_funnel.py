"""The write funnel (FS-1b.2 / FS-1b.6 / FS-1b.7 / FS-1b.9) - ``app.services.forest_units.write``."""

from __future__ import annotations

import uuid

from geoalchemy2.shape import from_shape
from shapely.geometry import mapping

from app.models.calculation import Calculation, CalculationStatus
from app.models.forest_block import ForestBlock
from app.services.forest_units.write import (
    clear_stale_domains,
    clear_stale_domains_for_calc,
    on_structure_changed,
    recompute_sub_area_breakdown,
    structure_write,
)
from app.services.sub_area_service import build_sub_area_dict

from . import fixtures


def _calc(db, forest):
    return db.query(Calculation).filter(Calculation.id == forest.calc_id).first()


def test_structure_write_rebuilds_the_arrays(make_forest, db):
    """After ``structure_write`` a mutation to forest_blocks, the derived array reflects it - no separate
    reconcile call needed."""
    f = make_forest("F1")
    calc = _calc(db, f)
    with structure_write(db, calc, change="add a block"):
        db.add(
            ForestBlock(
                calculation_id=calc.id,
                name="B3",
                block_name="B3",
                # clear of B1 and B2: a third top-level block laid ON them is an overlap, and the funnel now refuses it
                # (test_invariants_overlap.py). This test is about the derived arrays being rebuilt.
                geometry=from_shape(fixtures.rect(30, 0, 31, 1), srid=4326),
                area_hectares=1.0,
                index=99,
                is_compartment=False,
                division_level=1,
            )
        )
        db.flush()
    db.commit()
    names = {b["name"] for b in calc.result_data["blocks"]}
    assert names == {"B1", "B2", "B3"}


def test_structure_write_bumps_the_geometry_version(make_forest, db):
    f = make_forest("F1")
    calc = _calc(db, f)
    before = calc.geometry_version or 0
    with structure_write(db, calc):
        pass
    db.commit()
    assert calc.geometry_version == before + 1


def test_structure_write_marks_only_the_domains_that_have_data(make_forest, db):
    """The banner says "your numbers may be out of date", so it is only true for a domain that HAS
    numbers. F1 is a bare block forest: no analysis run, no sampling design, no field inventory, so a
    structural edit must write no flag at all (owner 2026-09-29: "why do I see this ribbon message
    always" — it was written for all three domains on every edit, forever)."""
    f = make_forest("F1")
    calc = _calc(db, f)
    with structure_write(db, calc, change="test edit"):
        pass
    db.commit()
    assert "structure_stale" not in (calc.result_data or {})


def test_structure_write_marks_stale_for_a_forest_that_has_downstream_data(
    make_forest, db
):
    """F10 holds a sampling design AND a field inventory, so both of those domains are marked — and
    `analysis` is not, because that forest's calculation was never run."""
    f = make_forest("F10")
    calc = _calc(db, f)
    with structure_write(db, calc, change="test edit"):
        pass
    db.commit()
    stale = calc.result_data["structure_stale"]
    assert stale["sampling"] is True
    assert stale["field_inventory"] is True
    assert stale["analysis"] is False
    assert stale["change"] == "test edit"
    assert "since" in stale


def test_structure_write_marks_analysis_once_the_calculation_has_run(make_forest, db):
    """A COMPLETED calculation is the only signal there is that the analysis numbers exist."""
    f = make_forest("F1")
    calc = _calc(db, f)
    calc.status = CalculationStatus.COMPLETED
    db.flush()
    with structure_write(db, calc, change="divide B1"):
        pass
    db.commit()
    assert calc.result_data["structure_stale"]["analysis"] is True


def test_an_explicit_domains_argument_overrides_the_probe(make_forest, db):
    """The probe is a default, not a policy: a caller that already knows can pass its own."""
    f = make_forest("F1")
    calc = _calc(db, f)
    on_structure_changed(db, calc, change="x", domains=("sampling",))
    db.commit()
    stale = calc.result_data["structure_stale"]
    assert stale["sampling"] is True and stale["analysis"] is False


def test_clear_stale_domains_clears_only_what_was_re_run(make_forest, db):
    """Re-analysing a forest does not make its sampling design fresh again."""
    f = make_forest("F10")
    calc = _calc(db, f)
    with structure_write(db, calc, change="divide B1"):
        pass
    db.commit()
    assert calc.result_data["structure_stale"]["sampling"] is True

    assert clear_stale_domains(db, calc, ("analysis",)) is True
    db.commit()
    assert calc.result_data["structure_stale"]["sampling"] is True
    assert calc.result_data["structure_stale"]["field_inventory"] is True


def test_clear_stale_domains_drops_the_key_once_nothing_is_flagged(make_forest, db):
    """Every domain re-run -> the key goes, so a consumer that only checks for its presence sees
    nothing. This is what makes the banner stop: the flag used to be write-only."""
    f = make_forest("F10")
    calc = _calc(db, f)
    with structure_write(db, calc, change="divide B1"):
        pass
    db.commit()

    assert clear_stale_domains(db, calc) is True
    db.commit()
    assert "structure_stale" not in (calc.result_data or {})


def test_clear_stale_domains_is_a_noop_when_there_is_no_flag(make_forest, db):
    f = make_forest("F1")
    calc = _calc(db, f)
    assert clear_stale_domains(db, calc) is False
    assert "structure_stale" not in (calc.result_data or {})


def test_clear_stale_domains_for_calc_by_id(make_forest, db):
    """The sampling engine and the field-inventory service commit internally and never load the
    Calculation, so their endpoints clear the flag by id."""
    f = make_forest("F10")
    calc = _calc(db, f)
    with structure_write(db, calc, change="divide B1"):
        pass
    db.commit()
    db.expire(calc)

    assert clear_stale_domains_for_calc(db, calc.id) is True
    db.commit()
    assert "structure_stale" not in (calc.result_data or {})
    # An unknown id is False, never an exception.
    assert clear_stale_domains_for_calc(db, uuid.uuid4()) is False


def test_structure_write_is_a_noop_on_exception(make_forest, db):
    """An exception inside the block means none of the funnel's housekeeping runs - the caller's own
    rollback (not exercised here) is what undoes the mutation itself."""
    f = make_forest("F1")
    calc = _calc(db, f)
    before = calc.geometry_version or 0
    try:
        with structure_write(db, calc):
            raise ValueError("boom")
    except ValueError:
        pass
    assert calc.geometry_version == before  # the funnel's steps did not run
    assert "structure_stale" not in (calc.result_data or {})


def test_recompute_sub_area_breakdown_updates_excluded_and_effective_area(
    make_forest, db
):
    f = make_forest("F1")
    calc = _calc(db, f)
    b1_id = str(f.units["B1"])
    sub = build_sub_area_dict(
        mapping(f.unit_geoms["B1"].buffer(-0.001)),
        "Private-1",
        "private_land",
        3.0,
        block_id=b1_id,
        block_name="B1",
        is_excluded=True,
    )
    rd = dict(calc.result_data)
    rd["sub_areas"] = [sub]
    calc.result_data = rd
    db.flush()

    changed = recompute_sub_area_breakdown(db, calc)

    assert changed is True
    b1 = next(b for b in calc.result_data["blocks"] if b["name"] == "B1")
    assert b1["excluded_area_hectares"] > 0
    assert b1["effective_area_hectares"] == round(
        b1["area_hectares"] - b1["excluded_area_hectares"], 4
    )
    b2 = next(b for b in calc.result_data["blocks"] if b["name"] == "B2")
    assert b2["excluded_area_hectares"] == 0
    assert calc.result_data["excluded_area_hectares"] > 0


def test_recompute_sub_area_breakdown_runs_on_compartments_too(make_forest, db):
    """N2: the old three copies of this logic only ever touched result_data['blocks'] - a compartment
    forest's sub-area edits silently updated an array nobody read."""
    f = make_forest("F2")
    calc = _calc(db, f)
    ha = 5.0
    geom = mapping(f.unit_geoms["C1"].buffer(-0.001))
    sub = build_sub_area_dict(
        geom,
        "Private-1",
        "private_land",
        ha,
        block_id=str(f.units["C1"]),
        block_name="C1",
        is_excluded=True,
    )
    rd = dict(calc.result_data)
    rd["sub_areas"] = [sub]
    calc.result_data = rd
    db.flush()

    changed = recompute_sub_area_breakdown(db, calc)

    assert changed is True
    c1 = next(c for c in calc.result_data["compartments"] if c["name"] == "C1")
    assert c1["excluded_area_hectares"] > 0
    c2 = next(c for c in calc.result_data["compartments"] if c["name"] == "C2")
    assert c2["excluded_area_hectares"] == 0


def test_recompute_sub_area_breakdown_is_a_noop_with_no_sub_areas(make_forest, db):
    f = make_forest("F1")
    calc = _calc(db, f)
    assert recompute_sub_area_breakdown(db, calc) is False


def test_recompute_sub_area_breakdown_resets_to_zero_once_every_sub_area_is_gone(
    make_forest, db
):
    """Regression: clearing every sub-area emptied ``rd['sub_areas']`` to ``[]`` (present, not absent) while
    the block/compartment arrays were also empty (a JSONB-only forest with no forest_blocks rows) - the
    per-unit loop had nothing to touch, so the stale forest-level total was never reset to 0.
    """
    f = make_forest(
        "F6"
    )  # JSONB-only: units in result_data['blocks'], no forest_blocks rows
    calc = _calc(db, f)
    rd = dict(calc.result_data)
    rd["area_hectares"] = 20.0
    rd["sub_areas"] = [
        build_sub_area_dict(
            mapping(f.boundary.buffer(-0.001)),
            "Private-1",
            "private_land",
            2.0,
            is_excluded=True,
        )
    ]
    calc.result_data = rd
    db.flush()
    assert recompute_sub_area_breakdown(db, calc) is True
    assert calc.result_data["excluded_area_hectares"] == 2.0

    rd2 = dict(calc.result_data)
    rd2["sub_areas"] = []  # cleared, key still present
    calc.result_data = rd2
    db.flush()

    assert recompute_sub_area_breakdown(db, calc) is True
    assert calc.result_data["excluded_area_hectares"] == 0.0
    assert calc.result_data["effective_area_hectares"] == 20.0


def test_on_structure_changed_preserves_other_result_data_keys(make_forest, db):
    f = make_forest("F10")  # has downstream data, so a flag is actually written
    calc = _calc(db, f)
    rd = dict(calc.result_data)
    rd["some_other_key"] = "keep me"
    calc.result_data = rd
    db.flush()
    on_structure_changed(db, calc, change="x")
    assert calc.result_data["some_other_key"] == "keep me"
    assert calc.result_data["structure_stale"]["change"] == "x"


def test_funnel_timing_budget_on_a_larger_fixture(make_forest, db):
    """Not a strict perf test (shared CI hardware) - just a sanity ceiling. FS-1b.9 asks for a timing record
    on a larger fixture; 60 units is well above every real forest today (max 9)."""
    import time

    from shapely.geometry import box

    f = make_forest("F1")
    calc = _calc(db, f)
    minx, miny, maxx, maxy = f.boundary.bounds
    dx = (maxx - minx) / 60
    for i in range(60):
        db.add(
            ForestBlock(
                calculation_id=calc.id,
                name=f"Extra-{i}",
                block_name=f"Extra-{i}",
                geometry=from_shape(
                    box(minx + i * dx, miny, minx + (i + 1) * dx, miny + 0.0001),
                    srid=4326,
                ),
                area_hectares=0.01,
                index=100 + i,
                is_compartment=False,
                division_level=1,
            )
        )
    db.flush()
    start = time.monotonic()
    with structure_write(db, calc, change="bulk add"):
        pass
    db.commit()
    elapsed = time.monotonic() - start
    assert (
        elapsed < 5.0
    ), f"structure_write took {elapsed:.2f}s on 62 units - record this if it grows"
