"""HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P2 — the core-4 Hazard & Erosion charts.

`chart:hazard_landslide_area_by_class` / `chart:hazard_slope_class_split` /
`chart:hazard_household_driver_split` / `chart:hazard_erosion_aoi_comparison`
resolve to a Chart.js dict from the collector payload, and degrade to ``None``
when their source data is absent.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.operational_plan.variable_registry import (
    VARIABLE_REGISTRY,
    get_variable,
)
from app.services.operational_plan.variable_resolver import VariableResolver

_CHART_KEYS = [
    "chart:hazard_landslide_area_by_class",
    "chart:hazard_slope_class_split",
    "chart:hazard_household_driver_split",
    "chart:hazard_erosion_aoi_comparison",
]

_RAW = {
    "basic_info": {"forest_name": "बृन्दाबन", "language": "NP"},
    "soil_erosion": {
        "soil_loss_aoi_comparison": [
            {"क्षेत्र": "सामुदायिक वन", "औसत_क्षय_टन_हे_वर्ष": 16.9},
            {"क्षेत्र": "उपभोक्ता क्षेत्र (कुल)", "औसत_क्षय_टन_हे_वर्ष": 51.8},
            {"क्षेत्र": "वन बाहिरको बस्ती भूमि", "औसत_क्षय_टन_हे_वर्ष": 60.1},
        ],
    },
    "hazard_vuln": {
        "lsi_area_by_class": [
            {"वर्ग": "धेरै न्यून", "क्षेत्रफल_हे": 40.0},
            {"वर्ग": "न्यून", "क्षेत्रफल_हे": 120.0},
            {"वर्ग": "मध्यम", "क्षेत्रफल_हे": 150.0},
            {"वर्ग": "उच्च", "क्षेत्रफल_हे": 150.0},
            {"वर्ग": "धेरै उच्च", "क्षेत्रफल_हे": 58.0},
        ],
        "fs_enabled": True,
        "fs_unstable_pct": 0.0,
        "fs_marginal_pct": 14.7,
        "hh_driver_counts": [
            {"कारक": "सामाजिक सीमान्तता", "घरधुरी": 44},
            {"कारक": "भौतिक प्रकोप एक्सपोजर", "घरधुरी": 26},
            {"कारक": "आर्थिक अवस्था", "घरधुरी": 19},
        ],
    },
}


def _resolver(raw) -> VariableResolver:
    r = VariableResolver(db=None, calculation_id=uuid.uuid4(), plan=None)
    r._raw_data = raw
    return r


@pytest.mark.parametrize("key", _CHART_KEYS)
def test_chart_is_registered_under_s9(key):
    v = get_variable(key)
    assert v is not None
    assert v.section == "S9"
    assert v.var_type == "dict"


@pytest.mark.parametrize("key", _CHART_KEYS)
def test_chart_resolves_to_a_valid_chartjs_dict(key):
    out = _resolver(_RAW)._resolve_chart(VARIABLE_REGISTRY[key])
    assert isinstance(out, dict)
    assert out["type"] in ("bar", "pie")
    assert out["labels"] and len(out["labels"]) >= 1
    assert out["datasets"] and out["datasets"][0]["data"]
    assert len(out["labels"]) == len(out["datasets"][0]["data"])


def test_slope_split_sums_to_100():
    out = _resolver(_RAW)._resolve_chart(
        VARIABLE_REGISTRY["chart:hazard_slope_class_split"]
    )
    assert out["labels"] == ["अस्थिर", "सीमान्त स्थिर", "स्थिर"]
    assert abs(sum(out["datasets"][0]["data"]) - 100.0) < 1e-6


@pytest.mark.parametrize("key", _CHART_KEYS)
def test_chart_returns_none_when_data_absent(key):
    out = _resolver({"soil_erosion": {}, "hazard_vuln": {}})._resolve_chart(
        VARIABLE_REGISTRY[key]
    )
    assert out is None


def test_slope_split_none_when_fs_disabled():
    raw = {"hazard_vuln": {"fs_enabled": False}, "soil_erosion": {}}
    out = _resolver(raw)._resolve_chart(
        VARIABLE_REGISTRY["chart:hazard_slope_class_split"]
    )
    assert out is None


@pytest.mark.parametrize("key", _CHART_KEYS)
def test_docx_generate_chart_is_graceful_on_empty(key):
    from app.services.operational_plan.op_docx_builder import _generate_chart

    chart_type = key.split(":", 1)[1]
    assert _generate_chart(chart_type, {"soil_erosion": {}, "hazard_vuln": {}}, "") is None
