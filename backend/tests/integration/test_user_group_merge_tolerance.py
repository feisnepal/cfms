"""A user-group merge must re-join the pieces a real cut produced.

The tracked gap this closes: `_merge_user_group_rows` used a plain `unary_union`,
which demands the selected polygons touch EXACTLY. `_merge_blocks` does not - it
applies a *guarded* point-touch glue, because a cut does not always leave
bit-identical shared edges. So two polygons a user plainly sees as joined could
come back "do not touch, so nothing was merged", and the user had no way to fix it.

The guard is the important half. The glue only applies when
`_touch_graph_connected` proves the pieces are within about a centimetre, so two
genuinely separate polygons still refuse to merge. Both halves are tested: a cut's
own output re-joins, and a far-apart pair does not.

`test_journey_...` in test_user_group_journey.py still xfails on the real cut
endpoint's output; if that stops happening the strict xfail will fail, which is
what we want.
"""

from __future__ import annotations

import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely import wkt as shp_wkt
from shapely.geometry import box, shape
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.user_group import UserGroupExtent

pytestmark = pytest.mark.usefixtures("forget_forests", "relax_user_group_limit")


def _register(client):
    email = f"ug-tol-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG Tolerance",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc(db, user_id):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name="UG Tolerance",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)
    return calc


def _rows(db, calc, geoms):
    rows = []
    for g in geoms:
        e = UserGroupExtent(
            calculation_id=calc.id, user_id=calc.user_id,
            extent_geometry=from_shape(g, srid=4326), source_type="manual",
        )
        db.add(e)
        rows.append(e)
    db.commit()
    for r in rows:
        db.refresh(r)
    return rows


def _count(db, calc_id):
    return db.execute(text(
        "SELECT COUNT(*) FROM user_group_extents WHERE calculation_id = :c"
    ), {"c": calc_id}).scalar()


def _merge(client, headers, calc, rows):
    return client.post(
        f"/api/v1/calculations/{calc.id}/geometry/merge-features",
        headers=headers,
        json={"layer_type": "user_group",
              "feature_ids": [str(r.id) for r in rows]},
    )


class TestAPiecesOwnOutputCanBeReJoined:
    def test_a_cut_result_merges_back(self, client, db):
        headers, uid = _register(client)
        calc = _calc(db, uid)
        whole = _cut_setup()
        rows = _rows(db, calc, [whole])

        cut = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/cut-polygon",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_id": str(rows[0].id),
                  "cut_line": {"type": "LineString",
                               "coordinates": [[83.05, 27.18], [83.35, 27.18]]}},
        )
        assert cut.status_code == 200, cut.text
        assert _count(db, calc.id) == 2

        halves = db.execute(text(
            "SELECT id FROM user_group_extents WHERE calculation_id = :c ORDER BY id"
        ), {"c": calc.id}).fetchall()

        merged = client.post(
            f"/api/v1/calculations/{calc.id}/geometry/merge-features",
            headers=headers,
            json={"layer_type": "user_group",
                  "feature_ids": [h[0] for h in halves]},
        )
        assert merged.status_code == 200, merged.text
        assert merged.json()["merged"] == 1, (
            "the two halves a cut just produced must be re-joinable; this is the "
            "gap the point-touch glue closes"
        )
        assert _count(db, calc.id) == 1

    def test_a_hairline_gap_still_merges(self, client, db):
        """Sub-degree noise from the cut must not read as 'not touching'."""
        headers, uid = _register(client)
        calc = _calc(db, uid)
        # Sub-millimetre noise, not an exact shared edge. A METRE gap is
        # correctly refused - the glue is 1 m, and the guard is what stops two
        # distant polygons being welded together (see the test below).
        gap = 0.0005 / 111_320.0  # half a millimetre, in degrees
        rows = _rows(db, calc, [
            box(83.10, 27.10, 83.30, 27.20),
            box(83.10, 27.20 + gap, 83.30, 27.30),
        ])
        resp = _merge(client, headers, calc, rows)
        assert resp.status_code == 200, resp.text
        assert resp.json()["merged"] == 1, (
            "a near-touching pair should merge, the same as blocks"
        )


class TestTheGlueIsGuarded:
    def test_genuinely_separate_polygons_still_refuse(self, client, db):
        """The safety half: the glue must not weld unrelated ground together."""
        headers, uid = _register(client)
        calc = _calc(db, uid)
        rows = _rows(db, calc, [
            box(83.10, 27.10, 83.30, 27.30),
            box(83.50, 27.50, 83.70, 27.70),
        ])
        before = _count(db, calc.id)
        resp = _merge(client, headers, calc, rows)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["merged"] == 0, "distant polygons must not be glued"
        assert "do not touch" in body["warning"]
        assert _count(db, calc.id) == before, "and nothing may be written"

    def test_touching_polygons_merge_without_a_cut(self, client, db):
        headers, uid = _register(client)
        calc = _calc(db, uid)
        rows = _rows(db, calc, [
            box(83.10, 27.10, 83.30, 27.20),
            box(83.10, 27.20, 83.30, 27.30),
        ])
        resp = _merge(client, headers, calc, rows)
        assert resp.json()["merged"] == 1
        assert _count(db, calc.id) == 1


def _cut_setup():
    return box(83.10, 27.10, 83.30, 27.30)
