"""ThematicMapSpec model + builtin registry (P1). No DB, no fixtures."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.operational_plan.thematic_map_spec import (  # noqa: E402
    BUILTIN_THEMEMAP_SPECS,
    THEMEMAP_RENDER_VERSION,
    ThematicMapSpec,
    all_specs,
    resolve_spec,
    spec_hash,
)
from app.services.operational_plan import prereq_check  # noqa: E402

_KNOWN_TAGS = set(prereq_check._CHECKS) | prereq_check.NOT_AVAILABLE_TAGS

_KNOWN_TECHNIQUES = {
    # P1
    "choropleth",
    "choropleth_div",
    "bivariate",
    "dasymetric",
    "alpha",
    "graduated",
    "graduated_nested",
    "label",
    # P5b — centroid glyphs + small multiples
    "pie",
    "donut",
    "stackbar",
    "radar",
    "waffle",
    "sparkline",
    "ternary",
    "smallmultiples",
    # P6 — point / density / surface + not-yet-available stubs
    "dotcat",
    "dotdensity",
    "hexbin",
    "heatmap",
    "isopleth",
    "vector",
    "hydrolines",
    "flow",
    "change",
    # P6z — S9 zonal aspect rose
    "rose",
    # P7 — opsmap drawn-feature + QA
    "features",
    "featurecat",
    "qaflag",
    # RUSLE soil-loss — a computed continuous raster surface
    "raster_surface",
    # P4 hazard/vuln — households/settlements graduated over a raster backdrop
    "dot_gradient",
}


def test_registry_is_non_empty_and_prefixed_lookup_works():
    assert len(BUILTIN_THEMEMAP_SPECS) >= 20
    s = resolve_spec("thememap:unit__growing_stock")
    assert s is not None and s.key == "unit__growing_stock"
    assert resolve_spec("unit__growing_stock") is s  # bare key also works
    assert resolve_spec("thememap:does__not__exist") is None


def test_every_spec_has_key_section_labels_and_a_known_technique():
    for key, s in BUILTIN_THEMEMAP_SPECS.items():
        assert s.key == key
        assert s.family == "thememap"
        assert s.section.startswith("S"), key
        assert s.label_ne and s.label_en, key
        assert s.viz in _KNOWN_TECHNIQUES, f"{key}: {s.viz} not a P1 technique"


def test_every_requires_tag_is_known_to_the_checker():
    for key, s in BUILTIN_THEMEMAP_SPECS.items():
        for tag in s.requires:
            assert tag in _KNOWN_TAGS, f"{key} requires unknown tag {tag!r}"


def test_geometry_source_specs_need_no_field_inventory():
    for s in BUILTIN_THEMEMAP_SPECS.values():
        if s.source == "geometry":
            assert "field_inventory" not in s.requires, s.key


def test_token_property():
    s = resolve_spec("thememap:unit__carbon")
    assert s.token == "thememap:unit__carbon"


def test_spec_hash_is_stable_and_version_salted():
    s = resolve_spec("thememap:unit__growing_stock")
    h1 = spec_hash(s)
    h2 = spec_hash(s.model_copy())
    assert h1 == h2 and len(h1) == 12

    bumped = s.model_copy(update={"class_count": s.class_count + 1})
    assert spec_hash(bumped) != h1

    # prose fields are excluded from the hash (cache-irrelevant)
    reworded = s.model_copy(update={"label_en": "totally different label"})
    assert spec_hash(reworded) == h1


def test_all_specs_helper_covers_both_families():
    keys = {s.token for s in all_specs()}
    assert "thememap:unit__forest_condition" in keys


def test_render_version_is_an_int():
    assert isinstance(THEMEMAP_RENDER_VERSION, int)


def test_model_defaults_are_sane():
    s = ThematicMapSpec(key="x")
    assert s.viz == "choropleth" and s.class_method == "quantile" and s.class_count == 5
    assert s.missing_data_behavior == "placeholder"
    assert s.basemap == "canvas_light"
