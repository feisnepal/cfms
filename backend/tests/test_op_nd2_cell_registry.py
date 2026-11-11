"""ND-2 (RC2): cell-path registry fallback for raster/climate/forest-type/user-year keys.

The builder's cell renderers use _resolve_var_from_raw/_resolve_var_text with
only raw_data + user_inputs merge; the registry (VARIABLE_REGISTRY + resolver
source paths) can supply elevation_* , temperature_* , precipitation_* ,
forest_type_dominant and op_preparation_year when raw_data doesn't have them.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.operational_plan import op_docx_builder as B
from app.services.operational_plan.variable_resolver import VariableResolver


class _StubPlan:
    plan_metadata = {}


def _resolver(calc_id):
    r = VariableResolver(db=None, calculation_id=calc_id, plan=_StubPlan())
    r._raw_data = {"basic_info": {"language": "NP"}}
    return r


def test_cell_resolves_elevation_via_registry(monkeypatch):
    calc = __import__("uuid").uuid4()
    r = _resolver(calc)
    # Stub resolver to return values
    monkeypatch.setattr(r, "resolve_keys", lambda keys: {k: {"elevation_min_m": 450, "elevation_max_m": 1250}.get(k) for k in keys})
    out = B._resolve_var_text("min={{elevation_min_m}} max={{elevation_max_m}}", r._raw_data, r)
    assert "४५०" in out and "१२५०" in out
    assert "डाटा उपलब्ध छैन" not in out


def test_cell_resolves_climate_and_forest_type(monkeypatch):
    calc = __import__("uuid").uuid4()
    r = _resolver(calc)
    monkeypatch.setattr(r, "resolve_keys", lambda keys: {
        "temperature_mean_c": 23.5,
        "precipitation_mean_mm": 1450.0,
        "forest_type_dominant": "Mixed Hardwood Forest",
    })
    out = B._resolve_var_text("T={{temperature_mean_c}} P={{precipitation_mean_mm}} FT={{forest_type_dominant}}", r._raw_data, r)
    assert "२३.५" in out and "१४५०" in out and "Mixed Hardwood Forest" in out


def test_op_preparation_year_resolves(monkeypatch):
    calc = __import__("uuid").uuid4()
    r = _resolver(calc)
    monkeypatch.setattr(r, "resolve_keys", lambda keys: {"op_preparation_year": 2083})
    out = B._resolve_var_text("वर्ष: {{op_preparation_year}}", r._raw_data, r)
    assert "२०८३" in out
