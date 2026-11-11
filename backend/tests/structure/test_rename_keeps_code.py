"""Renaming a polygon must not leave its automatic code behind.

Dividing a unit gives each piece an automatic code equal to its automatic name (SC2-1, SC2-2). Sampling, the field inventory and the
printed plan label a unit ``compartment_code or name``, so a rename that left the code as it was showed the polygon under two names.
A code the user typed themselves is theirs and stays.
"""

from types import SimpleNamespace

import pytest

from app.models.forest_block import ForestBlock
from app.models.user import User, UserStatus
from app.services.forest_units.write import keep_code_in_step
from app.utils.auth import hash_password


def _row(**kw):
    base = dict(name="SC2-2", block_name="SC2-2", compartment_code="SC2-2")
    base.update(kw)
    return SimpleNamespace(**base)


# ── the rule ────────────────────────────────────────────────────────────────────────────────


def test_a_code_that_was_a_copy_of_the_old_name_follows_the_rename():
    r = _row()
    r.name = r.block_name = "Encroached"
    assert keep_code_in_step(r, "SC2-2", "SC2-2") is True
    assert r.compartment_code == "Encroached"


def test_a_code_the_user_typed_is_left_alone():
    r = _row(compartment_code="CF-07")
    r.name = r.block_name = "Encroached"
    assert keep_code_in_step(r, "SC2-2", "SC2-2") is False
    assert r.compartment_code == "CF-07"


def test_no_code_stays_no_code_and_an_unchanged_name_changes_nothing():
    r = _row(compartment_code=None)
    r.name = "Encroached"
    assert keep_code_in_step(r, "SC2-2", "SC2-2") is False and r.compartment_code is None
    same = _row()
    assert keep_code_in_step(same, "SC2-2", "SC2-2") is False and same.compartment_code == "SC2-2"


def test_a_code_matching_the_old_block_name_also_follows():
    r = _row(name="Display", block_name="SC9", compartment_code="SC9")
    r.name = "New"
    assert keep_code_in_step(r, "Display", "SC9") is True and r.compartment_code == "New"


# ── through the real endpoints (both copies of the block edit) ─────────────────────────────────


@pytest.fixture()
def owner_headers(client, db):
    def _for(forest):
        user = db.query(User).filter(User.id == forest.user_id).first()
        user.hashed_password = hash_password("TestPass123!")
        user.status = UserStatus.ACTIVE
        db.commit()
        r = client.post("/api/auth/login", json={"email": user.email, "password": "TestPass123!"})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _for


def _unit(db, forest, name):
    return db.query(ForestBlock).filter(ForestBlock.id == forest.units[name]).one()


@pytest.mark.parametrize("prefix", ["/api/forests", "/api/blocks"])
def test_renaming_a_unit_through_the_block_edit_keeps_the_automatic_code_in_step(make_forest, db, client, owner_headers, prefix):
    f = make_forest("F3")
    u = _unit(db, f, "SB1")
    u.compartment_code = "SB1"  # the automatic code a divide would have given it
    db.commit()
    r = client.patch(
        f"{prefix}/calculations/{f.calc_id}/blocks/{u.id}",
        params={"name": "Encroached"},
        json={"natural_name": None},
        headers=owner_headers(f),
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    u = _unit(db, f, "SB1")
    assert u.name == "Encroached" and u.compartment_code == "Encroached"


def test_a_typed_code_survives_a_rename_through_the_endpoint(make_forest, db, client, owner_headers):
    f = make_forest("F3")
    u = _unit(db, f, "SB2")
    u.compartment_code = "CF-07"
    db.commit()
    r = client.patch(
        f"/api/forests/calculations/{f.calc_id}/blocks/{u.id}", params={"name": "Upper"}, json={"natural_name": None}, headers=owner_headers(f)
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _unit(db, f, "SB2").compartment_code == "CF-07"
