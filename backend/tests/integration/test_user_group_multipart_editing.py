"""The user-group extent is a real MultiPolygon layer: cut, vertex-edit, merge.

Found during P6 review (2026-09-28). Splitting one island in two did not work and
reported success while doing nothing::

    response          200 OK
    parts before      3
    parts after       3        <- expected 4
    island 0 changed  False    <- byte-for-byte the same island
    total area        0.030000 before, 0.030000 after

Cause: ``edit-geometry`` runs the payload through ``validate_geometry_edit`` →
``sanitize_geometry``, and a cut's two halves **share an edge**, which GEOS reports
as an *invalid* MultiPolygon. ``make_valid`` therefore unioned the pair straight back
into the polygon the user started with. The only warning raised was
``SELF_INTERSECTION_FIXED``, which the endpoint does not escalate (only
``TOPOLOGY_REJECTED`` becomes a 409), so the caller was told it had worked.

Ruled out by direct measurement, so the fix does not chase them:
``_splice_user_group_part`` is correct, PostGIS preserves touching parts through both
``ST_GeomFromEWKT`` and a ``::geometry(MULTIPOLYGON,4326)`` cast, and there is no
trigger on ``user_group_extents``.

The fix narrows ``sanitize_geometry`` only for :data:`MULTIPART_LAYERS`, and only for
parts that *touch* rather than overlap. The tests that matter are the ones asserting
it did NOT weaken anything: a genuine self-intersection is still healed, and a
structural layer still collapses exactly as before.
"""

from __future__ import annotations

import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely import wkt as shp_wkt
from shapely.geometry import MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union
from sqlalchemy import text

from app.models.user_group import UserGroupExtent
from app.services.geometry_edit_service import (
    MULTIPART_LAYERS,
    sanitize_geometry,
    validate_geometry_edit,
)

pytestmark = pytest.mark.usefixtures("forget_forests", "relax_user_group_limit")


def _register(client):
    email = f"ug-mp-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG Multi",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _three_islands():
    return MultiPolygon([
        box(83.10, 27.10, 83.20, 27.20),
        box(83.30, 27.30, 83.40, 27.40),
        box(83.50, 27.50, 83.60, 27.60),
    ])


def _calc_with_extent(db, user_id, extent_geom):
    from app.models.calculation import Calculation, CalculationStatus

    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name="UG Multi Forest",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    extent = UserGroupExtent(
        calculation_id=calc.id, user_id=user_id,
        extent_geometry=from_shape(extent_geom, srid=4326), source_type="manual",
    )
    db.add(extent)
    db.commit()
    db.refresh(extent)
    return calc, extent


def _stored(db, extent_id):
    row = db.execute(text(
        "SELECT ST_AsGeoJSON(extent_geometry) AS g FROM user_group_extents WHERE id = :i"
    ), {"i": extent_id}).first()
    return shape(json.loads(row.g))


def _edit(client, headers, calc_id, feature_id, geom):
    return client.post(
        f"/api/v1/calculations/{calc_id}/geometry/edit-geometry",
        headers=headers,
        json={"layer_type": "user_group", "feature_id": feature_id,
              "geometry": mapping(geom)},
    )


def _cut_halves():
    """A cut along y=27.15: the two edge-sharing halves it produces."""
    return box(83.10, 27.10, 83.20, 27.15), box(83.10, 27.15, 83.20, 27.20)


class TestCutKeepsItsPieces:
    def test_user_group_is_a_multipart_layer(self):
        assert "user_group" in MULTIPART_LAYERS

    def test_sanitize_keeps_both_halves_when_asked_to(self):
        lower, upper = _cut_halves()
        kept, warnings = sanitize_geometry(
            MultiPolygon([lower, upper]), preserve_touching_parts=True
        )
        assert len(list(getattr(kept, "geoms", [kept]))) == 2
        # And it is no longer reported as a self-intersection: nothing was healed.
        assert "SELF_INTERSECTION_FIXED" not in warnings

    def test_the_extent_gains_a_part_after_a_cut(self, client, db):
        """The regression: 3 islands, cut one, 4 islands."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        lower, upper = _cut_halves()
        area_before = sum(g.area for g in _stored(db, extent.id).geoms)

        resp = _edit(client, headers, calc.id, f"user_group#{extent.id}#0",
                     MultiPolygon([lower, upper]))
        assert resp.status_code == 200, resp.text

        db.expire_all()
        after = list(_stored(db, extent.id).geoms)
        assert len(after) == 4, f"expected 4 islands after the cut, got {len(after)}"
        assert after[0].equals(lower)
        assert after[1].equals(upper)
        # The untouched islands keep their positions and their area.
        assert after[2].equals(_three_islands().geoms[1])
        assert after[3].equals(_three_islands().geoms[2])
        assert abs(sum(g.area for g in after) - area_before) < 1e-12

    def test_vertex_edit_still_works_on_a_reshaped_island(self, client, db):
        """Cut, then move one of the halves - the two must not interfere."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        lower, upper = _cut_halves()
        assert _edit(client, headers, calc.id, f"user_group#{extent.id}#0",
                     MultiPolygon([lower, upper])).status_code == 200

        moved = box(83.10, 27.15, 83.22, 27.20)
        assert _edit(client, headers, calc.id, f"user_group#{extent.id}#1", moved).status_code == 200

        db.expire_all()
        after = list(_stored(db, extent.id).geoms)
        assert len(after) == 4
        assert after[0].equals(lower), "the other half must be untouched"
        assert after[1].equals(moved)


class TestTheNarrowingDidNotWeakenHealing:
    """The fix must not turn a real self-intersection into a stored defect."""

    def test_a_bow_tie_is_still_healed_for_a_multipart_layer(self):
        bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
        assert not bowtie.is_valid
        healed, warnings = sanitize_geometry(
            bowtie, preserve_touching_parts=True
        )
        assert healed.is_valid, "a genuine self-intersection must still be healed"
        assert "SELF_INTERSECTION_FIXED" in warnings

    def test_overlapping_parts_are_still_healed(self):
        """Touching is preserved; overlapping is still collapsed."""
        a = box(0, 0, 2, 2)
        overlapping = MultiPolygon([a, box(1, 0, 3, 2)])
        healed, _ = sanitize_geometry(overlapping, preserve_touching_parts=True)
        assert healed.is_valid, "overlapping parts must still be repaired"

    def test_the_default_behaviour_is_unchanged(self):
        """No layer gets the exemption by accident - only MULTIPART_LAYERS do."""
        lower, upper = _cut_halves()
        collapsed, _ = sanitize_geometry(MultiPolygon([lower, upper]))
        assert len(list(getattr(collapsed, "geoms", [collapsed]))) == 1
        assert collapsed.equals(unary_union([lower, upper]))

    def test_a_structural_layer_still_collapses_touching_parts(self):
        """blocks/compartments rely on this healing; user_group must not have
        changed it for them."""
        lower, upper = _cut_halves()
        result = validate_geometry_edit(
            mapping(MultiPolygon([lower, upper])), "blocks", None, []
        )
        healed = shape(result.geometry)
        # A Polygon has no `.geoms`, so normalise before counting.
        parts = list(getattr(healed, "geoms", [healed]))
        assert len(parts) == 1, f"a structural layer should still collapse to 1, got {len(parts)}"
        assert healed.equals(unary_union([lower, upper]))


class TestMergeIsTheInverseOfTheCut:
    def test_merging_two_islands_undoes_the_cut(self, client, db):
        """The round trip: 3 islands -> cut -> 4 -> merge back -> 3, same shape."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        original = _stored(db, extent.id)
        lower, upper = _cut_halves()
        assert _edit(client, headers, calc.id, f"user_group#{extent.id}#0",
                     MultiPolygon([lower, upper])).status_code == 200

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [f"user_group#{extent.id}#0", f"user_group#{extent.id}#1"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["merged"] == 1, "two islands fused into one"

        db.expire_all()
        after = list(_stored(db, extent.id).geoms)
        assert len(after) == 3
        assert after[0].equals(unary_union([lower, upper]))
        assert _stored(db, extent.id).equals(original), "the round trip must restore the extent"

    def test_merge_reports_the_new_island_ids(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        lower, upper = _cut_halves()
        _edit(client, headers, calc.id, f"user_group#{extent.id}#0",
              MultiPolygon([lower, upper]))
        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [f"user_group#{extent.id}#0", f"user_group#{extent.id}#1"]},
        )
        ids = resp.json()["feature_ids"]
        assert len(ids) == 3
        assert ids == [f"user_group#{extent.id}#{i}" for i in range(3)]

    def test_merging_islands_that_do_not_touch_changes_nothing(self, client, db):
        """Disjoint islands union back to the same shape, and that is reported."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        before = _stored(db, extent.id)
        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [f"user_group#{extent.id}#0", f"user_group#{extent.id}#2"]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["merged"] == 0
        assert "do not touch" in body["warning"]
        db.expire_all()
        assert _stored(db, extent.id).equals(before), "a non-touching merge must not move anything"

    def test_merge_rejects_a_whole_extent_id(self, client, db):
        """An id with no part names the whole extent, which is not mergeable."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [f"user_group#{extent.id}", f"user_group#{extent.id}#1"]},
        )
        assert resp.status_code == 400, resp.text

    def test_merge_rejects_a_duplicate_island(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [f"user_group#{extent.id}#1", f"user_group#{extent.id}#1"]},
        )
        assert resp.status_code == 400, resp.text

    def test_merge_is_audited_and_bumps_the_geometry_clock(self, client, db):
        from sqlalchemy import text as sql_text

        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        lower, upper = _cut_halves()
        _edit(client, headers, calc.id, f"user_group#{extent.id}#0",
              MultiPolygon([lower, upper]))
        db.expire_all()
        version_before = calc.geometry_version

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [f"user_group#{extent.id}#0", f"user_group#{extent.id}#1"]},
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        assert calc.geometry_version > version_before, "the client relies on this to refetch"
        audit = db.execute(sql_text(
            "SELECT operation FROM geometry_audits "
            "WHERE calculation_id = :c AND layer_type = 'user_group' ORDER BY id DESC LIMIT 1"
        ), {"c": calc.id}).scalar()
        assert audit == "MERGE", f"expected a MERGE audit row, got {audit!r}"


class TestGuardsStillHold:
    def test_disjoint_pieces_survive_without_the_flag(self):
        lower = box(83.10, 27.10, 83.20, 27.20)
        far = box(84.90, 27.10, 85.00, 27.20)
        kept, _ = sanitize_geometry(MultiPolygon([lower, far]))
        assert len(list(getattr(kept, "geoms", [kept]))) == 2

    def test_splice_keeps_both_pieces_and_the_neighbours(self):
        from app.api.editing import _splice_user_group_part

        stored = _three_islands()
        lower, upper = _cut_halves()
        parts = list(_splice_user_group_part(stored, 0, MultiPolygon([lower, upper])).geoms)
        assert len(parts) == 4
        assert parts[0].equals(lower) and parts[1].equals(upper)
        assert parts[2].equals(stored.geoms[1]) and parts[3].equals(stored.geoms[2])

    def test_an_out_of_range_part_index_is_refused(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _three_islands())
        resp = _edit(client, headers, calc.id, f"user_group#{extent.id}#9",
                     box(83.9, 27.9, 83.95, 27.95))
        assert resp.status_code == 404, resp.text
