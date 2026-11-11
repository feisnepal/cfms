"""Sustainable Forest Management OP data wiring (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P6).

``data_collector.get_sustainable_fm_data`` is read-only (never builds
``result_data['sfm']``), never raises, returns a JSON-serialisable dict keyed by
the exact ``sfm_*`` variable names, and yields empty-state strings — not a
``KeyError`` — when the classification has not been built. Every ``sfm_*``
variable is registered under section S3 and routes through the resolver + the
DOCX raw-var lookup.
"""

from __future__ import annotations

import json
import uuid

from app.models.calculation import Calculation
from app.models.user import User, UserRole
from app.services.operational_plan import variable_registry as vr
from app.services.operational_plan.data_collector import (
    OP_DATA_CACHE_VERSION,
    get_sustainable_fm_data,
)

_SCALAR_KEYS = (
    "sfm_dominant_type_ne",
    "sfm_dominant_type_en",
    "sfm_total_annual_harvest_m3",
    "sfm_production_area_ha",
    "sfm_protection_area_ha",
    "sfm_plan_regime_note",
    "sfm_sampling_intensity_note",
    "sfm_felling_series_note",
    "sfm_methodology",
    "sfm_findings",
    "sfm_prescription",
)
_LIST_KEYS = (
    "sfm_block_prescription_table",
    "sfm_type_area_table",
    "sfm_yield_table",
    "sfm_working_circle_table",
    "sfm_sampling_plan_table",
)


def test_cache_version_bumped_to_24():
    assert OP_DATA_CACHE_VERSION >= 24


def _calc(db, *, sfm=None, regime=None):
    u = User(
        email=f"sfmop{uuid.uuid4().hex[:8]}@t.com",
        full_name="x",
        role=UserRole.USER,
        hashed_password="x",
    )
    db.add(u)
    db.flush()
    c = Calculation(
        id=str(uuid.uuid4()),
        user_id=u.id,
        uploaded_filename="x.csv",
        is_draft=False,
        structure_locked=False,
        result_data={"sfm": sfm} if sfm is not None else {},
    )
    db.add(c)
    db.flush()
    if regime is not None:
        from app.models.operational_plan import OperationalPlan

        db.add(
            OperationalPlan(
                calculation_id=c.id,
                status="draft",
                plan_metadata={"template_regime": regime},
            )
        )
        db.flush()
    return c


# ── empty state ────────────────────────────────────────────────────────────
def test_empty_path_shape(db):
    d = get_sustainable_fm_data(db, str(uuid.uuid4()))
    assert d["sfm_available"] is False
    for k in _LIST_KEYS:
        assert d[k] == [], k
    for k in _SCALAR_KEYS:
        assert k in d  # never a KeyError
    # empty-state strings, not blanks
    assert d["sfm_methodology"] and d["sfm_findings"]
    assert d["sfm_total_annual_harvest_m3"] is None
    json.dumps(d)  # serialisable


def test_plan_regime_note_only_for_sustainable_fmp(db):
    other = _calc(db, regime="brief_fmp")
    assert get_sustainable_fm_data(db, str(other.id))["sfm_plan_regime_note"] == ""

    sfmp = _calc(db, regime="sustainable_fmp")
    note = get_sustainable_fm_data(db, str(sfmp.id))["sfm_plan_regime_note"]
    assert "दिगो वन व्यवस्थापन" in note and "MAI" in note


# ── populated ──────────────────────────────────────────────────────────────
_SFM_BLOCK = {
    "version": 1,
    "source": "stem_mapping",
    "zone_by_block": {
        "Block-1": {"sfm_zone": "LOWLAND_SAL", "slope_band": 1},
        "Block-2": {"sfm_zone": "HILL", "slope_band": 3},
    },
    "blocks": [
        {
            "block_name": "Block-1",
            "area_ha": 60.0,
            "effective_type_no": 1,
            "proposed_type_no": 1,
            "needs_review": False,
            "orientation": "Production",
            "working_circle_proposal": None,
            "inputs": {"gs_ge40_m3_per_ha": 210.0, "source": "stem_mapping"},
            "prescription": {
                "type_no": 1,
                "type_name_ne": "तराई/शिवालिक साल वन",
                "type_name_en": "Terai & Siwalik Sal forest",
                "system_ne": "छनौट प्रणाली",
                "system_en": "Selection system",
                "felling_cycle_years": 10,
                "regeneration_period_years": None,
            },
        },
        {
            "block_name": "Block-2",
            "area_ha": 40.0,
            "effective_type_no": 3,
            "proposed_type_no": 2,
            "needs_review": True,
            "orientation": "Protection",
            "working_circle_proposal": {
                "target": "protection",
                "justification_ne": "३१ डिग्रीभन्दा बढी भिरालो",
                "justification_en": "slope > 31 deg",
            },
            "inputs": {"gs_ge40_m3_per_ha": 90.0, "source": "stem_mapping"},
            "prescription": {
                "type_no": 3,
                "type_name_ne": "शिवालिक साल वन: > ३१°",
                "type_name_en": "Siwalik Sal forest, slope > 31 deg",
                "system_ne": "—",
                "system_en": "—",
            },
        },
    ],
    "felling_series": [
        {
            "id": 1,
            "type_no": 1,
            "method": "selection_felling_cycle",
            "C": 10,
            "R": None,
            "N": 10,
            "area_ha": 60.0,
            "gs_ge40_m3": 12600.0,
            "gs_ge40_m3_per_ha": 210.0,
            "pct": 2.0,
            "annual_harvest_m3": 252.0,
            "note_ne": "",
            "note_en": "",
        },
        {
            "id": 3,
            "type_no": 3,
            "method": "area_coupe",
            "C": None,
            "R": None,
            "N": None,
            "area_ha": 0.0,
            "gs_ge40_m3": None,
            "pct": None,
            "annual_harvest_m3": 0.0,
            "note_ne": "संरक्षणमुखी",
            "note_en": "Protection stratum",
        },
    ],
    "forest_summary": {
        "dominant_type_no": 1,
        "type_area_breakdown": {"1": 60.0, "3": 40.0},
        "production_area_ha": 60.0,
        "protection_area_ha": 40.0,
        "total_annual_harvest_m3": 252.0,
        "sampling_plan": [
            {
                "block_name": "Block-1",
                "stratum": "production",
                "intensity_pct": 2.0,
                "plot_size_sqm": 500,
                "plots": 24,
            },
            {
                "block_name": "Block-2",
                "stratum": "protection",
                "intensity_pct": 0.5,
                "plot_size_sqm": 100,
                "plots": 20,
            },
        ],
    },
}


def test_populated_shape(db):
    calc = _calc(db, sfm=_SFM_BLOCK)
    d = get_sustainable_fm_data(db, str(calc.id))

    assert d["sfm_available"] is True
    assert d["sfm_dominant_type_ne"] == "तराई/शिवालिक साल वन"
    assert d["sfm_total_annual_harvest_m3"] == 252.0
    assert d["sfm_production_area_ha"] == 60.0
    assert d["sfm_protection_area_ha"] == 40.0
    assert "MAI" not in d["sfm_plan_regime_note"]  # no OP → no regime note
    assert d["sfm_sampling_intensity_note"]

    pt = d["sfm_block_prescription_table"]
    assert len(pt) == 2
    assert pt[0]["खण्ड"] == "Block-1" and pt[0]["सि.नं."] == 1
    assert pt[0]["प्रणाली"] == "छनौट प्रणाली"
    assert pt[0]["भिरालो वर्ग"] == "< १९°"
    assert pt[1]["पुनरावलोकन"] == "आवश्यक"

    ta = d["sfm_type_area_table"]
    assert {r["सि.नं."] for r in ta} == {1, 3}
    assert abs(sum(r["प्रतिशत"] for r in ta) - 100.0) < 0.5

    yt = d["sfm_yield_table"]
    assert len(yt) == 2
    assert yt[0]["वार्षिक कटान (घन.मी.)"] == 252.0
    assert yt[0]["विधि"] == "छनौट — कटान चक्र"

    wc = d["sfm_working_circle_table"]
    assert wc[1]["अभिमुखीकरण"] == "प्रतिरक्षा"

    sp = d["sfm_sampling_plan_table"]
    assert {r["स्तर"] for r in sp} == {"उत्पादन", "प्रतिरक्षा"}

    assert d["sfm_methodology"] and d["sfm_findings"] and d["sfm_prescription"]
    json.dumps(d)


# ── registry / wiring ──────────────────────────────────────────────────────
def test_all_sfm_vars_registered_under_s3():
    sfm = vr.get_variables_by_source("sustainable_fm")
    keys = {v.key for v in sfm}
    for expect in _SCALAR_KEYS + _LIST_KEYS:
        assert expect in keys, expect
    for v in sfm:
        assert v.category == "A", v.key
        assert v.section == "S3", v.key
        assert v.label_ne and v.label_en, v.key


def test_list_vars_typed_list():
    for key in _LIST_KEYS:
        v = vr.get_variable(key)
        assert v is not None and v.var_type == "list", key


def test_resolver_and_docx_scan_include_sustainable_fm():
    import inspect

    from app.services.operational_plan import op_docx_builder as odb
    from app.services.operational_plan.variable_resolver import VariableResolver

    assert '"sustainable_fm": "sustainable_fm"' in inspect.getsource(
        VariableResolver.__dict__["_resolve_category_a"]
    )
    assert '"sustainable_fm"' in inspect.getsource(odb._resolve_var_from_raw)


def test_seed_tree_has_the_sfm_subsection():
    from app.services.operational_plan.seed_data import get_default_seed_tree
    from app.services.operational_plan.tree_models import TreeOperations

    titles = {n.title_en for n in TreeOperations.flatten(get_default_seed_tree())}
    assert any("Sustainable Forest Management" in t for t in titles)


def test_seed_node_resolves_without_raising(db, monkeypatch):
    """The ३.१० content, run through the real resolver with a stubbed raw
    payload, substitutes its scalar tokens and leaves the list/map tokens for
    op_docx_builder — no exception."""
    from app.models.operational_plan import OperationalPlan
    from app.services.operational_plan.seed_data import get_default_seed_tree
    from app.services.operational_plan.tree_models import TreeOperations
    from app.services.operational_plan.variable_resolver import VariableResolver

    calc = _calc(db, sfm=_SFM_BLOCK)
    plan = OperationalPlan(
        calculation_id=calc.id, status="draft", plan_metadata={}
    )
    resolver = VariableResolver(db, calc.id, plan)
    monkeypatch.setattr(
        resolver,
        "get_raw_data",
        lambda: {
            "basic_info": {"unit_label_np": "ब्लक"},
            "sustainable_fm": get_sustainable_fm_data(db, str(calc.id)),
        },
    )

    node = next(
        n
        for n in TreeOperations.flatten(get_default_seed_tree())
        if "Sustainable Forest Management" in (n.title_en or "")
    )
    out = resolver.resolve_node_content(node.content)
    # scalar tokens are substituted (gone from the text)…
    assert "{{sfm_total_annual_harvest_m3}}" not in out
    assert "{{sfm_methodology}}" not in out
    assert "{{sfm_plan_regime_note}}" not in out  # empty string → removed
    # …list + map tokens are left verbatim for the docx pass
    assert "{{sfm_yield_table}}" in out
    assert "{{sfm_block_prescription_table}}" in out
    assert "{{thememap:sfm__forest_type}}" in out
    # the harvest number rendered in Devanagari numerals
    assert "२५२" in out
