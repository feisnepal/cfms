"""The workspace's "Activity Features" layer: drawn features must be listed per calculation.

`activity_drawn_features.calculation_id` was added nullable (migration 038) and no writer ever
filled it, so `GET /calculations/{id}/drawn-features` - which filtered on it - was always empty,
and would have crashed on serialisation had it matched. Also covers collision-check and
intersecting, which shared the empty filter (and `intersecting` imported a module that does not
exist and had no owner check).
"""

from __future__ import annotations

import json
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import box
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.user import User
from app.services.optimistic_lock import check_and_bump
from app.models.yearly_activities import (
    ActivityDrawnFeature,
    PotentialActivity,
    ProposedYearlyActivity,
)

BASE = "/api/yearly-activities"


def _login(client, db):
    email = f"drawn-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/auth/register",
        json={"email": email, "password": "TestPass123!", "full_name": "Drawn"},
    )
    resp = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    return headers, db.query(User).filter(User.email == email).first()


def _calc_with_activity(db, user, name="Drawn CF", map_kind=None):
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name=name)
    db.add(calc)
    db.flush()
    pa = PotentialActivity(progarms="Program", activities="Plantation", display_order=0, map_kind=map_kind)
    db.add(pa)
    db.flush()
    act = ProposedYearlyActivity(
        calculation_id=calc.id,
        potential_activity_id=pa.id,
        default_quantity=1,
        default_yearly_budget=1000,
    )
    db.add(act)
    db.commit()
    return calc, act


def _draw_point(client, headers, act, lon=85.05, lat=27.44, name="Planting spot"):
    resp = client.post(
        f"{BASE}/proposed-activities/{act.id}/drawn-features",
        headers=headers,
        json={
            "feature_type": "point",
            "geometry": json.dumps({"type": "Point", "coordinates": [lon, lat]}),
            "properties": {"name": name, "years": [1]},
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_drawn_feature_knows_its_calculation_and_is_stored_as_wgs84(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)

    created = _draw_point(client, headers, act)

    db.expire_all()
    row = db.query(ActivityDrawnFeature).filter_by(id=created["id"]).one()
    assert row.calculation_id == calc.id  # was left NULL by every writer
    assert db.execute(
        text("SELECT ST_SRID(geometry) FROM activity_drawn_features WHERE id = :i"), {"i": created["id"]}
    ).scalar() == 4326  # was 0, which made every ST_Intersects against a block error


def test_the_layer_endpoint_lists_the_forests_features_with_geojson_geometry(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)
    _draw_point(client, headers, act, lon=85.05, lat=27.44, name="A")
    _draw_point(client, headers, act, lon=85.06, lat=27.45, name="B")

    resp = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {f["properties"]["name"] for f in body} == {"A", "B"}
    for f in body:
        geom = json.loads(f["geometry"])  # the API contract: geometry is a GeoJSON string
        assert geom["type"] == "Point"
    first = next(f for f in body if f["properties"]["name"] == "A")
    assert json.loads(first["geometry"])["coordinates"] == [85.05, 27.44]


def test_only_this_forests_live_features_are_listed(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user, "Mine")
    other_calc, other_act = _calc_with_activity(db, user, "Another forest")
    keep = _draw_point(client, headers, act, name="keep")
    gone = _draw_point(client, headers, act, name="deleted")
    _draw_point(client, headers, other_act, name="elsewhere")
    db.execute(
        text("UPDATE activity_drawn_features SET deleted_at = now() WHERE id = :i"), {"i": gone["id"]}
    )
    db.commit()

    body = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers).json()

    assert [f["id"] for f in body] == [keep["id"]]


def test_every_place_carries_its_plan_lines_quantity_and_how_many_places_share_it(client, db):
    """The quantity belongs to the plan line, so two places of one activity share it (plan section 5.2)."""
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)
    check_and_bump(db, "yearly_plan", act.id, None)  # a plan line is edited through its version, like the API does
    act.default_quantity = 4
    db.query(PotentialActivity).filter_by(id=act.potential_activity_id).update({"unit": "ha"})
    other_pa = PotentialActivity(progarms="Program", activities="Fire line", display_order=1, unit="km")
    db.add(other_pa)
    db.flush()
    other = ProposedYearlyActivity(
        calculation_id=calc.id, potential_activity_id=other_pa.id, default_quantity=2, default_yearly_budget=1000
    )
    db.add(other)
    db.commit()
    _draw_point(client, headers, act, name="one")
    _draw_point(client, headers, act, name="two", lon=85.06)
    gone = _draw_point(client, headers, act, name="deleted", lon=85.07)
    _draw_point(client, headers, other, name="alone")
    db.execute(text("UPDATE activity_drawn_features SET deleted_at = now() WHERE id = :i"), {"i": gone["id"]})
    db.commit()

    body = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers).json()

    by_name = {f["properties"]["name"]: f for f in body}
    assert set(by_name) == {"one", "two", "alone"}
    for name in ("one", "two"):  # a deleted place is not counted
        assert by_name[name]["shared_count"] == 2
        assert by_name[name]["plan_quantity"] == 4
        assert by_name[name]["plan_unit"] == "ha"
        assert by_name[name]["proposed_activity_id"] == str(act.id)
    assert by_name["alone"]["shared_count"] == 1
    assert by_name["alone"]["plan_quantity"] == 2
    assert by_name["alone"]["plan_unit"] == "km"


def test_someone_elses_forest_is_not_listed(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)
    _draw_point(client, headers, act)
    intruder, _ = _login(client, db)

    resp = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=intruder)

    assert resp.status_code == 404


def test_the_column_can_no_longer_be_left_empty(client, db):
    """NOT NULL (migration 089): a writer that forgets it fails loudly instead of creating a
    feature that no layer, collision check or intersect query can ever see."""
    _, user = _login(client, db)
    _, act = _calc_with_activity(db, user)
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO activity_drawn_features (id, proposed_activity_id, feature_type, geometry, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :a, 'point', ST_GeomFromText('POINT(85 27)', 4326), now(), now())"
            ),
            {"a": str(act.id)},
        )
    db.rollback()


def test_collision_check_sees_the_forests_features(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)
    _draw_point(client, headers, act, lon=85.05, lat=27.44)

    near = client.get(
        f"{BASE}/calculations/{calc.id}/drawn-features/collision-check",
        headers=headers,
        params={"geometry": json.dumps({"type": "Point", "coordinates": [85.05, 27.44]})},
    )
    far = client.get(
        f"{BASE}/calculations/{calc.id}/drawn-features/collision-check",
        headers=headers,
        params={"geometry": json.dumps({"type": "Point", "coordinates": [85.5, 27.9]})},
    )

    assert near.status_code == 200, near.text
    assert near.json()["has_collision"] is True
    assert far.json()["has_collision"] is False


def test_intersecting_returns_features_inside_a_block_and_checks_the_owner(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)
    inside = _draw_point(client, headers, act, lon=85.05, lat=27.44, name="inside")
    _draw_point(client, headers, act, lon=85.9, lat=27.9, name="outside")
    block = ForestBlock(
        id=uuid.uuid4(),
        calculation_id=calc.id,
        name="B1",
        block_name="B1",
        geometry=from_shape(box(85.0, 27.4, 85.1, 27.5), srid=4326),
        area_hectares=1.0,
        index=0,
    )
    db.add(block)
    db.commit()

    ok = client.get(
        f"{BASE}/calculations/{calc.id}/drawn-features/intersecting",
        headers=headers,
        params={"block_id": str(block.id)},
    )
    intruder, _ = _login(client, db)
    denied = client.get(
        f"{BASE}/calculations/{calc.id}/drawn-features/intersecting",
        headers=intruder,
        params={"block_id": str(block.id)},
    )

    assert ok.status_code == 200, ok.text
    assert [f["id"] for f in ok.json()["features"]] == [inside["id"]]
    assert denied.status_code == 404


def test_a_copied_feature_keeps_the_calculation(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)
    src = _draw_point(client, headers, act)

    resp = client.post(
        f"{BASE}/proposed-activities/{act.id}/drawn-features/{src['id']}/copy",
        headers=headers,
        json={"target_year": 3},
    )

    assert resp.status_code == 200, resp.text
    db.expire_all()
    copy = db.query(ActivityDrawnFeature).filter_by(id=resp.json()["id"]).one()
    assert copy.calculation_id == calc.id
    body = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers).json()
    assert len(body) == 2


def test_the_layer_list_carries_the_activity_it_belongs_to(client, db):
    """The map labels a feature "<activity> · year 1", so the list must say which activity."""
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)  # PotentialActivity: programme "Program", activity "Plantation"
    _draw_point(client, headers, act, name="Ridge nursery")

    (row,) = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers).json()

    assert row["activity_name"] == "Plantation"
    assert row["program_name"] == "Program"
    assert row["block_name"] is None  # the activity is not tied to a block
    assert row["properties"]["name"] == "Ridge nursery"  # a name the user gave is kept


def test_a_feature_saved_without_a_name_is_named_after_its_activity(client, db):
    headers, user = _login(client, db)
    _, act = _calc_with_activity(db, user)

    resp = client.post(
        f"{BASE}/proposed-activities/{act.id}/drawn-features",
        headers=headers,
        json={
            "feature_type": "point",
            "geometry": json.dumps({"type": "Point", "coordinates": [85.05, 27.44]}),
            "properties": {"years": [1]},
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["properties"]["name"] == "Plantation"  # not "Feature 1", not blank


def test_a_feature_draws_as_its_activitys_kind_unless_it_names_its_own(client, db):
    """The symbol: the feature's own properties.kind, else its activity's default, else generic."""
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user, map_kind="nursery")
    _draw_point(client, headers, act, name="plain")
    resp = client.post(
        f"{BASE}/proposed-activities/{act.id}/drawn-features",
        headers=headers,
        json={
            "feature_type": "line",
            "geometry": json.dumps({"type": "LineString", "coordinates": [[85.0, 27.4], [85.1, 27.5]]}),
            "properties": {"name": "access", "kind": "Forest Road", "years": [1]},  # alias of "road"
        },
    )
    assert resp.status_code == 200, resp.text

    body = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers).json()
    kinds = {f["properties"]["name"]: f["kind"] for f in body}

    assert kinds == {"plain": "nursery", "access": "road"}


def test_an_activity_with_no_kind_gets_the_generic_symbol(client, db):
    headers, user = _login(client, db)
    calc, act = _calc_with_activity(db, user)  # map_kind NULL
    _draw_point(client, headers, act)

    (row,) = client.get(f"{BASE}/calculations/{calc.id}/drawn-features", headers=headers).json()

    assert row["kind"] == ""
