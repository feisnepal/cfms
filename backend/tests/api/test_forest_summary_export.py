"""FP-11 gate: the plain-text export says what the panel says, in the reader's language, for the people allowed to open the
panel, and only once the summary has been prepared."""
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import unquote

import pytest

from app.models.calculation import Calculation
from app.models.forest_decision import ForestDecision
from app.models.op_data_cache import OpDataCache
from app.models.organization import Organization
from app.models.user import User, UserRole, UserStatus
from app.services.operational_plan.data_collector import OP_DATA_CACHE_VERSION
from app.utils.auth import hash_password

PASSWORD = "TestPass123!"


def _op():
    return {
        "basic_info": {"total_area_sqm": 1_000_000.0, "forest_name": "बृन्दाबन"},
        "field_inventory": {"available": True, "fi_growing_stock_m3_per_ha": 150.0, "fi_carbon_stock_tc_per_ha": 30.0,
                            "fi_aah_table": [{"block_name": "Grand Total (Weighted)", "total_aah_m3_per_ha": 2.0}],
                            "fi_block_summaries": [{"block_name": "B1", "forest_condition": "Good"},
                                                   {"block_name": "B2", "forest_condition": "Weak"}]},
        "hazard_vuln": {"lsi_prone_area_pct": 20.0, "lsi_class_method": "quantile", "hh_count": 10, "hh_priority_count": 3},
        "soil_erosion": {"soil_loss_available": True, "soil_loss_mean_t_ha": 5.0},
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


def _user(db, role=UserRole.USER, org=None, name="Tester"):
    user = User(id=uuid.uuid4(), email=f"fp11-{uuid.uuid4().hex[:10]}@example.com", hashed_password=hash_password(PASSWORD),
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
    calc = Calculation(id=str(uuid.uuid4()), user_id=owner.id, uploaded_filename="fp11.csv", is_draft=False,
                       map_lifecycle_status="completed", forest_name="बृन्दाबन परीक्षण")
    db.add(calc)
    db.flush()
    _add_units(db, calc)
    db.commit()
    return {"org": org, "owner": owner, "dfo": dfo, "calc": calc}


def _cache(db, calc):
    db.add(OpDataCache(calculation_id=calc.id, data={**_op(), "_cache_version": OP_DATA_CACHE_VERSION}))
    db.commit()


def _url(calc, tail="forest-summary/export"):
    return f"/api/calculations/{calc.id}/{tail}"


def test_409_until_the_summary_is_prepared(client, db, world):
    r = client.get(_url(world["calc"]), headers=_headers(client, world["owner"]))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "summary.not_collected"


def test_english_export_matches_the_panel(client, db, world):
    _cache(db, world["calc"])
    h = _headers(client, world["owner"])
    panel = client.get(_url(world["calc"], "forest-summary"), headers=h).json()
    r = client.get(_url(world["calc"]), headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain") and "utf-8" in r.headers["content-type"].lower()
    assert r.content.startswith(b"\xef\xbb\xbf")  # BOM, so Windows Notepad shows Nepali
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "FOREST SUMMARY - बृन्दाबन परीक्षण"
    assert "Area: Forest" in text and f"Date: {datetime.now(timezone.utc):%Y-%m-%d}" in text
    assert panel["verdict"] in text  # the very same sentence
    assert "Growing stock: 150 m³/ha" in text and "Carbon: 30 tC/ha" in text and "Allowable harvest: 2 m³/ha/yr" in text
    assert "Area: 100 ha (2)" in text
    assert re.search(r"Species: not computed \(step 6\)", text)
    for tile in panel["tiles"]:
        if tile["state"] == "ready":
            assert f"{tile['value']:.0f}" in text or f"{tile['value']:.1f}" in text
    assert "Landslide classes are relative to this forest." in text


def test_nepali_export(client, db, world):
    _cache(db, world["calc"])
    h = _headers(client, world["owner"])
    panel = client.get(_url(world["calc"], "forest-summary") + "?lang=ne", headers=h).json()
    text = client.get(_url(world["calc"]) + "?lang=ne", headers=h).content.decode("utf-8-sig")
    assert text.startswith("वन सारांश - बृन्दाबन परीक्षण")
    assert "सारांश\n" in text and "मुख्य तथ्याङ्क" in text and "आधार" in text
    assert panel["verdict"] in text and "{{" not in text


def test_user_group_export_says_which_figures_are_forest_only(client, db, world):
    _cache(db, world["calc"])
    text = client.get(_url(world["calc"]) + "?area=user_group", headers=_headers(client, world["owner"])).content.decode("utf-8-sig")
    assert "Area: User group" in text
    assert "Growing stock: not available for the user group (forest only)" in text


def test_decisions_are_listed_with_who_decided(client, db, world):
    # a saved decision clears the cached OP data (it has a calculation_id), so the cache is written after it
    db.add(ForestDecision(calculation_id=world["calc"].id, key="household_placement", choice="building_footprints", decided_by=world["dfo"].id))
    db.commit()
    _cache(db, world["calc"])
    text = client.get(_url(world["calc"]), headers=_headers(client, world["dfo"])).content.decode("utf-8-sig")
    section = text.split("DECISIONS\n", 1)[1].split("\n\n", 1)[0]
    assert "How to place households on the map: Building footprints - Decided by Ram Thapa (DFO)" in section
    assert "Landslide classes: relative or calibrated?: Open" in section


def test_file_name_follows_the_export_convention(client, db, world):
    _cache(db, world["calc"])
    r = client.get(_url(world["calc"]), headers=_headers(client, world["owner"]))
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment")
    name = unquote(disposition.split("filename*=UTF-8''", 1)[1])
    assert name == f"बृन्दाबन_परीक्षण_ForestSummary_Report_{datetime.now(timezone.utc):%Y%m%d}.txt"


@pytest.mark.parametrize("who,expected", [("dfo_same", 200), ("dfo_other", 403), ("plain_user", 403)])
def test_export_access(client, db, world, who, expected):
    _cache(db, world["calc"])
    if who == "dfo_same":
        user = world["dfo"]
    elif who == "dfo_other":
        other = Organization(name=f"Other-{uuid.uuid4().hex[:8]}", contact_email="x@example.com")
        db.add(other)
        db.flush()
        user = _user(db, UserRole.ORG_ADMIN, other)
    else:
        user = _user(db, UserRole.USER, world["org"])
    db.commit()
    assert client.get(_url(world["calc"]), headers=_headers(client, user)).status_code == expected


def test_nepali_export_writes_every_number_in_devanagari_and_english_in_latin(client, db, world):
    _cache(db, world["calc"])
    h = _headers(client, world["owner"])
    ne = client.get(_url(world["calc"]) + "?lang=ne", headers=h).content.decode("utf-8-sig")
    en = client.get(_url(world["calc"]), headers=h).content.decode("utf-8-sig")
    # unit names such as B2 are data and keep their Latin characters; every other digit is Devanagari
    assert not re.search(r"[0-9]", ne.replace("B2", "")), ne
    assert re.search(r"[०-९]", ne)
    assert "क्षेत्रफल: १०० हे. (२)" in ne  # area, its unit word and the unit count
    assert "वृद्धि मौज्दात: १५० घन मि./हे." in ne and "कार्बन: ३० टन कार्बन/हे." in ne
    assert "वार्षिक अनुमत कटान: २ घन मि./हे./वर्ष" in ne
    assert " ha" not in ne and "species" not in ne  # no English unit word left in the Nepali export
    assert f"मिति: {datetime.now(timezone.utc):%Y-%m-%d}".translate(str.maketrans("0123456789", "०१२३४५६७८९")) in ne
    assert "(चरण" in ne and "step 6" not in ne  # a not-computed tile names its step in the language
    assert not re.search(r"[०-९]", en)
