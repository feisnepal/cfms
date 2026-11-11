"""Colours the user changed in the workspace's Analysis maps group reach the OP document's SFM print maps — and only
those that really differ from the system palette, so an untouched map keeps its cache key."""
from types import SimpleNamespace
from uuid import uuid4

from app.core import semantic_palettes as sp
from app.services.operational_plan import thematic_overlay as to
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS, spec_hash


class _Q:
    def __init__(self, calc):
        self.calc = calc

    def filter(self, *a, **k):
        return self

    def first(self):
        return self.calc


class _Db:
    def __init__(self, layer_renderers):
        self.calc = SimpleNamespace(result_data={"layer_renderers": layer_renderers} if layer_renderers is not None else {})

    def query(self, *a, **k):
        return _Q(self.calc)


def _spec(key):
    return SPECS[key]


def test_a_changed_forest_type_colour_is_carried_and_changes_the_cache_key():
    default = sp.CATEGORICAL["sfm_forest_type"]
    saved = {"analysis:sfm_type": {"mode": "categorized", "field": "sfm_type", "classes": [
        {"value": "7", "color": "#123456"}, {"value": "1", "color": default["1"]},  # 1 is unchanged
        {"value": "none", "color": "#000000"},  # the grey "no type" class is not a palette category
    ]}}
    out = to._with_user_colours(_Db(saved), uuid4(), _spec("sfm__forest_type"))
    assert out.colour_overrides == {"7": "#123456"}
    assert spec_hash(out) != spec_hash(_spec("sfm__forest_type"))


def test_nothing_changed_means_the_very_same_spec_and_cache_key():
    default = sp.CATEGORICAL["sfm_orientation"]
    saved = {"analysis:sfm_orientation": {"mode": "categorized", "field": "sfm_orientation", "classes": [
        {"value": k, "color": v} for k, v in default.items()]}}
    spec = _spec("sfm__orientation")
    out = to._with_user_colours(_Db(saved), uuid4(), spec)
    assert out is spec and out.colour_overrides is None
    assert to._with_user_colours(_Db({}), uuid4(), spec) is spec
    assert to._with_user_colours(_Db(None), uuid4(), spec) is spec


def test_stock_colours_are_carried_by_class_index():
    spec = _spec("sfm__gs_vs_threshold")
    base = sp.sample_ramp(spec.palette, 3)
    saved = {"analysis:sfm_stock": {"mode": "graduated", "field": "sfm_gs", "breaks": [150, 200],
                                    "colors": [base[0], "#00ff00", base[2]], "ramp": "custom"}}
    out = to._with_user_colours(_Db(saved), uuid4(), spec)
    assert out.colour_overrides == {"1": "#00ff00"}


def test_malformed_or_unsafe_saved_colours_are_ignored_not_fatal():
    spec = _spec("sfm__forest_type")
    for junk in ("not-a-dict", {"mode": "categorized", "classes": [{"value": "7", "color": "red; drop table"}]},
                 {"mode": "categorized", "classes": [{"value": "99", "color": "#123456"}]}, {"mode": "weird"}):
        assert to._with_user_colours(_Db({"analysis:sfm_type": junk}), uuid4(), spec) is spec


def test_other_maps_are_never_touched():
    spec = _spec("soil__annual_loss")
    assert to._with_user_colours(_Db({"analysis:sfm_type": {"mode": "categorized", "classes": []}}), uuid4(), spec) is spec


def test_the_renderer_uses_the_override_for_units_and_legend():
    spec = _spec("sfm__forest_type").model_copy(update={"colour_overrides": {"7": "#123456"}})
    units = [{"name": "A"}, {"name": "B"}]
    values = {"A": {spec.measure: "7"}, "B": {spec.measure: "3"}}
    feat, rows = to._categorical_colours(units, values, spec)
    assert feat["A"] == "#123456" and feat["B"] == sp.CATEGORICAL["sfm_forest_type"]["3"]
    assert "#123456" in [r[0] for r in rows]


def test_the_graduated_renderer_uses_the_override_per_class():
    spec = _spec("sfm__gs_vs_threshold").model_copy(update={"colour_overrides": {"2": "#abcdef"}})
    units = [{"name": "A"}, {"name": "B"}]
    values = {"A": {spec.measure: 50.0}, "B": {spec.measure: 400.0}}
    feat, rows = to._sequential_colours(units, values, spec)
    assert feat["B"] == "#abcdef"  # top class
    assert feat["A"] == sp.sample_ramp(spec.palette, 3)[0]


# ── hazard maps: class-indexed colours, shared by the print maps and the workspace tiles ─────────────────────────────
def test_every_hazard_tile_key_has_an_analysis_id_and_every_mapped_spec_exists():
    from app.services.operational_plan import hazard_tiles as ht
    from app.services.operational_plan import user_map_colours as ucm

    ids = set(ucm.SPEC_TO_ANALYSIS.values())
    for key in ht.TILE_KEYS:
        assert f"hazard_{key}" in ids, key
    for spec_key in ucm.SPEC_TO_ANALYSIS:
        assert spec_key in SPECS, spec_key


def test_indexed_overrides_keep_only_valid_entries():
    from app.services.operational_plan import user_map_colours as ucm

    good = {"mode": "indexed", "colors": {"0": "#112233", "2": "#AABBCC", "bad key!": "#000000", "1": "red", "3": 5}}
    assert ucm.indexed_overrides(good) == {"0": "#112233", "2": "#AABBCC"}
    for junk in (None, {}, {"mode": "indexed"}, {"mode": "indexed", "colors": []}, {"mode": "categorized", "colors": {"0": "#112233"}}):
        assert ucm.indexed_overrides(junk) == {}


def test_apply_replaces_only_the_overridden_classes_and_is_a_no_op_without_any():
    from app.services.operational_plan import user_map_colours as ucm

    base = ["#000001", "#000002", "#000003"]
    assert ucm.apply(base, {"1": "#ffffff"}) == ["#000001", "#ffffff", "#000003"]
    assert ucm.apply(base, None) is base and ucm.apply(base, {}) is base
    assert ucm.apply(base, {"9": "#ffffff"}) == base  # a class that does not exist is ignored
    assert ucm.signature({}) == "" and ucm.signature({"1": "#ffffff"}) != ""


def test_a_hazard_spec_gets_the_saved_classes_and_a_new_cache_key():
    saved = {"analysis:hazard_soil": {"mode": "indexed", "colors": {"5": "#123456"}}}
    spec = _spec("soil__annual_loss")
    out = to._with_user_colours(_Db(saved), uuid4(), spec)
    assert out.colour_overrides == {"5": "#123456"} and spec_hash(out) != spec_hash(spec)
    # the user-group variant of the same map shares the choice
    ug = to._with_user_colours(_Db(saved), uuid4(), _spec("soil__annual_loss__user_group"))
    assert ug.colour_overrides == {"5": "#123456"}
    # nothing saved -> the very same spec
    assert to._with_user_colours(_Db({}), uuid4(), spec) is spec


def test_tile_surface_colours_and_cache_signature_follow_the_overrides():
    import numpy as np

    from app.services.operational_plan import hazard_tiles as ht

    s = ht.surface_from_array(
        "soil", np.array([[1.0, 50.0]]), bounds=(0, 0, 2, 1), inside=np.ones((1, 2), bool), cell_area_ha=np.ones((1, 2)),
        breaks=[5.0, 10.0, 20.0, 40.0, 80.0], colours=sp.sample_ramp("reds", 6), labels_ne=[], labels_en=[], params_hash="h", cell_m=30.0,
    )
    default = list(s.colours)
    ht._finish(s, {"4": "#00ff00"})
    assert s.colours[4] == "#00ff00" and s.colours[:4] == default[:4] and s.colour_sig
    assert ht.legend(s)["custom_colours"] is True
