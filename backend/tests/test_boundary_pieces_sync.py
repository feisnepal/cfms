"""`forest_boundary_pieces` must stay in sync with `calculations.boundary_geom`
across every write path (BOUNDARY_PIECES_PLAN.md P2) -- the same "about a dozen
places write boundary_geom directly" problem `test_sub_area_boundary_paths.py`
already covers for sub-area re-clipping, mirrored here for piece rows.

Two things every writer must get right:
  - a single-polygon write keeps exactly one piece row (updated in place if one
    already existed, so a plain reshape doesn't lose a user-given name);
  - `merge-forest-boundary` with N disjoint polygons produces N piece rows, one
    per polygon the user actually drew -- never fused, never dropped.
"""

from __future__ import annotations

import itertools
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.affinity import translate
from shapely.geometry import box, mapping

from app.models.calculation import Calculation
from app.models.forest_boundary_piece import ForestBoundaryPiece
from app.models.user import User

pytestmark = pytest.mark.usefixtures("forget_forests")  # committed forests / rows are purged before and after each test: see conftest (test order is random)

_slot = itertools.count()


class World:
    def __init__(self, n: int):
        dx, dy = 0.05 * (n % 60), 0.05 * (n // 60)  # inside Nepal, never overlaps another test's ground

        def at(g):
            return translate(g, xoff=82.0 + dx, yoff=27.0 + dy)

        self.at = at
        self.SMALL = at(box(0.000, 0.000, 0.010, 0.020))
        self.PIECE_A = at(box(0.000, 0.000, 0.004, 0.004))
        self.PIECE_B = at(box(0.010, 0.010, 0.014, 0.014))  # disjoint from PIECE_A


@pytest.fixture()
def w():
    return World(next(_slot))


def _owner(client, db):
    email = f"bndp-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Boundary Pieces"},
    )
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    user = db.query(User).filter(User.email == email).first()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, user


def _calc(db, user, boundary=None, draft=False):
    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user.id,
        forest_name="Bnd Pieces Forest",
        uploaded_filename="bndp.csv",
        is_draft=draft,
    )
    db.add(calc)
    db.flush()
    if boundary is not None:
        calc.boundary_geom = from_shape(boundary, srid=4326)
    db.commit()
    return calc


def _pieces(db, calc):
    db.expire_all()
    return (
        db.query(ForestBoundaryPiece)
        .filter(ForestBoundaryPiece.calculation_id == calc.id)
        .order_by(ForestBoundaryPiece.created_at)
        .all()
    )


class TestSinglePolygonWriters:
    def test_put_boundary_creates_one_piece(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)

        r = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(w.SMALL), "confirmed": True},
        )
        assert r.status_code == 200, r.text

        pieces = _pieces(db, calc)
        assert len(pieces) == 1
        assert pieces[0].area_hectares > 0

    def test_reshaping_the_only_piece_updates_it_in_place(self, client, db, w):
        """A plain reshape (still one polygon) must keep the SAME piece row --
        this is what lets a user-given name survive an ordinary edit."""
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(w.SMALL), "confirmed": True},
        )
        before = _pieces(db, calc)
        assert len(before) == 1
        before_id = before[0].id
        before_area = before[0].area_hectares  # snapshot the value, not the ORM object --
        # `_pieces()` expires the session, and SQLAlchemy's identity map means
        # `before[0]` and a later `after[0]` are literally the same Python
        # object for the same row, so comparing the objects after a second
        # `_pieces()` call would compare a value against itself.

        # Reshape: a slightly bigger version of the same polygon.
        reshaped = w.at(box(0.000, 0.000, 0.012, 0.022))
        r = client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(reshaped), "confirmed": True},
        )
        assert r.status_code == 200, r.text

        after = _pieces(db, calc)
        assert len(after) == 1
        assert after[0].id == before_id, "reshaping a single piece must update it in place, not replace it"
        assert after[0].area_hectares > before_area

    def test_polygon_from_points_creates_one_piece(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        ring = list(w.SMALL.exterior.coords)[:-1]

        r = client.post(
            f"/api/workspace/{calc.id}/polygon-from-points",
            headers=headers,
            json={"points": [list(p) for p in ring], "target_type": "boundary", "name": "b"},
        )
        assert r.status_code == 200, r.text
        assert len(_pieces(db, calc)) == 1

    def test_draft_convert_creates_one_piece(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None, draft=True)

        r = client.post(
            f"/api/forests/drafts/{calc.id}/convert",
            headers=headers,
            json={"outer_boundary": mapping(w.SMALL)},
        )
        assert r.status_code == 200, r.text
        assert len(_pieces(db, calc)) == 1

    def test_deleting_the_boundary_deletes_its_pieces(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=w.SMALL)
        # backfill-equivalent: the direct-assignment fixture above bypasses the
        # write funnel, so seed the piece row the same way the app would have.
        db.add(
            ForestBoundaryPiece(
                calculation_id=calc.id, name="Piece 1",
                geometry=from_shape(w.SMALL, srid=4326), area_hectares=1.0,
            )
        )
        db.commit()
        assert len(_pieces(db, calc)) == 1

        r = client.delete(f"/api/v1/calculations/{calc.id}/boundary", headers=headers)
        assert r.status_code == 204, r.text
        assert len(_pieces(db, calc)) == 0


class TestMergeForestBoundary:
    def test_two_disjoint_polygons_become_two_pieces(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)

        r = client.post(
            f"/api/forests/calculations/{calc.id}/merge-forest-boundary",
            headers=headers,
            json={"geometries": [mapping(w.PIECE_A), mapping(w.PIECE_B)]},
        )
        assert r.status_code == 200, r.text

        pieces = _pieces(db, calc)
        assert len(pieces) == 2, "two disjoint drawn pieces must survive as two rows, not fused into one"
        names = sorted(p.name for p in pieces)
        assert names == ["Piece 1", "Piece 2"]
        # boundary_geom itself stays the union -- untouched by this plan.
        db.expire_all()
        stored_calc = db.get(Calculation, calc.id)
        assert stored_calc.boundary_geom is not None

    def test_adding_a_third_piece_later_replaces_the_set(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        client.post(
            f"/api/forests/calculations/{calc.id}/merge-forest-boundary",
            headers=headers,
            json={"geometries": [mapping(w.PIECE_A), mapping(w.PIECE_B)]},
        )
        assert len(_pieces(db, calc)) == 2

        piece_c = w.at(box(0.020, 0.020, 0.024, 0.024))
        r = client.post(
            f"/api/forests/calculations/{calc.id}/merge-forest-boundary",
            headers=headers,
            json={"geometries": [mapping(w.PIECE_A), mapping(w.PIECE_B), mapping(piece_c)]},
        )
        assert r.status_code == 200, r.text
        assert len(_pieces(db, calc)) == 3


class TestBoundaryPiecesApi:
    """BOUNDARY_PIECES_PLAN.md P3 — GET (list) + PATCH (rename)."""

    def test_list_returns_one_piece_with_its_default_name(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(w.SMALL), "confirmed": True},
        )

        r = client.get(f"/api/forests/calculations/{calc.id}/boundary-pieces", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_count"] == 1
        assert body["pieces"][0]["name"] == "Piece 1"
        assert body["pieces"][0]["area_hectares"] > 0
        assert body["pieces"][0]["geometry"]["type"] == "Polygon"
        assert body["total_area_hectares"] == body["pieces"][0]["area_hectares"]

    def test_list_returns_two_pieces_after_merge(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        client.post(
            f"/api/forests/calculations/{calc.id}/merge-forest-boundary",
            headers=headers,
            json={"geometries": [mapping(w.PIECE_A), mapping(w.PIECE_B)]},
        )

        r = client.get(f"/api/forests/calculations/{calc.id}/boundary-pieces", headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["total_count"] == 2

    def test_rename_a_piece(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(w.SMALL), "confirmed": True},
        )
        piece_id = _pieces(db, calc)[0].id

        r = client.patch(
            f"/api/forests/calculations/{calc.id}/boundary-pieces/{piece_id}",
            headers=headers,
            json={"name": "Main parcel"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Main parcel"

        r2 = client.get(f"/api/forests/calculations/{calc.id}/boundary-pieces", headers=headers)
        assert r2.json()["pieces"][0]["name"] == "Main parcel"

    def test_renamed_piece_survives_a_reshape(self, client, db, w):
        """The whole point of the "update in place" heuristic (P2): a rename
        must not get reset by an ordinary later edit."""
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=None)
        client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(w.SMALL), "confirmed": True},
        )
        piece_id = _pieces(db, calc)[0].id
        client.patch(
            f"/api/forests/calculations/{calc.id}/boundary-pieces/{piece_id}",
            headers=headers,
            json={"name": "Main parcel"},
        )

        reshaped = w.at(box(0.000, 0.000, 0.012, 0.022))
        client.put(
            f"/api/forests/calculations/{calc.id}/boundary",
            headers=headers,
            json={"geometry": mapping(reshaped), "confirmed": True},
        )

        r = client.get(f"/api/forests/calculations/{calc.id}/boundary-pieces", headers=headers)
        assert r.json()["pieces"][0]["name"] == "Main parcel"

    def test_renaming_an_unknown_piece_404s(self, client, db, w):
        headers, user = _owner(client, db)
        calc = _calc(db, user, boundary=w.SMALL)
        r = client.patch(
            f"/api/forests/calculations/{calc.id}/boundary-pieces/{uuid.uuid4()}",
            headers=headers,
            json={"name": "Nope"},
        )
        assert r.status_code == 404
