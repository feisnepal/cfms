"""V-1 — vertex classification engine unit tests.

Covers the authoritative per-level classification table (plan §1.5):
  - shared: vertex on the common boundary of two same-level units (incl.
    mid-edge vertex lying on a neighbour's edge segment)
  - shell:  vertex on the enclosing parent shell (wins over shared)
  - editable = shared − shell
  - boundary (Rule A): fully editable (caller gates on no-structure)

Explicit coordinate rings are used throughout so vertex indices are
deterministic (shapely's ``box()`` ring start corner is not stable).
"""
import math
import pytest

from app.services.vertex_classification_service import (
    BOUNDARY_LAYER,
    classify_vertices,
    coord_at_index,
    iter_vertices,
    ring_of_index,
)


def _gj(ring):
    return {"type": "Polygon", "coordinates": [list(ring)]}


def _gj_multi(rings):
    return {"type": "MultiPolygon", "coordinates": [[list(r)] for r in rings]}


def _as_feature(geom, fid):
    return {"id": str(fid), "geometry": geom}


BOUNDARY = _gj([(83.0, 27.0), (84.0, 27.0), (84.0, 28.0), (83.0, 28.0)])

# Block A and B share the vertical segment x=83.5 (y 27.2..27.8).
A = _gj([(83.2, 27.2), (83.5, 27.2), (83.5, 27.8), (83.2, 27.8)])
B = _gj([(83.5, 27.2), (83.8, 27.2), (83.8, 27.8), (83.5, 27.8)])


# ---------------------------------------------------------------------------
# 1. Two adjacent blocks sharing an interior edge
# ---------------------------------------------------------------------------

def test_two_blocks_shared_interior_vertices_editable():
    """Interior shared-vertex pair is editable; non-shared interior vertices are
    not editable (Rule B: only shared vertices may be edited)."""
    res = classify_vertices(
        A, "blocks",
        same_level_features=[_as_feature(B, "b")],
        parent_shell=BOUNDARY,
    )
    # A ring: (83.2,27.2),(83.5,27.2),(83.5,27.8),(83.2,27.8)
    # indices 1 & 2 are on B's boundary (shared, inside shell) → editable.
    assert res["editable"] == [1, 2], res
    assert res["shared"] == [1, 2], res
    assert res["shell"] == [], res
    assert res["vertex_count"] == 4


def test_two_blocks_shell_vertices_locked():
    """Block vertices on the forest boundary are shell → locked (not editable)."""
    # A touches the boundary's left edge (x=83.0) and bottom edge (y=27.0)
    a = _gj([(83.0, 27.0), (83.5, 27.0), (83.5, 27.5), (83.0, 27.5)])
    b = _gj([(83.0, 27.5), (83.5, 27.5), (83.5, 28.0), (83.0, 28.0)])
    # A vertices:
    #   (83.0,27.0) on shell (corner)            → shell
    #   (83.5,27.0) on shell (y=27.0)            → shell (not shared with b)
    #   (83.5,27.5) shared with B, interior      → editable
    #   (83.0,27.5) on shell (x=83.0) + shared   → shell wins
    res = classify_vertices(
        a, "blocks",
        same_level_features=[_as_feature(b, "b")],
        parent_shell=BOUNDARY,
    )
    assert res["shell"] == [0, 1, 3], res
    assert res["shared"] == [2, 3], res
    assert res["editable"] == [2], res


# ---------------------------------------------------------------------------
# 2. Mid-edge vertex on a shared edge (no coincident neighbour vertex)
# ---------------------------------------------------------------------------

def test_mid_edge_vertex_on_shared_segment_is_shared():
    """A vertex lying mid-edge on a neighbour's segment (no coincident vertex)
    is classified shared → editable (plan §1.1)."""
    # B has no vertex at (83.5, 27.5); A inserts a vertex there.
    a = _gj([(83.2, 27.2), (83.5, 27.2), (83.5, 27.5), (83.5, 27.8), (83.2, 27.8)])
    res = classify_vertices(
        a, "blocks",
        same_level_features=[_as_feature(B, "b")],
        parent_shell=BOUNDARY,
    )
    # A ring: index 2 = (83.5,27.5) lies ON B's left segment → shared, interior
    assert 2 in res["shared"], res
    assert 2 in res["editable"], res


def test_mid_edge_vertex_off_shared_segment_not_shared():
    """A vertex near but NOT on a neighbour segment (> tolerance) is not shared."""
    a = _gj([(83.2, 27.2), (83.5, 27.2), (83.45, 27.5), (83.5, 27.8), (83.2, 27.8)])
    res = classify_vertices(
        a, "blocks",
        same_level_features=[_as_feature(B, "b")],
        parent_shell=BOUNDARY,
    )
    # (83.45,27.5) is ~0.05 deg (~5.5km) off the shared edge → beyond 150m tol
    assert 2 not in res["shared"], res
    assert 2 not in res["editable"], res


# ---------------------------------------------------------------------------
# 3. Junction on the boundary — shared but locked
# ---------------------------------------------------------------------------

def test_junction_on_boundary_locked():
    """A 2-block junction lying ON the forest boundary is shared BUT on the
    shell → locked (rule 4)."""
    a = _gj([(83.0, 27.0), (83.5, 27.0), (83.5, 27.5), (83.0, 27.5)])
    b = _gj([(83.0, 27.5), (83.5, 27.5), (83.5, 28.0), (83.0, 28.0)])
    res = classify_vertices(
        a, "blocks",
        same_level_features=[_as_feature(b, "b")],
        parent_shell=BOUNDARY,
    )
    # (83.0,27.5) = A index 3, on the boundary's left edge + coincident with B
    # index 0 → shared AND shell → locked.
    assert 3 in res["shell"], res
    assert 3 in res["shared"], res
    assert 3 not in res["editable"], res


# ---------------------------------------------------------------------------
# 4. Compartment inside a block
# ---------------------------------------------------------------------------

def test_compartment_interior_shared_editable_block_shell_locked():
    """Compartments: interior shared vertices editable; vertices on the parent
    block shell locked."""
    block = _gj([(83.0, 27.0), (84.0, 27.0), (84.0, 28.0), (83.0, 28.0)])
    c1 = _gj([(83.2, 27.2), (83.6, 27.2), (83.6, 27.8), (83.2, 27.8)])
    c2 = _gj([(83.6, 27.2), (84.0, 27.2), (84.0, 27.8), (83.6, 27.8)])

    res = classify_vertices(
        c1, "compartments",
        same_level_features=[_as_feature(c2, "c2")],
        parent_shell=block,
    )
    # c1 indices 1,2 on c2's boundary, interior to block → editable
    assert res["editable"] == [1, 2], res
    assert res["shell"] == [], res


def test_compartment_vertex_on_block_shell_locked():
    """A compartment vertex ON the parent block shell is locked even when shared."""
    block = _gj([(83.0, 27.0), (84.0, 27.0), (84.0, 28.0), (83.0, 28.0)])
    # c1 touches the block's bottom (y=27.0) and shares a vertical edge with c2
    c1 = _gj([(83.0, 27.0), (83.5, 27.0), (83.5, 28.0), (83.0, 28.0)])
    c2 = _gj([(83.5, 27.0), (84.0, 27.0), (84.0, 28.0), (83.5, 28.0)])
    res = classify_vertices(
        c1, "compartments",
        same_level_features=[_as_feature(c2, "c2")],
        parent_shell=block,
    )
    # c1 vertices (83.0,27.0),(83.5,27.0),(83.5,28.0),(83.0,28.0) all lie on the
    # block shell (y edges) → nothing editable
    assert res["editable"] == [], res
    assert set(res["shell"]) == {0, 1, 2, 3}, res


# ---------------------------------------------------------------------------
# 5. Sub-compartment inside a compartment (one level deeper)
# ---------------------------------------------------------------------------

def test_sub_compartment_deep_pattern():
    """Sub-compartments classify identically one level deeper."""
    parent_comp = _gj([(83.0, 27.0), (83.5, 27.0), (83.5, 28.0), (83.0, 28.0)])
    sub_a = _gj([(83.1, 27.1), (83.3, 27.1), (83.3, 27.9), (83.1, 27.9)])
    sub_b = _gj([(83.3, 27.1), (83.5, 27.1), (83.5, 27.9), (83.3, 27.9)])

    res = classify_vertices(
        sub_a, "sub_compartments",
        same_level_features=[_as_feature(sub_b, "sub_b")],
        parent_shell=parent_comp,
    )
    assert res["editable"] == [1, 2], res
    assert res["shell"] == [], res


def test_sub_compartment_on_parent_shell_locked():
    """Sub-compartment vertices on the parent compartment shell are locked."""
    parent_comp = _gj([(83.0, 27.0), (83.5, 27.0), (83.5, 28.0), (83.0, 28.0)])
    sub_a = _gj([(83.0, 27.0), (83.25, 27.0), (83.25, 28.0), (83.0, 28.0)])
    sub_b = _gj([(83.25, 27.0), (83.5, 27.0), (83.5, 28.0), (83.25, 28.0)])
    res = classify_vertices(
        sub_a, "sub_compartments",
        same_level_features=[_as_feature(sub_b, "sub_b")],
        parent_shell=parent_comp,
    )
    assert res["editable"] == [], res
    assert len(res["shell"]) == 4, res


# ---------------------------------------------------------------------------
# 6. Isolated block + boundary layer
# ---------------------------------------------------------------------------

def test_isolated_block_touching_boundary_nothing_editable():
    """A lone block (no structural siblings) touching the boundary has no
    editable vertices — a fully shell-bounded unit is not editable."""
    a = _gj([(83.0, 27.0), (83.5, 27.0), (83.5, 27.5), (83.0, 27.5)])
    res = classify_vertices(
        a, "blocks",
        same_level_features=[],
        parent_shell=BOUNDARY,
    )
    assert res["shared"] == [], res
    assert res["editable"] == [], res
    # (83.5,27.5) is interior to the boundary → not on shell, but also not
    # shared → still not editable (Rule B).
    assert 2 not in res["editable"]


def test_boundary_layer_fully_editable():
    """Rule A classifier: boundary has no shell / no same-level neighbours →
    every vertex editable (the no-structure gate is the caller's job)."""
    res = classify_vertices(
        BOUNDARY, BOUNDARY_LAYER,
        same_level_features=[],
        parent_shell=None,
    )
    assert res["editable"] == [0, 1, 2, 3], res
    assert res["shell"] == []
    assert res["vertex_count"] == 4


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_iter_and_resolve_helpers():
    verts = list(iter_vertices(BOUNDARY))
    assert verts == [
        (0, (83.0, 27.0)),
        (1, (84.0, 27.0)),
        (2, (84.0, 28.0)),
        (3, (83.0, 28.0)),
    ]
    assert coord_at_index(BOUNDARY, 2) == (84.0, 28.0)
    assert coord_at_index(BOUNDARY, 99) is None
    assert ring_of_index(BOUNDARY, 2) == (0, 2)
    assert ring_of_index(BOUNDARY, 99) is None


def test_multi_polygon_indices_flat_across_polys():
    """MultiPolygon vertex indices are flat across both polygons."""
    geom = _gj_multi([
        [(83.0, 27.0), (83.5, 27.0), (83.5, 27.5), (83.0, 27.5)],
        [(83.5, 27.5), (84.0, 27.5), (84.0, 28.0), (83.5, 28.0)],
    ])
    verts = list(iter_vertices(geom))
    assert len(verts) == 8
    assert verts[0] == (0, (83.0, 27.0))
    assert verts[4] == (4, (83.5, 27.5))
    assert coord_at_index(geom, 7) == (83.5, 28.0)
    assert ring_of_index(geom, 5) == (1, 1)


def test_classify_empty_geometry():
    res = classify_vertices(
        {"type": "Polygon", "coordinates": []}, "blocks",
        same_level_features=[], parent_shell=None,
    )
    assert res == {"shared": [], "shell": [], "editable": [], "vertex_count": 0}


def test_classify_accepts_shapely_directly():
    from shapely.geometry import Polygon
    a = Polygon([(83.2, 27.2), (83.5, 27.2), (83.5, 27.8), (83.2, 27.8)])
    b = Polygon([(83.5, 27.2), (83.8, 27.2), (83.8, 27.8), (83.5, 27.8)])
    res = classify_vertices(a, "blocks", same_level_features=[b], parent_shell=None)
    assert res["editable"] == [1, 2], res


@pytest.mark.parametrize("geom", [None, {"type": "Point", "coordinates": [83.5, 27.5]}])
def test_classify_non_polygon_geometry(geom):
    res = classify_vertices(geom, "blocks", same_level_features=[], parent_shell=None)
    assert res["editable"] == []
    assert res["vertex_count"] == 0


def test_small_forest_blocks_keep_editable_shared_vertices():
    """Regression: the shell test must be a point-on-line check, not the 150 m
    neighbour SEARCH radius.

    Two 150 m x 300 m blocks tiling a ~9 ha forest.  Every vertex is within
    150 m of the forest boundary, so reusing MAX_EDGE_TOLERANCE_M as the
    classification tolerance marked all of them 'shell' -> editable == []
    -> the vertex tool rendered no drag markers at all on any small forest.
    The two vertices on the interior shared edge must stay editable.
    """
    # ~0.00135 deg latitude ~= 150 m; longitude at 27N is scaled by cos(27).
    d = 150.0 / 111_320.0
    dx = d / math.cos(math.radians(27.0))
    x0, y0 = 83.0, 27.0
    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [x0, y0], [x0 + 2 * dx, y0], [x0 + 2 * dx, y0 + 2 * d],
            [x0, y0 + 2 * d], [x0, y0],
        ]],
    }
    # Both blocks carry a mid-edge vertex halfway up the shared edge.  Plain
    # rectangles would not exercise anything: their only shared vertices are
    # the outer corners, where shell legitimately wins.
    left = {
        "type": "Polygon",
        "coordinates": [[
            [x0, y0], [x0 + dx, y0], [x0 + dx, y0 + d], [x0 + dx, y0 + 2 * d],
            [x0, y0 + 2 * d], [x0, y0],
        ]],
    }
    right = {
        "type": "Polygon",
        "coordinates": [[
            [x0 + dx, y0], [x0 + 2 * dx, y0], [x0 + 2 * dx, y0 + 2 * d],
            [x0 + dx, y0 + 2 * d], [x0 + dx, y0 + d], [x0 + dx, y0],
        ]],
    }

    # NB: same_level_features takes FEATURE dicts -- a bare geometry dict is
    # silently skipped (feat.get("geometry") is None), yielding no neighbours.
    res = classify_vertices(left, "blocks", [{"id": "right", "geometry": right}], boundary)

    # The whole forest fits inside a 150 m band, so the old tolerance made
    # every vertex shell and left nothing to drag.
    assert res["editable"], (
        "no editable vertices on a small forest -- the shell test is using a "
        "search radius instead of a point-on-line tolerance"
    )
    # Corners sit on the forest boundary (shell wins over shared, rule 4), so
    # the ONLY editable vertex is the mid-edge one on the interior shared edge.
    assert len(res["editable"]) == 1, res
    x, y = coord_at_index(left, res["editable"][0])
    assert abs(x - (x0 + dx)) < 1e-9, "editable vertex is not on the shared edge"
    assert abs(y - (y0 + d)) < 1e-9, "editable vertex is not the mid-edge one"
