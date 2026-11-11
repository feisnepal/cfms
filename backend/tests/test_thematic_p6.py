"""P6 — point / density / surface techniques + template-node spec overrides.

Pure: drives ``render_from_fixture`` and ``resolve_spec`` directly, no DB.
Run with ``pytest --noconftest tests/test_thematic_p6.py``.
"""

import os
import sys
import warnings

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan import _thememap_fixture as fx  # noqa: E402
from app.services.operational_plan.thematic_map_spec import (  # noqa: E402
    BUILTIN_THEMEMAP_SPECS,
    OVERRIDABLE_FIELDS,
    resolve_spec,
    spec_hash,
)
from app.services.operational_plan.thematic_overlay import (  # noqa: E402
    POINT_SURFACE_TECHNIQUES,
    render_from_fixture,
)

_P6_REAL = [
    "plot__location",
    "plot__zone",
    "grid__plot_density",
    "forest__plot_kde",
    "forest__growing_stock_surface",
    "forest__carbon_surface",
    "unit__stems_dotdensity",
]
_P6_STUBS = [
    "unit__forest_cover_change",
    "flow__settlement_to_unit",
]
# forest__drainage_vectors was a stub; now wired to river.river84 (viz=hydrolines).
_P6_WIRED = ["forest__drainage_vectors"]


def test_p6_specs_are_registered():
    for k in _P6_REAL + _P6_STUBS + _P6_WIRED:
        assert k in BUILTIN_THEMEMAP_SPECS, k


@pytest.mark.parametrize("key", _P6_REAL + _P6_STUBS + _P6_WIRED)
def test_p6_spec_renders_a_real_png_from_the_fixture(key):
    spec = BUILTIN_THEMEMAP_SPECS[key]
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)  # missing-glyph → failure
        buf = render_from_fixture(spec)
    data = buf.getvalue()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", key
    assert len(data) > 3000, f"{key}: suspiciously small PNG ({len(data)}B)"


def test_point_surface_techniques_set_matches_the_real_specs():
    from_specs = {s.viz for s in BUILTIN_THEMEMAP_SPECS.values() if s.key in _P6_REAL}
    assert from_specs <= POINT_SURFACE_TECHNIQUES | {"dotdensity"}
    # every point/surface viz is exercised by at least one builtin spec
    assert POINT_SURFACE_TECHNIQUES <= {s.viz for s in BUILTIN_THEMEMAP_SPECS.values()}


def test_stub_specs_declare_a_not_yet_available_requirement():
    from app.services.operational_plan import prereq_check

    for k in _P6_STUBS:
        reqs = BUILTIN_THEMEMAP_SPECS[k].requires
        assert reqs, k
        assert any(r in prereq_check.NOT_AVAILABLE_TAGS for r in reqs), k


def test_fixture_plot_points_are_well_formed():
    pts = fx.plot_points()
    assert len(pts) >= 20
    blocks = {u["name"] for u in fx.UNITS}
    for p in pts:
        assert p["block_name"] in blocks
        assert p["zone_type"] in ("productive", "protected")
        assert p["gs_raw"] > 0
        assert fx.BBOX[0] <= p["lon"] <= fx.BBOX[2]
        assert fx.BBOX[1] <= p["lat"] <= fx.BBOX[3]
    assert any(p["zone_type"] == "protected" for p in pts)


# ── template-node overrides (P6b) ───────────────────────────────────────
def test_override_merges_only_whitelisted_fields():
    base = resolve_spec("thememap:unit__growing_stock")
    merged = resolve_spec(
        "thememap:unit__growing_stock",
        override={
            "class_count": 8,
            "palette": "blues",
            "basemap": "hillshade",
            "label_en": "should be ignored",
            "requires": ["bogus"],
            "key": "hijacked",
        },
    )
    assert merged is not base
    assert merged.class_count == 8
    assert merged.palette == "blues"
    assert merged.basemap == "hillshade"
    assert merged.label_en == base.label_en
    assert merged.requires == base.requires
    assert merged.key == base.key


def test_override_changes_the_cache_hash():
    base = resolve_spec("thememap:unit__carbon")
    merged = resolve_spec("thememap:unit__carbon", override={"class_count": 9})
    assert spec_hash(base) != spec_hash(merged)


def test_empty_or_noop_override_returns_the_builtin_object():
    base = resolve_spec("thememap:unit__carbon")
    assert resolve_spec("thememap:unit__carbon", override={}) is base
    assert resolve_spec("thememap:unit__carbon", override=None) is base
    assert (
        resolve_spec("thememap:unit__carbon", override={"label_en": "x"}) is base
    )  # non-whitelisted only → no copy


def test_bad_override_value_falls_back_to_builtin():
    base = resolve_spec("thememap:unit__carbon")
    merged = resolve_spec(
        "thememap:unit__carbon", override={"class_method": "not-a-method"}
    )
    assert merged is base  # invalid → model_copy raises → builtin returned


def test_overridable_fields_are_all_real_model_fields():
    from app.services.operational_plan.thematic_map_spec import ThematicMapSpec

    fields = set(ThematicMapSpec.model_fields)
    assert OVERRIDABLE_FIELDS <= fields


def test_node_map_target_resolves_opsmap_key_and_year():
    from app.services.operational_plan.op_docx_builder import _node_map_target

    class _N:
        map_type = None
        opsmap_key = "unit__felling_year"
        thememap_spec = None
        year = 4

    token, override = _node_map_target(_N())
    assert token == "opsmap:unit__felling_year"
    assert override == {"year": 4}


def test_node_map_target_merges_thememap_spec_override():
    from app.services.operational_plan.op_docx_builder import _node_map_target

    class _N:
        map_type = "thememap:unit__carbon"
        opsmap_key = None
        thememap_spec = {"palette": "magma", "class_count": 6}
        year = None

    token, override = _node_map_target(_N())
    assert token == "thememap:unit__carbon"
    assert override == {"palette": "magma", "class_count": 6}
