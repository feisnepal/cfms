"""System Template — T1 (OP_TEMPLATE_MANAGEMENT_PLAN.md §3.1).

The one ``is_system`` op_templates row is:
  - rebuilt from the code-owned seed tree by migration 081 /
    ``scripts.rebuild_system_template`` (deterministic, idempotent),
  - always ``published`` and never removable — every lifecycle transition that
    would move it off ``published`` or out of the gallery is refused,
  - editable by super admin only,
  - readable by anyone via ``GET /templates/system`` with a seed-sync report.
"""

from __future__ import annotations

import re
import uuid

import pytest

from app.models.op_template import OPTemplate
from app.models.user import User, UserRole
from app.services.operational_plan.variable_registry import VARIABLE_REGISTRY
from scripts.rebuild_system_template import (
    _canonical,
    build_system_tree,
    rebuild_system_template,
)

PREFIX = "/api/v1/operational-plans"
_PW = "TestPass123!"
_SKIP = ("chart:", "map:", "table:", "thememap:", "opsmap:")


def _uniq(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


def _login(client, email: str) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": _PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user_with_role(client, db, role: UserRole, prefix: str) -> dict:
    email = _uniq(prefix)
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": _PW, "full_name": "Tester"},
    )
    assert r.status_code in (200, 201), r.text
    u = db.query(User).filter(User.email == email).first()
    u.role = role
    db.commit()
    return _login(client, email)


@pytest.fixture()
def admin_headers(client, db):
    return _user_with_role(client, db, UserRole.SUPER_ADMIN, "super")


@pytest.fixture()
def designer_headers(client, db):
    return _user_with_role(client, db, UserRole.TEMPLATE_DESIGNER, "designer")


def _tokens(nodes: list) -> set:
    out: set = set()
    for n in nodes or []:
        for m in re.finditer(r"\{\{([^}]+)\}\}", (n.get("content") or "")):
            out.add(m.group(1).strip())
        out |= _tokens(n.get("children") or [])
    return out


def _count_cover(nodes: list) -> int:
    return sum(1 for n in nodes or [] if isinstance(n, dict) and n.get("is_cover"))


# ── the row itself ───────────────────────────────────────────────────────


def _system_row(db) -> OPTemplate:
    row = (
        db.query(OPTemplate)
        .filter(OPTemplate.is_system.is_(True))
        .order_by(OPTemplate.updated_at.desc())
        .first()
    )
    assert row is not None, "migration 081 should have left an is_system row"
    return row


def test_system_row_is_published_and_matches_seed_tree(db):
    row = _system_row(db)
    assert row.status == "published"
    assert _canonical(row.tree) == _canonical(build_system_tree())
    assert _count_cover(row.tree) == 1


def test_system_row_uses_only_registered_tokens(db):
    row = _system_row(db)
    unknown = sorted(
        t
        for t in _tokens(row.tree)
        if t not in VARIABLE_REGISTRY
        and not t.startswith(_SKIP)
        and not t.endswith(":full")
    )
    assert unknown == [], f"System Template references unregistered tokens: {unknown}"


def test_build_system_tree_is_deterministic():
    assert _canonical(build_system_tree()) == _canonical(build_system_tree())


def test_rebuild_is_a_noop_once_synced(db):
    report = rebuild_system_template(db, dry_run=True)
    db.rollback()
    assert report["action"] == "noop"
    assert report["changed"] is False


# ── GET /templates/system ────────────────────────────────────────────────


def test_get_system_template_reports_in_sync(client, designer_headers):
    r = client.get(f"{PREFIX}/templates/system", headers=designer_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["template"]["is_system"] is True
    assert body["seed_sync"]["in_sync"] is True
    assert body["seed_sync"]["missing_sections"] == []
    assert body["seed_sync"]["unregistered_tokens"] == []


def test_get_system_template_readable_by_plain_user(client, db):
    headers = _user_with_role(client, db, UserRole.USER, "plain")
    r = client.get(f"{PREFIX}/templates/system", headers=headers)
    assert r.status_code == 200, r.text


# ── protection ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("action", ["submit", "unpublish", "deprecate", "retire"])
def test_lifecycle_transitions_refuse_the_system_template(
    client, admin_headers, db, action
):
    tid = str(_system_row(db).id)
    body = {"note": "x"} if action in ("retire",) else {}
    r = client.post(
        f"{PREFIX}/templates/{tid}/{action}", headers=admin_headers, json=body
    )
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "system_protected"


def test_designer_cannot_edit_the_system_template(client, designer_headers, db):
    tid = str(_system_row(db).id)
    r = client.put(
        f"{PREFIX}/templates/{tid}",
        headers=designer_headers,
        json={"description": "hijacked"},
    )
    assert r.status_code == 403, r.text


def test_system_template_cannot_be_deleted(client, admin_headers, db):
    tid = str(_system_row(db).id)
    r = client.delete(f"{PREFIX}/templates/{tid}", headers=admin_headers)
    assert r.status_code == 400, r.text


def test_super_admin_can_still_edit_the_system_template_tree(client, admin_headers, db):
    tid = str(_system_row(db).id)
    tree = build_system_tree()
    tree[-1]["content"] = (tree[-1].get("content") or "") + " — edited"
    r = client.put(
        f"{PREFIX}/templates/{tid}", headers=admin_headers, json={"tree": tree}
    )
    assert r.status_code == 200, r.text
    # restore so later tests / ordering see a synced row
    rebuild_system_template(db)
    db.commit()
