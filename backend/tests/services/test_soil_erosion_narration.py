"""RUSLE soil-loss narration — the three adaptive paragraphs (P4)."""

from __future__ import annotations

import pytest

from app.services.operational_plan import soil_erosion_narration as nar

_BASE = {
    "soil_loss_available": True,
    "soil_loss_mean_t_ha": 16.9,
    "soil_loss_total_t_yr": 9265.0,
    "soil_loss_area_ha": 547.7,
    "soil_loss_tolerable": 10.0,
    "soil_loss_pct_above_tolerable": 41.0,
    "soil_loss_dominant_factor": "C",
    "soil_loss_r_method": "mfi",
    "soil_loss_severity_breaks": [5, 10, 20, 40, 80],
    "soil_loss_hotspot_units_str": "blocks-5 · blocks-2",
    "soil_loss_assumptions": ["क", "ख"],
    "soil_loss_assumptions_en": ["a", "b"],
    "soil_loss_params_provenance": {
        "r_method": "default",
        "slope_length_cap_m": "default",
    },
    "soil_loss_ug_minus_cf_mean_t_ha": 51.8,
}


def test_unavailable_degrades_to_one_sentence():
    d = {"soil_loss_available": False}
    for fn in (nar.methodology, nar.findings, nar.prescription):
        for lang in ("ne", "en"):
            txt = fn(d, lang)
            assert txt and "\n" not in txt.strip()


def test_methodology_names_method_and_flags_customised():
    ne = nar.methodology(_BASE, "ne")
    assert "Arnoldus 1980" in ne and "5, 10, 20, 40, 80" in ne
    assert "समायोजन" not in ne  # all-default provenance → no customised note

    cust = {**_BASE, "soil_loss_params_provenance": {"slope_length_cap_m": "forest"}}
    assert "समायोजन" in nar.methodology(cust, "ne")
    assert "customised" in nar.methodology(cust, "en").lower()


def test_findings_reports_mean_pct_dominant_hotspots_and_ug():
    ne = nar.findings(_BASE, "ne")
    assert "16.9" in ne and "41.0%" in ne
    assert "भू-आवरण तथा व्यवस्थापन (C)" in ne
    assert "blocks-5 · blocks-2" in ne
    assert "51.8" in ne  # the UG-minus-CF line
    en = nar.findings(_BASE, "en")
    assert "above the tolerable limit" in en and "cover management (C)" in en


def test_findings_says_within_when_below_tolerable():
    d = {**_BASE, "soil_loss_mean_t_ha": 4.0, "soil_loss_pct_above_tolerable": 3.0}
    assert "सह्य सीमाभित्र" in nar.findings(d, "ne")
    assert "within the tolerable limit" in nar.findings(d, "en")


@pytest.mark.parametrize(
    "dom,needle_ne",
    [
        ("LS", "भू-प्राविधिक"),
        ("C", "छत्र-घनत्व"),
        ("K", "मल्चिङ"),
        ("R", "पानी निकास"),
    ],
)
def test_prescription_switches_on_dominant_factor(dom, needle_ne):
    d = {**_BASE, "soil_loss_dominant_factor": dom}
    assert needle_ne in nar.prescription(d, "ne")


def test_prescription_adds_ug_clause_only_when_catchment_much_worse():
    with_ug = nar.prescription(_BASE, "ne")  # ug 51.8 >> cf 16.9
    assert "वैकल्पिक ऊर्जा" in with_ug and "विपन्न घरधुरी" in with_ug
    close = {**_BASE, "soil_loss_ug_minus_cf_mean_t_ha": 18.0}
    assert "वैकल्पिक ऊर्जा" not in nar.prescription(close, "ne")


def test_all_narration_has_six_keys():
    keys = set(nar.all_narration(_BASE))
    assert keys == {
        "soil_loss_methodology_narration",
        "soil_loss_methodology_narration_en",
        "soil_loss_findings_narration",
        "soil_loss_findings_narration_en",
        "soil_loss_prescription_narration",
        "soil_loss_prescription_narration_en",
    }
