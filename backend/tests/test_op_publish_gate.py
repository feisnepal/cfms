"""Publish gate — description length + plan-kind required (T6).

OP_TEMPLATE_MANAGEMENT_PLAN.md §3.4 / D5. A published template's name +
description are the reader's only guide in the gallery, so:
  - description >= 120 chars to publish (a warning on demand below that),
  - plan regime + stage must be set,
  - is_system (the base) is exempt.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.user import User, UserRole

PREFIX = "/api/v1/operational-plans"
_PW = "TestPass123!"
_LONG = (
    "A thorough brief forest management plan template covering objectives, "
    "block-wise description, yield regulation and the ten-year activity "
    "schedule — safe to publish for any community forest."
)


def _uniq(p):
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


def _user(client, db, role, prefix):
    email = _uniq(prefix)
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PW, "full_name": "Tester"},
    )
    assert r.status_code in (200, 201), r.text
    u = db.query(User).filter(User.email == email).first()
    u.role = role
    db.commit()
    lr = client.post("/api/auth/login", json={"email": email, "password": _PW})
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


@pytest.fixture()
def dh(client, db):
    return _user(client, db, UserRole.TEMPLATE_DESIGNER, "designer")


@pytest.fixture()
def ah(client, db):
    return _user(client, db, UserRole.SUPER_ADMIN, "super")


def _tree():
    return [
        {"id": "c", "type": "preamble", "title_ne": "आवरण", "content": "{{forest_name}}",
         "is_cover": True, "children": []},
        {"id": "toc", "type": "toc", "title_ne": "विषयसूची", "content": "", "children": []},
        {"id": "s1", "type": "section", "title_ne": "परिचय",
         "content": "{{forest_name}} — {{total_area_hectares}}", "children": []},
    ]


def _create(client, dh, *, description, regime="brief_fmp", stage="new"):
    body = {"name": f"t-{uuid.uuid4().hex[:6]}", "description": description, "tree": _tree()}
    if regime:
        body["plan_regime"] = regime
    if stage:
        body["plan_stage"] = stage
    r = client.post(f"{PREFIX}/templates", json=body, headers=dh)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _approve(client, ah, tid):
    return client.post(
        f"{PREFIX}/templates/{tid}/review", json={"action": "approve"}, headers=ah
    )


def test_short_description_blocks_publish(client, dh, ah):
    tid = _create(client, dh, description="Too short.")
    # submit passes (short desc is only a warning here)
    assert client.post(f"{PREFIX}/templates/{tid}/submit", headers=dh).status_code == 200
    r = _approve(client, ah, tid)
    assert r.status_code == 422, r.text
    assert "description_too_short" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_missing_kind_blocks_publish(client, dh, ah):
    tid = _create(client, dh, description=_LONG, regime=None, stage=None)
    client.post(f"{PREFIX}/templates/{tid}/submit", headers=dh)
    r = _approve(client, ah, tid)
    assert r.status_code == 422, r.text
    assert "kind_required" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_long_description_with_kind_publishes(client, dh, ah):
    tid = _create(client, dh, description=_LONG)
    assert client.post(f"{PREFIX}/templates/{tid}/submit", headers=dh).status_code == 200
    r = _approve(client, ah, tid)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"


def test_on_demand_validate_warns_about_short_description(client, dh):
    tid = _create(client, dh, description="Still too short for the gallery.")
    r = client.post(f"{PREFIX}/templates/{tid}/validate", headers=dh)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True  # a warning, not an error
    assert "description_short" in {w["code"] for w in body["warnings"]}


def test_system_template_is_exempt_from_the_publish_gate(client, ah):
    r = client.get(f"{PREFIX}/templates/system", headers=ah)
    sid = r.json()["template"]["id"]
    v = client.post(f"{PREFIX}/templates/{sid}/validate", headers=ah)
    assert v.status_code == 200, v.text
    codes = {i["code"] for i in v.json()["errors"]} | {
        w["code"] for w in v.json()["warnings"]
    }
    assert "description_too_short" not in codes
    assert "description_short" not in codes
    assert "kind_required" not in codes
