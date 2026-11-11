"""P7b: the user-group reads must be over the UNION, never "the latest row".

Why this file exists
--------------------
A calculation can hold SEVERAL user-group polygons, one row each (P7a). The reads
that predate that decision all shared one idiom:

    db.query(UserGroupExtent).filter(calculation_id == ...).order_by(
        UserGroupExtent.created_at.desc()).first()

With a single row that is harmless. With N rows it is not a shortcut, it is a
silently ARBITRARY pick - a wrong answer rather than an error, which is why the
test below is a source-level gate as well as a behavioural one.

The owner's decision (2026-09-28): rows are a storage and display concern, so the
ANALYSIS stays one computation over the UNION of the polygons.

Two layers of check:

1. :class:`TestNoLatestWinsReadsRemain` greps the source, so a re-introduced
   `.first()` fails even in a branch the behavioural tests do not reach.
2. The behavioural tests actually create several rows and assert the union is
   used - these are what would have caught the original bug at runtime.

Readers that take an explicit ``extent_id`` (``..._for_extent`` and friends) are
deliberately untouched: they were always about ONE row, and still are.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import pytest
from geoalchemy2.shape import from_shape
from shapely import wkt as shp_wkt
from shapely.geometry import MultiPolygon, box, shape
from sqlalchemy import text

import pytest as _pytest_for_limit

pytestmark = _pytest_for_limit.mark.usefixtures("relax_user_group_limit")

SERVICE = (
    Path(__file__).resolve().parents[2]
    / "app" / "services" / "user_group_analysis.py"
)


def _three_islands():
    return MultiPolygon([
        box(83.10, 27.10, 83.20, 27.20),
        box(83.30, 27.30, 83.40, 27.40),
        box(83.50, 27.50, 83.60, 27.60),
    ])


def _register(client):
    email = f"ug-p7b-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/register", json={
        "email": email, "password": "TestPass123!", "full_name": "UG P7b",
    })
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    return headers, me.json()["id"]


def _calc_with_several_extents(db, user_id):
    """One calculation holding THREE separate rows - the P7a end state."""
    from app.models.calculation import Calculation, CalculationStatus
    from app.models.user_group import UserGroupExtent

    calc = Calculation(
        id=uuid.uuid4(), user_id=user_id, forest_name="UG P7b Forest",
        boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
        status=CalculationStatus.PROCESSING, is_draft=True,
    )
    db.add(calc)
    db.commit()
    db.refresh(calc)

    rows = []
    for i, poly in enumerate(_three_islands().geoms):
        ext = UserGroupExtent(
            calculation_id=calc.id, user_id=user_id,
            extent_geometry=from_shape(poly, srid=4326), source_type="manual",
        )
        db.add(ext)
        rows.append(ext)
    db.commit()
    for r in rows:
        db.refresh(r)
    return calc, rows


@pytest.fixture
def service(db):
    from app.services.user_group_analysis import UserGroupAnalysisService

    return UserGroupAnalysisService(db)


class TestNoLatestWinsReadsRemain:
    """The source-level gate: a re-introduced pick-one would slip past behaviour."""

    def test_the_latest_wins_idiom_is_gone(self):
        src = SERVICE.read_text(encoding="utf-8")
        offenders = [
            m.start() for m in re.finditer(
                r"order_by\(UserGroupExtent\.created_at\.desc\(\)\)\.first\(\)", src
            )
        ]
        assert not offenders, (
            f"{len(offenders)} latest-wins read(s) remain in {SERVICE.name}. With "
            "several extents each one silently analyses an arbitrary polygon. Use "
            "get_extents() and union it, or read the row by explicit id."
        )

    def test_extents_are_read_through_the_shared_helpers(self):
        src = SERVICE.read_text(encoding="utf-8")
        for helper in ("get_extents(", "get_union_extent_geometry("):
            assert helper in src, f"{helper} is not used anywhere in the service"


class TestTheUnionIsUsed:
    def test_get_extents_returns_every_row_in_a_stable_order(self, client, db, service):
        _headers, uid = _register(client)
        calc, rows = _calc_with_several_extents(db, uid)

        got = service.get_extents(str(calc.id))
        assert len(got) == 3, "every polygon must come back, not just one"
        assert [r.id for r in got] == [r.id for r in rows], "stable order"
        # And stable across a second call, which the old DESC-first read was not.
        assert [r.id for r in service.get_extents(str(calc.id))] == [r.id for r in rows]

    def test_get_union_extent_geometry_covers_all_three(self, client, db, service):
        _headers, uid = _register(client)
        calc, _rows = _calc_with_several_extents(db, uid)

        union = service.get_union_extent_geometry(str(calc.id))
        assert union is not None
        assert len(union.geoms) == 3, "the union of three islands is three parts"
        # The union's area equals the sum of the rows - nothing dropped.
        total = sum(g.area for g in _three_islands().geoms)
        assert abs(union.area - total) < 1e-12

    def test_get_extent_geojson_is_the_union_and_reports_the_count(self, client, db, service):
        _headers, uid = _register(client)
        calc, rows = _calc_with_several_extents(db, uid)

        info = service.get_extent_geojson(str(calc.id))
        assert info is not None
        assert info["polygon_count"] == 3
        assert set(info["extent_ids"]) == {str(r.id) for r in rows}
        geom = shape(json.loads(json.dumps(info["geometry"])))
        assert len(geom.geoms) == 3
        # The area is the union's, so overlapping polygons would not double count.
        # Compared against PostGIS's own per-row total, so the check is like-for-like.
        per_row_total = db.execute(text(
            "SELECT SUM(ST_Area(geography(extent_geometry))) / 10000.0 "
            "FROM user_group_extents WHERE calculation_id = :c"
        ), {"c": calc.id}).scalar()
        assert abs(info["area_hectares"] - round(float(per_row_total), 4)) < 0.01

    def test_get_extent_features_is_one_feature_per_row(self, client, db, service):
        """The attribute-table view: three separated polygons, three features."""
        _headers, uid = _register(client)
        calc, rows = _calc_with_several_extents(db, uid)

        feats = service.get_extent_features(str(calc.id))
        assert len(feats) == 3
        # Plain row ids, not synthetic part references - that is what retires P6.
        assert [f["id"] for f in feats] == [str(r.id) for r in rows]
        for f in feats:
            assert f["geometry"] is not None
            assert f["area_hectares"] and f["area_hectares"] > 0
        # Each row is ONE polygon, so no MultiPolygon is handed to the table.
        assert all(shape(f["geometry"]).geom_type == "Polygon" for f in feats)

    def test_no_extents_gives_none_rather_than_an_error(self, client, db, service):
        from app.models.calculation import Calculation, CalculationStatus

        _headers, uid = _register(client)
        calc = Calculation(
            id=uuid.uuid4(), user_id=uid, forest_name="UG Empty",
            boundary_geom=shp_wkt.dumps(box(83.0, 27.0, 84.0, 28.0)),
            status=CalculationStatus.PROCESSING, is_draft=True,
        )
        db.add(calc)
        db.commit()
        assert service.get_extents(str(calc.id)) == []
        assert service.get_union_extent_geometry(str(calc.id)) is None
        assert service.get_extent_geojson(str(calc.id)) is None
        assert service.get_extent_features(str(calc.id)) == []
