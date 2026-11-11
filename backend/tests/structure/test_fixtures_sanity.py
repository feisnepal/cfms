"""The structure fixtures must build what they claim (FS-0.4).

Every later structure test leans on these forests, so a fixture that quietly builds something other than
its docstring says would poison a whole phase. Each check here reads the database directly (raw SQL, no
service code) and compares it with the fixture's own ``expect`` record.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.utils.forest_dimension import ForestDimension, get_forest_dimension

from . import fixtures

KEYS = list(fixtures.BUILDERS)


def _rows(db, forest):
    r = db.execute(
        text(
            "SELECT b.name, b.is_compartment, b.division_level, p.name AS parent, b.area_hectares, "
            "       b.working_circle "
            "FROM forest_blocks b LEFT JOIN forest_blocks p ON p.id = b.parent_block_id "
            "WHERE b.calculation_id = :c ORDER BY b.index"
        ),
        {"c": str(forest.calc_id)},
    ).fetchall()
    return {row.name: row for row in r}


def _leaf_names(rows):
    parents = {r.parent for r in rows.values() if r.parent}
    return [n for n in rows if n not in parents]


@pytest.mark.parametrize("key", KEYS)
def test_fixture_units_match_expectation(make_forest, db, key):
    f = make_forest(key)
    rows = _rows(db, f)
    if key == "F6":
        assert rows == {}, "F6 is JSONB-only: it must have no forest_blocks rows"
        assert [
            b["name"]
            for b in db.execute(
                text("SELECT result_data->'blocks' FROM calculations WHERE id = :c"),
                {"c": str(f.calc_id)},
            ).scalar()
        ] == f.expect["jsonb_blocks"]
        return
    assert set(rows) == set(f.expect["top"]) | set(f.expect["leaf"])
    top = [n for n, r in rows.items() if r.parent is None]
    assert sorted(top) == sorted(f.expect["top"])
    assert sorted(_leaf_names(rows)) == sorted(f.expect["leaf"])
    assert all(r.area_hectares > 0 for r in rows.values())


@pytest.mark.parametrize("key", KEYS)
def test_fixture_legacy_dimension(make_forest, db, key):
    """What today's code says a forest is - the baseline P1a must not change for conforming forests."""
    f = make_forest(key)
    assert get_forest_dimension(db, f.calc_id) == ForestDimension(
        f.expect["legacy_dimension"]
    )


@pytest.mark.parametrize("key", ["F1", "F2", "F3", "F4", "F5", "F7", "F8", "F9", "F10"])
def test_leaf_units_tile_the_boundary(make_forest, db, key):
    """Where a fixture says its units tile the boundary, they do (the tiling invariant I3 is built on this)."""
    f = make_forest(key)
    rows = _rows(db, f)
    leaf_ha = sum(rows[n].area_hectares for n in f.expect["leaf"])
    outer = float(
        db.execute(
            text(
                "SELECT ST_Area(boundary_geom::geography) / 10000.0 FROM calculations WHERE id = :c"
            ),
            {"c": str(f.calc_id)},
        ).scalar()
    )
    if key == "F9":
        assert leaf_ha == pytest.approx(outer, rel=0.005)
    else:
        assert leaf_ha == pytest.approx(
            outer, rel=0.005
        ), f"{key}: leaf units do not tile the boundary"


def _subs(db, forest):
    rd = db.execute(
        text("SELECT result_data->'sub_areas' FROM calculations WHERE id = :c"),
        {"c": str(forest.calc_id)},
    ).scalar()
    return {s["name"]: s for s in rd}


def test_f7_private_land_cases(make_forest, db):
    f = make_forest("F7")
    subs = _subs(db, f)
    assert set(subs) == set(f.expect["private_land"])
    assert {n for n, s in subs.items() if s["isExcluded"]} == set(f.expect["flagged"])
    assert subs["PL_UNFLAGGED"]["isExcluded"] is False
    assert subs["PL_ENCLAVE"]["area_hectares"] == pytest.approx(
        f.expect["enclave_ha"], rel=0.05
    )

    def touches(sub, unit):
        return f.sub_geoms[sub].intersects(f.unit_geoms[unit])

    assert touches("PL_SPAN", "B1") and touches(
        "PL_SPAN", "B2"
    ), "PL_SPAN must straddle both blocks"
    assert touches("PL_FLAGGED", "B1") and not touches("PL_FLAGGED", "B2")
    assert touches("PL_ENCLAVE", "B2") and not touches("PL_ENCLAVE", "B1")
    assert f.sub_geoms["PL_NOTCH"].intersects(
        f.boundary.boundary
    ), "PL_NOTCH must touch the outer boundary"
    assert not f.sub_geoms["PL_FLAGGED"].intersects(
        f.boundary.boundary
    ), "PL_FLAGGED is an interior hole"


def test_f8_protected_overlaps_the_protection_unit_and_a_production_block(
    make_forest, db
):
    f = make_forest("F8")
    rows = _rows(db, f)
    assert rows["P-1"].working_circle == "protection"
    assert rows["B1"].working_circle == "production"
    assert _subs(db, f)["PROT"]["category"] == "protected"
    hits = {n for n, g in f.unit_geoms.items() if f.sub_geoms["PROT"].intersects(g)}
    assert hits == {"B1", "P-1"}


def test_f9_ratios(make_forest, db):
    f = make_forest("F9")
    rows = _rows(db, f)
    outer = rows["B1"].area_hectares
    subs = {n: s["area_hectares"] for n, s in _subs(db, f).items()}
    ratios = f.expect["ratios"]
    assert subs["PRIVATE"] / outer == pytest.approx(ratios["private"], rel=0.01)
    assert subs["PROTECTED"] / outer == pytest.approx(ratios["protected"], rel=0.01)
    total = (outer - subs["PRIVATE"]) / outer
    assert total == pytest.approx(ratios["total_forest"], rel=0.01)
    effective = (
        (outer - subs["PRIVATE"] - subs["PROTECTED"])
        * f.expect["tree_cover_ratio"]
        / outer
    )
    assert effective == pytest.approx(ratios["effective"], rel=0.01)


def test_f10_downstream_data_is_present(make_forest, db):
    f = make_forest("F10")

    def count(sql):
        return db.execute(text(sql), {"c": str(f.calc_id)}).scalar()

    assert count("SELECT count(*) FROM sampling_designs WHERE calculation_id = :c") == 1
    assert (
        count(
            "SELECT count(*) FROM inventory_trees t JOIN inventory_calculations i "
            "ON i.id = t.inventory_calculation_id WHERE i.calculation_id = :c"
        )
        == 3
    )
    assert (
        count(
            "SELECT count(*) FROM field_inventory_calculations WHERE calculation_id = :c"
        )
        == 1
    )
    assert (
        count(
            "SELECT count(*) FROM proposed_yearly_activities WHERE calculation_id = :c"
        )
        == 1
    )
    per_block = {
        r[0]: r[1]
        for r in db.execute(
            text(
                "SELECT b.name, count(*) FROM inventory_trees t "
                "JOIN inventory_calculations i ON i.id = t.inventory_calculation_id "
                "JOIN forest_blocks b ON b.calculation_id = i.calculation_id "
                "  AND ST_Within(t.location::geometry, b.geometry) "
                "WHERE i.calculation_id = :c GROUP BY b.name"
            ),
            {"c": str(f.calc_id)},
        ).fetchall()
    }
    assert per_block == f.expect["trees_in"]


def test_f11_orphan_inventories_cannot_exist(db, make_forest):
    """F11 (inventory with no forest) has no builder: work package FD made ``calculation_id`` NOT NULL,
    so the database refuses such a row. This is why FS-1d.6 was dropped."""
    f = make_forest("F1")
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO public.inventory_calculations (id, user_id, uploaded_filename, status) "
                "VALUES (gen_random_uuid(), :u, 'orphan.csv', 'completed')"
            ),
            {"u": str(f.user_id)},
        )
    db.rollback()
