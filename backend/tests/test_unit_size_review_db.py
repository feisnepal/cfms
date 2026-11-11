"""P8 tier 1 - adjacency on real PostGIS, against geometry this test builds itself.

Self-contained on purpose. The suite runs against a per-worker test database
(``cf_db_test_<worker>``, rebuilt per session), so the dev calculation is not
visible here by design - and a test that silently skips when its fixture is absent
is how a real defect stays hidden. Everything below is created and removed here.

What is worth testing against a real database is the **predicate**, because it is
the one thing a pure unit test cannot check: does ``ST_Touches`` plus a
sub-millimetre ``ST_DWithin`` find a genuine neighbour, and does it *not* invent
one across a real gap?
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon, box

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserStatus
from app.services.forest_units import queries as fuq
from app.services.unit_size_review import (
    DEFAULT_TOUCH_TOLERANCE_M,
    pick_largest_touching,
    review_units,
    summarise,
)

SQM_PER_HA = 10_000.0

# Two large neighbours sharing the sliver's eastern edge, plus one deliberately
# separated by a 30 m gap so an over-broad tolerance would join it and be caught.
BIG_WEST = box(0.0, 0.0, 100.0, 200.0)      # 2.00 ha
BIG_EAST = box(100.0, 0.0, 300.0, 200.0)    # 4.00 ha
FAR_AWAY = box(1000.0, 0.0, 1100.0, 200.0)  # 2.00 ha, 700 m away
SLIVER = box(100.0, 100.0, 100.1, 100.2)    # 0.0002 ha, tucked onto the shared edge
ISLAND = box(5000.0, 0.0, 5000.1, 5000.1)   # isolated, nothing touches it

UNITS = [
    ("BIG-W", BIG_WEST),
    ("BIG-E", BIG_EAST),
    ("FAR", FAR_AWAY),
    ("SLIVER", SLIVER),
    ("ISLAND", ISLAND),
]


def _area_ha(geom: Polygon) -> float:
    return geom.area / SQM_PER_HA


@pytest.fixture
def forest(db):
    """A five-unit forest: two touching neighbours, a sliver, a gap, an island.

    Uses the suite's ``db`` fixture, which is bound to the per-worker test database,
    and removes everything it created. ``forest_blocks.calculation_id`` is a real FK,
    so a Calculation (and its User) has to exist first.
    """
    user = User(
        id=uuid.uuid4(),
        email=f"p8-unit-size-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="P8 Unit Size",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    calc = Calculation(id=uuid.uuid4(), user_id=user.id, forest_name="P8 fixture forest")
    db.add(calc)
    db.flush()
    for i, (name, geom) in enumerate(UNITS):
        db.add(
            ForestBlock(
                id=uuid.uuid4(),
                calculation_id=calc.id,
                name=name,
                block_name=name,
                geometry=from_shape(geom, srid=4326),
                area_hectares=_area_ha(geom),
                index=i,
                is_compartment=False,
                division_level=1,
            )
        )
    db.commit()
    try:
        yield db, calc.id
    finally:
        db.query(Calculation).filter(Calculation.id == calc.id).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.id == user.id).delete(synchronize_session=False)
        db.commit()


def _touching(db, calc_id, areas, tol_m: float = DEFAULT_TOUCH_TOLERANCE_M) -> dict:
    """The adjacency query, on real PostGIS geometry.

    ``ST_Touches`` alone is too strict for digitised data - hairline gaps are normal -
    so a sub-millimetre ``ST_DWithin`` is allowed alongside it. Bounding-box tests are
    deliberately not used: they would call units neighbours across a real gap.
    """
    from sqlalchemy import text

    rows = db.execute(
        text(
            """
            SELECT a.block_name AS a_name, b.block_name AS b_name
            FROM forest_blocks a
            JOIN forest_blocks b
              ON a.calculation_id = b.calculation_id
             AND a.id <> b.id
             AND a.block_name IS NOT NULL
             AND b.block_name IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM forest_blocks c WHERE c.parent_block_id = a.id)
             AND NOT EXISTS (SELECT 1 FROM forest_blocks c WHERE c.parent_block_id = b.id)
             AND (ST_Touches(a.geometry, b.geometry)
                  OR ST_DWithin(a.geometry, b.geometry, :tol))
            WHERE a.calculation_id = :cid
            """
        ),
        {"cid": str(calc_id), "tol": tol_m},
    ).fetchall()

    out: dict = {name: [] for name in areas}
    for a_name, b_name in rows:
        if a_name in out and b_name in out:
            out[a_name].append(b_name)
    return out


# ── the predicate ─────────────────────────────────────────────────────────────
def test_touching_finds_the_shared_edge(forest):
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    # BIG-W's eastern edge is shared with BIG-E, and the sliver sits on that same
    # edge - so it is a genuine neighbour of both, not just the bigger one.
    assert {"BIG-E", "SLIVER"} <= set(touching["BIG-W"])
    assert {"BIG-W", "SLIVER"} <= set(touching["BIG-E"])
    assert "FAR" not in touching["BIG-W"]
    assert "FAR" not in touching["BIG-E"]


def test_touching_is_symmetric(forest):
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    for a, others in touching.items():
        for b in others:
            assert a in touching.get(b, ()), f"{a} touches {b} but not the reverse"


def test_tolerance_does_not_bridge_a_real_gap(forest):
    """The unit 700 m away must not be reported as touching anything."""
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    assert touching["FAR"] == []
    assert "FAR" not in touching["BIG-E"]


def test_tolerance_bridges_only_a_hairline(forest):
    """A sub-millimetre gap is digitising noise; a 30 m gap is not."""
    from sqlalchemy import text

    # Both sit just below BIG-E's southern edge (y = 0), far apart in x so they
    # cannot be neighbours of each other and confuse the assertion.
    hairline = box(100.0, -100.0, 300.0, -0.0000005)   # 0.5 mm gap
    gap_30m = box(400.0, -100.0, 600.0, -30.0)         # 30 m gap
    db, calc_id = forest
    for name, geom in (("HAIRLINE", hairline), ("GAP-30M", gap_30m)):
        db.add(
            ForestBlock(
                id=uuid.uuid4(),
                calculation_id=calc_id,
                name=name,
                block_name=name,
                geometry=from_shape(geom, srid=4326),
                area_hectares=_area_ha(geom),
                index=99,
                is_compartment=False,
                division_level=1,
            )
        )
    db.commit()
    try:
        areas = fuq.leaf_areas_by_name(db, calc_id)
        touching = _touching(db, calc_id, areas)
        assert "BIG-E" in touching["HAIRLINE"], "a 0.5 mm gap must be forgiven"
        assert touching["GAP-30M"] == [], "a 30 m gap must not be bridged"
    finally:
        db.query(ForestBlock).filter(
            ForestBlock.calculation_id == calc_id,
            ForestBlock.block_name.in_(["GAP-30M", "HAIRLINE"]),
        ).delete(synchronize_session=False)
        db.commit()


def test_island_touches_nothing(forest):
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    assert touching["ISLAND"] == []


# ── the outcome on real geometry ──────────────────────────────────────────────
def test_sliver_gets_the_larger_of_its_two_touching_neighbours(forest):
    """Touching first, then largest - not nearest, and not invented."""
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    by_name = {c.block_name: c for c in review_units(areas, boundary_ha=10.0, touching=touching)}
    sliver = by_name["SLIVER"]
    assert sliver.band.value == "sub_mmu"
    assert set(touching["SLIVER"]) == {"BIG-W", "BIG-E"}
    assert sliver.neighbour == "BIG-E"  # 4.00 ha beats 2.00 ha
    assert sliver.neighbour_area_ha == pytest.approx(4.0)


def test_island_is_unmergeable_not_silently_fine(forest):
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    by_name = {c.block_name: c for c in review_units(areas, boundary_ha=10.0, touching=touching)}
    island = by_name["ISLAND"]
    assert island.band.value == "sub_mmu"
    assert island.unmergeable is True
    assert island.neighbour is None
    # It still demands a decision rather than passing as 'no action'.
    assert island.action == "merge_offer"


def test_large_units_get_no_action(forest):
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    by_name = {c.block_name: c for c in review_units(areas, boundary_ha=10.0, touching=touching)}
    assert by_name["BIG-W"].action == "none"
    assert by_name["FAR"].action == "none"


def test_summary_counts_add_up_on_real_geometry(forest):
    db, calc_id = forest
    areas = fuq.leaf_areas_by_name(db, calc_id)
    touching = _touching(db, calc_id, areas)
    counts = summarise(review_units(areas, boundary_ha=10.0, touching=touching))
    assert counts["total"] == counts["sub_mmu"] + counts["review"] + counts["ok"]
    assert counts["sub_mmu"] == 2  # SLIVER and ISLAND
    assert counts["unmergeable"] == 1  # the island
    assert counts["merge_offers"] == 1


# ── the leaf view is the authoritative one ────────────────────────────────────
def test_leaf_view_uses_not_exists_child_not_parent_is_null(forest):
    """A naive ``parent_block_id IS NULL`` filter readmits subdivided parents.

    That was the bug in the plan's own note (P8 11a): it returned 28 units where 24
    are leaves. Here a parent with one child must contribute the child only.
    """
    db, calc_id = forest
    parent = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc_id,
        name="PARENT",
        block_name="PARENT",
        geometry=from_shape(box(0.0, 1000.0, 100.0, 1200.0), srid=4326),
        area_hectares=_area_ha(box(0.0, 1000.0, 100.0, 1200.0)),
        index=90,
        is_compartment=False,
        division_level=1,
    )
    db.add(parent)
    db.flush()
    child = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc_id,
        name="PARENT-SC1",
        block_name="PARENT-SC1",
        geometry=from_shape(box(0.0, 1000.0, 100.0, 1100.0), srid=4326),
        area_hectares=_area_ha(box(0.0, 1000.0, 100.0, 1100.0)),
        index=91,
        is_compartment=False,
        parent_block_id=parent.id,
        division_level=2,
    )
    db.add(child)
    db.commit()
    try:
        names = {u.block_name for u in fuq.units(db, calc_id, fuq.View.LEAF)}
        assert "PARENT" not in names
        assert "PARENT-SC1" in names
    finally:
        db.delete(child)
        db.delete(parent)
        db.commit()


def test_pick_largest_touching_is_callable_without_a_database(forest):
    """The pure helper needs no session - adjacency is injected, not looked up."""
    areas = {"sliver": 0.01, "a": 1.0, "b": 5.0}
    assert pick_largest_touching("sliver", areas, ["a", "b"]) == "b"
    assert pick_largest_touching("sliver", areas, []) is None
