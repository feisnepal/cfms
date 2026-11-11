"""
Tests for the DBH classification SSOT module (app.core.dbh_classifier).

Covers all public functions, the DbhClassRegistry, and the classify API
endpoint.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.dbh_classifier import (
    DbhClassRegistry,
    DbhClassDef,
    classify_simple,
    classify_detailed,
    classify_with_guideline,
    generate_class_filters,
    generate_case_statement,
    generate_case_pole_tree_sort,
    generate_excel_dbh_formula,
    generate_excel_plot_factor_formula,
    FALLBACK_LABEL_FORMATS,
    _FALLBACK_CLASS_DEFS,
)


# ── A. classify_simple ─────────────────────────────────────────

def test_classify_simple_seedling():
    assert classify_simple(2) == "Seedling", "DBH=2 should map to Seedling"


def test_classify_simple_sapling():
    assert classify_simple(6) == "Sapling", "DBH=6 should map to Sapling"


def test_classify_simple_pole():
    assert classify_simple(15) == "Pole", "DBH=15 should map to Pole"


def test_classify_simple_tree():
    assert classify_simple(45) == "Tree", "DBH=45 should map to Tree"


# ── B. classify_detailed ───────────────────────────────────────

def test_classify_detailed_all_8():
    cases = [
        (2, "Seedling (0-4)"),
        (6, "Sapling (4-10)"),
        (15, "Sm. Pole (10-20)"),
        (25, "Lg. Pole (20-30)"),
        (35, "Sm. Tree (30-40)"),
        (45, "Med. Tree (40-50)"),
        (55, "Lg. Tree (50-60)"),
        (65, "V. Lg. Tree (60+)"),
    ]
    for dbh, expected in cases:
        result = classify_detailed(dbh)
        assert result == expected, f"DBH={dbh}: expected '{expected}', got '{result}'"


def test_classify_boundary_exact():
    assert classify_detailed(4) == "Sapling (4-10)", "DBH=4 → Sapling (not Seedling)"
    assert classify_detailed(10) == "Sm. Pole (10-20)", "DBH=10 → Sm. Pole (not Sapling)"
    assert classify_detailed(30) == "Sm. Tree (30-40)", "DBH=30 → Sm. Tree (not Pole)"


def test_classify_above_max():
    assert classify_detailed(999) == "V. Lg. Tree (60+)", "DBH=999 → V. Lg. Tree"


# ── C. classify_with_guideline ────────────────────────────────

def test_harvesting_cfmg():
    assert classify_with_guideline(5) == "Regeneration", "DBH=5 → Regeneration"
    assert classify_with_guideline(25) == "Advance Growth", "DBH=25 → Advance Growth"
    assert classify_with_guideline(50) == "Mature Tree", "DBH=50 → Mature Tree"


# ── D. DbhClassDef dataclass ───────────────────────────────────

def test_dbh_class_def_contains():
    cls = DbhClassDef(key="test", lower=0, upper=10, label_en="T", label_np="ट")
    assert cls.contains(5) is True, "5 must be in [0, 10)"
    assert cls.contains(0) is True, "lower bound is inclusive"
    assert cls.contains(10) is False, "upper bound is exclusive"
    assert cls.contains(-1) is False, "negative DBH must not match"


def test_dbh_class_def_no_upper():
    cls = DbhClassDef(key="test", lower=0, upper=None, label_en="T", label_np="ट")
    assert cls.contains(5) is True, "5 >= 0 with no upper bound"
    assert cls.contains(999) is True, "999 >= 0 with no upper bound"
    assert cls.contains(-1) is False, "-1 < 0"


# ── E. DbhClassRegistry ───────────────────────────────────────

def test_get_system_guideline_2061():
    classes = DbhClassRegistry.get_system("guideline_2061")
    assert len(classes) == 8, "guideline_2061 should define exactly 8 classes"
    assert classes[0].key == "0_4", f"first class key should be '0_4', got '{classes[0].key}'"
    assert classes[-1].key == "60_plus", f"last class key should be '60_plus', got '{classes[-1].key}'"


def test_get_system_unknown():
    with pytest.raises(ValueError, match="Unknown classification system"):
        DbhClassRegistry.get_system("nonexistent_system")


def test_classify_registry():
    result = DbhClassRegistry.classify(25.5, "guideline_2061")
    assert result is not None, "classify(25.5) must return a DbhClassDef"
    assert result.key == "20_30", f"expected key '20_30', got '{result.key}'"
    assert result.lower == 20
    assert result.upper == 30


def test_classify_no_match():
    result = DbhClassRegistry.classify(-1, "guideline_simple")
    assert result is None, "classify(-1) must return None (no class matches negative DBH)"


# ── F. Format labels ──────────────────────────────────────────

def test_format_label_detailed():
    label = DbhClassRegistry.format_label("10_20", "detailed")
    assert label == "Sm. Pole (10-20)", f"expected 'Sm. Pole (10-20)', got '{label}'"


def test_format_label_np():
    label = DbhClassRegistry.format_label("10_20", "np_detailed")
    # Nepali Unicode range: 0x0900–0x097F; Nepali digits: 0x0966–0x096F
    assert any(ord(c) > 0x0900 for c in label), "label must contain Nepali Unicode characters"
    assert "१" in label or "०" in label, "label must contain Nepali digits (e.g. १, ०)"


def test_format_label_space_dash():
    label = DbhClassRegistry.format_label("Sm. Pole (10-20)", "space_dash")
    assert label == "10-20 Sm.Pole", f"expected '10-20 Sm.Pole', got '{label}'"


# ── G. SQL Generators ─────────────────────────────────────────

def test_generate_class_filters():
    result = generate_class_filters()
    assert "COUNT(*) FILTER" in result, "output must contain FILTER aggregate clause"
    for key in ("0_4", "4_10", "10_20", "20_30", "30_40", "40_50", "50_60", "60_plus"):
        assert key in result, f"output must reference class key '{key}'"


def test_generate_case_statement():
    result = generate_case_statement()
    assert "CASE" in result
    assert "WHEN" in result
    assert "THEN 'Seedling'" in result
    assert "THEN 'Sapling'" in result
    assert "THEN 'Pole'" in result
    assert "THEN 'Tree'" in result
    assert "ELSE 'Unknown'" in result
    assert "END" in result


def test_generate_case_pole_tree_sort():
    result = generate_case_pole_tree_sort()
    assert "CASE m.dbh_class" in result, "must start with CASE on m.dbh_class"
    for label in ("Sm. Pole", "Lg. Pole", "Sm. Tree", "Med. Tree", "Lg. Tree", "V. Lg. Tree"):
        assert label in result, f"output must contain '{label}'"
    assert "ELSE 9" in result, "unmatched classes must default to 9"


# ── H. Excel Formula Generators ───────────────────────────────

def test_generate_excel_dbh_formula():
    result = generate_excel_dbh_formula()
    assert result.startswith("=IF("), f"formula must start with '=IF(', got: {result[:30]}"
    for label in ("0-4 Seedling", "4-10 Sapling", "10-20 Sm.Pole", "20-30 Lg.Pole",
                  "30-40 Sm.Tree", "40-50 Med.Tree", "50-60 Lg.Tree", "60+ V.Lg.Tree"):
        assert label in result, f"output must contain label '{label}'"


def test_generate_excel_plot_factor_formula():
    result = generate_excel_plot_factor_formula()
    for factor in ("1000", "400", "100", "20"):
        assert factor in result, f"output must contain expansion factor {factor}"
    assert result.startswith("IF("), f"formula must start with 'IF(', got: {result[:30]}"


# ── I. API endpoint ───────────────────────────────────────────

def test_api_classify_endpoint(client, auth_headers):
    # H2.3 / S1-03: this route used to take no credentials at all.
    resp = client.post("/api/dbh-classes/classify?dbh=25.5&system=guideline_2061",
                       headers=auth_headers)
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["key"] == "20_30", f"expected key '20_30', got '{body.get('key')}'"
    assert body["lower"] == 20
    assert body["upper"] == 30


# ── J. Fallback consistency ──────────────────────────────────

def test_fallback_class_defs_match():
    expected = {"guideline_2061", "guideline_simple", "harvesting_cfmg", "dfo_export", "validation"}
    actual = set(_FALLBACK_CLASS_DEFS.keys())
    assert actual == expected, f"expected {expected}, got {actual}"
