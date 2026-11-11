"""Hazard + household-vulnerability narration (P6).

``hazard_vuln_narration`` — three adaptive bilingual paragraphs from the
``get_hazard_vuln_data`` dict; a one-sentence fallback when the hazard layer is
unavailable. Pure functions, no DB.
"""

from __future__ import annotations

import pytest

from app.services.operational_plan import hazard_vuln_narration as n

_FULL = {
    "hazard_vuln_available": True,
    "lsi_prone_area_ha": 231.6,
    "lsi_prone_area_pct": 42.0,
    "lsi_high_units_str": "क-३ · क-२",
    "lsi_class_method": "quantile",
    "lsi_consistency_ratio": 0.0,
    "lsi_customised": False,
    "fs_enabled": True,
    "fs_unstable_pct": 0.4,
    "fs_marginal_pct": 14.7,
    "fs_scenario_note": "FS मनसुन परिदृश्य टिप्पणी।",
    "fs_scenario_note_en": "FS monsoon scenario note.",
    "hazard_assumptions": ["मान्यता १", "मान्यता २"],
    "hazard_assumptions_en": ["Assumption 1", "Assumption 2"],
    "hh_count": 99,
    "hh_priority_count": 15,
    "hh_hazard_layer_informative": True,
    "hh_driver_counts": [
        {"कारक": "Social marginalisation", "घरधुरी": 52},
        {"कारक": "Economic status", "घरधुरी": 33},
        {"कारक": "Physical hazard exposure", "घरधुरी": 0},
    ],
    "hh_settlement_rollup_table": [
        {"टोल": "गाउँ-15", "प्राथमिकता": 2},
        {"टोल": "गाउँ-5", "प्राथमिकता": 1},
        {"टोल": "गाउँ-9", "प्राथमिकता": 0},
    ],
    "hazard_aoi_comparison": [
        {"क्षेत्र": "सामुदायिक वन", "सापेक्ष_उच्च_%": 42.0},
        {"क्षेत्र": "वन बाहिरको बस्ती भूमि", "सापेक्ष_उच्च_%": 30.0},
    ],
}


@pytest.mark.parametrize("lang", ["ne", "en"])
def test_all_three_paragraphs_render_when_available(lang):
    for fn in (n.methodology, n.findings, n.prescription):
        s = fn(_FULL, lang)
        assert isinstance(s, str) and len(s) > 60


def test_all_narration_returns_the_six_keys():
    out = n.all_narration(_FULL)
    assert set(out) == {
        "hazard_methodology_narration",
        "hazard_methodology_narration_en",
        "hazard_findings_narration",
        "hazard_findings_narration_en",
        "hazard_prescription_narration",
        "hazard_prescription_narration_en",
    }
    assert all(v for v in out.values())


def test_findings_mentions_prone_pct_worst_units_and_household_count():
    en = n.findings(_FULL, "en")
    assert "42.0%" in en and "क-३" in en and "99" in en
    assert "social marginalisation" in en.lower()


def test_findings_flags_non_informative_hazard_layer():
    d = {**_FULL, "hh_hazard_layer_informative": False}
    en = n.findings(d, "en")
    assert "coordinates were not precise enough" in en
    ne = n.findings(d, "ne")
    assert "निर्देशांक" in ne


def test_findings_notes_building_footprint_fallback_at_settlement_granularity():
    # P10 — survey coords replaced by building footprints; the caveat is a
    # settlement-granularity note, not the "socio-economic only" one.
    d = {
        **_FULL,
        "hh_coord_source": "building_footprint",
        "hh_hazard_layer_informative": False,
    }
    en = n.findings(d, "en")
    assert "settlement granularity" in en
    assert "coordinates were not precise enough" not in en
    ne = n.findings(d, "ne")
    assert "बस्ती स्तरको" in ne


def test_methodology_flags_customised_params():
    d = {**_FULL, "lsi_customised": True}
    assert "customised for this forest" in n.methodology(d, "en")
    assert "समायोजन" in n.methodology(d, "ne")


def test_methodology_carries_the_fs_scenario_note():
    assert "monsoon scenario note" in n.methodology(_FULL, "en")


def test_prescription_names_the_priority_toles_and_driver_action():
    en = n.prescription(_FULL, "en")
    assert "गाउँ-15" in en
    assert "Dalit / Janajati" in en  # Social marginalisation → its EN action


def test_prescription_extends_to_the_settlement_land_when_ug_prone_ge_cf():
    # aoi: CF 42, UG-outside 30 → not >= , so no settlement-land clause
    assert "settlement land outside the forest" not in n.prescription(_FULL, "en")
    d = {
        **_FULL,
        "hazard_aoi_comparison": [
            {"क्षेत्र": "सामुदायिक वन", "सापेक्ष_उच्च_%": 30.0},
            {"क्षेत्र": "वन बाहिरको बस्ती भूमि", "सापेक्ष_उच्च_%": 45.0},
        ],
    }
    assert "settlement land outside the forest" in n.prescription(d, "en")


@pytest.mark.parametrize("lang", ["ne", "en"])
def test_one_sentence_fallback_when_unavailable(lang):
    d = {"hazard_vuln_available": False}
    for fn in (n.methodology, n.findings, n.prescription):
        s = fn(d, lang)
        assert isinstance(s, str) and 20 < len(s) < 400
        assert "\n" not in s.strip()  # a single sentence, no bullet list
