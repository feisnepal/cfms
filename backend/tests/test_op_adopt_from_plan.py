"""System Template — adopt structure from a plan (T4).

OP_TEMPLATE_MANAGEMENT_PLAN.md §3.1 / Example A:
  POST /operational-plans/templates/system/adopt-from-plan takes a plan's
  structure and restores {{tokens}} from the current System Template. The
  plan's resolved numbers never enter the template. The value-baking
  PUT /{plan_id}/update-default-template is gone (410).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.models.calculation import Calculation
from app.models.op_template import OPTemplate, OPTemplateVersion
from app.models.operational_plan import OperationalPlan
from app.models.user import User, UserRole

PREFIX = "/api/v1/operational-plans"
_PW = "TestPass123!"


def _uniq(p):
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


def _user(client, db, role=UserRole.USER, prefix="u"):
    email = _uniq(prefix)
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PW, "full_name": "Tester"},
    )
    assert r.status_code in (200, 201), r.text
    u = db.query(User).filter(User.email == email).first()
    if role != UserRole.USER:
        u.role = role
        db.commit()
    lr = client.post("/api/auth/login", json={"email": email, "password": _PW})
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}, u


def _system_id(db) -> str:
    return str(
        db.query(OPTemplate)
        .filter(OPTemplate.is_system.is_(True))
        .order_by(OPTemplate.updated_at.desc())
        .first()
        .id
    )


@pytest.fixture()
def admin(client, db):
    return _user(client, db, UserRole.SUPER_ADMIN, "super")


def _plan_from_system(client, db, admin_headers, admin_user):
    calc = Calculation(user_id=admin_user.id, forest_name=f"CF {uuid.uuid4().hex[:6]}")
    db.add(calc)
    db.commit()
    r = client.post(
        f"{PREFIX}", json={"calculation_id": str(calc.id)}, headers=admin_headers
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_dry_run_diff_then_apply(client, db, admin):
    headers, u = admin
    plan_id = _plan_from_system(client, db, headers, u)

    # dry run
    r = client.post(
        f"{PREFIX}/templates/system/adopt-from-plan"
        f"?plan_id={plan_id}&confirm=false",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is False
    assert body["template"] is None
    # the plan is an exact clone of the system tree -> every node matches by id
    assert body["diff"]["kept"] > 0
    assert body["diff"]["added"] == []
    # matched nodes with a {{token}} in the template get it restored
    assert len(body["diff"]["token_restored"]) > 0

    sys_id = _system_id(db)
    before = (
        db.query(OPTemplate).filter(OPTemplate.id == sys_id).one().version
    )

    # apply
    r = client.post(
        f"{PREFIX}/templates/system/adopt-from-plan"
        f"?plan_id={plan_id}&confirm=true",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is True
    assert body["template"]["is_system"] is True

    db.expire_all()
    row = db.query(OPTemplate).filter(OPTemplate.id == sys_id).one()
    assert row.version == before + 1
    snaps = (
        db.query(OPTemplateVersion)
        .filter(OPTemplateVersion.template_id == sys_id)
        .count()
    )
    assert snaps >= 1

    # a template never carries a plan's bookkeeping (plan_live.py): this used to leak into the System Template and
    # make it differ from the seed, which broke the "in sync" checks that run later
    def _walk(nodes):
        for n in nodes or []:
            yield n
            yield from _walk(n.get("children") or [])

    leaked = [n["id"] for n in _walk(row.tree) if n.get("source_content") is not None or n.get("populated_hash") is not None]
    assert leaked == []

    # the System Template still uses only registered tokens
    sysr = client.get(f"{PREFIX}/templates/system", headers=headers)
    assert sysr.json()["seed_sync"]["unregistered_tokens"] == []


def test_new_section_with_numbers_is_flagged_for_review(client, db, admin):
    headers, u = admin
    plan_id = _plan_from_system(client, db, headers, u)

    plan = db.query(OperationalPlan).filter(OperationalPlan.id == plan_id).one()
    tree = plan.sections["tree"]
    tree.append(
        {
            "id": "brand_new_node",
            "type": "section",
            "title_ne": "नयाँ खण्ड",
            "title_en": "Brand New Section",
            "content_type": "richtext",
            "content": "कुल क्षेत्रफल 123.45 हेक्टर छ।",
            "children": [],
        }
    )
    plan.sections = dict(plan.sections)
    flag_modified(plan, "sections")
    db.commit()

    r = client.post(
        f"{PREFIX}/templates/system/adopt-from-plan"
        f"?plan_id={plan_id}&confirm=false",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    diff = r.json()["diff"]
    assert "नयाँ खण्ड" in diff["added"]
    assert "नयाँ खण्ड" in diff["needs_review"]


def test_adopt_requires_super_admin(client, db):
    headers, u = _user(client, db, UserRole.TEMPLATE_DESIGNER, "designer")
    calc = Calculation(user_id=u.id, forest_name="X")
    db.add(calc)
    db.commit()
    r = client.post(
        f"{PREFIX}/templates/system/adopt-from-plan?plan_id={uuid.uuid4()}",
        headers=headers,
    )
    assert r.status_code == 403, r.text


def test_update_default_template_is_gone(client, db, admin):
    headers, u = admin
    plan_id = _plan_from_system(client, db, headers, u)
    r = client.put(
        f"{PREFIX}/{plan_id}/update-default-template", json={}, headers=headers
    )
    assert r.status_code == 410, r.text
    assert r.json()["detail"]["code"] == "endpoint_gone"
