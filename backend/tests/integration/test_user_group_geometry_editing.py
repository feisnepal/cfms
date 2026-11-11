"""user_group extent through the shared geometry-editing API.

The user-group extent is a SINGLE stored row (``user_group_extents``) with no
name/area columns, so it cannot ride the ForestBlock-shaped path. These tests
pin that the shared router accepts it for every operation the toolbar offers
on a polygon layer -- vertex edit, cut, delete-guard, snapshot + restore -- and
that the response is keyed the way the client's feature is (``user_group#<id>``).
"""
import json
import uuid

from shapely import wkt as shp_wkt
from shapely.geometry import MultiPolygon, box, shape
from geoalchemy2.shape import from_shape
from sqlalchemy import text

from app.models.user_group import UserGroupExtent

import pytest

pytestmark = pytest.mark.usefixtures("forget_forests", "relax_user_group_limit")


def _register(client):
    email = f"ug-edit-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG Edit",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc_with_extent(db, user_id, extent_geom=None):
    """A calculation carrying one user-group extent, as the manual endpoint leaves it."""
    from app.models.calculation import Calculation, CalculationStatus

    calc = Calculation(
        id=uuid.uuid4(),
        user_id=user_id,
        forest_name="UG Edit Forest",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING,
        is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)

    if extent_geom is None:
        extent_geom = MultiPolygon([box(83.2, 27.2, 83.6, 27.6)])
    extent = UserGroupExtent(
        calculation_id=calc.id,
        user_id=user_id,
        extent_geometry=from_shape(extent_geom, srid=4326),
        source_type="manual",
    )
    db.add(extent)
    db.commit()
    db.refresh(extent)
    return calc, extent


def _url(calc_id, tail, api="/api/v1"):
    return f"{api}/calculations/{calc_id}/geometry/{tail}"


def _extent_geojson(db, extent_id):
    row = db.execute(text(
        "SELECT ST_AsGeoJSON(extent_geometry) AS g FROM user_group_extents WHERE id = :i"
    ), {"i": extent_id}).first()
    return shape(json.loads(row.g)) if row and row.g else None


def _extent_wkt(db, extent_id):
    row = db.execute(text(
        "SELECT ST_AsText(extent_geometry) AS w FROM user_group_extents WHERE id = :i"
    ), {"i": extent_id}).first()
    return row[0] if row and row[0] else ""


class TestUserGroupGeometryEditing:
    def test_vertex_edit_reshapes_the_single_extent_row(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid)
        before = _extent_geojson(db, extent.id)

        # Nudge the north edge south by moving one vertex.
        moved = {
            "type": "Polygon",
            "coordinates": [[[83.2, 27.2], [83.6, 27.2], [83.6, 27.5], [83.2, 27.5], [83.2, 27.2]]],
        }
        resp = client.post(
            _url(calc.id, "edit-geometry"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}",
                "geometry": moved,
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        # Keyed exactly like the client's feature, so the response maps back.
        assert body["feature"]["id"] == f"user_group#{extent.id}"
        assert shape(body["feature"]["geometry"]).bounds[3] == pytest.approx(27.5)

        db.expire_all()
        assert _extent_geojson(db, extent.id) != before

    def test_stored_extent_stays_a_multipolygon_column_value(self, client, db):
        """A plain Polygon edit must not violate the MULTIPOLYGON column typmod."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid)
        resp = client.post(
            _url(calc.id, "edit-geometry"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[83.2, 27.2], [83.5, 27.2], [83.5, 27.5], [83.2, 27.2]]],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        wkt = _extent_wkt(db, extent.id)
        assert wkt.upper().startswith("MULTIPOLYGON"), (
            f"column stores {wkt[:40]!r}, not a MULTIPOLYGON"
        )

    def test_cut_persists_the_cut_shape_on_the_same_row(self, client, db):
        """A cut re-stores one row (no pieces), so the extent survives it."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid)
        resp = client.post(
            _url(calc.id, "cut-polygon"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}",
                "cut_line": {"type": "LineString", "coordinates": [[83.4, 27.0], [83.4, 28.0]]},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["pieces"]) >= 2
        # Single-row model: no new rows were created to delete on undo.
        assert not body["piece_ids"]
        rows = db.execute(text(
            "SELECT count(*) AS n FROM user_group_extents WHERE calculation_id = :c"
        ), {"c": calc.id}).first().n
        assert rows == 1

    def test_delete_guard_allows_removing_the_extent(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid)
        resp = client.get(
            _url(calc.id, "delete-guard"),
            headers=headers,
            params={"layer_type": "user_group", "feature_id": f"user_group#{extent.id}"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["blocked"] is False

    def test_snapshot_then_restore_round_trips_the_shape(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid)
        original = _extent_geojson(db, extent.id)

        snap = client.get(
            _url(calc.id, "feature"),
            headers=headers,
            params={"layer_type": "user_group", "feature_id": f"user_group#{extent.id}"},
        )
        assert snap.status_code == 200, snap.text
        snapshot = snap.json()["snapshot"]
        assert snapshot["geometry"]["type"] in ("Polygon", "MultiPolygon")

        # Reshape it away, then undo.
        client.post(
            _url(calc.id, "edit-geometry"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[83.2, 27.2], [83.3, 27.2], [83.3, 27.3], [83.2, 27.2]]],
                },
            },
        )
        restored = client.post(
            _url(calc.id, "restore-feature"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}",
                "snapshot": snapshot,
            },
        )
        assert restored.status_code == 200, restored.text
        db.expire_all()
        after = _extent_geojson(db, extent.id)
        assert after is not None, "restore dropped the extent"
        assert after.area == pytest.approx(original.area)


def _archipelago():
    """Three disjoint islands — the Japan case."""
    return MultiPolygon([
        box(83.10, 27.10, 83.20, 27.20),
        box(83.30, 27.30, 83.40, 27.40),
        box(83.50, 27.50, 83.60, 27.60),
    ])


def _part_bounds(geom):
    return sorted(tuple(round(v, 6) for v in g.bounds) for g in geom.geoms)


class TestUserGroupMultiIslandEditing:
    """A multi-island extent is edited island by island, like a boundary.

    The extent is one stored row holding a MultiPolygon, so every write has to
    replace exactly ONE island and leave its neighbours byte-identical — the
    failure mode being guarded here is an edit that silently drops the other
    islands (or replaces the whole extent with the one edited piece).
    """

    def test_part_addressing_resolves_one_island_only(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _archipelago())

        resp = client.get(
            _url(calc.id, "feature"),
            headers=headers,
            params={"layer_type": "user_group", "feature_id": f"user_group#{extent.id}"},
        )
        assert resp.status_code == 200, resp.text
        # The snapshot is the WHOLE extent (undo restores the whole row)...
        assert shape(resp.json()["snapshot"]["geometry"]).geom_type == "MultiPolygon"

        # ...while a resolve of a part id is that island alone.
        from app.api.editing import _resolve_feature

        part = _resolve_feature(db, calc, "user_group", f"user_group#{extent.id}#1")
        assert part["geometry"]["type"] == "Polygon"
        assert part["part_index"] == 1
        assert part["part_count"] == 3
        assert part["id"] == f"user_group#{extent.id}#1"

    def test_vertex_edit_of_one_island_keeps_the_others(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _archipelago())
        before = _part_bounds(_extent_geojson(db, extent.id))

        # Shrink island 0 only.
        resp = client.post(
            _url(calc.id, "edit-geometry"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}#0",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[83.10, 27.10], [83.15, 27.10], [83.15, 27.15], [83.10, 27.15], [83.10, 27.10]]],
                },
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The response answers for the island that was edited.
        assert body["feature"]["id"] == f"user_group#{extent.id}#0"

        db.expire_all()
        after_geom = _extent_geojson(db, extent.id)
        after = _part_bounds(after_geom)
        assert len(after) == 3, "an island was lost"
        # Islands 1 and 2 are untouched; only island 0 shrank.
        assert after[1] == before[1]
        assert after[2] == before[2]
        assert after[0] != before[0]
        assert after_geom.area < _archipelago().area

    def test_cut_of_one_island_keeps_the_others(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _archipelago())
        before = _part_bounds(_extent_geojson(db, extent.id))

        # Slice island 1 in half; islands 0 and 2 must not move.
        resp = client.post(
            _url(calc.id, "cut-polygon"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}#1",
                "cut_line": {"type": "LineString", "coordinates": [[83.35, 27.0], [83.35, 28.0]]},
            },
        )
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["pieces"]) >= 2

        db.expire_all()
        after = _part_bounds(_extent_geojson(db, extent.id))
        # island 0 (lowest lon) and island 2 (highest lon) are byte-identical.
        assert after[0] == before[0]
        assert after[-1] == before[-1]
        # The cut island became two, so the extent now holds four islands.
        assert len(after) == 4

    def test_out_of_range_part_is_a_404(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _archipelago())
        resp = client.post(
            _url(calc.id, "edit-geometry"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}#9",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[83.1, 27.1], [83.2, 27.1], [83.2, 27.2], [83.1, 27.1]]],
                },
            },
        )
        assert resp.status_code == 404, resp.text

    def test_whole_extent_id_still_replaces_everything(self, client, db):
        """No part suffix keeps meaning the whole extent (single-island clients)."""
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _archipelago())
        resp = client.post(
            _url(calc.id, "edit-geometry"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}",
                "geometry": {"type": "Polygon", "coordinates": [[[83.0, 27.0], [83.1, 27.0], [83.1, 27.1], [83.0, 27.0]]]},
            },
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        after = _extent_geojson(db, extent.id)
        assert len(after.geoms) == 1, "a whole-extent write should collapse to one island"

    def test_snapshot_restore_brings_back_every_island(self, client, db):
        headers, uid = _register(client)
        calc, extent = _calc_with_extent(db, uid, _archipelago())
        original = _part_bounds(_extent_geojson(db, extent.id))

        snap = client.get(
            _url(calc.id, "feature"),
            headers=headers,
            params={"layer_type": "user_group", "feature_id": f"user_group#{extent.id}#0"},
        ).json()["snapshot"]

        # Destroy two islands, then undo.
        for part in (0, 1):
            client.post(
                _url(calc.id, "edit-geometry"),
                headers=headers,
                json={
                    "layer_type": "user_group",
                    "feature_id": f"user_group#{extent.id}#{part}",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[83.0 + part, 27.0], [83.01 + part, 27.0], [83.01 + part, 27.01], [83.0 + part, 27.0]]],
                    },
                },
            )
        assert _part_bounds(_extent_geojson(db, extent.id)) != original

        restored = client.post(
            _url(calc.id, "restore-feature"),
            headers=headers,
            json={
                "layer_type": "user_group",
                "feature_id": f"user_group#{extent.id}#0",
                "snapshot": snap,
            },
        )
        assert restored.status_code == 200, restored.text
        db.expire_all()
        assert _part_bounds(_extent_geojson(db, extent.id)) == original

