"""A second plan for a forest: the answer says what to do, and "start again" replaces the draft but never a submitted plan."""
import uuid

from sqlalchemy import text

from app.models.calculation import Calculation
from tests.test_op_template_upgrade import PREFIX, _user


def _forest(client, db):
    h, u = _user(client, db, prefix="replacer")
    c = Calculation(user_id=u.id, forest_name=f"Replace CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.commit()
    return h, c


def _make(client, h, c, replace=False):
    q = "?plan_regime=brief_fmp&plan_stage=new" + ("&replace=true" if replace else "")
    return client.post(f"{PREFIX}{q}", json={"calculation_id": str(c.id)}, headers=h)


def test_a_second_plan_is_refused_with_what_the_screen_needs(client, db):
    h, c = _forest(client, db)
    first = _make(client, h, c)
    assert first.status_code == 201, first.text
    again = _make(client, h, c)
    assert again.status_code == 400
    d = again.json()["detail"]
    assert d["code"] == "PLAN_EXISTS" and d["plan_id"] == first.json()["id"]
    assert d["can_replace"] is True and d["blocked_reason"] is None and d["template_name"]


def test_start_again_replaces_the_draft_with_a_new_plan(client, db):
    h, c = _forest(client, db)
    first = _make(client, h, c).json()
    new = _make(client, h, c, replace=True)
    assert new.status_code == 201, new.text
    assert new.json()["id"] != first["id"]
    assert db.execute(text("select count(*) from operational_plans where calculation_id = :c"), {"c": c.id}).scalar() == 1
    assert client.get(f"{PREFIX}/calculation/{c.id}", headers=h).json()["id"] == new.json()["id"]


def test_a_submitted_plan_cannot_be_replaced(client, db):
    h, c = _forest(client, db)
    first = _make(client, h, c).json()
    db.execute(text("update operational_plans set status = 'submitted' where id = :p"), {"p": first["id"]})
    db.commit()
    r = _make(client, h, c, replace=True)
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "PLAN_EXISTS" and d["can_replace"] is False and d["blocked_reason"]
    assert db.execute(text("select count(*) from operational_plans where calculation_id = :c"), {"c": c.id}).scalar() == 1


def test_only_the_owner_may_start_again(client, db):
    h, c = _forest(client, db)
    assert _make(client, h, c).status_code == 201
    other, _ = _user(client, db, prefix="intruder")
    r = _make(client, other, c, replace=True)
    assert r.status_code == 403
    assert db.execute(text("select count(*) from operational_plans where calculation_id = :c"), {"c": c.id}).scalar() == 1


def test_replace_status_says_whether_a_plan_exists_and_may_be_replaced(client, db):
    h, c = _forest(client, db)
    none = client.get(f"{PREFIX}/calculation/{c.id}/replace-status", headers=h)
    assert none.status_code == 200 and none.json() == {"exists": False}

    first = _make(client, h, c).json()
    s = client.get(f"{PREFIX}/calculation/{c.id}/replace-status", headers=h).json()
    assert s["exists"] is True and s["plan_id"] == first["id"] and s["can_replace"] is True and s["template_name"]

    db.execute(text("update operational_plans set status = 'submitted' where id = :p"), {"p": first["id"]})
    db.commit()
    s = client.get(f"{PREFIX}/calculation/{c.id}/replace-status", headers=h).json()
    assert s["exists"] is True and s["can_replace"] is False and s["blocked_reason"]


def test_replace_status_is_for_the_owner_only(client, db):
    h, c = _forest(client, db)
    other, _ = _user(client, db, prefix="peeker")
    assert client.get(f"{PREFIX}/calculation/{c.id}/replace-status", headers=other).status_code == 403
