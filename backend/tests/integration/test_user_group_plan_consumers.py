"""P7f, proven: a management plan must see the WHOLE user group.

This is the silent-wrongness test. Under the old single-row model
``_get_usergroup_extent`` took ``.first()`` and drew ONE polygon, and
``_get_usergroup_settlements`` filtered buildings on that same single
``extent_id``. Both looked fine on a group made of one polygon, which is exactly
why the defect survived review - and why a DOCX operational plan would have
quietly omitted settlements while still reading as though the whole group were
covered.

It also pins a bug this test was written to catch: an intermediate version of the
P7f fix left the old query block in place underneath the new one, referencing an
``extent`` variable that no longer existed. It parsed, and every docx test still
passed, because nothing generated settlements. The last test here calls the
function directly so that "nothing calls it" can never be a reason for it to rot.
"""

from __future__ import annotations

import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely import wkt as shp_wkt
from shapely.geometry import box, mapping
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from app.models.user_group import UserGroupBuilding, UserGroupExtent

pytestmark = pytest.mark.usefixtures("forget_forests", "relax_user_group_limit")


def _register(client):
    email = f"ug-p7f-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG P7f",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc_with_two_polygons(db, user_id):
    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name="UG P7f",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)

    # Two separated polygons: one user group, two rows, two features.
    rows = []
    for g in (box(83.10, 27.10, 83.30, 27.30), box(83.50, 27.50, 83.70, 27.70)):
        e = UserGroupExtent(
            calculation_id=calc.id, user_id=user_id,
            extent_geometry=from_shape(g, srid=4326), source_type="manual",
        )
        db.add(e)
        rows.append(e)
    db.commit()
    for r in rows:
        db.refresh(r)
    return calc, rows


def _settlement(db, extent_id, name, point):
    db.add(UserGroupBuilding(
        extent_id=extent_id,
        settlement_name=name,
        building_count=5,
        # A list of {lat, lon} points - the shape the consumer actually reads
        # (`geo[0].get("lat")`), not a GeoJSON geometry object.
        buildings_geojson=[{"lat": point[1], "lon": point[0]}] * 3,
    ))
    db.commit()


class TestTheMapDrawsTheWholeGroup:
    def test_the_drawn_extent_is_the_union_not_one_polygon(self, client, db):
        from app.services.management_plan_docx.plan_map_service import (
            _get_usergroup_extent,
        )

        _h, uid = _register(client)
        calc, rows = _calc_with_two_polygons(db, uid)

        geom = _get_usergroup_extent(db, calc.id)
        assert geom is not None
        # The old `.first()` returned ONE polygon. The DOCX would then have shown a
        # map of half the group while the text claimed the whole group.
        assert len(geom.geoms) == 2, (
            "the plan map must draw BOTH polygons of the group, not the first one"
        )
        total = sum(g.area for g in geom.geoms)
        expected = rows[0].extent_geometry is not None
        assert expected
        assert abs(total - (0.20 * 0.20 + 0.20 * 0.20)) < 1e-9

    def test_a_single_polygon_group_still_works(self, client, db):
        """The union must not change the one-polygon case that everything relied on."""
        from app.services.management_plan_docx.plan_map_service import (
            _get_usergroup_extent,
        )

        _h, uid = _register(client)
        calc = Calculation(
            id=uuid.uuid4(), user_id=uid, forest_name="one",
            boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
            status=CalculationStatus.PROCESSING, is_draft=True,
        )
        db.add(calc)
        db.commit()
        db.refresh(calc)
        db.add(UserGroupExtent(
            calculation_id=calc.id, user_id=uid,
            extent_geometry=from_shape(box(83.1, 27.1, 83.3, 27.3), srid=4326),
            source_type="manual",
        ))
        db.commit()

        geom = _get_usergroup_extent(db, calc.id)
        assert geom is not None
        # The column is MULTIPOLYGON, so one polygon reads back as a 1-part
        # MultiPolygon - exactly what the pre-P7f code returned, so the single-row
        # case is unchanged rather than newly reshaped.
        assert len(geom.geoms) == 1, "one polygon must stay one part"


class TestSettlementsAreNeverDropped:
    def test_settlements_from_every_polygon_are_listed(self, client, db):
        """The silent-omission failure: a plan that looks complete but isn't."""
        from app.services.management_plan_docx.plan_map_service import (
            _get_usergroup_settlements,
        )

        _h, uid = _register(client)
        calc, rows = _calc_with_two_polygons(db, uid)
        # One settlement inside EACH polygon. The second is the one the old
        # `extent_id == extent.id` filter threw away.
        _settlement(db, rows[0].id, "North", (83.2, 27.2))
        _settlement(db, rows[1].id, "South", (83.6, 27.6))

        out = _get_usergroup_settlements(db, calc.id)
        names = sorted(s.get("name") for s in out)
        assert names == ["North", "South"], (
            f"a settlement was dropped from the plan: got {names}"
        )

    def test_the_function_is_reachable_and_does_not_raise(self, client, db):
        """Guards the P7f regression where a stale `extent` reference survived.

        An intermediate fix left the old query under the new one, referencing a
        variable that no longer existed. It parsed, and every docx test still
        passed, because nothing here called the function. Calling it directly is
        the only thing that makes "nobody calls it" an insufficient excuse.
        """
        from app.services.management_plan_docx.plan_map_service import (
            _get_usergroup_settlements,
        )

        _h, uid = _register(client)
        calc, rows = _calc_with_two_polygons(db, uid)
        _settlement(db, rows[0].id, "Only", (83.2, 27.2))

        # Must not raise NameError - that was the regression.
        assert _get_usergroup_settlements(db, calc.id) is not None

    def test_a_group_with_no_settlements_is_empty_not_an_error(self, client, db):
        from app.services.management_plan_docx.plan_map_service import (
            _get_usergroup_settlements,
        )

        _h, uid = _register(client)
        calc, _rows = _calc_with_two_polygons(db, uid)
        assert _get_usergroup_settlements(db, calc.id) == []
