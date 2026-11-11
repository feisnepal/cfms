"""SFM prescription card + branch selection + orientation + narration (P3)."""

from __future__ import annotations

from app.services.sustainable_fm.orientation import propose
from app.services.sustainable_fm.prescription import (
    build_card,
    load_prescriptions,
    pick_branch,
)
from app.services.sustainable_fm.sfm_config import DEFAULT_PARAMS
from app.services.sustainable_fm import sfm_narration as narr

P = DEFAULT_PARAMS


def _blk(area, adequate, source="stem_mapping"):
    return {"area_ha": area, "inputs": {"regen_adequate": adequate, "source": source}}


# ── pick_branch ────────────────────────────────────────────────────────
def test_pick_branch_adequate_when_all_known_adequate():
    assert pick_branch([_blk(50, True), _blk(50, True)], P) == "adequate"


def test_pick_branch_inadequate_on_any_no():
    assert pick_branch([_blk(50, True), _blk(50, False)], P) == "inadequate"


def test_pick_branch_inadequate_when_mostly_uninventoried():
    # 70 % prior → below the 60 % inventoried floor → conservative
    grp = [_blk(70, None, source="prior"), _blk(30, True)]
    assert pick_branch(grp, P) == "inadequate"


def test_pick_branch_inadequate_when_state_unknown():
    assert pick_branch([_blk(50, None), _blk(50, None)], P) == "inadequate"


# ── build_card ─────────────────────────────────────────────────────────
def test_build_card_type1_adequate(db):
    row = load_prescriptions(db)[1]
    card = build_card(row, "adequate", gs_ge40_m3_per_ha=180.0, pct=1.0, params=P)
    assert card["type_no"] == 1
    assert card["method"] == "selection_felling_cycle"
    assert card["felling_cycle_years"] == 10
    assert card["orientation"] == "Production"
    assert card["yield_basis"] == "growing_stock_pct_ge40"
    assert card["yield_pct"] == 1.0
    assert card["gs_ge40_m3_per_ha"] == 180.0


def test_build_card_shelterwood_gets_mother_target_from_params(db):
    row = load_prescriptions(db)[8]
    card = build_card(row, "inadequate", gs_ge40_m3_per_ha=None, pct=None, params=P)
    assert card["method"] == "shelterwood_periodic_block"
    # type 8 inadequate has no mother_trees_per_ha → falls back to params
    assert card["mother_tree_target"] == [
        P.mother_tree_target_min,
        P.mother_tree_target_max,
    ]


def test_build_card_none_row_is_a_stub():
    card = build_card(None, "default", gs_ge40_m3_per_ha=None, pct=None, params=P)
    assert card["type_no"] is None and card["system_ne"] == "—"


# ── orientation ────────────────────────────────────────────────────────
class _Row:
    def __init__(self, orientation):
        self.orientation = orientation


def test_orientation_production_no_proposal():
    ori, wc, just = propose(2, {"slope_band": 2}, _Row("Conservation"), P)
    assert ori == "Conservation" and wc is None
    # D7 follow-up (2026-09-15): a plain base orientation with no override
    # still gets a read-only justification naming the सि.नं. reference.
    assert "सि.नं. 2" in just["justification_ne"]
    assert "type 2" in just["justification_en"]
    assert "Conservation" in just["justification_en"]


def test_orientation_protection_type_proposes_protection():
    ori, wc, just = propose(3, {"slope_band": 3}, _Row("Protection"), P)
    assert ori == "Protection"
    assert wc["target"] == "protection"
    assert "संरक्षण कार्य वृत्त" in wc["justification_ne"]
    # The plain justification (no working-circle arrow) is also returned.
    assert just["justification_en"] == "type 3 · protection-oriented forest type"


def test_orientation_band4_upgrades_slope45_type():
    """अनुसूची-१'s own wording for types 8/9/10/13 at slope > 45° is
    "संरक्षणमुखी" -- Conservation oriented, not full Protection (corrected
    2026-09-12). The working-circle proposal still fires -- the prescribed
    behaviour (salvage-only) is unchanged, only the label was wrong."""
    ori, wc, just = propose(8, {"slope_band": 4}, _Row("Production"), P)
    assert ori == "Conservation"
    assert wc["target"] == "protection"
    assert "45" in wc["justification_en"]
    assert "general policy" not in wc["justification_en"]
    assert just["justification_en"] == "type 8 · slope > 45° · erosion-sensitive"
    # band 3 for the same type stays production
    ori2, wc2, just2 = propose(8, {"slope_band": 3}, _Row("Production"), P)
    assert ori2 == "Production" and wc2 is None
    assert "type 8" in just2["justification_en"]


def test_orientation_band4_upgrades_every_type():
    """Owner decision 2026-09-14: >45° erosion-sensitivity is a general
    policy, not limited to the four अनुसूची-१-named types (8/9/10/13). A
    type never named for this trigger (e.g. type 1) is upgraded too, and the
    reason text says honestly that this is a policy extension, not a
    guideline-verbatim clause."""
    ori, wc, just = propose(1, {"slope_band": 4}, _Row("Production"), P)
    assert ori == "Conservation"
    assert wc["target"] == "protection"
    assert "general policy" in wc["justification_en"]
    assert "general policy" in just["justification_en"]


def test_orientation_band4_never_downgrades_protection():
    """A type whose base orientation is already Protection (सि.नं. 3) is
    never downgraded to Conservation by the band-4 rule."""
    ori, wc, just = propose(3, {"slope_band": 4}, _Row("Protection"), P)
    assert ori == "Protection"
    assert wc["target"] == "protection"
    assert just["justification_en"] == "type 3 · protection-oriented forest type"


def test_type_12_is_plain_production_not_ambiguous():
    """Resolved 2026-09-15: the owner consulted the responsible official
    directly, who confirmed सि.नं. 12 is Production Oriented, matching its
    own harvest table (>200 m3/ha -> 1%, <200 -> 0.5%) and the parenthetical
    scan tag -- not ambiguous. It now carries a plain Production base with no
    slope-band-3 exception; only the general band-4 policy (every type)
    still applies to it."""
    for band in (1, 2, 3):
        ori, wc, just = propose(12, {"slope_band": band}, _Row("Production"), P)
        assert ori == "Production" and wc is None
        assert just["justification_en"] == "type 12 · Production-oriented per अनुसूची-१"
        assert "ambiguous" not in just["justification_en"]

    # Band 4 still applies (the universal policy, unrelated to type 12's
    # former ambiguity) -- type 12 is not exempt from it.
    ori4, wc4, just4 = propose(12, {"slope_band": 4}, _Row("Production"), P)
    assert ori4 == "Conservation"
    assert wc4["target"] == "protection"
    assert "general policy" in just4["justification_en"]


def test_orientation_non_ambiguous_type_band3_unaffected():
    """Band 3 (31-45°) resolves the ambiguity only for a type actually
    listed in AMBIGUOUS_ORIENTATION_TYPES (empty by default, 2026-09-15 --
    सि.नं. 12 was resolved outright, see test above) -- any other type's
    base orientation ignores this threshold entirely."""
    ori, wc, just = propose(1, {"slope_band": 3}, _Row("Production"), P)
    assert ori == "Production" and wc is None
    assert just["justification_en"] == "type 1 · Production-oriented per अनुसूची-१"


def test_ambiguous_orientation_mechanism_still_works_for_a_flagged_type(monkeypatch):
    """AMBIGUOUS_ORIENTATION_TYPES is empty now that सि.नं. 12 was resolved,
    but the band-3 resolution mechanism itself stays wired for a genuinely
    contested type found later. Proven here with a type temporarily flagged
    via monkeypatch, rather than a real type_no, since none is contested
    today."""
    import app.services.sustainable_fm.orientation as orientation_module

    monkeypatch.setattr(
        orientation_module, "AMBIGUOUS_ORIENTATION_TYPES", frozenset({99})
    )

    ori3, wc3, just3 = propose(99, {"slope_band": 3}, _Row("Production"), P)
    assert ori3 == "Conservation"
    assert wc3["target"] == "protection"
    assert "ambiguous" in just3["justification_en"]

    ori2, wc2, just2 = propose(99, {"slope_band": 2}, _Row("Production"), P)
    assert ori2 == "Production" and wc2 is None
    assert "ambiguous" in just2["justification_en"]


# ── narration ──────────────────────────────────────────────────────────
def _sfm(source="stem_mapping", series=None, summary=None, blocks=None):
    return {
        "source": source,
        "blocks": blocks or [{"effective_type_no": 1, "needs_review": False}],
        "felling_series": series
        or [
            {
                "type_no": 1,
                "method": "selection_felling_cycle",
                "C": 10,
                "R": None,
                "N": 10,
                "pct": 1.0,
                "area_ha": 100.0,
                "annual_harvest_m3": 180.0,
            }
        ],
        "forest_summary": summary
        or {
            "dominant_type_no": 1,
            "production_area_ha": 100.0,
            "protection_area_ha": 0.0,
            "total_annual_harvest_m3": 180.0,
        },
    }


def test_narration_blocks_present_and_bilingual():
    out = narr.all_blocks(_sfm())
    for key in ("methodology", "findings", "prescription"):
        assert out[key]["ne"] and out[key]["en"]
    assert "४० से.मि." in out["methodology"]["ne"]
    assert "Mean Annual Increment" in out["methodology"]["en"]
    assert "40 cm" in out["methodology"]["en"]


def test_narration_prior_source_adds_caveat():
    out = narr.findings(_sfm(source="prior"))
    assert "सूचक मात्र" in out["ne"]
    assert "indicative" in out["en"].lower()


def test_narration_protection_series_line():
    sfm = _sfm(
        series=[
            {
                "type_no": 3,
                "method": "area_coupe",
                "C": None,
                "R": None,
                "N": None,
                "pct": None,
                "area_ha": 0.0,
                "annual_harvest_m3": 0.0,
            }
        ]
    )
    out = narr.prescription(sfm)
    assert "सल्भेज" in out["ne"]
    assert "salvage" in out["en"].lower()
    # P9 — a protection working circle also gets a summary line + a findings note
    assert "कटान शून्य" in out["ne"]
    assert "zero harvest" in narr.prescription(sfm)["en"].lower()
    f = narr.findings(sfm)
    assert "संरक्षण कार्य वृत्त" in f["ne"]
    assert "protection working circle" in f["en"].lower()


# ── P9 narration polish ──────────────────────────────────────────────
def test_narration_empty_state_when_no_blocks():
    empty = {
        "source": "prior",
        "blocks": [],
        "felling_series": [],
        "forest_summary": {},
    }
    m = narr.methodology(empty)
    f = narr.findings(empty)
    assert "वर्गीकृत भएको छैन" in m["ne"]
    assert "not been built" in f["en"]


def test_narration_field_inventory_estimate_caveat():
    m = narr.methodology(_sfm(source="field_inventory"))
    assert "अनुमानित" in m["ne"]
    assert "estimated from the" in m["en"]
    # stem mapping (full census) has no such caveat
    assert "estimated from the" not in narr.methodology(_sfm())["en"]


def test_narration_inner_terai_wording():
    sfm = _sfm()
    sfm["zone_by_block"] = {"Block-1": {"sfm_zone": "LOWLAND_SAL", "inner_terai": True}}
    m = narr.methodology(sfm)
    assert "भित्री मधेश" in m["ne"]
    assert "Inner Terai" in m["en"]
