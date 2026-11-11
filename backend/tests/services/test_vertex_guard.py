"""VR-3 — server-side locked-vertex guard.

Until this phase the vertex rules existed only in the browser: the mask hid
markers the user was not allowed to grab, and that was the whole enforcement.
Undo/redo, a retried request, a stale tab or curl could move a locked vertex
and the API stored it.  These tests pin that the server now refuses.

They deliberately bypass the frontend entirely — every case builds a request
geometry directly, which is precisely the attack surface the guard exists for.
"""
import uuid

import pytest
from shapely.geometry import Polygon, mapping

from app.core.constants import VERTEX_MOVE_EPSILON_M
from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User, UserRole
from app.services import vertex_guard_service as guard
from app.services.geometry_edit_service import area_sqm


# ---------------------------------------------------------------------------
# Geometry: two blocks tiling a boundary, sharing the edge x=85.7620.
# ---------------------------------------------------------------------------

BOUNDARY = Polygon([(85.7610, 27.4137), (85.7630, 27.4137),
                    (85.7630, 27.4145), (85.7610, 27.4145)])
LEFT = Polygon([(85.7610, 27.4137), (85.7620, 27.4137),
                (85.7620, 27.4145), (85.7610, 27.4145)])
RIGHT = Polygon([(85.7620, 27.4137), (85.7630, 27.4137),
                 (85.7630, 27.4145), (85.7620, 27.4145)])

M = 1 / 111_320.0


def _gj(poly):
    return mapping(poly)


def _make_calc(db, boundary=BOUNDARY):
    user = User(
        email=f"vr3{uuid.uuid4().hex[:8]}@test.com",
        full_name="VR-3 Tester",
        role=UserRole.USER,
        hashed_password="not-a-real-hash",
    )
    db.add(user)
    db.flush()
    calc = Calculation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        uploaded_filename="vr3-guard.csv",
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


def _add_block(db, calc, geom, level=1, parent=None, name=None):
    from geoalchemy2.shape import from_shape
    row = ForestBlock(
        calculation_id=calc.id,
        name=name or f"b-{uuid.uuid4().hex[:4]}",
        geometry=from_shape(geom, srid=4326),
        area_hectares=round(area_sqm(geom) / 10000.0, 4),
        area_sqm=round(area_sqm(geom), 2),
        index=0,
        is_compartment=level >= 1,
        division_level=level,
        parent_block_id=parent.id if parent is not None else None,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------------------
# diff_vertices
# ---------------------------------------------------------------------------

def test_identical_geometry_reports_no_movement():
    assert guard.diff_vertices(LEFT, LEFT) == {"moved": [], "added": []}


def test_round_trip_noise_is_not_a_move():
    """Micro-degree drift from PostGIS -> GeoJSON -> LatLng must not trip the guard."""
    jittered = Polygon([(x + 1e-9, y - 1e-9) for x, y in LEFT.exterior.coords[:-1]])
    assert guard.diff_vertices(LEFT, jittered)["moved"] == []


def test_a_real_move_is_detected():
    moved = Polygon([(85.7610, 27.4137), (85.7620 + 5 * M, 27.4137),
                     (85.7620, 27.4145), (85.7610, 27.4145)])
    assert guard.diff_vertices(LEFT, moved)["moved"] == [1]


def test_a_move_just_above_epsilon_is_detected():
    delta = (VERTEX_MOVE_EPSILON_M * 3) * M
    moved = Polygon([(85.7610, 27.4137), (85.7620 + delta, 27.4137),
                     (85.7620, 27.4145), (85.7610, 27.4145)])
    assert guard.diff_vertices(LEFT, moved)["moved"] == [1]


def test_insertion_elsewhere_does_not_flag_the_whole_tail():
    """Position-independent diffing: an insert renumbers, it does not move."""
    inserted = Polygon([(85.7610, 27.4137), (85.7615, 27.4137), (85.7620, 27.4137),
                        (85.7620, 27.4145), (85.7610, 27.4145)])
    delta = guard.diff_vertices(LEFT, inserted)
    assert delta["moved"] == []
    assert delta["added"] == [1]


# ---------------------------------------------------------------------------
# assert_no_locked_vertex_change
# ---------------------------------------------------------------------------

def _siblings():
    return [{"id": "right", "geometry": RIGHT}]


def test_moving_a_shell_vertex_is_refused():
    # (85.7610, 27.4137) is a corner of the forest boundary -> shell -> locked.
    attacked = Polygon([(85.7610 - 5 * M, 27.4137 - 5 * M), (85.7620, 27.4137),
                        (85.7620, 27.4145), (85.7610, 27.4145)])
    with pytest.raises(guard.LockedVertexError) as exc:
        guard.assert_no_locked_vertex_change(
            LEFT, attacked, "blocks", _siblings(), BOUNDARY,
        )
    assert exc.value.code == guard.VERTEX_LOCKED
    assert 0 in exc.value.indices


def test_removing_a_shell_vertex_is_refused():
    dropped = Polygon([(85.7620, 27.4137), (85.7620, 27.4145), (85.7610, 27.4145)])
    with pytest.raises(guard.LockedVertexError):
        guard.assert_no_locked_vertex_change(
            LEFT, dropped, "blocks", _siblings(), BOUNDARY,
        )


def test_adding_a_vertex_on_the_shell_is_refused():
    """Otherwise the shell can be reshaped by addition rather than by movement."""
    added = Polygon([(85.7610, 27.4137), (85.7615, 27.4137), (85.7620, 27.4137),
                     (85.7620, 27.4145), (85.7610, 27.4145)])
    with pytest.raises(guard.LockedVertexError) as exc:
        guard.assert_no_locked_vertex_change(
            LEFT, added, "blocks", _siblings(), BOUNDARY,
        )
    assert exc.value.code == guard.VERTEX_LOCKED


def test_moving_a_shared_non_shell_vertex_is_allowed(db):
    """The gesture the whole feature exists for must still pass.

    A taller boundary leaves the blocks' shared edge in the interior, so its
    vertices are shared-but-not-shell.
    """
    tall = Polygon([(85.7600, 27.4130), (85.7640, 27.4130),
                    (85.7640, 27.4150), (85.7600, 27.4150)])
    # Shared edge endpoints are now strictly inside `tall`.
    inner_left = Polygon([(85.7610, 27.4137), (85.7620, 27.4137),
                          (85.7620, 27.4145), (85.7610, 27.4145)])
    inner_right = Polygon([(85.7620, 27.4137), (85.7630, 27.4137),
                           (85.7630, 27.4145), (85.7620, 27.4145)])
    moved = Polygon([(85.7610, 27.4137), (85.7620 + 2 * M, 27.4137),
                     (85.7620, 27.4145), (85.7610, 27.4145)])
    guard.assert_no_locked_vertex_change(
        inner_left, moved, "blocks",
        [{"id": "right", "geometry": inner_right}], tall,
    )  # must not raise
    assert db is not None


def test_no_shell_means_nothing_to_guard():
    moved = Polygon([(85.7610 - 5 * M, 27.4137), (85.7620, 27.4137),
                     (85.7620, 27.4145), (85.7610, 27.4145)])
    guard.assert_no_locked_vertex_change(LEFT, moved, "blocks", _siblings(), None)


def test_sub_areas_are_not_guarded():
    moved = Polygon([(85.7610 - 5 * M, 27.4137), (85.7620, 27.4137),
                     (85.7620, 27.4145), (85.7610, 27.4145)])
    guard.assert_no_locked_vertex_change(LEFT, moved, "sub_areas", _siblings(), BOUNDARY)


# ---------------------------------------------------------------------------
# Rule A
# ---------------------------------------------------------------------------

def test_boundary_is_editable_with_no_structure(db):
    calc = _make_calc(db)
    guard.assert_boundary_editable(db, calc)  # must not raise
    assert guard.has_structural_features(db, calc) is False


def test_boundary_is_locked_once_a_block_exists(db):
    calc = _make_calc(db)
    _add_block(db, calc, LEFT)
    assert guard.has_structural_features(db, calc) is True
    with pytest.raises(guard.LockedVertexError) as exc:
        guard.assert_boundary_editable(db, calc)
    assert exc.value.code == guard.BOUNDARY_LOCKED_BY_STRUCTURE


def test_boundary_is_locked_by_a_compartment_too(db):
    calc = _make_calc(db)
    block = _add_block(db, calc, LEFT)
    _add_block(db, calc, LEFT, level=2, parent=block)
    with pytest.raises(guard.LockedVertexError):
        guard.assert_boundary_editable(db, calc)
