"""FP-2 gate: the plan decisions (``GET/PUT /calculations/{id}/decisions``), who may use them, and the shared
orientation helper behind both ``update_block`` routes.

Every test makes its OWN users (never the shared ``testuser@example.com`` account, see ``conftest.auth_headers``).
"""
import uuid

import pytest
from geoalchemy2.shape import from_shape
from shapely.geometry import Polygon

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.forest_decision import ForestDecision
from app.models.organization import Organization
from app.models.user import User, UserRole, UserStatus
from app.utils.auth import hash_password

PASSWORD = "TestPass123!"


def _org(db):
    org = Organization(name=f"DFO-{uuid.uuid4().hex[:8]}", contact_email="dfo@example.com")
    db.add(org)
    db.flush()
    return org


def _user(db, role=UserRole.USER, org=None, name="Tester"):
    user = User(id=uuid.uuid4(), email=f"fp2-{uuid.uuid4().hex[:10]}@example.com", hashed_password=hash_password(PASSWORD),
                full_name=name, role=role, status=UserStatus.ACTIVE, organization_id=org.id if org else None)
    db.add(user)
    db.flush()
    return user


def _headers(client, user):
    resp = client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _calc(db, owner, status="completed"):
    calc = Calculation(id=str(uuid.uuid4()), user_id=owner.id, uploaded_filename="fp2.csv", is_draft=False,
                       structure_locked=True,  # set at submit, so it is already true while the DFO reviews
                       map_lifecycle_status=status)
    db.add(calc)
    db.flush()
    return calc


def _block(db, calc, name="B1", current=None, suggested=None):
    geom = Polygon([(0.0, 0.0), (0.01, 0.0), (0.01, 0.01), (0.0, 0.01)])
    block = ForestBlock(calculation_id=calc.id, name=name, block_name=name, geometry=from_shape(geom, srid=4326),
                        area_hectares=1.0, area_sqm=10000.0, index=0, is_compartment=False, division_level=1,
                        is_locked=False, child_count=0, management_orientation=current, suggested_orientation=suggested)
    db.add(block)
    db.flush()
    return block


@pytest.fixture()
def world(client, db):
    """An owner, a DFO of the owner's organisation, and the forest — committed so the API (same session) sees it."""
    org = _org(db)
    owner = _user(db, UserRole.USER, org, "Sita Rai")
    dfo = _user(db, UserRole.ORG_ADMIN, org, "Ram Thapa")
    calc = _calc(db, owner)
    db.commit()
    return {"org": org, "owner": owner, "dfo": dfo, "calc": calc}


def _url(calc, tail="decisions"):
    return f"/api/calculations/{calc.id}/{tail}"


# ---- who may use the panel ---------------------------------------------------------------------------------------

def test_owner_reads_two_open_forest_wide_decisions(client, db, world):
    r = client.get(_url(world["calc"]), headers=_headers(client, world["owner"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["open_count"] == 2 and body["locked"] is False
    assert {i["key"] for i in body["items"]} == {"landslide_method", "household_placement"}


def test_dfo_of_same_organisation_can_answer_while_structure_locked(client, db, world):
    """structure_locked is already true during the DFO review; it must not stop the DFO."""
    assert world["calc"].structure_locked is True
    r = client.put(_url(world["calc"], "decisions/landslide_method"), json={"choice": "relative"},
                   headers=_headers(client, world["dfo"]))
    assert r.status_code == 200, r.text
    item = next(i for i in r.json()["items"] if i["key"] == "landslide_method")
    assert item["state"] == "answered" and item["choice"] == "relative"
    assert item["decided_by"]["kind"] == "dfo" and item["decided_by"]["name"] == "Ram Thapa"
    assert r.json()["open_count"] == 1


def test_owner_answer_is_marked_owner_and_a_second_answer_replaces_the_first(client, db, world):
    h = _headers(client, world["owner"])
    client.put(_url(world["calc"], "decisions/landslide_method"), json={"choice": "relative"}, headers=h)
    r = client.put(_url(world["calc"], "decisions/landslide_method"), json={"choice": "needs_calibration"}, headers=h)
    item = next(i for i in r.json()["items"] if i["key"] == "landslide_method")
    assert item["choice"] == "needs_calibration" and item["decided_by"]["kind"] == "owner"
    assert db.query(ForestDecision).filter(ForestDecision.calculation_id == world["calc"].id).count() == 1


def test_super_admin_allowed(client, db, world):
    admin = _user(db, UserRole.SUPER_ADMIN)
    db.commit()
    r = client.get(_url(world["calc"]), headers=_headers(client, admin))
    assert r.status_code == 200


@pytest.mark.parametrize("who", ["dfo_other_org", "dfo_no_org", "plain_user"])
def test_everyone_else_is_refused(client, db, world, who):
    if who == "dfo_other_org":
        other = _user(db, UserRole.ORG_ADMIN, _org(db))
    elif who == "dfo_no_org":
        other = _user(db, UserRole.ORG_ADMIN, None)
    else:
        other = _user(db, UserRole.USER, world["org"])  # same organisation, but not a DFO and not the owner
    db.commit()
    h = _headers(client, other)
    assert client.get(_url(world["calc"]), headers=h).status_code == 403
    assert client.put(_url(world["calc"], "decisions/landslide_method"), json={"choice": "relative"},
                      headers=h).status_code == 403


def test_owner_without_organisation_is_not_reachable_by_a_dfo_without_organisation(client, db):
    owner = _user(db, UserRole.USER, None)
    dfo = _user(db, UserRole.ORG_ADMIN, None)
    calc = _calc(db, owner)
    db.commit()
    assert client.get(_url(calc), headers=_headers(client, dfo)).status_code == 403


def test_unknown_forest_is_404(client, db, world):
    r = client.get(f"/api/calculations/{uuid.uuid4()}/decisions", headers=_headers(client, world["owner"]))
    assert r.status_code == 404


# ---- the lock keys on map_lifecycle_status ------------------------------------------------------------------------

@pytest.mark.parametrize("status,allowed", [("draft", True), ("submitted", True), ("completed", True), ("failed", True),
                                            ("calculating", False), ("locked", False)])
def test_lock_follows_the_lifecycle_status(client, db, world, status, allowed):
    world["calc"].map_lifecycle_status = status
    db.commit()
    r = client.put(_url(world["calc"], "decisions/landslide_method"), json={"choice": "relative"},
                   headers=_headers(client, world["dfo"]))
    if allowed:
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 423
        assert r.json()["detail"]["code"] == "decisions.locked"
        assert r.headers["X-Locked-Reason"] == status
        assert client.get(_url(world["calc"]), headers=_headers(client, world["dfo"])).json()["locked"] is True
    assert db.query(ForestDecision).filter(ForestDecision.calculation_id == world["calc"].id).count() == (1 if allowed else 0)


# ---- validation ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("key,body", [
    ("no_such_decision", {"choice": "relative"}),
    ("landslide_method", {"choice": "no_such_choice"}),
    ("landslide_method", {"choice": "relative", "scope": "b1"}),
    ("orientation", {"choice": "accept_suggested"}),                         # needs a block
    ("orientation", {"choice": "custom", "scope": str(uuid.uuid4())}),         # custom needs a valid value
    ("orientation", {"choice": "accept_suggested", "scope": "not-a-uuid"}),
    ("orientation", {"choice": "accept_suggested", "scope": str(uuid.uuid4())}),  # block of no forest
])
def test_bad_requests_are_422(client, db, world, key, body):
    r = client.put(_url(world["calc"], f"decisions/{key}"), json=body, headers=_headers(client, world["owner"]))
    assert r.status_code == 422, r.text
    assert db.query(ForestDecision).filter(ForestDecision.calculation_id == world["calc"].id).count() == 0


# ---- orientation: the answer writes the block, and open/answered is read from the columns -------------------------

def test_orientation_card_exists_only_when_the_block_differs_from_the_suggestion(client, db, world):
    calc = world["calc"]
    _block(db, calc, "same", current="Protection", suggested="Protection")
    differs = _block(db, calc, "differs", current="Production", suggested="Protection")
    unset = _block(db, calc, "unset", current=None, suggested="Conservation")
    _block(db, calc, "no-suggestion", current="Production", suggested=None)
    db.commit()
    body = client.get(_url(calc), headers=_headers(client, world["owner"])).json()
    cards = {i["scope"]: i for i in body["items"] if i["key"] == "orientation"}
    assert set(cards) == {str(differs.id), str(unset.id)}
    assert all(c["state"] == "open" for c in cards.values())
    assert body["open_count"] == 4  # 2 forest-wide + 2 blocks


def test_accept_suggested_writes_the_block_and_the_result_data_snapshot(client, db, world):
    calc = world["calc"]
    block = _block(db, calc, "B7", current="Production", suggested="Protection")
    calc.result_data = {"blocks": [{"block_id": str(block.id), "management_orientation": "Production"}]}
    db.commit()
    r = client.put(_url(calc, "decisions/orientation"), json={"choice": "accept_suggested", "scope": str(block.id)},
                   headers=_headers(client, world["dfo"]))
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(ForestBlock, block.id).management_orientation == "Protection"
    assert db.get(Calculation, calc.id).result_data["blocks"][0]["management_orientation"] == "Protection"
    # now equal to the suggestion, so the audit row keeps the card as answered
    card = next(i for i in r.json()["items"] if i["key"] == "orientation")
    assert card["state"] == "answered" and card["decided_by"]["kind"] == "dfo"


def test_custom_orientation_is_answered_and_reopens_if_the_column_is_cleared(client, db, world):
    calc = world["calc"]
    block = _block(db, calc, "B7", current="Production", suggested="Protection")
    db.commit()
    h = _headers(client, world["owner"])
    r = client.put(_url(calc, "decisions/orientation"), json={"choice": "custom", "scope": str(block.id), "value": "Conservation"}, headers=h)
    assert r.status_code == 200, r.text
    card = next(i for i in r.json()["items"] if i["key"] == "orientation")
    assert card["state"] == "answered" and card["current"] == "Conservation" and card["note"] == "Conservation"
    # someone clears the orientation in the attribute table: the answer must not hide the open question
    db.expire_all()
    db.get(ForestBlock, block.id).management_orientation = None
    db.commit()
    card = next(i for i in client.get(_url(calc), headers=h).json()["items"] if i["key"] == "orientation")
    assert card["state"] == "open"


def test_bad_custom_value_is_rejected(client, db, world):
    block = _block(db, world["calc"], "B7", current="Production", suggested="Protection")
    db.commit()
    r = client.put(_url(world["calc"], "decisions/orientation"),
                   json={"choice": "custom", "scope": str(block.id), "value": "Logging"}, headers=_headers(client, world["owner"]))
    assert r.status_code == 422


# ---- both update_block routes go through the one helper ----------------------------------------------------------

@pytest.mark.parametrize("prefix", ["/api/blocks", "/api/forests"])
def test_both_update_block_routes_write_column_and_snapshot(client, db, world, prefix):
    calc = world["calc"]
    block = _block(db, calc, "B1", current="Production", suggested=None)
    calc.result_data = {"blocks": [{"block_id": str(block.id), "management_orientation": "Production"}]}
    calc.structure_locked = False
    db.commit()
    r = client.patch(f"{prefix}/calculations/{calc.id}/blocks/{block.id}", json={"management_orientation": "Conservation"},
                     headers=_headers(client, world["owner"]))
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(ForestBlock, block.id).management_orientation == "Conservation"
    assert db.get(Calculation, calc.id).result_data["blocks"][0]["management_orientation"] == "Conservation"


def test_deleting_a_forest_removes_its_decisions(client, db, world):
    client.put(_url(world["calc"], "decisions/landslide_method"), json={"choice": "relative"}, headers=_headers(client, world["owner"]))
    calc_id = world["calc"].id
    db.expire_all()
    db.delete(db.get(Calculation, calc_id))
    db.commit()
    assert db.query(ForestDecision).filter(ForestDecision.calculation_id == calc_id).count() == 0
