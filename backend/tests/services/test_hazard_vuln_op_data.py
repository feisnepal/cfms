"""Hazard + household-vulnerability OP data wiring (P5).

``data_collector.get_hazard_vuln_data`` never raises and returns a PII-free,
JSON-serialisable dict; every ``hazard_vuln`` variable is registered under S9
and resolves through the ``_resolve_category_a`` source map.
"""

from __future__ import annotations

import json
import uuid

from app.services.operational_plan import variable_registry as vr
from app.services.operational_plan.data_collector import (
    OP_DATA_CACHE_VERSION,
    get_hazard_vuln_data,
)

_LIST_KEYS = {
    "lsi_area_by_class",
    "lsi_by_unit",
    "fs_by_unit",
    "hazard_aoi_comparison",
    "hh_priority_table",
    "hh_settlement_rollup_table",
    "hh_driver_counts",
    "hazard_assumptions",
}
_NARRATION_KEYS = {
    "hazard_methodology_narration",
    "hazard_methodology_narration_en",
    "hazard_findings_narration",
    "hazard_findings_narration_en",
    "hazard_prescription_narration",
    "hazard_prescription_narration_en",
}
# these substrings must never appear as a key in the OP payload
_PII_KEY_HINTS = ("surname", "latitude", "longitude", "caste")


def test_cache_version_bumped_for_hazard_vuln():
    assert OP_DATA_CACHE_VERSION >= 21  # P10 bumped to 21 (+hh_coord_source)


def test_empty_path_returns_full_shape(db):
    d = get_hazard_vuln_data(db, str(uuid.uuid4()))  # no such calc → exception path
    assert d["hazard_vuln_available"] is False
    for k in _LIST_KEYS:
        assert isinstance(d[k], list), k
    for k in _NARRATION_KEYS:
        assert k in d and isinstance(d[k], str)
    assert d["hazard_assumptions"] and d["hazard_assumptions_en"]
    assert d["hh_coord_source"] == "survey"  # P10 — always present
    json.dumps(d)  # must not raise (no np types, no datetimes)


def test_no_pii_key_names_anywhere(db):
    d = get_hazard_vuln_data(db, str(uuid.uuid4()))
    blob = json.dumps(d, ensure_ascii=False).lower()
    for hint in _PII_KEY_HINTS:
        assert f'"{hint}"' not in blob, hint


def test_hazard_vuln_vars_registered_under_s9():
    hv = vr.get_variables_by_source("hazard_vuln")
    assert len(hv) >= 25
    keys = {v.key for v in hv}
    for expect in (
        "lsi_prone_area_ha",
        "lsi_area_by_class",
        "fs_unstable_area_ha",
        "hazard_aoi_comparison",
        "hh_priority_table",
        "hh_settlement_rollup_table",
        "hazard_findings_narration",
    ):
        assert expect in keys
    for v in hv:
        assert v.category == "A", v.key
        assert v.section == "S9", v.key
        assert v.label_ne and v.label_en, v.key


def test_list_vars_are_typed_list():
    for key in _LIST_KEYS - {"hazard_assumptions"}:
        v = vr.get_variable(key)
        assert v is not None and v.var_type == "list", key


def test_source_map_routes_hazard_vuln():
    from app.services.operational_plan.variable_resolver import VariableResolver

    src = VariableResolver.__dict__["_resolve_category_a"]
    # the source_map literal lives in the function body — assert it maps the key
    import inspect

    body = inspect.getsource(src)
    assert '"hazard_vuln": "hazard_vuln"' in body


def test_docx_section_scan_includes_hazard_vuln():
    import inspect

    from app.services.operational_plan import op_docx_builder as odb

    body = inspect.getsource(odb._resolve_var_from_raw)
    assert '"hazard_vuln"' in body
