"""FP-3 gate: ``GET /calculations/{id}/forest-summary`` reads the cache only, ``POST .../refresh`` is the only call that
collects, and the same access rule as the decisions applies (owner, same-organisation DFO, super admin)."""
import re
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.household_summary_data import HouseholdSummaryData
from app.models.op_data_cache import OpDataCache
from app.models.organization import Organization
from app.models.user import User, UserRole, UserStatus
from app.services.operational_plan.data_collector import OP_DATA_CACHE_VERSION
from app.utils.auth import hash_password

PASSWORD = "TestPass123!"


def _op():
    return {
        "basic_info": {"total_area_sqm": 1_000_000.0},
        "field_inventory": {"available": True, "fi_growing_stock_m3_per_ha": 150.0, "fi_carbon_stock_tc_per_ha": 30.0,
                            "fi_aah_table": [{"block_name": "Grand Total (Weighted)", "total_aah_m3_per_ha": 2.0}],
                            "fi_block_summaries": [{"block_name": "B1", "forest_condition": "Good"},
                                                   {"block_name": "B2", "forest_condition": "Weak"}]},
        "hazard_vuln": {"lsi_prone_area_pct": 20.0, "lsi_class_method": "quantile", "hh_count": 10, "hh_priority_count": 3},
        "soil_erosion": {"soil_loss_available": True, "soil_loss_mean_t_ha": 5.0},
        "species": {"species_count": 12},
    }


def _add_units(db, calc):
    """The forest's two leaf units, in the forest_blocks table (where the summary reads unit areas from)."""
    from geoalchemy2.shape import from_shape
    from shapely.geometry import Polygon

    from app.models.forest_block import ForestBlock

    for i, (name, ha) in enumerate((("B1", 60.0), ("B2", 40.0))):
        db.add(ForestBlock(calculation_id=calc.id, name=name, block_name=name, area_hectares=ha, area_sqm=ha * 10000.0, index=i,
                           geometry=from_shape(Polygon([(0, 0), (0.01, 0), (0.01, 0.01), (0, 0.01)]), srid=4326),
                           is_compartment=False, division_level=1, is_locked=False, child_count=0))
    db.flush()


def _put_cache(db, calc, version=OP_DATA_CACHE_VERSION):
    db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).delete()
    db.add(OpDataCache(calculation_id=calc.id, data={**_op(), "_cache_version": version}))
    db.commit()


def _user(db, role=UserRole.USER, org=None, name="Tester"):
    user = User(id=uuid.uuid4(), email=f"fp3-{uuid.uuid4().hex[:10]}@example.com", hashed_password=hash_password(PASSWORD),
                full_name=name, role=role, status=UserStatus.ACTIVE, organization_id=org.id if org else None)
    db.add(user)
    db.flush()
    return user


def _headers(client, user):
    resp = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def world(client, db):
    org = Organization(name=f"DFO-{uuid.uuid4().hex[:8]}", contact_email="dfo@example.com")
    db.add(org)
    db.flush()
    owner = _user(db, UserRole.USER, org, "Sita Rai")
    dfo = _user(db, UserRole.ORG_ADMIN, org, "Ram Thapa")
    calc = Calculation(id=str(uuid.uuid4()), user_id=owner.id, uploaded_filename="fp3.csv", is_draft=False,
                       map_lifecycle_status="completed", structure_locked=True)
    db.add(calc)
    db.flush()
    _add_units(db, calc)
    db.commit()
    return {"org": org, "owner": owner, "dfo": dfo, "calc": calc}


def _url(calc, tail="forest-summary"):
    return f"/api/calculations/{calc.id}/{tail}"


def test_nothing_cached_answers_not_collected_and_never_collects(client, db, world, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("GET must not collect")

    monkeypatch.setattr("app.api.forest_summary.collect_all_op_data", boom)
    r = client.get(_url(world["calc"]), headers=_headers(client, world["owner"]))
    assert r.status_code == 200, r.text
    assert r.json() == {"state": "not_collected", "area": "forest", "tiles": [], "themes": [], "verdict": None, "basis": None}


def test_a_stale_cache_version_counts_as_not_collected(client, db, world):
    _put_cache(db, world["calc"], version="an-older-version")
    assert client.get(_url(world["calc"]), headers=_headers(client, world["owner"])).json()["state"] == "not_collected"


def test_cached_data_gives_tiles_themes_and_an_english_verdict(client, db, world):
    _put_cache(db, world["calc"])
    r = client.get(_url(world["calc"]), headers=_headers(client, world["owner"]))
    body = r.json()
    assert body["state"] == "ready" and body["area"] == "forest"
    tiles = {t["key"]: t for t in body["tiles"]}
    assert tiles["area"]["value"] == 100.0 and tiles["growing_stock"]["value"] == 150.0 and tiles["species"]["value"] == 12
    assert tiles["condition_good"]["value"] == 60.0
    assert "60% of the area is in good condition" in body["verdict"] and "B2" in body["verdict"]
    assert "relative" in body["verdict"]
    assert body["basis"]["collected_at"] and body["basis"]["hazard_method"] == "quantile"
    assert [t["key"] for t in body["themes"]] == ["stock", "health", "biodiversity", "hazard", "people"]


def test_nepali_verdict(client, db, world):
    _put_cache(db, world["calc"])
    body = client.get(_url(world["calc"]) + "?lang=ne", headers=_headers(client, world["owner"])).json()
    assert re.search(r"[ऀ-ॿ]", body["verdict"]) and "{{" not in body["verdict"] and "B2" in body["verdict"]


def test_user_group_scope(client, db, world):
    _put_cache(db, world["calc"])
    body = client.get(_url(world["calc"]) + "?area=user_group", headers=_headers(client, world["owner"])).json()
    tiles = {t["key"]: t for t in body["tiles"]}
    assert body["area"] == "user_group" and tiles["growing_stock"]["state"] == "forest_only"


def test_households_come_from_the_aggregate_not_the_op_cache(client, db, world):
    db.add(HouseholdSummaryData(calculation_id=world["calc"].id, total_households=214, male_count=500, female_count=520,
                                  created_by=world["owner"].id))
    db.commit()
    _put_cache(db, world["calc"])
    body = client.get(_url(world["calc"]), headers=_headers(client, world["owner"])).json()
    people = {r["key"]: r for r in next(t for t in body["themes"] if t["key"] == "people")["rows"]}
    assert people["households"]["value"] == 214


def test_refresh_collects_once_then_the_summary_is_ready(client, db, world, monkeypatch):
    calls = []

    def fake_collect(session, calculation_id):
        calls.append(calculation_id)
        session.add(OpDataCache(calculation_id=world["calc"].id, data={**_op(), "_cache_version": OP_DATA_CACHE_VERSION}))
        session.flush()

    monkeypatch.setattr("app.api.forest_summary.collect_all_op_data", fake_collect)
    h = _headers(client, world["dfo"])
    assert client.get(_url(world["calc"]), headers=h).json()["state"] == "not_collected"
    r = client.post(_url(world["calc"], "forest-summary/refresh"), headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ready" and calls == [str(world["calc"].id)]


def test_a_locked_map_can_still_be_read(client, db, world):
    world["calc"].map_lifecycle_status = "locked"
    db.commit()
    _put_cache(db, world["calc"])
    assert client.get(_url(world["calc"]), headers=_headers(client, world["owner"])).json()["state"] == "ready"


def test_bad_query_values_are_422(client, db, world):
    h = _headers(client, world["owner"])
    assert client.get(_url(world["calc"]) + "?area=ward", headers=h).status_code == 422
    assert client.get(_url(world["calc"]) + "?lang=fr", headers=h).status_code == 422


@pytest.mark.parametrize("who,expected", [("dfo_same", 200), ("super_admin", 200), ("dfo_other", 403), ("dfo_no_org", 403),
                                          ("plain_user", 403)])
def test_access_for_get_and_refresh(client, db, world, monkeypatch, who, expected):
    monkeypatch.setattr("app.api.forest_summary.collect_all_op_data", lambda session, cid: None)
    if who == "dfo_same":
        user = world["dfo"]
    elif who == "super_admin":
        user = _user(db, UserRole.SUPER_ADMIN)
    elif who == "dfo_other":
        other = Organization(name=f"Other-{uuid.uuid4().hex[:8]}", contact_email="x@example.com")
        db.add(other)
        db.flush()
        user = _user(db, UserRole.ORG_ADMIN, other)
    elif who == "dfo_no_org":
        user = _user(db, UserRole.ORG_ADMIN, None)
    else:
        user = _user(db, UserRole.USER, world["org"])
    db.commit()
    h = _headers(client, user)
    assert client.get(_url(world["calc"]), headers=h).status_code == expected
    assert client.post(_url(world["calc"], "forest-summary/refresh"), headers=h).status_code == expected


def test_unknown_forest_is_404(client, db, world):
    assert client.get(f"/api/calculations/{uuid.uuid4()}/forest-summary", headers=_headers(client, world["owner"])).status_code == 404
