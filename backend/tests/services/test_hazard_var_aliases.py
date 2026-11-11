"""HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P1 — the canonical `hazard_*` naming
layer over the Hazard & Erosion variables.

Every value on the Hazard & Erosion page now has one descriptive `hazard_*`
key. The legacy keys (`soil_loss_*` / `lsi_* `/ `fs_*` / `hh_*`) stay registered
and resolvable so already-authored templates keep working; the picker hides
them (``alias_of`` set).
"""

from __future__ import annotations

import uuid

import pytest

from app.services.operational_plan import variable_registry as vr
from app.services.operational_plan.variable_registry import (
    LEGACY_TO_CANONICAL,
    VARIABLE_ALIASES,
    VARIABLE_REGISTRY,
    get_variable,
    search_variables,
)
from app.services.operational_plan.variable_resolver import VariableResolver

# a synthetic collector payload — one entry per legacy key the aliases point at
_RAW = {
    "soil_erosion": {
        "soil_loss_mean_t_ha": 16.9,
        "soil_loss_total_t_yr": 8760.0,
        "soil_loss_area_ha": 518.0,
        "soil_loss_tolerable": 10.0,
        "soil_loss_pct_above_tolerable": 41.0,
        "soil_loss_by_unit": [{"unit": "B1", "t_ha": 12.0}],
        "soil_loss_hotspot_units_str": "B3 · B7",
        "soil_loss_dominant_factor": "C",
        "soil_loss_r_method": "arnoldus_mfi",
        "soil_loss_assumptions": ["a1", "a2"],
        "soil_loss_ug_mean_t_ha": 51.8,
        "soil_loss_ug_total_t_yr": 12000.0,
        "soil_loss_ug_minus_cf_mean_t_ha": 60.1,
        "soil_loss_ug_minus_cf_total_t_yr": 9000.0,
        "soil_loss_aoi_comparison": [{"area": "CF", "mean": 16.9}],
        "soil_loss_delivered_t_yr": 537.0,
        "soil_loss_delivered_ug_t_yr": 700.0,
        "soil_loss_basin_sdr": 0.06,
        "soil_loss_methodology_narration": "विधि …",
        "soil_loss_methodology_narration_en": "Method …",
        "soil_loss_findings_narration": "निष्कर्ष …",
        "soil_loss_findings_narration_en": "Findings …",
        "soil_loss_prescription_narration": "निर्देशन …",
        "soil_loss_prescription_narration_en": "Prescription …",
        # P2 — previously unregistered scalars
        "soil_loss_customised": True,
        "soil_loss_sdr_enabled": False,
        "soil_loss_sdr_mean": 0.06,
        "soil_loss_severity_breaks": [1.0, 5.0, 10.0, 20.0],
        "soil_loss_ug_area_ha": 900.0,
        "soil_loss_ug_minus_cf_area_ha": 382.0,
        "hazard_erosion_full_narration": "माटो क्षय — विधि\n…",
    },
    "hazard_vuln": {
        "lsi_prone_area_ha": 217.0,
        "lsi_prone_area_pct": 42.0,
        "lsi_area_by_class": [{"class": "उच्च", "ha": 100.0}],
        "lsi_by_unit": [{"unit": "B1", "class": "मध्यम"}],
        "lsi_high_units_str": "B3 · B2",
        "lsi_class_method": "quantile",
        "lsi_consistency_ratio": 0.03,
        "hazard_aoi_comparison": [{"area": "CF", "prone_pct": 42.0}],
        "fs_enabled": "true",
        "fs_unstable_area_ha": 0.0,
        "fs_unstable_pct": 0.0,
        "fs_marginal_pct": 14.7,
        "fs_scenario_note": "मनसुन …",
        "fs_scenario_note_en": "Monsoon …",
        "fs_by_unit": [{"unit": "B1", "marginal_pct": 5.0}],
        "hh_count": 99,
        "hh_priority_count": 15,
        "hh_mean_score": 0.4,
        "hh_hazard_layer_informative": "true",
        "hh_priority_table": [{"घर_नं": 1, "अंक": 0.8}],
        "hh_settlement_rollup_table": [{"टोल": "गाउँ-1", "प्राथमिकता": 2}],
        "hh_driver_counts": [{"कारक": "भौतिक", "घरधुरी": 26}],
        "hazard_methodology_narration": "पहिरो विधि …",
        "hazard_findings_narration": "पहिरो निष्कर्ष …",
        "hazard_prescription_narration": "पहिरो निर्देशन …",
        # P2 — previously unregistered scalars
        "lsi_customised": False,
        "fs_marginal_area_ha": 76.1,
        "fs_depth_mean_m": 2.1,
        "hh_max_score": 0.91,
        "hh_coord_source": "building_footprint",
    },
}


def _resolver() -> VariableResolver:
    r = VariableResolver(db=None, calculation_id=uuid.uuid4(), plan=None)
    r._raw_data = _RAW
    return r


def test_alias_map_is_non_empty_and_covers_all_four_groups():
    prefixes = {k.split("_")[1] for k in VARIABLE_ALIASES}
    assert {"erosion", "landslide", "slope", "household"} <= prefixes
    assert len(VARIABLE_ALIASES) >= 40


def test_every_canonical_key_is_registered_and_not_itself_an_alias():
    for canon in VARIABLE_ALIASES:
        v = get_variable(canon)
        assert v is not None, canon
        assert v.alias_of == "", canon
        assert v.section == "S9", canon
        assert v.category == "A", canon
        assert v.label_ne and v.label_en, canon


# P1 aliases point at a key that already had its own _reg entry (now marked
# alias_of); P2 aliases point at a raw-payload-only collector key with no _reg.
_LEGACY_REGISTERED = {c: l for c, l in VARIABLE_ALIASES.items() if l in VARIABLE_REGISTRY}
_LEGACY_RAW_ONLY = {c: l for c, l in VARIABLE_ALIASES.items() if l not in VARIABLE_REGISTRY}


def test_every_registered_legacy_key_is_marked_alias():
    assert _LEGACY_REGISTERED  # P1 set is non-empty
    for canon, legacy in _LEGACY_REGISTERED.items():
        v = get_variable(legacy)
        assert v is not None and v.alias_of == canon, legacy


def test_raw_only_legacy_keys_have_no_registry_entry():
    # the 11 P2 scalars: their canonical key is the only registered form
    assert _LEGACY_RAW_ONLY  # non-empty after P2
    for legacy in _LEGACY_RAW_ONLY.values():
        assert get_variable(legacy) is None, legacy


def test_reverse_map_round_trips():
    for canon, legacy in VARIABLE_ALIASES.items():
        assert LEGACY_TO_CANONICAL[legacy] == canon


@pytest.mark.parametrize("canon,legacy", list(VARIABLE_ALIASES.items()))
def test_canonical_resolves_via_its_legacy_payload_slot(canon, legacy):
    r = _resolver()
    section = "soil_erosion" if legacy in _RAW["soil_erosion"] else "hazard_vuln"
    expected = _RAW[section][legacy]
    assert r._resolve_category_a(VARIABLE_REGISTRY[canon]) == expected


def test_search_hazard_returns_the_full_canonical_set_without_legacy_dupes():
    hits = {v.key for v in search_variables("hazard_")}
    # every canonical key present
    assert set(VARIABLE_ALIASES) <= hits
    # a legacy key that does not itself start "hazard_" is not a search hit here
    assert "lsi_prone_area_ha" not in hits
    assert "soil_loss_mean_t_ha" not in hits


def test_docx_builder_falls_through_alias():
    from app.services.operational_plan.op_docx_builder import _resolve_var_from_raw

    assert _resolve_var_from_raw("hazard_landslide_prone_area_pct", _RAW) == 42.0
    assert _resolve_var_from_raw("hazard_erosion_mean_t_ha", _RAW) == 16.9
    assert (
        _resolve_var_from_raw("hazard_household_priority_table", _RAW)
        == _RAW["hazard_vuln"]["hh_priority_table"]
    )


def test_cache_version_bumped_for_full_narration():
    # P2 adds hazard_erosion_full_narration to the collector payload.
    from app.services.operational_plan.data_collector import OP_DATA_CACHE_VERSION

    assert OP_DATA_CACHE_VERSION >= 22


def test_p2_previously_unregistered_scalars_are_now_registered():
    p2 = [
        "hazard_erosion_customised",
        "hazard_erosion_sdr_enabled",
        "hazard_erosion_sdr_mean",
        "hazard_erosion_severity_breaks",
        "hazard_erosion_ug_area_ha",
        "hazard_erosion_ug_minus_cf_area_ha",
        "hazard_landslide_customised",
        "hazard_slope_marginal_area_ha",
        "hazard_slope_depth_mean_m",
        "hazard_household_max_score",
        "hazard_household_coord_source",
    ]
    for k in p2:
        v = get_variable(k)
        assert v is not None and v.section == "S9" and v.alias_of == "", k
        assert k in VARIABLE_ALIASES, k
        # resolves through the alias fall-through
        assert _resolver()._resolve_category_a(VARIABLE_REGISTRY[k]) is not None, k


def test_full_narration_variable_registered_and_assembles():
    from app.services.operational_plan.data_collector import (
        _assemble_hazard_full_narration,
    )

    assert get_variable("hazard_erosion_full_narration") is not None
    txt = _assemble_hazard_full_narration(
        _RAW["soil_erosion"], _RAW["hazard_vuln"]
    )
    assert "माटो क्षय — विधि" in txt and "पहिरो र घरधुरी जोखिम — निष्कर्ष" in txt
    assert _assemble_hazard_full_narration({}, {}) == ""


def test_no_duplicate_registry_keys_and_enrichment_section_present():
    from app.services.operational_plan.variable_enrichment import SUB_GROUPS

    for canon in VARIABLE_ALIASES:
        assert canon in VARIABLE_REGISTRY
        assert SUB_GROUPS.get(canon, "").startswith("9"), canon
