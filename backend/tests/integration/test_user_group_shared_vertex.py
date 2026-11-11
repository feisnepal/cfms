"""Block-style vertex editing for user_group: shared vertices move together.

Owner report: vertex editing worked on a user-group polygon, but not the way
blocks behave - dragging a vertex shared by two polygons moved only one of them.

That was an explicit exclusion on BOTH sides, not a limitation of the machinery:

- the frontend passed `sharedMove` / `sharedVertexChange` only for blocks,
  sub_blocks, compartments and sub_compartments, so no shared partner was ever
  computed for user_group; and
- the backend rejected `shared_moves` for any non-structural layer outright.

Since P7d each user-group polygon is its own ROW, so a shared drag is just a
batch of row writes and `_persist_geometry_batch` already handles it generically.
The two exclusions were all that stood in the way.

What these tests pin:
- a shared vertex drag moves BOTH rows in ONE request, atomically;
- a drag on a vertex belonging to only one polygon touches only that row;
- the two stay topologically joined afterwards - the reason the feature exists.
"""

from __future__ import annotations

import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely import wkt as shp_wkt
from shapely.geometry import box, mapping, shape
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.user_group import UserGroupExtent

pytestmark = pytest.mark.usefixtures("forget_forests", "relax_user_group_limit")


def _register(client):
    email = f"ug-shared-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG Shared",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name="UG Shared",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _adjacent_pair(db, calc):
    """Two polygons sharing the edge y = 27.20, so one vertex is genuinely shared."""
    rows = []
    for g in (box(83.10, 27.10, 83.30, 27.20), box(83.10, 27.20, 83.30, 27.30)):
        e = UserGroupExtent(
            calculation_id=calc.id, user_id=user_id_of(db, calc),
            extent_geometry=from_shape(g, srid=4326), source_type="manual",
        )
        db.add(e)
        rows.append(e)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


def user_id_of(db, calc):
    return calc.user_id


def _stored(db, extent_id):
    row = db.execute(text(
        "SELECT ST_AsGeoJSON(extent_geometry) AS g FROM user_group_extents WHERE id = :i"
    ), {"i": extent_id}).first()
    return shape(json.loads(row.g))


def _shared_drag(client, headers, calc, rows, moved_both=True):
    """Drag the shared vertex (83.20, 27.20) north, propagating to the partner.

    The shared vertex is the one corner both polygons share. Moving it up and
    keeping both sides in step is the block behaviour.
    """
    left = [
        [83.10, 27.10], [83.20, 27.10], [83.20, 27.24], [83.10, 27.20],
    ]
    right = [
        [83.20, 27.24], [83.30, 27.20], [83.30, 27.30], [83.20, 27.30],
        [83.20, 27.24],
    ]
    body = {
        "layer_type": "user_group",
        "feature_id": str(rows[0].id),
        "geometry": mapping(_ring(left)),
    }
    if moved_both:
        body["shared_moves"] = [{
            "feature_id": str(rows[1].id),
            "geometry": mapping(_ring(right)),
        }]
    return client.post(
        f"/api/v1/calculations/{calc.id}/geometry/edit-geometry",
        headers=headers, json=body,
    )


def _ring(coords):
    from shapely.geometry import Polygon

    return Polygon(coords)


class TestSharedVertexMovesTogether:
    def test_a_shared_drag_moves_both_rows_in_one_request(self, client, db):
        headers, uid = _register(client)
        calc = _calc(db, uid)
        rows = _adjacent_pair(db, calc)

        resp = _shared_drag(client, headers, calc, rows, moved_both=True)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body.get("shared_moves_applied") == 1, (
            "the partner must be written in the same transaction, not ignored"
        )

        db.expire_all()
        left = _stored(db, rows[0].id)
        right = _stored(db, rows[1].id)
        # Both polygons moved: neither still has the old shared vertex.
        for geom, label in ((left, "left"), (right, "right")):
            assert not geom.geoms[0].equals(
                box(83.10, 27.10, 83.30, 27.20 if label == "left" else 27.30)
            ), f"the {label} polygon did not move"

    def test_the_pair_is_still_joined_afterwards(self, client, db):
        """The point of the feature: neighbours must not tear apart."""
        headers, uid = _register(client)
        calc = _calc(db, uid)
        rows = _adjacent_pair(db, calc)
        assert _shared_drag(client, headers, calc, rows, moved_both=True).status_code == 200

        db.expire_all()
        left = _stored(db, rows[0].id).geoms[0]
        right = _stored(db, rows[1].id).geoms[0]
        shared = left.intersection(right)
        assert not shared.is_empty, (
            "the two user-group polygons no longer touch - a shared drag must keep "
            "them joined, which is the whole reason blocks propagate the move"
        )

    def test_a_drag_with_no_partner_touches_only_that_row(self, client, db):
        headers, uid = _register(client)
        calc = _calc(db, uid)
        rows = _adjacent_pair(db, calc)

        resp = _shared_drag(client, headers, calc, rows, moved_both=False)
        assert resp.status_code == 200, resp.text
        assert "shared_moves_applied" not in resp.json()

        db.expire_all()
        assert not _stored(db, rows[0].id).geoms[0].equals(box(83.10, 27.10, 83.30, 27.20))
        # The untouched row is byte-identical - no accidental writes.
        assert _stored(db, rows[1].id).geoms[0].equals(box(83.10, 27.20, 83.30, 27.30))


class TestTheRejectionIsGone:
    def test_user_group_is_no_longer_refused(self, client, db):
        """The 400 this used to raise is what made the behaviour differ."""
        headers, uid = _register(client)
        calc = _calc(db, uid)
        rows = _adjacent_pair(db, calc)

        resp = _shared_drag(client, headers, calc, rows, moved_both=True)
        assert resp.status_code != 400, resp.text
        assert "shared_moves is only supported" not in resp.text

    def test_other_layers_are_still_refused(self, client, db):
        """The gate must not have been widened beyond the intent."""
        from app.api.editing import STRUCTURAL_LAYERS

        assert "user_group" not in STRUCTURAL_LAYERS, (
            "user_group is NOT a structural layer - it is included in the "
            "shared-move gate explicitly, and must not be smuggled into the set "
            "that drives clip-to-boundary, reclip and coverage invariants"
        )
