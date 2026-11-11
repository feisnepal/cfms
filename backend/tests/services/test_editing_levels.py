"""VR-1 — structural level model + parent-shell ladder.

Covers the two defects the vertex-edit audit pinned down:

  D-2  ``compartments`` and ``sub_compartments`` both resolved to
       ``is_compartment == True``, so a sub-compartment was validated against
       its own PARENT compartment (a full containment overlap) and R6 rejected
       every edit with 409 TOPOLOGY_REJECTED — permanently.  The feature set
       must come from ``division_level`` instead.

  D-4  The parent shell was a fixed ladder with no fallback and was resolved by
       spatial guessing.  A compartment whose level above is EMPTY must still
       get a shell (walk up to the forest boundary), and the parent must be
       resolved through ``parent_block_id``.
"""
import uuid

import pytest
from shapely.geometry import Polygon

from app.api.editing import (
    LEVEL_FILTERS,
    _features_for_store,
    _level_filter,
    resolve_parent_shell,
)
from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services.forest_units.model import DEPTH_SUB, DEPTH_TOP_BLOCK, DEPTH_TOP_COMPARTMENT
from app.services.geometry_edit_service import area_sqm, check_shared_edge_integrity


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _rect(x0, y0, x1, y1):
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _make_calc(db, boundary=None):
    user = User(
        email=f"vr1{uuid.uuid4().hex[:8]}@test.com",
        full_name="VR-1 Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="vr1-levels.csv",
        is_draft=False,
        structure_locked=False,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        from geoalchemy2.shape import from_shape
        calc.boundary_geom = from_shape(boundary, srid=4326)
        db.flush()
    return calc


_LEVEL_OF = {
    "blocks": DEPTH_TOP_BLOCK,
    "sub_blocks": DEPTH_SUB,
    "compartments": DEPTH_TOP_COMPARTMENT,
    "sub_compartments": DEPTH_SUB,
}


def _add(db, calc, geom, layer="blocks", name=None, parent=None):
    from geoalchemy2.shape import from_shape
    level = _LEVEL_OF[layer]
    # I10: the branch is the layer itself, never derived from the depth number
    # -- migration 094 put top-level blocks and top-level compartments at the
    # same depth (DEPTH_TOP_BLOCK == DEPTH_TOP_COMPARTMENT == 1).
    is_compartment = layer in ("compartments", "sub_compartments")
    row = ForestBlock(
        calculation_id=calc.id,
        name=name or f"{layer}-{uuid.uuid4().hex[:4]}",
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(area_sqm(geom) / 10000.0, 4),
        area_sqm=round(area_sqm(geom), 2),
        index=0,
        is_compartment=is_compartment,
        division_level=level,
        parent_block_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    return row


BOUNDARY = _rect(83.0, 27.0, 84.0, 28.0)


# ---------------------------------------------------------------------------
# D-2 — level filtering
# ---------------------------------------------------------------------------

def test_level_filters_cover_the_four_structural_layers():
    """FS-4a.3: sub_blocks joined the registry -- the four unit types D1's rule
    recognises (block/sub-block on one branch, compartment/sub-compartment on the
    other), not the legacy three."""
    assert set(LEVEL_FILTERS) == {"blocks", "sub_blocks", "compartments", "sub_compartments"}


def test_each_layer_sees_only_its_own_level(db):
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments", parent=block)
    sub = _add(db, calc, _rect(83.25, 27.25, 83.4, 27.5), "sub_compartments", parent=comp)

    ids = lambda layer: {f["id"] for f in _features_for_store(db, calc, layer)}

    assert ids("blocks") == {str(block.id)}
    assert ids("compartments") == {str(comp.id)}
    assert ids("sub_compartments") == {str(sub.id)}
    # The regression itself: the two finer layers must NOT share a set.
    assert ids("compartments").isdisjoint(ids("sub_compartments"))


def test_sub_compartment_is_not_validated_against_its_parent(db):
    """D-2 regression — the guaranteed 409.

    Before the fix the sub-compartment layer returned every ``is_compartment``
    row, so the parent compartment landed in the neighbour set and the
    containment overlap made R6 reject the edit unconditionally.
    """
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments", parent=block)
    sub = _add(db, calc, _rect(83.25, 27.25, 83.4, 27.5), "sub_compartments", parent=comp)

    neighbours = [
        f["geometry"] for f in _features_for_store(db, calc, "sub_compartments")
        if f["id"] != str(sub.id)
    ]
    assert neighbours == [], "a lone sub-compartment has no same-level neighbours"

    edited = _rect(83.25, 27.25, 83.41, 27.5)  # nudge one edge
    valid, warnings = check_shared_edge_integrity(edited, neighbours)
    assert valid is True
    assert warnings == []


def test_compartment_is_not_validated_against_its_own_sub_compartments(db):
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments", parent=block)
    _add(db, calc, _rect(83.25, 27.25, 83.4, 27.5), "sub_compartments", parent=comp)

    neighbours = [
        f["geometry"] for f in _features_for_store(db, calc, "compartments")
        if f["id"] != str(comp.id)
    ]
    assert neighbours == []

    valid, warnings = check_shared_edge_integrity(_rect(83.2, 27.2, 83.61, 27.8), neighbours)
    assert valid is True


def test_two_sibling_compartments_still_see_each_other(db):
    """The filter must narrow the set without breaking real adjacency."""
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    a = _add(db, calc, _rect(83.2, 27.2, 83.5, 27.8), "compartments", parent=block)
    b = _add(db, calc, _rect(83.5, 27.2, 83.8, 27.8), "compartments", parent=block)

    ids = {f["id"] for f in _features_for_store(db, calc, "compartments")}
    assert ids == {str(a.id), str(b.id)}


def test_sub_blocks_is_not_the_same_set_as_sub_compartments(db):
    """FS-4a.3: a sub-block and a sub-compartment share the same depth
    (``DEPTH_SUB``) but sit on opposite branches (I10) -- the sub_blocks filter
    must not pick up a compartment forest's sub-compartments and vice versa,
    the same D-2 regression LEVEL_FILTERS already guards against for
    compartments/sub_compartments."""
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    sub_block = _add(db, calc, _rect(83.15, 27.15, 83.5, 27.85), "sub_blocks", parent=block)
    comp = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "compartments")
    sub_comp = _add(db, calc, _rect(83.15, 27.15, 83.5, 27.85), "sub_compartments", parent=comp)

    ids = lambda layer: {f["id"] for f in _features_for_store(db, calc, layer)}
    assert ids("sub_blocks") == {str(sub_block.id)}
    assert ids("sub_compartments") == {str(sub_comp.id)}
    assert ids("sub_blocks").isdisjoint(ids("sub_compartments"))


def test_level_filter_helper_is_a_noop_for_unknown_layers(db):
    calc = _make_calc(db, BOUNDARY)
    _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    q = db.query(ForestBlock).filter(ForestBlock.calculation_id == calc.id)
    assert _level_filter(q, "sub_areas").count() == q.count()


# ---------------------------------------------------------------------------
# D-4 — parent-shell ladder
# ---------------------------------------------------------------------------

def test_block_shell_is_the_forest_boundary(db):
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    shell = resolve_parent_shell(db, calc, "blocks", str(block.id))
    assert shell is not None
    assert shell.equals(BOUNDARY)


def test_compartment_shell_is_its_parent_block_by_id(db):
    calc = _make_calc(db, BOUNDARY)
    parent = _rect(83.1, 27.1, 83.9, 27.9)
    other = _rect(83.0, 27.0, 83.05, 27.05)
    block = _add(db, calc, parent, "blocks")
    _add(db, calc, other, "blocks")  # a decoy the old spatial guess could pick
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments", parent=block)

    shell = resolve_parent_shell(db, calc, "compartments", str(comp.id))
    assert shell.equals(parent)


def test_sub_compartment_shell_is_its_parent_compartment(db):
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    comp_geom = _rect(83.2, 27.2, 83.6, 27.8)
    comp = _add(db, calc, comp_geom, "compartments", parent=block)
    sub = _add(db, calc, _rect(83.25, 27.25, 83.4, 27.5), "sub_compartments", parent=comp)

    shell = resolve_parent_shell(db, calc, "sub_compartments", str(sub.id))
    assert shell.equals(comp_geom)


def test_sub_block_shell_is_its_parent_block(db):
    """FS-4a.3: the primary path (walk ``parent_block_id``) is generic and needs
    no new branching for sub_blocks -- only the registry entry itself was
    missing before this phase."""
    calc = _make_calc(db, BOUNDARY)
    block_geom = _rect(83.1, 27.1, 83.9, 27.9)
    block = _add(db, calc, block_geom, "blocks")
    sub = _add(db, calc, _rect(83.15, 27.15, 83.5, 27.85), "sub_blocks", parent=block)

    shell = resolve_parent_shell(db, calc, "sub_blocks", str(sub.id))
    assert shell.equals(block_geom)


def test_sub_block_with_no_parent_falls_back_to_the_boundary(db):
    """FS-4a.3: STRUCTURAL_LAYER_FALLBACK["sub_blocks"] = ("blocks",) -- a
    sub-block with no ``parent_block_id`` (and no other block on the ground)
    still gets a shell, mirroring sub_compartments' own no-parent fallback."""
    calc = _make_calc(db, BOUNDARY)
    sub = _add(db, calc, _rect(83.25, 27.25, 83.4, 27.5), "sub_blocks")
    assert sub.parent_block_id is None

    shell = resolve_parent_shell(db, calc, "sub_blocks", str(sub.id))
    assert shell is not None
    assert shell.equals(BOUNDARY)


def test_compartment_with_no_block_level_falls_back_to_the_boundary(db):
    """D-4 regression — the rule used to invert here.

    With no blocks the old code found no shell, so NOTHING was locked and a
    compartment junction sitting on the forest boundary became editable.
    """
    calc = _make_calc(db, BOUNDARY)
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments")
    assert comp.parent_block_id is None

    shell = resolve_parent_shell(db, calc, "compartments", str(comp.id))
    assert shell is not None
    assert shell.equals(BOUNDARY)


def test_sub_compartment_with_no_compartment_level_falls_back_up(db):
    calc = _make_calc(db, BOUNDARY)
    block_geom = _rect(83.1, 27.1, 83.9, 27.9)
    _add(db, calc, block_geom, "blocks")
    sub = _add(db, calc, _rect(83.25, 27.25, 83.4, 27.5), "sub_compartments")

    shell = resolve_parent_shell(db, calc, "sub_compartments", str(sub.id))
    # No parent id and no compartment level → the containing block.
    assert shell.equals(block_geom)


def test_deep_nesting_uses_the_immediate_parent(db):
    """Level 3+ is still ``sub_compartments``; the shell is the DIRECT parent.

    (A dangling ``parent_block_id`` is not tested: a FK constraint on
    ``forest_blocks.parent_block_id`` makes that state unreachable.)
    """
    calc = _make_calc(db, BOUNDARY)
    block = _add(db, calc, _rect(83.1, 27.1, 83.9, 27.9), "blocks")
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments", parent=block)
    lvl2_geom = _rect(83.25, 27.25, 83.5, 27.6)
    lvl2 = _add(db, calc, lvl2_geom, "sub_compartments", parent=comp)

    from geoalchemy2.shape import from_shape
    lvl3 = ForestBlock(
        calculation_id=calc.id,
        name="deep-3",
        geometry=from_shape(_rect(83.26, 27.26, 83.35, 27.4), srid=4326),
        area_hectares=1.0,
        area_sqm=10000.0,
        index=0,
        is_compartment=True,
        division_level=3,
        parent_block_id=lvl2.id,
    )
    db.add(lvl3)
    db.flush()

    # Both live in the sub_compartments layer (division_level >= 2)…
    ids = {f["id"] for f in _features_for_store(db, calc, "sub_compartments")}
    assert ids == {str(lvl2.id), str(lvl3.id)}
    # …and the level-3 feature's shell is its level-2 parent, not the block.
    assert resolve_parent_shell(db, calc, "sub_compartments", str(lvl3.id)).equals(lvl2_geom)


def test_no_boundary_and_no_parent_returns_none(db):
    calc = _make_calc(db, boundary=None)
    comp = _add(db, calc, _rect(83.2, 27.2, 83.6, 27.8), "compartments")
    assert resolve_parent_shell(db, calc, "compartments", str(comp.id)) is None


def test_missing_feature_falls_back_to_the_boundary(db):
    calc = _make_calc(db, BOUNDARY)
    shell = resolve_parent_shell(db, calc, "compartments", str(uuid.uuid4()))
    assert shell.equals(BOUNDARY)


# ---------------------------------------------------------------------------
# SL-5 — an UNDIVIDED top-level unit shown in a sub layer
# ---------------------------------------------------------------------------
# The Sub-compartment / Sub-block layers list every undivided unit of the branch,
# so a depth-1 compartment (no parent) appears there. Vertex edits are guarded by
# `resolve_parent_shell(layer_type, id)`: with no parent row it falls back to the
# coarser layer, finds the unit ITSELF, and returns its own shape as the shell --
# so every vertex is locked. That is the intended behaviour (a top-level unit's
# edges are shared with units this layer does not hold; move them in the
# Compartments / Blocks layer, where the neighbour set is complete). Pinned here
# so it stays deliberate rather than an accident of the fallback.

def test_undivided_compartment_in_sub_layer_is_fully_locked(db):
    calc = _make_calc(db, BOUNDARY)
    geom = _rect(83.2, 27.2, 83.6, 27.8)
    comp = _add(db, calc, geom, "compartments")  # depth 1, no parent

    shell = resolve_parent_shell(db, calc, "sub_compartments", str(comp.id))
    assert shell is not None and shell.equals(geom)


def test_undivided_block_in_sub_layer_is_fully_locked(db):
    calc = _make_calc(db, BOUNDARY)
    geom = _rect(83.2, 27.2, 83.6, 27.8)
    block = _add(db, calc, geom, "blocks")  # depth 1, no parent

    shell = resolve_parent_shell(db, calc, "sub_blocks", str(block.id))
    assert shell is not None and shell.equals(geom)
