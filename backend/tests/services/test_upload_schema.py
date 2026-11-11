"""Canonical upload schema — structural guarantees the generator + validator rely on.

The schema (app.services.upload.schema) is the single source of truth for upload
purposes, their columns, the auto-classification signals and the validation
rules. These tests pin the invariants both consumers assume.
"""

from __future__ import annotations

import json

import pytest

from app.services.upload import schema


def test_schema_version_is_a_string():
    assert isinstance(schema.SCHEMA_VERSION, str) and schema.SCHEMA_VERSION


def test_forest_boundary_is_first_and_required_in_a_bundle():
    order = schema.ordered()
    assert order[0].id == "forest_boundary"
    assert order[0].order == 0
    assert schema.boundary().required_in_bundle is True


def test_every_purpose_has_a_unique_order_and_layer_name():
    purposes = list(schema.PURPOSES.values())
    orders = [p.order for p in purposes]
    layer_names = [p.layer_name for p in purposes]
    assert len(orders) == len(set(orders)), "duplicate order values"
    assert len(layer_names) == len(set(layer_names)), "duplicate layer names"


def test_registry_key_matches_purpose_id():
    for key, p in schema.PURPOSES.items():
        assert key == p.id


def test_by_layer_name_matches_canonical_name_and_aliases():
    assert schema.by_layer_name("forest_boundary").id == "forest_boundary"
    assert schema.by_layer_name("Forest Boundary").id == "forest_boundary"
    assert schema.by_layer_name("boundary").id == "forest_boundary"
    assert schema.by_layer_name("TREES").id == "trees"
    assert schema.by_layer_name("nothing-like-this") is None


def test_spatial_and_tabular_partitions_cover_the_right_kinds():
    spatial_ids = {p.id for p in schema.spatial()}
    tabular_ids = {p.id for p in schema.tabular()}
    assert "forest_boundary" in spatial_ids
    assert "households" in tabular_ids
    assert "trees" in spatial_ids and "trees" in tabular_ids  # spatial_or_tabular
    for p in schema.PURPOSES.values():
        if p.kind == "spatial":
            assert p.id in spatial_ids and p.id not in tabular_ids
        elif p.kind == "tabular":
            assert p.id in tabular_ids and p.id not in spatial_ids
        else:
            assert p.id in spatial_ids and p.id in tabular_ids


def test_spatial_purposes_declare_geometry_types():
    for p in schema.spatial():
        assert p.geometry_types, f"{p.id} is spatial but declares no geometry_types"


def test_every_rule_code_is_globally_unique():
    codes = [r.code for p in schema.PURPOSES.values() for r in p.rules]
    dupes = {c for c in codes if codes.count(c) > 1}
    assert not dupes, f"duplicate rule codes: {dupes}"


def test_every_rule_is_error_or_warning_with_bilingual_messages():
    for p in schema.PURPOSES.values():
        for r in p.rules:
            assert r.level in ("error", "warning")
            assert r.message_en and r.message_ne
            assert r.kind


def test_column_enums_and_ranges_are_coherent():
    for p in schema.PURPOSES.values():
        for c in p.columns:
            assert c.name and c.dtype
            if c.minimum is not None and c.maximum is not None:
                assert c.minimum <= c.maximum
            if c.enum:
                assert all(isinstance(v, str) for v in c.enum)


def test_required_columns_rules_name_real_columns():
    for p in schema.PURPOSES.values():
        col_names = {c.name for c in p.columns}
        for r in p.rules:
            if r.kind == "required_columns":
                missing = set(r.params.get("columns", [])) - col_names
                assert not missing, f"{p.id}/{r.code} names unknown columns {missing}"


def test_sub_area_categories_match_the_category_column_enum():
    sub_areas = schema.get("sub_areas")
    cat = next(c for c in sub_areas.columns if c.name == "category")
    assert tuple(cat.enum) == schema.SUB_AREA_CATEGORIES
    assert len(schema.SUB_AREA_CATEGORIES) == 14


def test_forest_boundary_rule_points_at_the_real_validator():
    (rule,) = schema.boundary().rules
    assert rule.kind == "handler"
    ref = rule.params["ref"]
    module_path, func = ref.split(":")
    mod = __import__(module_path, fromlist=[func])
    assert callable(getattr(mod, func))


def test_boundary_validation_reuses_the_schema_thresholds():
    from app.services import boundary_validation as bv

    assert bv.MAX_AREA_HA == schema.MAX_AREA_HA
    assert bv.MAX_BUILTUP_CROPLAND_PCT == schema.MAX_BUILTUP_CROPLAND_PCT
    assert bv.PA_NON_BUFFER_TOLERANCE_PCT == schema.PA_NON_BUFFER_TOLERANCE_PCT
    assert bv.NEPAL_OUTSIDE_TOLERANCE_PCT == schema.NEPAL_OUTSIDE_TOLERANCE_PCT
    assert bv._ESA_BUILT_UP == schema.ESA_BUILT_UP
    assert bv._ESA_CROPLAND == schema.ESA_CROPLAND


def test_to_dict_is_json_serialisable_and_round_trips_the_shape():
    d = schema.to_dict()
    blob = json.dumps(d, ensure_ascii=False)
    back = json.loads(blob)
    assert back["schema_version"] == schema.SCHEMA_VERSION
    assert back["purposes"][0]["id"] == "forest_boundary"
    assert len(back["purposes"]) == len(schema.PURPOSES)
    assert back["thresholds"]["max_area_ha"] == schema.MAX_AREA_HA
    assert back["sub_area_categories"] == list(schema.SUB_AREA_CATEGORIES)
    # every purpose dict carries the keys the frontend/generator read
    for p in back["purposes"]:
        assert {
            "id",
            "label_en",
            "label_ne",
            "kind",
            "order",
            "columns",
            "rules",
        } <= p.keys()


def test_classification_signals_present_where_a_purpose_needs_them():
    # a tabular purpose that shares column-space with another needs a fingerprint
    for pid in ("trees", "households", "sample_plots", "activities", "field_inventory"):
        p = schema.get(pid)
        assert (
            p.fingerprint_required
        ), f"{pid} needs a column fingerprint to disambiguate"


@pytest.mark.parametrize("pid", list(schema.PURPOSES))
def test_as_dict_matches_json_for_each_purpose(pid):
    p = schema.get(pid)
    assert json.loads(json.dumps(p.as_dict(), ensure_ascii=False))["id"] == pid
