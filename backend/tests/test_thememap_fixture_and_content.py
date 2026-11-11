"""P3 content pass + preview fixture. No DB.

Covers: every spec has NE+EN label + description; every section has a name;
the synthetic fixture renders every builtin spec; legacy map:* metadata is
consistent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan import _thememap_fixture as fx  # noqa: E402
from app.services.operational_plan import prereq_check as pc  # noqa: E402
from app.services.operational_plan.thematic_map_spec import (  # noqa: E402
    BUILTIN_THEMEMAP_SPECS,
    LEGACY_MAP_META,
    SECTION_NAMES,
    all_specs,
)
from app.services.operational_plan.thematic_overlay import (
    render_from_fixture,
)  # noqa: E402


# ── content pass ───────────────────────────────────────────────────────
def test_every_spec_has_bilingual_label_and_description():
    for s in all_specs():
        assert s.label_ne and s.label_en, s.key
        assert s.description_ne and s.description_en, f"{s.key} missing a description"
        # description should be a real sentence, not the key echoed back
        assert s.description_en != s.key
        assert len(s.description_en) > 15


def test_every_spec_section_has_a_bilingual_name():
    for s in all_specs():
        assert s.section in SECTION_NAMES, s.section
        assert SECTION_NAMES[s.section]["ne"] and SECTION_NAMES[s.section]["en"]


def test_section_names_cover_s1_to_s20():
    assert {f"S{i}" for i in range(1, 21)} <= set(SECTION_NAMES)


def test_legacy_map_meta_is_well_formed():
    for key, (section, requires, desc_en, basemap) in LEGACY_MAP_META.items():
        assert key.startswith("map:")
        assert isinstance(requires, list)
        assert desc_en
        assert basemap in (
            "canvas_light",
            "hillshade",
            "topo",
            "osm",
            "imagery",
            "none",
        )


def test_activity_features_map_variable_was_dropped():
    from app.services.operational_plan.variable_registry import get_variable

    assert get_variable("map:activity_features") is None


# ── fixture ────────────────────────────────────────────────────────────
def test_fixture_shape():
    us = fx.units()
    assert len(us) == 5
    assert all("geometry" in u and "area_ha" in u and "area_share_pct" in u for u in us)
    assert set(fx.VALUES) == {u["name"] for u in us}
    assert any(v == "protection" for v in fx.WORKING_CIRCLE.values())
    # every unit carries the measures the specs read
    for m in (
        "total_growing_stock_m3_per_ha",
        "forest_condition",
        "carbon_stock_tc_per_ha",
        "mai_total_m3_per_ha",
        "aah_total_m3_per_ha",
        "_stems_total",
        "_field_minus_satellite",
    ):
        assert all(m in v for v in fx.VALUES.values()), m


def test_fixture_renders_every_builtin_spec():
    for key, spec in BUILTIN_THEMEMAP_SPECS.items():
        png = render_from_fixture(spec).getvalue()
        assert png[:8] == b"\x89PNG\r\n\x1a\n", key
        assert len(png) > 4000, f"{key}: {len(png)} bytes"


# ── prereq: the P3 tag set ────────────────────────────────────────────
def test_all_documented_tags_resolve():
    for tag in (
        "field_inventory",
        "sub_areas",
        "protected_sub_area",
        "compartments",
        "sampling",
        "tree_mapping",
        "user_group_extent",
        "fieldbook",
        "proposed_activities",
        "activity_drawn_features",
    ):
        d = pc.describe_tag(tag)
        assert d["available_capability"] is True
        assert d["hint_en"] and d["hint_ne"]


def test_capability_tags_are_flagged_unavailable():
    for tag in ("flow_accumulation", "road_network", "two_inventory_cycles"):
        assert pc.describe_tag(tag)["available_capability"] is False


def test_generic_check_returns_amber_with_hints():
    r = pc.check(None, None, ["sub_areas"])
    assert r.status == "partial"
    assert r.copyable is True
    assert "sub-areas" in r.reason_en.lower()
    assert r.hint_ne
