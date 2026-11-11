"""OP multi-template — Phase 4: version pinning, template-status, upgrade path,
suggest-kind, published gallery.

See OP_MULTI_TEMPLATE_PLAN.md §3.5 / §3.7.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User, UserRole
from app.models.calculation import Calculation
from app.models.operational_plan import OperationalPlan

PREFIX = "/api/v1/operational-plans"


def _uniq(p):
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


def _user(client, db, role=UserRole.USER, prefix="u"):
    email = _uniq(prefix)
    rr = client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "Tester"})
    assert rr.status_code in (200, 201), rr.text
    u = db.query(User).filter(User.email == email).first()
    if role != UserRole.USER:
        u.role = role
        db.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, u


@pytest.fixture()
def designer(client, db):
    return _user(client, db, UserRole.TEMPLATE_DESIGNER, "designer")


@pytest.fixture()
def admin(client, db):
    return _user(client, db, UserRole.SUPER_ADMIN, "super")


def _tree(intro_content="{{forest_name}} परिचय"):
    return [
        {"id": "c", "type": "preamble", "title_ne": "आवरण", "content": "{{forest_name}}",
         "is_cover": True, "children": []},
        {"id": "toc", "type": "toc", "title_ne": "विषयसूची", "content": "", "children": []},
        {"id": "s_intro", "type": "section", "title_ne": "परिचय", "content": intro_content,
         "children": []},
    ]


def _publish_template(client, db, dh, ah, *, tree=None, name=None):
    r = client.post(f"{PREFIX}/templates", json={
        "name": name or f"tmpl-{uuid.uuid4().hex[:6]}",
        "description": (
            "A publishable brief forest management plan template covering the "
            "standard sections, safe to offer in the gallery for any community "
            "forest that needs a straightforward operational plan."
        ),
        "tree": tree or _tree(),
        "plan_regime": "brief_fmp", "plan_stage": "new",
    }, headers=dh)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert client.post(f"{PREFIX}/templates/{tid}/submit", headers=dh).status_code == 200
    rr = client.post(f"{PREFIX}/templates/{tid}/review", json={"action": "approve"}, headers=ah)
    assert rr.status_code == 200, rr.text
    return tid, rr.json()


def _seed_plan(db, user_id, template_id, template_version, plan_tree, *, forest=None):
    c = Calculation(user_id=user_id, forest_name=forest or f"CF {uuid.uuid4().hex[:6]}")
    db.add(c)
    db.flush()
    p = OperationalPlan(
        calculation_id=c.id, forest_name=c.forest_name,
        sections={"tree": plan_tree},
        plan_metadata={
            "language": "NP",
            "template_id": str(template_id),
            "template_version": template_version,
            "template_kind": "brief_fmp_new",
        },
    )
    db.add(p)
    db.commit()
    return c.id, p.id


# ── template-status ─────────────────────────────────────────────────────

def test_status_no_template(client, db):
    h, u = _user(client, db)
    c = Calculation(user_id=u.id, forest_name="Nada CF")
    db.add(c); db.flush()
    p = OperationalPlan(calculation_id=c.id, forest_name="Nada CF", plan_metadata={})
    db.add(p); db.commit()
    r = client.get(f"{PREFIX}/{p.id}/template-status", headers=h)
    assert r.status_code == 200
    assert r.json()["has_template"] is False


def test_status_and_upgrade_flow(client, db, designer, admin):
    dh, _ = designer
    ah, _ = admin
    uh, uu = _user(client, db, prefix="owner")

    tid, pub = _publish_template(client, db, dh, ah)
    assert pub["published_version"] == 1

    # plan pinned to v1; the user edited the intro section
    plan_tree = _tree(intro_content="MY OWN INTRO TEXT")
    calc_id, plan_id = _seed_plan(db, uu.id, tid, 1, plan_tree)

    r = client.get(f"{PREFIX}/{plan_id}/template-status", headers=uh)
    assert r.status_code == 200, r.text
    assert r.json()["has_template"] is True
    assert r.json()["upgrade_available"] is False

    # ship v2: unpublish -> edit (add a section) -> submit -> approve
    assert client.post(f"{PREFIX}/templates/{tid}/unpublish", json={}, headers=ah).status_code == 200
    new_tree = _tree() + [{"id": "s_extra", "type": "section", "title_ne": "थप खण्ड",
                           "content": "", "children": []}]
    assert client.put(f"{PREFIX}/templates/{tid}", json={"tree": new_tree}, headers=dh).status_code == 200
    assert client.post(f"{PREFIX}/templates/{tid}/submit", headers=dh).status_code == 200
    rr = client.post(f"{PREFIX}/templates/{tid}/review",
                     json={"action": "approve", "note": "added थप खण्ड"}, headers=ah)
    assert rr.status_code == 200, rr.text
    assert rr.json()["published_version"] == 2

    r = client.get(f"{PREFIX}/{plan_id}/template-status", headers=uh)
    body = r.json()
    assert body["upgrade_available"] is True
    assert body["pinned_version"] == 1
    assert body["latest_published_version"] == 2
    assert "added थप खण्ड" in body["changelog_since"]

    # dry run
    r = client.post(f"{PREFIX}/{plan_id}/template-upgrade", json={"confirm": False}, headers=uh)
    assert r.status_code == 200, r.text
    dry = r.json()
    assert dry["applied"] is False
    assert "थप खण्ड" in dry["diff"]["added"]
    assert dry["diff"]["content_preserved"] >= 1

    # confirm
    r = client.post(f"{PREFIX}/{plan_id}/template-upgrade", json={"confirm": True}, headers=uh)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] is True

    db.expire_all()
    plan = db.query(OperationalPlan).get(plan_id)
    titles = [n["title_ne"] for n in plan.sections["tree"]]
    assert "थप खण्ड" in titles
    intro = next(n for n in plan.sections["tree"] if n["id"] == "s_intro")
    assert intro["content"] == "MY OWN INTRO TEXT"          # authored content kept
    assert plan.plan_metadata["template_version"] == 2      # re-pinned
    assert "pre_upgrade_snapshot" in plan.plan_metadata     # recoverable

    # second upgrade is a no-op
    r = client.post(f"{PREFIX}/{plan_id}/template-upgrade", json={"confirm": True}, headers=uh)
    assert r.json()["applied"] is False


# ── suggest-kind ────────────────────────────────────────────────────────

def test_suggest_kind_new_then_revision(client, db):
    h, u = _user(client, db, prefix="sk")
    forest = f"Suggest CF {uuid.uuid4().hex[:6]}"

    c1 = Calculation(user_id=u.id, forest_name=forest)
    db.add(c1); db.flush()
    p1 = OperationalPlan(calculation_id=c1.id, forest_name=forest, plan_metadata={})
    db.add(p1); db.commit()

    c2 = Calculation(user_id=u.id, forest_name=forest)
    db.add(c2); db.commit()

    r = client.get(f"{PREFIX}/suggest-kind", params={"calculation_id": str(c2.id), "regime": "brief_fmp"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["suggested_stage"] == "new"

    # approve a prior plan of that regime for the same forest
    p1.status = "approved"
    p1.plan_metadata = {"template_regime": "brief_fmp"}
    flag_modified(p1, "plan_metadata")
    db.commit()

    r = client.get(f"{PREFIX}/suggest-kind", params={"calculation_id": str(c2.id), "regime": "brief_fmp"}, headers=h)
    assert r.json()["suggested_stage"] == "revision"
    assert r.json()["has_prior_plan"] is True


# ── published gallery ──────────────────────────────────────────────────

def test_public_gallery_is_status_driven_with_kinds(client, db, designer, admin):
    dh, _ = designer
    ah, _ = admin
    tid, _ = _publish_template(client, db, dh, ah, name="Gallery Brief New")

    # a draft the same designer owns must NOT appear
    draft = client.post(f"{PREFIX}/templates", json={
        "name": "Gallery Draft", "description": "x", "tree": _tree(),
    }, headers=dh).json()

    r = client.get(f"{PREFIX}/templates/public", headers=dh)
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {t["id"] for t in body["templates"]}
    assert tid in ids
    assert draft["id"] not in ids
    assert all(t["status"] == "published" for t in body["templates"])
    assert len(body["kinds"]) == 6
    # the बृन्दावन base is every kind's default
    assert any(t["is_kind_default"] for t in body["templates"])


def test_gallery_tag_filter_uses_jsonb_containment(client, db, designer, admin):
    """Regression: `tags @> 'demo'` (a bare word) is invalid JSON and 500s.
    The filter must wrap the tag as a one-element array."""
    dh, _ = designer
    ah, _ = admin
    cr = client.post(f"{PREFIX}/templates", json={
        "name": "Tagged Template",
        "description": (
            "A tagged brief forest management plan template used to check the "
            "gallery tag filter — safe to publish for any community forest."
        ),
        "tree": _tree(),
        "plan_regime": "brief_fmp", "plan_stage": "new",
        "tags": ["demo", "pilot"],
    }, headers=dh)
    assert cr.status_code == 201, cr.text
    tid = cr.json()["id"]
    assert client.post(f"{PREFIX}/templates/{tid}/submit", headers=dh).status_code == 200
    assert client.post(
        f"{PREFIX}/templates/{tid}/review", json={"action": "approve"}, headers=ah
    ).status_code == 200

    r = client.get(f"{PREFIX}/templates/public?tag=demo", headers=dh)
    assert r.status_code == 200, r.text
    assert tid in {t["id"] for t in r.json()["templates"]}

    r2 = client.get(f"{PREFIX}/templates/public?tag=not-a-real-tag", headers=dh)
    assert r2.status_code == 200
    assert tid not in {t["id"] for t in r2.json()["templates"]}

    r3 = client.get(f"{PREFIX}/templates?scope=published&tag=pilot", headers=dh)
    assert r3.status_code == 200, r3.text
    assert tid in {t["id"] for t in r3.json()["templates"]}


def test_create_plan_resolves_kind_default_and_pins_regime_stage(client, db):
    h, u = _user(client, db, prefix="creator")
    c = Calculation(user_id=u.id, forest_name=f"Create CF {uuid.uuid4().hex[:6]}")
    db.add(c); db.commit()

    r = client.post(
        f"{PREFIX}?plan_regime=scientific_fmp&plan_stage=revision",
        json={"calculation_id": str(c.id)}, headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    meta = body["plan_metadata"]
    assert meta["template_regime"] == "scientific_fmp"
    assert meta["template_stage"] == "revision"
    # every kind currently points at the बृन्दावन base
    assert meta["template_id"]

    # template-status works on the freshly created plan
    st = client.get(f"{PREFIX}/{body['id']}/template-status", headers=h).json()
    assert st["has_template"] is True


# ── Phase 6: feature-flagged kind-match + auto-stage ────────────────────

@pytest.fixture()
def flags():
    from app.core.feature_flags import feature_flags
    saved = dict(feature_flags._cache)
    yield feature_flags
    feature_flags._cache = saved


def test_kind_match_off_allows_mismatch(client, db, designer, admin):
    dh, _ = designer
    ah, _ = admin
    tid, _ = _publish_template(client, db, dh, ah)  # brief_fmp_new
    h, u = _user(client, db, prefix="km")
    c = Calculation(user_id=u.id, forest_name=f"KM CF {uuid.uuid4().hex[:6]}")
    db.add(c); db.commit()
    r = client.post(
        f"{PREFIX}?template_id={tid}&plan_regime=scientific_fmp&plan_stage=revision",
        json={"calculation_id": str(c.id)}, headers=h,
    )
    assert r.status_code == 201  # flag off -> no enforcement


def test_kind_match_on_rejects_mismatch(client, db, designer, admin, flags):
    dh, _ = designer
    ah, _ = admin
    tid, _ = _publish_template(client, db, dh, ah)  # brief_fmp_new
    h, u = _user(client, db, prefix="km2")
    c = Calculation(user_id=u.id, forest_name=f"KM2 CF {uuid.uuid4().hex[:6]}")
    db.add(c); db.commit()

    flags.set_for_test("op_template_kind_match", True)
    r = client.post(
        f"{PREFIX}?template_id={tid}&plan_regime=scientific_fmp&plan_stage=revision",
        json={"calculation_id": str(c.id)}, headers=h,
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "KIND_MISMATCH"

    # matching regime/stage still works
    r = client.post(
        f"{PREFIX}?template_id={tid}&plan_regime=brief_fmp&plan_stage=new",
        json={"calculation_id": str(c.id)}, headers=h,
    )
    assert r.status_code == 201


def test_auto_stage_resolves_from_history(client, db, flags):
    h, u = _user(client, db, prefix="as")
    forest = f"AutoStage CF {uuid.uuid4().hex[:6]}"
    c1 = Calculation(user_id=u.id, forest_name=forest)
    db.add(c1); db.flush()
    p1 = OperationalPlan(calculation_id=c1.id, forest_name=forest, status="approved",
                         plan_metadata={"template_regime": "brief_fmp"})
    db.add(p1)
    c2 = Calculation(user_id=u.id, forest_name=forest)
    db.add(c2); db.commit()

    flags.set_for_test("op_auto_stage", True)
    r = client.post(
        f"{PREFIX}?plan_regime=brief_fmp",  # stage omitted
        json={"calculation_id": str(c2.id)}, headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["plan_metadata"]["template_stage"] == "revision"


def test_list_templates_scope_mine_vs_published(client, db, designer, admin):
    dh, _ = designer
    ah, _ = admin
    draft = client.post(f"{PREFIX}/templates", json={
        "name": f"scope-{uuid.uuid4().hex[:5]}", "description": "x", "tree": _tree(),
    }, headers=dh).json()

    mine = client.get(f"{PREFIX}/templates", params={"scope": "mine"}, headers=dh).json()
    assert draft["id"] in {t["id"] for t in mine["templates"]}

    published = client.get(f"{PREFIX}/templates", params={"scope": "published"}, headers=dh).json()
    assert draft["id"] not in {t["id"] for t in published["templates"]}
