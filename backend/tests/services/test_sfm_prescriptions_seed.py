"""The 14 दिगो वन व्यवस्थापन कार्यविधि अनुसूची-१ rows (P0).

Pure-data checks on ``scripts.seed_sfm_prescriptions.PRESCRIPTION_ROWS`` plus a
DB check that migration 082 seeded them (the test schema is built by
``alembic upgrade head``).
"""

from __future__ import annotations

from scripts.seed_sfm_prescriptions import (
    AREA_COUPE,
    PRESCRIPTION_ROWS,
    SELECTION,
    SHELTERWOOD,
    STEM_COUNT,
    seed,
)

_METHODS = {SELECTION, SHELTERWOOD, STEM_COUNT, AREA_COUPE}
_BASES = {"growing_stock_pct_ge40", "stem_count", "area_volume", "none"}
_ORIENTATIONS = {"Production", "Conservation", "Protection", "Restoration", "Multi-use"}
_ZONES = {"LOWLAND_SAL", "HILL", "TEMPERATE", "HIGH_MOUNTAIN"}


# ── shape ────────────────────────────────────────────────────────────────
def test_fourteen_rows_numbered_1_to_14():
    assert len(PRESCRIPTION_ROWS) == 14
    assert {r["type_no"] for r in PRESCRIPTION_ROWS} == set(range(1, 15))


def test_names_and_orientation():
    for r in PRESCRIPTION_ROWS:
        assert r["name_ne"] and r["name_en"]
        assert r["orientation"] in _ORIENTATIONS
        assert r["origin"] in (None, "natural", "plantation")
        assert set(r["zone_triggers"]) <= _ZONES
        assert r["species_groups"]  # never empty


def test_slope_band_only_on_types_1_2_3():
    for r in PRESCRIPTION_ROWS:
        if r["slope_band"] is not None:
            assert r["type_no"] in (1, 2, 3)
            assert r["slope_band"] in (1, 2, 3)


def test_every_branch_has_a_valid_method_and_basis():
    for r in PRESCRIPTION_ROWS:
        branches = r["branches"]
        assert branches, f"type {r['type_no']} has no branch"
        assert set(branches) <= {"adequate", "inadequate", "default"}
        for name, b in branches.items():
            assert b["method"] in _METHODS, (r["type_no"], name, b["method"])
            assert b["yield_rules"]["basis"] in _BASES


def test_growing_stock_steps_are_contiguous_and_open_ended():
    for r in PRESCRIPTION_ROWS:
        for name, b in r["branches"].items():
            yr = b["yield_rules"]
            if yr["basis"] != "growing_stock_pct_ge40":
                continue
            steps = yr["steps"]
            assert steps, (r["type_no"], name)
            # ordered high → low: first open at the top, last open at the bottom
            assert steps[0]["gs_per_ha_max"] is None
            assert steps[-1]["gs_per_ha_min"] is None
            for lo, hi in zip(steps, steps[1:]):
                assert lo["gs_per_ha_min"] == hi["gs_per_ha_max"], (r["type_no"], name)
            for s in steps:
                assert 0 < s["pct"] <= 10


def test_shelterwood_branches_carry_a_regeneration_period():
    for r in PRESCRIPTION_ROWS:
        for name, b in r["branches"].items():
            if b["method"] == SHELTERWOOD:
                assert b["regeneration_period_years"], (r["type_no"], name)


def test_protection_type_3_has_no_yield():
    row3 = next(r for r in PRESCRIPTION_ROWS if r["type_no"] == 3)
    assert row3["orientation"] == "Protection"
    assert row3["branches"]["default"]["yield_rules"]["basis"] == "none"


def test_plantation_types_flag_origin():
    for tno in (4, 9, 14):
        row = next(r for r in PRESCRIPTION_ROWS if r["type_no"] == tno)
        assert row["origin"] == "plantation"
    assert (
        next(r for r in PRESCRIPTION_ROWS if r["type_no"] == 8)["origin"] == "natural"
    )


# ── DB ───────────────────────────────────────────────────────────────────
def test_migration_082_seeded_the_rows(db):
    from app.models.sfm_prescription import SfmForestTypePrescription

    rows = db.query(SfmForestTypePrescription).all()
    assert len(rows) == 14
    by_no = {r.type_no: r for r in rows}
    assert by_no[3].orientation == "Protection"
    assert by_no[1].branches["adequate"]["yield_rules"]["steps"][0]["pct"] == 2.0
    assert by_no[8].origin == "natural"


def test_seed_is_idempotent(db):
    from app.models.sfm_prescription import SfmForestTypePrescription

    seed(db)
    seed(db)
    db.flush()
    assert db.query(SfmForestTypePrescription).count() == 14
