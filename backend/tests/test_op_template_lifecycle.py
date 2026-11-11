"""OP multi-template — Phase 1: lifecycle state machine, validation gate,
audit trail, plan kinds.

See OP_MULTI_TEMPLATE_PLAN.md §3.2–§3.6.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.user import User, UserRole

PREFIX = "/api/v1/operational-plans"


# ── helpers ──────────────────────────────────────────────────────────────

_PW = "TestPass123!"


def _uniq(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


def _login(client, email: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": _PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user_with_role(client, db, role: UserRole, prefix: str) -> dict:
    email = _uniq(prefix)
    r = client.post("/api/auth/register", json={
        "email": email, "password": _PW, "full_name": "T D",
    })
    assert r.status_code in (200, 201), r.text
    u = db.query(User).filter(User.email == email).first()
    u.role = role
    db.commit()
    return _login(client, email)


@pytest.fixture()
def designer_headers(client, db):
    return _user_with_role(client, db, UserRole.TEMPLATE_DESIGNER, "designer")


@pytest.fixture()
def admin_headers(client, db):
    return _user_with_role(client, db, UserRole.SUPER_ADMIN, "super")


def _tree(*, unknown_token=False, description_token="forest_name"):
    bad = "{{totally_not_a_registered_variable}}" if unknown_token else ""
    return [
        {"id": "n_cover", "type": "preamble", "title_ne": "आवरण", "title_en": "Cover",
         "content_type": "richtext", "content": "{{forest_name}}", "is_cover": True,
         "children": []},
        {"id": "n_toc", "type": "toc", "title_ne": "विषयसूची", "title_en": "Contents",
         "content_type": "richtext", "content": "", "children": []},
        {"id": "n_1", "type": "section", "title_ne": "परिचय", "title_en": "Introduction",
         "content_type": "richtext",
         "content": f"क्षेत्रफल {{{{total_area_hectares}}}} हेक्टर {bad}", "children": []},
    ]


# A publish-gate-valid description (>= 120 chars) + a real kind, so the shared
# helper produces templates that can go all the way to `published` (T6).
_PUBLISHABLE_DESC = (
    "A test template for the OP lifecycle suite. It covers the standard "
    "sections a brief forest management plan needs and is safe to publish "
    "in the gallery for any community forest."
)


def _create_template(client, headers, *, name=None, tree=None, description=_PUBLISHABLE_DESC,
                     plan_regime="brief_fmp", plan_stage="new"):
    body = {
        "name": name or f"tmpl-{uuid.uuid4().hex[:6]}",
        "description": description,
        "tree": tree if tree is not None else _tree(),
    }
    if plan_regime:
        body["plan_regime"] = plan_regime
    if plan_stage:
        body["plan_stage"] = plan_stage
    r = client.post(f"{PREFIX}/templates", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ── plan kinds ───────────────────────────────────────────────────────────

def test_plan_kinds_seeded_six_with_inheritance(client, auth_headers):
    r = client.get(f"{PREFIX}/plan-kinds", headers=auth_headers)
    assert r.status_code == 200, r.text
    kinds = {k["key"]: k for k in r.json()}
    assert set(kinds) == {
        "sustainable_fmp_new", "sustainable_fmp_revision",
        "brief_fmp_new", "brief_fmp_revision",
        "scientific_fmp_new", "scientific_fmp_revision",
    }
    assert kinds["brief_fmp_revision"]["parent_kind_key"] == "brief_fmp_new"
    # every kind points at the Brindaban base initially
    assert kinds["sustainable_fmp_new"]["default_template_id"] is not None


def test_plan_kind_required_sections_inherit_from_parent(client, admin_headers, auth_headers):
    # give the New kind two required sections, the Revision kind one extra
    r = client.put(f"{PREFIX}/plan-kinds/scientific_fmp_new",
                   json={"required_section_keys": ["intro", "silviculture"]},
                   headers=admin_headers)
    assert r.status_code == 200, r.text
    r = client.put(f"{PREFIX}/plan-kinds/scientific_fmp_revision",
                   json={"required_section_keys": ["review_of_previous"]},
                   headers=admin_headers)
    assert r.status_code == 200, r.text

    r = client.get(f"{PREFIX}/plan-kinds", headers=auth_headers)
    kinds = {k["key"]: k for k in r.json()}
    eff = kinds["scientific_fmp_revision"]["effective_required_section_keys"]
    assert eff == ["intro", "silviculture", "review_of_previous"]

    # reset so other tests are unaffected
    for key in ("scientific_fmp_new", "scientific_fmp_revision"):
        client.put(f"{PREFIX}/plan-kinds/{key}",
                   json={"required_section_keys": []}, headers=admin_headers)


def test_plan_kind_update_requires_super_admin(client, designer_headers):
    r = client.put(f"{PREFIX}/plan-kinds/brief_fmp_new",
                   json={"label_en": "hacked"}, headers=designer_headers)
    assert r.status_code == 403


# ── validation gate ──────────────────────────────────────────────────────

def test_validate_flags_unknown_token(client, designer_headers):
    t = _create_template(client, designer_headers, tree=_tree(unknown_token=True))
    r = client.post(f"{PREFIX}/templates/{t['id']}/validate", headers=designer_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    codes = {i["code"] for i in body["errors"]}
    assert "unknown_token" in codes


def test_validate_clean_template_ok(client, designer_headers):
    t = _create_template(client, designer_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/validate", headers=designer_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


# ── lifecycle ────────────────────────────────────────────────────────────

def test_submit_blocked_by_validation(client, designer_headers):
    t = _create_template(client, designer_headers, tree=_tree(unknown_token=True))
    r = client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "validation_failed"


def test_full_happy_path_submit_approve_publishes(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    assert t["status"] == "draft"

    r = client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_review"

    r = client.post(f"{PREFIX}/templates/{t['id']}/review",
                    json={"action": "approve", "note": "looks good"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["status"] == "published"
    assert pub["published_version"] == pub["version"]
    # legacy shims kept in sync for the un-migrated gallery
    assert pub["approval_status"] == "approved"
    assert pub["is_active"] is True
    assert pub["visibility"] == "global"

    # a published snapshot exists
    r = client.get(f"{PREFIX}/templates/{t['id']}/versions", headers=admin_headers)
    assert r.status_code == 200
    assert any(v["version"] == pub["published_version"] for v in r.json())

    # audit trail recorded submit + approve_publish
    r = client.get(f"{PREFIX}/templates/{t['id']}/audit", headers=admin_headers)
    assert r.status_code == 200, r.text
    actions = [a["action"] for a in r.json()]
    assert "submit" in actions and "approve_publish" in actions


def test_reject_requires_note_and_sets_rejected(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)

    r = client.post(f"{PREFIX}/templates/{t['id']}/review",
                    json={"action": "reject", "note": ""}, headers=admin_headers)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "note_required"

    r = client.post(f"{PREFIX}/templates/{t['id']}/review",
                    json={"action": "reject", "note": "missing chapter 4"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"


def test_editing_in_review_template_returns_it_to_draft(client, designer_headers):
    t = _create_template(client, designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    r = client.put(f"{PREFIX}/templates/{t['id']}",
                   json={"tree": _tree()}, headers=designer_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft"


def test_approve_from_draft_is_conflict(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/review",
                    json={"action": "approve"}, headers=admin_headers)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "bad_state"


def test_unpublish_deprecate_retire(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/review",
                json={"action": "approve"}, headers=admin_headers)

    # deprecate (published -> deprecated), still visible
    r = client.post(f"{PREFIX}/templates/{t['id']}/deprecate",
                    json={"note": "superseded"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deprecated"

    # retire (-> retired) with a live-plan count
    r = client.post(f"{PREFIX}/templates/{t['id']}/retire",
                    json={"note": "withdrawn by DFO"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["template"]["status"] == "retired"
    assert r.json()["live_plan_count"] == 0

    # retire again -> conflict
    r = client.post(f"{PREFIX}/templates/{t['id']}/retire",
                    json={"note": "again"}, headers=admin_headers)
    assert r.status_code == 409


def test_retire_requires_note(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/review",
                json={"action": "approve"}, headers=admin_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/retire", json={"note": ""},
                    headers=admin_headers)
    assert r.status_code == 400


def test_lifecycle_endpoints_forbidden_for_ordinary_user(client, auth_headers, designer_headers):
    t = _create_template(client, designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    for path in ("review", "unpublish", "deprecate", "retire"):
        payload = {"action": "approve"} if path == "review" else {"note": "x"}
        r = client.post(f"{PREFIX}/templates/{t['id']}/{path}", json=payload,
                        headers=auth_headers)
        assert r.status_code == 403, f"{path} -> {r.status_code}"


# ── clone New -> Revision ────────────────────────────────────────────────

def test_clone_with_target_plan_kind(client, designer_headers):
    t = _create_template(client, designer_headers,
                         plan_regime="sustainable_fmp", plan_stage="new")
    assert t["plan_kind"] == "sustainable_fmp_new"
    r = client.post(f"{PREFIX}/templates/{t['id']}/clone",
                    json={"name": "Sustainable Revision",
                          "target_plan_stage": "revision"},
                    headers=designer_headers)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["plan_kind"] == "sustainable_fmp_revision"
    assert c["plan_stage"] == "revision"
    assert c["status"] == "draft"


# ── legacy publish shim ──────────────────────────────────────────────────

def test_legacy_flags_are_derived_from_status(client, designer_headers, admin_headers, db):
    """Phase 7: the visibility / is_active / approval_status / is_default columns
    are gone; the API derives them from `status` for response compatibility."""
    from sqlalchemy import inspect
    cols = {c["name"] for c in inspect(db.get_bind()).get_columns("op_templates", schema="public")}
    assert {"visibility", "is_active", "approval_status", "is_default"}.isdisjoint(cols)

    t = _create_template(client, designer_headers)
    assert t["status"] == "draft"
    assert t["is_active"] is False
    assert t["visibility"] == "private"
    assert t["approval_status"] == "none"

    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/review",
                    json={"action": "approve"}, headers=admin_headers)
    pub = r.json()
    assert pub["status"] == "published"
    assert pub["is_active"] is True
    assert pub["visibility"] == "global"
    assert pub["approval_status"] == "approved"


def test_legacy_publish_toggle_syncs_status(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    r = client.put(f"{PREFIX}/templates/{t['id']}/publish",
                   json={"is_active": True}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published"
    assert r.json()["is_active"] is True

    r = client.put(f"{PREFIX}/templates/{t['id']}/publish",
                   json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "draft"
    assert r.json()["is_active"] is False


# ── any signed-in user may copy a template they can see (owner, 2026-10-16) ──

def _publish(client, designer_headers, admin_headers):
    t = _create_template(client, designer_headers)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/review", json={"action": "approve"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    return t


def test_ordinary_user_can_copy_a_published_template(client, auth_headers, designer_headers, admin_headers):
    t = _publish(client, designer_headers, admin_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/clone", json={"name": "My copy"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "draft" and c["name"] == "My copy"
    assert c["source_template_id"] == t["id"]
    assert c["id"] != t["id"]
    # the original is untouched and still published
    orig = client.get(f"{PREFIX}/templates/{t['id']}", headers=designer_headers).json()
    assert orig["status"] == "published" and orig["name"] == t["name"]


def test_ordinary_user_cannot_copy_someone_elses_unpublished_template(client, auth_headers, designer_headers):
    t = _create_template(client, designer_headers)  # a draft
    r = client.post(f"{PREFIX}/templates/{t['id']}/clone", json={}, headers=auth_headers)
    assert r.status_code == 403


def test_user_can_copy_their_own_draft(client, auth_headers):
    t = _create_template(client, auth_headers)
    r = client.post(f"{PREFIX}/templates/{t['id']}/clone", json={}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["source_template_id"] == t["id"]


def test_copy_of_a_copy_keeps_pointing_at_its_direct_parent(client, auth_headers, designer_headers, admin_headers):
    t = _publish(client, designer_headers, admin_headers)
    c1 = client.post(f"{PREFIX}/templates/{t['id']}/clone", json={}, headers=auth_headers).json()
    c2 = client.post(f"{PREFIX}/templates/{c1['id']}/clone", json={}, headers=auth_headers).json()
    assert c2["source_template_id"] == c1["id"]
