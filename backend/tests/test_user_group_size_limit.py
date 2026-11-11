"""Owner decision D2 (2026-10-12): a user group over the analysis limit is refused on EVERY path that writes it, and nothing is saved."""
from __future__ import annotations

import uuid

import pytest
from shapely import wkt as shp_wkt
from shapely.geometry import box
from sqlalchemy import text

from app.models.calculation import Calculation, CalculationStatus
from tests import upload_fixtures as fx
from tests.integration.test_user_group_journey import _draw, _register, _row_count

pytestmark = pytest.mark.usefixtures("forget_forests")

SMALL = [[85.55, 27.40], [85.57, 27.40], [85.57, 27.42], [85.55, 27.42]]  # about 490 ha
HUGE = [[85.5, 27.3], [85.8, 27.3], [85.8, 27.6], [85.5, 27.6]]  # about 98,000 ha


@pytest.fixture()
def forest(client, db):
    headers, uid = _register(client)
    c = Calculation(id=uuid.uuid4(), user_id=uid, forest_name="UG limit", boundary_geom=shp_wkt.dumps(box(85.5, 27.35, 85.65, 27.45)),
                    status=CalculationStatus.PROCESSING, is_draft=True)
    db.add(c)
    db.commit()
    return headers, c


def _area(db, cid) -> float:
    db.rollback()  # the test shares its session with the app: after a refused write the failed transaction must be closed (production closes it per request)
    db.expire_all()
    return float(db.execute(text("SELECT COALESCE(SUM(ST_Area(extent_geometry::geography))/10000, 0) FROM user_group_extents WHERE calculation_id=:c"), {"c": cid}).scalar())


def _manual(client, headers, cid, ring):
    return client.post(f"/api/calculations/{cid}/user-group/manual", headers=headers, json={"geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]}})


def test_drawing_an_oversized_group_is_refused_and_nothing_is_saved(client, db, forest):
    headers, c = forest
    r = _manual(client, headers, c.id, HUGE)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "user_group.too_large"
    assert _row_count(db, c.id) == 0


def test_drawing_a_second_polygon_that_pushes_the_total_over_the_limit_is_refused(client, db, forest):
    """Drawing APPENDS, so the limit applies to the union with what is already there."""
    headers, c = forest
    _draw(client, headers, c.id, SMALL)
    r = _manual(client, headers, c.id, [[85.58, 27.40], [85.78, 27.40], [85.78, 27.60], [85.58, 27.60]])
    assert r.status_code == 400 and r.json()["detail"]["code"] == "user_group.too_large"
    assert _row_count(db, c.id) == 1


def test_a_group_just_under_the_limit_is_accepted(client, db, forest):
    headers, c = forest
    r = _manual(client, headers, c.id, [[85.55, 27.40], [85.55 + 0.20, 27.40], [85.55 + 0.20, 27.40 + 0.2], [85.55, 27.40 + 0.2]])
    assert r.status_code == 400  # 0.2 deg x 0.2 deg is about 43,000 ha: over
    r = _manual(client, headers, c.id, [[85.55, 27.40], [85.55 + 0.05, 27.40], [85.55 + 0.05, 27.40 + 0.05], [85.55, 27.40 + 0.05]])
    assert r.status_code == 200 and 2000 < _area(db, c.id) < 5000  # about 3,000 ha


def test_auto_buffer_over_the_limit_is_refused_and_the_old_group_kept(client, db, forest):
    headers, c = forest
    _draw(client, headers, c.id, SMALL)
    before = _area(db, c.id)
    r = client.post(f"/api/calculations/{c.id}/user-group/auto-buffer", headers=headers, params={"buffer_distance": 5000})
    # the forest is ~170 km2 (17,000 ha) so even a 5 km ring is far over the limit
    assert r.status_code == 400 and r.json()["detail"]["code"] == "user_group.too_large"
    assert abs(_area(db, c.id) - before) < 1


def test_editing_a_vertex_so_the_group_grows_past_the_limit_is_refused_by_the_commit_backstop(client, db, forest):
    """The edit endpoint writes the geometry directly; the commit-time backstop is what stops it, with the same coded message."""
    headers, c = forest
    d = _draw(client, headers, c.id, SMALL)
    small = _area(db, c.id)
    r = client.post(
        f"/api/calculations/{c.id}/geometry/edit-geometry", headers=headers,
        json={"layer_type": "user_group", "feature_id": f"user_group#{d['extent_id']}", "geometry": {"type": "Polygon", "coordinates": [HUGE + [HUGE[0]]]}},
    )
    assert r.status_code == 400 and r.json()["detail"]["code"] == "user_group.too_large"
    db.rollback()  # shared test session: close the refused transaction before touching ORM objects again
    assert abs(_area(db, c.id) - small) < 1  # the old shape is still stored


def test_an_already_oversized_group_can_still_be_edited_downward(db, forest):
    """A group saved before the rule exists may be shrunk: only a change that GROWS it past the limit is refused."""
    from geoalchemy2.shape import from_shape
    from shapely.geometry import MultiPolygon
    from app.models.user_group import UserGroupExtent

    headers, c = forest
    # saved before the rule existed: written with a raw statement, which does not go through the ORM events
    db.execute(text("INSERT INTO user_group_extents (calculation_id, user_id, extent_geometry, source_type) "
                    "VALUES (:c, :u, ST_Multi(ST_MakeEnvelope(85.5,27.3,85.8,27.6,4326)), 'manual')"), {"c": str(c.id), "u": str(c.user_id)})
    db.commit()
    assert _area(db, c.id) > 50_000
    r = db.query(UserGroupExtent).filter(UserGroupExtent.calculation_id == c.id).first()
    r.extent_geometry = from_shape(MultiPolygon([box(85.5, 27.3, 85.7, 27.5)]), srid=4326)  # smaller, still over the limit
    db.commit()  # must NOT raise
    assert 5000 < _area(db, c.id) < 60_000


def test_the_message_is_bilingual_and_says_what_to_do(client, forest):
    headers, c = forest
    d = _manual(client, headers, c.id, HUGE).json()["detail"]
    assert "Draw or upload a smaller boundary" in d["message"]
    assert "सानो सीमा" in d["message_np"]
