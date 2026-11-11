"""Forest metadata endpoints: who may read a record, and who may write one.

WORKSPACE_FLOW_NAV_PLAN D5. The cover page of a .docx that gets printed and
filed is a record of a forest, so these are the two things worth pinning down.

**Write is owner-only, and a super admin writing someone else's forest gets a
404 rather than a 403.** That is not an accident of the test client: the admin
needs the *read* so they can support users, but a cover page must be something
the forest's own officer recorded. A 403 would confirm the calculation exists to
someone poking at ids, so the endpoint answers as if it were not there.

**A GET never creates a row**, which is why the first test asserts the count as
well as the flag -- a read that quietly wrote a record would mean every page load
manufactures one.

Every account here is registered fresh and unique. The shared `auth_headers`
user is deliberately not used: promoting it to super admin for one test leaves it
promoted and breaks every later test in the run, which is exactly what
`conftest.auth_headers` refuses to allow.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.forest_metadata import ForestMetadata
from app.models.user import User, UserRole, UserStatus

PATH = "/api/calculations/{calc_id}/forest-metadata"
PASSWORD = "TestPass123!"


def _register(client, email: str) -> str:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Metadata Tester"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _login(client, email: str) -> dict:
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _new_user(client, db, prefix: str, role: UserRole = UserRole.USER):
    """Register a unique account, activate it, and log it in."""
    email = f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"
    user_id = _register(client, email)
    user = db.query(User).filter(User.id == user_id).first()
    # Registration creates PENDING accounts; these tests need a working login.
    user.status = UserStatus.ACTIVE
    user.role = role
    db.commit()
    return user_id, _login(client, email)


def _calc(db, user_id: str, forest_name: str) -> Calculation:
    """Commit, not flush: the TestClient's request opens its own session, so an
    uncommitted row would be invisible to the route and every call a 404."""
    calculation = Calculation(user_id=user_id, forest_name=forest_name, is_draft=False)
    db.add(calculation)
    db.commit()
    return calculation


@pytest.fixture
def owner(client, db):
    user_id, headers = _new_user(client, db, "fm-owner")
    return {"headers": headers, "calc": _calc(db, user_id, "Owned forest")}


@pytest.fixture
def stranger(client, db):
    user_id, headers = _new_user(client, db, "fm-stranger")
    return {"headers": headers, "calc": _calc(db, user_id, "Not yours")}


def test_owner_sees_suggestions_without_a_row_being_created(client, db, owner):
    r = client.get(PATH.format(calc_id=owner["calc"].id), headers=owner["headers"])
    assert r.status_code == 200
    assert r.json()["persisted"] is False
    assert r.json()["forest_name"] == "Owned forest"
    assert db.query(ForestMetadata).filter(
        ForestMetadata.calculation_id == owner["calc"].id
    ).count() == 0, "a GET must not manufacture a record"


def test_owner_saves_and_reads_back_their_record(client, owner):
    r = client.put(
        PATH.format(calc_id=owner["calc"].id),
        headers=owner["headers"],
        json={"forest_name": "काली प्रसाद वन", "cf_national_code": "CF-08123", "fy_start": "२०८१/८२"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["cf_national_code"] == "CF-08123"
    # The envelope is bilingual so the panel can toast without a second lookup.
    assert r.json()["message_np"]

    r = client.get(PATH.format(calc_id=owner["calc"].id), headers=owner["headers"])
    assert r.json()["persisted"] is True
    assert r.json()["forest_name"] == "काली प्रसाद वन"
    assert r.json()["fy_start"] == "२०८१/८२"


def test_an_empty_save_is_a_400_with_a_bilingual_reason(client, owner):
    r = client.put(PATH.format(calc_id=owner["calc"].id), headers=owner["headers"], json={})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "forest_metadata.empty_update"
    assert r.json()["detail"]["message_np"]


def test_a_backwards_fiscal_year_is_a_400(client, owner):
    r = client.put(
        PATH.format(calc_id=owner["calc"].id),
        headers=owner["headers"],
        json={"forest_name": "F", "fy_start": "2085/86", "fy_end": "2080/81"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "forest_metadata.fy_order"
    assert r.json()["detail"]["message_np"]


def test_an_over_long_code_is_a_422_from_the_schema(client, owner):
    r = client.put(
        PATH.format(calc_id=owner["calc"].id),
        headers=owner["headers"],
        json={"forest_name": "F", "cf_national_code": "x" * 33},
    )
    assert r.status_code == 422


def test_another_user_can_neither_read_nor_write_the_record(client, db, owner, stranger):
    """A neighbour's forest is not a neighbour's metadata."""
    calc_id = owner["calc"].id
    assert client.get(PATH.format(calc_id=calc_id), headers=stranger["headers"]).status_code == 404
    r = client.put(
        PATH.format(calc_id=calc_id), headers=stranger["headers"], json={"forest_name": "Mine now"}
    )
    assert r.status_code == 404
    assert db.query(ForestMetadata).filter(ForestMetadata.calculation_id == calc_id).count() == 0


def test_no_token_is_401(client, owner):
    assert client.get(PATH.format(calc_id=owner["calc"].id)).status_code == 401


def test_a_malformed_id_is_404_rather_than_500(client, owner):
    r = client.get(PATH.format(calc_id="not-a-uuid"), headers=owner["headers"])
    assert r.status_code == 404


def test_a_malformed_id_on_write_is_404_not_500(client, owner):
    r = client.put(
        PATH.format(calc_id="not-a-uuid"), headers=owner["headers"], json={"forest_name": "F"}
    )
    assert r.status_code == 404


def test_a_super_admin_may_read_but_may_not_author_another_forest(client, db, owner):
    """Support needs to see the record; it must not be able to invent one."""
    _, admin = _new_user(client, db, "fm-admin", UserRole.SUPER_ADMIN)
    calc_id = owner["calc"].id
    client.put(PATH.format(calc_id=calc_id), headers=owner["headers"], json={"forest_name": "F"})

    assert client.get(PATH.format(calc_id=calc_id), headers=admin).status_code == 200

    r = client.put(PATH.format(calc_id=calc_id), headers=admin, json={"province": "Tampered"})
    assert r.status_code == 404, "a 403 would confirm the calculation exists"
    assert r.json()["detail"]["code"] == "forest_metadata.calc_not_found"
    assert db.query(ForestMetadata).filter(
        ForestMetadata.calculation_id == calc_id
    ).one().province != "Tampered"


def test_an_admin_may_still_save_their_own_forest(client, db):
    """The rule is ownership, not rank: super admins own forests too."""
    user_id, admin = _new_user(client, db, "fm-adminowner", UserRole.SUPER_ADMIN)
    calculation = _calc(db, user_id, "Admin's own")

    r = client.put(
        PATH.format(calc_id=calculation.id), headers=admin, json={"province": "Gandaki"}
    )
    assert r.status_code == 200
    assert db.query(ForestMetadata).filter(
        ForestMetadata.calculation_id == calculation.id
    ).one().province == "Gandaki"


def test_the_endpoint_is_mounted_at_both_api_prefixes(client, owner):
    """Clients are split between the two prefixes, so both must resolve."""
    calc_id = owner["calc"].id
    for prefix in ("/api/v1", "/api"):
        r = client.get(
            f"{prefix}/calculations/{calc_id}/forest-metadata", headers=owner["headers"]
        )
        assert r.status_code == 200, f"{prefix} did not resolve: {r.status_code} {r.text[:120]}"


def test_saving_twice_updates_one_record(client, db, owner):
    for ward in ("1", "2", "3"):
        client.put(
            PATH.format(calc_id=owner["calc"].id), headers=owner["headers"], json={"ward": ward}
        )
    rows = db.query(ForestMetadata).filter(
        ForestMetadata.calculation_id == owner["calc"].id
    ).all()
    assert len(rows) == 1
    assert rows[0].ward == "3"


def test_report_generation_no_longer_requires_a_posted_metadata_blob():
    """The old contract made every caller restate the forest's details.

    Now the record supplies them, so `metadata` is optional. Guarded through
    OpenAPI rather than by calling generate, which would kick off real AI
    generation and need a provider key.
    """
    from app.main import app

    schema = app.openapi()
    for prefix in ("/api/v1", "/api"):
        body = schema["paths"][f"{prefix}/report/{{calculation_id}}/generate"]["post"][
            "requestBody"
        ]["content"]["application/json"]["schema"]
        ref = body.get("$ref", "")
        assert ref, f"{prefix} generate is no longer a plain model: {body}"

        name = ref.rsplit("/", 1)[-1]
        required = schema["components"]["schemas"][name].get("required", [])
        assert "metadata" not in required, (
            "a caller with no metadata row of its own must still be able to "
            "generate; the server reads the record"
        )
