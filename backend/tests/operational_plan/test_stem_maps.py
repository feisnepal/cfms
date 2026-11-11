"""Stem-point maps (unit__stems_all / _felling / _mother) - spec shape and the pure point filter."""
from app.services.operational_plan.thematic_map_spec import BUILTIN_THEMEMAP_SPECS as SPECS
from app.services.operational_plan.thematic_overlay import _load_tree_points


class _Db:
    """Minimal stand-in: execute(...).all() returns canned (lon, lat, remark) rows."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_a, **_k):
        class _R:
            def __init__(s, rows):
                s._rows = rows

            def all(s):
                return s._rows

        return _R(self._rows)


ROWS = [(85.0, 27.0, "Felling Tree"), (85.1, 27.1, "Mother Tree"), (85.2, 27.2, None), (85.3, 27.3, "Mother Tree")]


def test_three_stem_specs_are_tree_dot_maps_needing_tree_mapping():
    for key, flt in (("unit__stems_all", "all"), ("unit__stems_felling", "felling"), ("unit__stems_mother", "mother")):
        s = SPECS[key]
        assert (s.layer, s.viz, s.source, s.tree_filter) == ("tree", "dotcat", "tree_mapping", flt)
        assert s.requires == ["tree_mapping"]


def test_tree_filter_selects_by_remark():
    db = _Db(ROWS)
    assert len(_load_tree_points(db, "c", "all")) == 4
    assert [p["remark_group"] for p in _load_tree_points(db, "c", "felling")] == ["Felling Tree"]
    assert len(_load_tree_points(db, "c", "mother")) == 2
    assert [p["remark_group"] for p in _load_tree_points(db, "c", "protected")] == ["Protected Tree"]


def test_a_failing_query_gives_no_points_not_an_error():
    class _Bad:
        def execute(self, *_a, **_k):
            raise RuntimeError("no table")

    assert _load_tree_points(_Bad(), "c", "all") == []
