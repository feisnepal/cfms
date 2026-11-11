"""Contract of the units module ``app.services.forest_units`` (written failing-first in FS-0.2, made to
pass in FS-1a.1; plan Appendix A). FS-1a.16 adds the cross-subsystem "one unit set" test on top of it.

The contract on the fixtures (see fixtures.py; F12 / F13 are forests that ARE one block / one compartment):
  * ``forest_stream``  - BLOCK / COMPARTMENT like today's ``get_forest_dimension`` on conforming forests;
                         UNDECIDED when there are no units.
  * ``units(view=TOP_LEVEL)`` - units whose parent is the outer boundary.
  * ``units(view=LEAF)``      - units that are not a parent of another unit (the "analysis" set).
  * ``units(view=BY_LEVEL, depth=d)`` - units at exactly that depth.
  * ``children_of`` / ``descendants_of`` - by parent id.
  * every view is scoped to ONE calculation and ordered by ``index``.
  * ``sql`` fragments carry the numeric depth so no caller hard-codes it (invariant I10).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _mod():
    from app.services.forest_units import mode, model, queries, sql

    return model, queries, mode, sql


def _names(units):
    return [u.name for u in units]


def test_unit_dataclass_has_the_documented_fields():
    model, *_ = _mod()
    fields = set(model.Unit.__dataclass_fields__)
    assert {
        "id",
        "name",
        "block_name",
        "branch",
        "depth",
        "parent_id",
        "geometry",
        "area_ha",
        "working_circle",
        "is_locked",
        "index",
    } <= fields
    assert {b.value for b in model.Branch} == {"block", "compartment"}
    assert {s.value for s in model.Stream} == {"block", "compartment", "undecided"}
    assert model.DEPTH_ROOT == 0


@pytest.mark.parametrize("key", ["F1", "F2", "F3", "F4", "F0"])
def test_stream_agrees_with_the_rule_on_conforming_forests(make_forest, db, key):
    _, _, mode, _ = _mod()
    f = make_forest(key)
    assert mode.forest_stream(db, f.calc_id).value == f.expect["stream"]


@pytest.mark.parametrize("key", ["F1", "F2", "F3", "F4", "F5"])
def test_leaf_view_is_every_unit_that_is_not_a_parent(make_forest, db, key):
    model, queries, *_ = _mod()
    f = make_forest(key)
    got = queries.units(db, f.calc_id, queries.View.LEAF)
    assert sorted(_names(got)) == sorted(f.expect["leaf"])


@pytest.mark.parametrize("key", ["F1", "F2", "F3", "F4", "F5"])
def test_top_level_view_is_the_units_directly_under_the_boundary(make_forest, db, key):
    _, queries, *_ = _mod()
    f = make_forest(key)
    got = queries.units(db, f.calc_id, queries.View.TOP_LEVEL)
    assert sorted(_names(got)) == sorted(f.expect["top"])


@pytest.mark.parametrize("key", ["F3", "F4"])
def test_by_level_view_returns_exactly_that_depth(make_forest, db, key):
    model, queries, *_ = _mod()
    f = make_forest(key)
    got = queries.units(db, f.calc_id, queries.View.BY_LEVEL, depth=model.DEPTH_SUB)
    assert sorted(_names(got)) == sorted(f.expect["sub"])


def test_children_and_descendants(make_forest, db):
    _, queries, *_ = _mod()
    f = make_forest("F3")
    assert sorted(_names(queries.children_of(db, f.units["B1"]))) == ["SB1", "SB2"]
    assert queries.children_of(db, f.units["B2"]) == []
    g = make_forest("F5")  # chain: B1 > C1, C2
    assert sorted(_names(queries.descendants_of(db, g.units["B1"]))) == ["C1", "C2"]


def test_views_are_scoped_to_one_calculation_and_ordered_by_index(make_forest, db):
    _, queries, *_ = _mod()
    a = make_forest("F2")
    b = make_forest("F1")
    got_a = queries.units(db, a.calc_id, queries.View.LEAF)
    got_b = queries.units(db, b.calc_id, queries.View.LEAF)
    assert _names(got_a) == ["C1", "C2", "C3"]  # creation order == index order
    assert _names(got_b) == ["B1", "B2"]
    assert not ({u.id for u in got_a} & {u.id for u in got_b})


def test_sql_fragments_select_the_same_units_as_the_views(make_forest, db):
    """Raw SQL must never hard-code a depth: it asks the module for the predicate (I10)."""
    model, queries, _, sql = _mod()
    f = make_forest("F3")

    def count(where):
        return db.execute(
            text(
                f"SELECT count(*) FROM forest_blocks b WHERE b.calculation_id = :c AND {where}"
            ),
            {"c": str(f.calc_id)},
        ).scalar()

    assert count(sql.top_level("b")) == 2  # B1, B2
    assert count(sql.is_sub("b")) == 2  # SB1, SB2
    assert (
        count(sql.branch("b", model.Branch.BLOCK)) == 4
    )  # every unit of F3 is in the block branch
    assert count(sql.branch("b", model.Branch.COMPARTMENT)) == 0


@pytest.mark.parametrize("key,stream", [("F12", "block"), ("F13", "compartment")])
def test_a_forest_that_is_one_unit_is_an_ordinary_forest(make_forest, db, key, stream):
    """Owner, 2026-09-21: a forest boundary is sometimes itself one block or one compartment. Every view returns
    that one unit, the stream is its branch, and it is neither a special case nor a parent of anything.
    """
    model, queries, mode, _ = _mod()
    f = make_forest(key)
    (name,) = f.expect["top"]
    assert mode.forest_stream(db, f.calc_id).value == stream
    for view in (queries.View.TOP_LEVEL, queries.View.LEAF):
        got = queries.units(db, f.calc_id, view)
        assert _names(got) == [name]
        assert got[0].is_top_level
    assert queries.children_of(db, f.units[name]) == []
    assert queries.descendants_of(db, f.units[name]) == []
