"""P7d: the ROW is the feature - a cut makes a row, a merge deletes rows.

The owner's model (2026-09-28): *each feature (boundary) is one row; three
separated polygons are three attribute rows; all features can be cut, and a cut
makes its own row.* That last clause is this file.

Until P7d a user-group extent was ONE row holding a MultiPolygon, so a cut could
only store its pieces as extra PARTS of that row (`_splice_user_group_part`) and
the frontend re-split them. Now a cut deletes the source row and inserts one row
per piece, and a merge deletes N rows and inserts the union - the same shape the
block layer has used all along.

The legacy `user_group#<id>#<part>` addressing is still supported, because the
frontend does not move to row ids until P7e. Both paths are asserted here, so the
migration cannot silently break the client that is still out there.
"""

from __future__ import annotations

import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely import wkt as shp_wkt
from shapely.geometry import LineString, MultiPolygon, box, mapping, shape
from sqlalchemy import text

from app.models.user_group import UserGroupExtent

pytestmark = pytest.mark.usefixtures("forget_forests", "relax_user_group_limit")


def _register(client):
    email = f"ug-p7d-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG P7d",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc_with_polygons(db, user_id, geoms):
    from app.models.calculation import Calculation, CalculationStatus

    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name="UG P7d Forest",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    rows = []
    for g in geoms:
        ext = UserGroupExtent(
            calculation_id=calc.id, user_id=user_id,
            extent_geometry=from_shape(g, srid=4326), source_type="manual",
        )
        db.add(ext)
        rows.append(ext)
    db.commit()
    for r in rows:
        db.refresh(r)
    return calc, rows


def _stored(db, calc_id):
    """The rows and their geometries, read with RAW SQL.

    Deliberately not the ORM: these tests run against the same session the app
    uses, and an identity-mapped object can survive a row being deleted elsewhere,
    which would make the row count a test artefact rather than the truth. Raw SQL
    is what is actually in the table.
    """
    ids = [r[0] for r in db.execute(text(
        "SELECT id FROM user_group_extents WHERE calculation_id = :c "
        "ORDER BY created_at ASC, id ASC"
    ), {"c": calc_id}).fetchall()]
    out = []
    for i in ids:
        row = db.execute(text(
            "SELECT ST_AsGeoJSON(extent_geometry) AS g FROM user_group_extents WHERE id = :i"
        ), {"i": i}).first()
        out.append(shape(json.loads(row.g)))
    return out


def _adjacent_pair():
    """Two polygons sharing an edge at y=27.20 - so they really can merge."""
    return box(83.10, 27.10, 83.30, 27.20), box(83.10, 27.20, 83.30, 27.30)


def _separated_pair():
    return box(83.10, 27.10, 83.30, 27.20), box(83.50, 27.50, 83.70, 27.60)


def _cut_with_line(client, headers, calc_id, row_id, line):
    """Split one row with a real cut LINE, the way the toolbar does.

    `cut-polygon` computes the pieces itself, so a test that hands it pre-computed
    pieces would not exercise the path the user actually takes.
    """
    return client.post(
        f"/api/v1/calculations/{calc_id}/geometry/cut-polygon",
        headers=headers,
        json={
            "layer_type": "user_group",
            "feature_id": str(row_id),
            "cut_line": mapping(line),
        },
    )


def _split_box_horizontally(x0, y0, x1, y1, at):
    """A box, and a cut line that bisects it."""
    return box(x0, y0, x1, y1), LineString([(x0 - 0.05, at), (x1 + 0.05, at)])


class TestCutMakesItsOwnRow:
    def test_a_cut_replaces_one_row_with_one_row_per_piece(self, client, db):
        headers, uid = _register(client)
        whole, line = _split_box_horizontally(83.10, 27.10, 83.30, 27.30, 27.18)
        calc, rows = _calc_with_polygons(db, uid, [whole])
        assert len(rows) == 1

        resp = _cut_with_line(client, headers, calc.id, rows[0].id, line)
        assert resp.status_code == 200, resp.text

        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 2, (
            f"a cut must make its own row: expected 2 rows, got {len(parts)}"
        )
        # Two SEPARATE rows, each holding one polygon. If the halves were unioned
        # back together the cut would be silently undone, which is the defect this
        # whole model change exists to make impossible.
        assert all(len(_parts(p)) == 1 for p in parts), "one row must hold exactly one polygon"
        assert abs(sum(p.area for p in parts) - whole.area) < 1e-12
        assert len({round(p.area, 9) for p in parts}) == 2, "the halves must differ"

    def test_the_other_rows_are_untouched_by_a_cut(self, client, db):
        headers, uid = _register(client)
        whole, line = _split_box_horizontally(83.10, 27.10, 83.30, 27.30, 27.18)
        spare = box(83.50, 27.50, 83.70, 27.60)
        calc, rows = _calc_with_polygons(db, uid, [whole, spare])

        resp = _cut_with_line(client, headers, calc.id, rows[0].id, line)
        assert resp.status_code == 200, resp.text

        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 3, "the cut adds rows; it must not disturb the others"
        assert any(p.equals(_mp(spare)) for p in parts), "the spare row must survive"

    def test_the_union_still_covers_everything_after_a_cut(self, client, db):
        """The analysis reads the union, so a cut must not change the group's area."""
        from app.services.user_group_analysis import UserGroupAnalysisService

        headers, uid = _register(client)
        whole, line = _split_box_horizontally(83.10, 27.10, 83.30, 27.30, 27.18)
        calc, rows = _calc_with_polygons(db, uid, [whole])
        area_before = whole.area

        assert _cut_with_line(client, headers, calc.id, rows[0].id, line).status_code == 200
        db.expire_all()

        union = UserGroupAnalysisService(db).get_union_extent_geometry(str(calc.id))
        assert union is not None
        assert abs(union.area - area_before) < 1e-12, (
            "cutting a polygon in two must not change the group's total area"
        )
        # The two halves are ADJACENT, so the union is correctly ONE polygon again -
        # they are two rows, not two disjoint pieces. What matters is that the area
        # survives and the row count went up.
        assert _parts(union)[0].equals(whole), "the union must still be the whole polygon"

    def test_cutting_a_row_that_does_not_exist_is_a_404(self, client, db):
        headers, uid = _register(client)
        whole, line = _split_box_horizontally(83.10, 27.10, 83.30, 27.30, 27.18)
        calc, _rows = _calc_with_polygons(db, uid, [whole])
        # A numeric id that is simply not there: a missing row, not a malformed one.
        assert _cut_with_line(client, headers, calc.id, 999999, line).status_code == 404

    def test_a_non_numeric_row_id_is_a_400_not_a_500(self, client, db):
        """`UserGroupExtent.id` is an Integer, so a UUID id is a bad request.

        Worth pinning: the coercion used to raise ValueError, which surfaced as an
        internal 500 for a plainly malformed request.
        """
        headers, uid = _register(client)
        whole, line = _split_box_horizontally(83.10, 27.10, 83.30, 27.30, 27.18)
        calc, _rows = _calc_with_polygons(db, uid, [whole])
        resp = _cut_with_line(client, headers, calc.id, uuid.uuid4(), line)
        assert resp.status_code == 400, resp.text


class TestMergeIsTheInverse:
    def test_merging_two_rows_gives_one_row(self, client, db):
        headers, uid = _register(client)
        lower, upper = _adjacent_pair()
        calc, rows = _calc_with_polygons(db, uid, [lower, upper])
        assert len(rows) == 2

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [str(r.id) for r in rows]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["merged"] == 1

        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 1, "two rows merged into one"
        survivor = db.query(UserGroupExtent).filter(
            UserGroupExtent.calculation_id == calc.id).one()
        assert body["merged_id"] == str(survivor.id)
        assert _parts(parts[0])[0].equals(lower.union(upper))

    def test_cut_then_merge_restores_the_original_row(self, client, db):
        """The round trip, at row granularity this time."""
        headers, uid = _register(client)
        whole, line = _split_box_horizontally(83.10, 27.10, 83.30, 27.30, 27.18)
        calc, rows = _calc_with_polygons(db, uid, [whole])

        assert _cut_with_line(client, headers, calc.id, rows[0].id, line).status_code == 200
        db.expire_all()
        assert len(_stored(db, calc.id)) == 2

        halves = db.query(UserGroupExtent).filter(
            UserGroupExtent.calculation_id == calc.id
        ).order_by(UserGroupExtent.created_at.asc()).all()
        merged = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [str(r.id) for r in halves]},
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["merged"] == 1

        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 1
        assert _parts(parts[0])[0].equals(whole), "the round trip must restore the polygon"

    def test_merging_separated_rows_writes_nothing(self, client, db):
        """Disjoint polygons union to the same shape, so nothing is written."""
        headers, uid = _register(client)
        a, b = _separated_pair()
        calc, rows = _calc_with_polygons(db, uid, [a, b])
        before = calc.geometry_version

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [str(r.id) for r in rows]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["merged"] == 0
        assert "do not touch" in resp.json()["warning"]

        db.expire_all()
        assert len(_stored(db, calc.id)) == 2, "both rows must survive"
        assert calc.geometry_version == before, "a no-op must not churn the clock"

    def test_merge_merges_a_subset_and_leaves_the_rest(self, client, db):
        headers, uid = _register(client)
        lower, upper = _adjacent_pair()
        spare = box(83.50, 27.50, 83.70, 27.60)
        calc, rows = _calc_with_polygons(db, uid, [lower, upper, spare])

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [str(rows[0].id), str(rows[1].id)]},
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 2, "the two halves became one; the spare is untouched"
        assert any(p.equals(_mp(spare)) for p in parts)

    def test_merge_rejects_a_row_from_another_calculation(self, client, db):
        headers, uid = _register(client)
        a, b = _adjacent_pair()
        calc, rows = _calc_with_polygons(db, uid, [a, b])
        _other_calc, other_rows = _calc_with_polygons(db, uid, [a, b])

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [str(rows[0].id), str(other_rows[0].id)]},
        )
        assert resp.status_code == 404, resp.text

    def test_merge_is_audited_and_bumps_the_geometry_clock(self, client, db):
        from sqlalchemy import text as sql_text

        headers, uid = _register(client)
        lower, upper = _adjacent_pair()
        calc, rows = _calc_with_polygons(db, uid, [lower, upper])
        before = calc.geometry_version

        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [str(r.id) for r in rows]},
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        assert calc.geometry_version > before, "the client relies on this to refetch"
        audit = db.execute(sql_text(
            "SELECT operation FROM geometry_audits "
            "WHERE calculation_id = :c AND layer_type = 'user_group' "
            "ORDER BY id DESC LIMIT 1"
        ), {"c": calc.id}).scalar()
        assert audit == "MERGE", f"expected a MERGE audit row, got {audit!r}"


class TestLegacyPartAddressingStillWorks:
    """The frontend is still on part ids until P7e, so that path must survive."""

    def test_a_vertex_edit_on_a_part_id_still_splices(self, client, db):
        headers, uid = _register(client)
        stored_mp = MultiPolygon([box(83.10, 27.10, 83.20, 27.20),
                                 box(83.50, 27.50, 83.60, 27.60)])
        calc, rows = _calc_with_polygons(db, uid, [stored_mp])

        moved = box(83.11, 27.11, 83.21, 27.21)
        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/edit-geometry",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_id": f"user_group#{rows[0].id}#0",
                  "geometry": mapping(moved)},
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 1, "the legacy path edits inside the row"
        assert moved.equals(_parts(parts[0])[0])
        assert _parts(parts[0])[1].equals(stored_mp.geoms[1]), "island 1 untouched"

    def test_a_vertex_edit_on_a_row_id_replaces_that_row(self, client, db):
        headers, uid = _register(client)
        a, b = _separated_pair()
        calc, rows = _calc_with_polygons(db, uid, [a, b])

        moved = box(83.15, 27.15, 83.25, 27.25)
        resp = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/edit-geometry",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_id": str(rows[0].id),
                  "geometry": mapping(moved)},
        )
        assert resp.status_code == 200, resp.text
        db.expire_all()
        parts = _stored(db, calc.id)
        assert len(parts) == 2, "a row edit must not merge or drop the other row"
        assert _parts(parts[0])[0].equals(moved)
        assert _parts(parts[1])[0].equals(b)


def _parts(geom):
    """A row's geometry, whatever PostGIS hands back.

    A one-part MULTIPOLYGON comes back from `ST_AsGeoJSON` as a bare Polygon,
    so the reader must not assume `.geoms` exists.
    """
    return list(getattr(geom, "geoms", [geom]))


def _mp(geom):
    return MultiPolygon([geom])
