"""Hazard + household-vulnerability thematic render (P4).

The 16 new ``hazard__*`` / ``hh__*`` specs render a real PNG from the synthetic
fixture, degrade to a captioned placeholder when a prereq is unmet, and are all
wired to ``source="hazard_grid"`` under section S9.
"""

from __future__ import annotations

import pytest

from app.services.operational_plan import prereq_check
from app.services.operational_plan.thematic_map_spec import (
    BUILTIN_THEMEMAP_SPECS,
    resolve_spec,
)
from app.services.operational_plan.thematic_overlay import (
    _placeholder_png,
    render_from_fixture,
)

_PNG = b"\x89PNG\r\n\x1a\n"

_HAZARD_KEYS = [k for k in BUILTIN_THEMEMAP_SPECS if k.startswith(("hazard__", "hh__"))]
_LSI_FACTOR_KEYS = [k for k in _HAZARD_KEYS if k.startswith("hazard__lsi_factor_")]


def test_expected_hazard_specs_registered():
    assert len(_HAZARD_KEYS) == 18  # 5 surfaces + 10 factor bands + 3 hh
    assert len(_LSI_FACTOR_KEYS) == 10
    for k in (
        "hazard__landslide_susceptibility",
        "hazard__factor_of_safety",
        "hazard__landslide_prone_area",
        "hh__vulnerability",
        "hh__priority_settlements",
    ):
        assert k in BUILTIN_THEMEMAP_SPECS


def test_all_hazard_specs_are_s9_hazard_grid_with_known_tags():
    known = set(prereq_check._CHECKS) | prereq_check.NOT_AVAILABLE_TAGS
    for k in _HAZARD_KEYS:
        s = BUILTIN_THEMEMAP_SPECS[k]
        assert s.section == "S9", k
        assert s.source == "hazard_grid", k
        assert s.family == "thememap", k
        assert s.label_ne and s.label_en, k
        assert s.description_ne and s.description_en, k
        for tag in s.requires:
            assert tag in known, (k, tag)


@pytest.mark.parametrize("key", _HAZARD_KEYS)
def test_hazard_spec_renders_a_real_png_from_the_fixture(key):
    buf = render_from_fixture(BUILTIN_THEMEMAP_SPECS[key])
    data = buf.getvalue()
    assert data[:8] == _PNG, key
    assert len(data) > 4000, f"{key}: only {len(data)}B (likely a placeholder)"


def test_lsi_and_fs_specs_carry_fixed_class_breaks():
    lsi = resolve_spec("thememap:hazard__landslide_susceptibility")
    fs = resolve_spec("thememap:hazard__factor_of_safety")
    assert lsi.class_method == "fixed" and lsi.fixed_breaks == [1.8, 2.6, 3.4, 4.2]
    assert fs.class_method == "fixed" and fs.fixed_breaks == [1.0, 1.5]


def test_dot_gradient_specs_use_the_household_layer():
    for k in ("hh__vulnerability", "hh__vulnerability__user_group"):
        s = BUILTIN_THEMEMAP_SPECS[k]
        assert s.viz == "dot_gradient" and s.layer == "household"
    assert BUILTIN_THEMEMAP_SPECS["hh__priority_settlements"].layer == "settlement"


def test_new_prereq_tags_have_working_predicates():
    for tag in ("geology", "household_data"):
        assert tag in prereq_check._CHECKS
        predicate = prereq_check._TAGS[tag].predicate
        assert callable(predicate)


def test_user_group_variants_require_the_extent():
    for k in _HAZARD_KEYS:
        if k.endswith("__user_group"):
            assert "user_group_extent" in BUILTIN_THEMEMAP_SPECS[k].requires, k


def test_placeholder_is_smaller_than_a_real_render():
    spec = BUILTIN_THEMEMAP_SPECS["hazard__landslide_susceptibility"]
    ph = _placeholder_png(spec, "", "no data", 96).getvalue()
    real = render_from_fixture(spec).getvalue()
    assert ph[:8] == _PNG and real[:8] == _PNG
    assert len(real) > len(ph)
