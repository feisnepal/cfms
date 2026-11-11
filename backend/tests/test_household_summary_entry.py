"""Summary-only household entry: totals typed by the user stand in for household rows (owner, 2026-10-05).

Rules under test: demands auto-calculate from the entered totals with the household form's formulas;
every consumer reads one aggregate; household rows replace the summary; a summary is refused while rows exist.
"""
from __future__ import annotations

import uuid

from sqlalchemy import text

from app.models.user import User
from app.services.household_aggregate import compute_demands, get_aggregate
from app.services.household_calculations import HouseholdCalculations

BASE = {
    "total_households": 40, "male_count": 90, "female_count": 100,
    "forest_occupation_households": 25, "other_occupation_households": 10,
    "cow_ox_count": 30, "buffalo_count": 20, "goat_sheep_count": 50,
    "caste_distribution": {"जनजाती": 25, "दलित": 15},
    "prosperity_distribution": {"मध्यम": 30, "विपन्न": 10},
}


def _setup(db):
    uid = str(db.query(User).filter(User.email == "testuser@example.com").first().id)
    cid = uuid.uuid4()
    db.execute(text("INSERT INTO calculations (id, user_id, forest_name, status) VALUES (:i,:u,'F','PROCESSING')"),
               {"i": cid, "u": uid})
    db.commit()
    return uid, cid


def test_demands_equal_the_per_household_formula_applied_to_totals():
    d = compute_demands(40, 90, 100, 30, 20, 50)
    assert d["firewood_demand_bhari"] == HouseholdCalculations.calculate_firewood_demand(100, 90, 30, 20)
    assert d["grass_demand_bhari"] == HouseholdCalculations.calculate_grass_demand(30, 20, 50)
    assert d["bedding_demand_bhari"] == HouseholdCalculations.calculate_bedding_demand(30, 20)
    assert d["timber_demand_cft"] == 200 and d["pole_demand"] == 200  # 5 cft and 5 poles per household


def test_save_read_aggregate_and_delete(client, db, auth_headers):
    _, cid = _setup(db)
    url = f"/api/household/calculations/{cid}/summary-entry"
    r = client.put(url, json=BASE, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == []
    assert r.json()["firewood_demand_bhari"] is not None

    agg = get_aggregate(db, cid)
    assert agg["source"] == "summary" and agg["total_population"] == 190
    s = client.get(f"/api/household/calculations/{cid}/summary", headers=auth_headers)
    assert s.status_code == 200 and s.json()["source"] == "summary"
    assert s.json()["forest_dependent_households"] == 25

    assert client.delete(url, headers=auth_headers).json() == {"deleted": 1}
    assert client.get(f"/api/household/calculations/{cid}/summary", headers=auth_headers).status_code == 404


def test_mismatched_distributions_warn_but_save(client, db, auth_headers):
    _, cid = _setup(db)
    body = {**BASE, "caste_distribution": {"जनजाती": 5}}
    r = client.put(f"/api/household/calculations/{cid}/summary-entry", json=body, headers=auth_headers)
    assert r.status_code == 200 and "caste_total_mismatch" in r.json()["warnings"]


def test_household_rows_replace_the_summary_and_block_a_new_one(client, db, auth_headers):
    uid, cid = _setup(db)
    url = f"/api/household/calculations/{cid}/summary-entry"
    assert client.put(url, json=BASE, headers=auth_headers).status_code == 200

    hh = {"house_no": 1, "surname": "Shrestha", "female_count": 2, "male_count": 3}
    created = client.post(f"/api/household/calculations/{cid}/households", json=hh, headers=auth_headers)
    assert created.status_code in (200, 201), created.text

    assert client.get(url, headers=auth_headers).json() is None  # summary deleted
    assert get_aggregate(db, cid)["source"] == "households"
    assert client.put(url, json=BASE, headers=auth_headers).status_code == 409


def test_old_janajati_spelling_is_folded_into_the_correct_one(client, db, auth_headers):
    _, cid = _setup(db)
    old, new = "जनजाति", "जनजाती"
    body = {**BASE, "caste_distribution": {old: 10, new: 15, "दलित": 15}}
    r = client.put(f"/api/household/calculations/{cid}/summary-entry", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["caste_distribution"] == {new: 25, "दलित": 15}


def test_user_group_tiles_use_every_polygon_not_just_the_newest(db, auth_headers):
    """The raster tiles were clipped to the newest polygon only, so a second polygon showed rasters and the first did not."""
    from shapely import wkt
    from app.services.tile_service import TileService

    uid, cid = _setup(db)
    squares = ["POLYGON((85.0 27.0,85.001 27.0,85.001 27.001,85.0 27.001,85.0 27.0))",
               "POLYGON((85.01 27.0,85.011 27.0,85.011 27.001,85.01 27.001,85.01 27.0))"]
    for i, g in enumerate(squares):
        db.execute(text(
            "INSERT INTO user_group_extents (calculation_id, user_id, extent_geometry, source_type, created_at) "
            "VALUES (:c, :u, ST_Multi(ST_GeomFromText(:g, 4326)), 'manual', now() + (:i || ' seconds')::interval)"
        ), {"c": cid, "u": uid, "g": g, "i": i})
    db.commit()
    for getter in (TileService(db)._get_user_group_extent_geometry, TileService(db)._get_user_group_net_geometry):
        geom = wkt.loads(getter(str(cid)))
        assert geom.contains(wkt.loads(squares[0]).centroid) and geom.contains(wkt.loads(squares[1]).centroid)
