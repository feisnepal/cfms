"""OP multi-template — Phase 3: template-owned cover page.

See OP_MULTI_TEMPLATE_PLAN.md §3.9.
"""
from __future__ import annotations

import uuid

import pytest

from app.models.user import User, UserRole
from app.services.operational_plan.cover import (
    ensure_cover_node, partition_cover, find_cover_node,
)

PREFIX = "/api/v1/operational-plans"


# ── cover.py unit ────────────────────────────────────────────────────────

def _n(nid, ntype="section", **kw):
    return {"id": nid, "type": ntype, "title_ne": nid, "content": "", "children": [], **kw}


def test_ensure_cover_promotes_first_preamble():
    tree = [_n("p1", "preamble"), _n("s1"), _n("s2")]
    out = ensure_cover_node(tree, "brief")
    assert out[0]["is_cover"] is True
    assert out[1].get("page_break_before") is True
    assert sum(1 for x in out if x.get("is_cover")) == 1


def test_ensure_cover_prepends_when_no_preamble():
    tree = [_n("s1"), _n("s2")]
    out = ensure_cover_node(tree, "scientific")
    assert out[0]["is_cover"] is True
    assert out[0]["id"] == "node_cover"
    assert len(out) == 3


def test_ensure_cover_dedupes_multiple():
    tree = [_n("c1", "preamble", is_cover=True), _n("c2", "preamble", is_cover=True), _n("s1")]
    out = ensure_cover_node(tree, None)
    assert [x.get("is_cover", False) for x in out] == [True, False, False]


def test_ensure_cover_idempotent():
    tree = [_n("c1", "preamble", is_cover=True), _n("s1", page_break_before=True)]
    before = [dict(x) for x in tree]
    out = ensure_cover_node(tree, None)
    assert [x.get("is_cover", False) for x in out] == [x.get("is_cover", False) for x in before]
    assert sum(1 for x in out if x.get("is_cover")) == 1


def test_partition_cover_splits_top_level_only():
    tree = [_n("c", "preamble", is_cover=True), _n("s1"), _n("s2")]
    cover, body = partition_cover(tree)
    assert cover["id"] == "c"
    assert [b["id"] for b in body] == ["s1", "s2"]
    assert find_cover_node(body) is None


# ── validation: missing cover is now an error ────────────────────────────

def _uniq(p):
    return f"{p}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture()
def designer_headers(client, db):
    email = _uniq("designer")
    rr = client.post("/api/auth/register", json={"email": email, "password": "TestPass123!", "full_name": "T D"})
    assert rr.status_code in (200, 201), rr.text
    u = db.query(User).filter(User.email == email).first()
    u.role = UserRole.TEMPLATE_DESIGNER
    db.commit()
    r = client.post("/api/auth/login", json={"email": email, "password": "TestPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _tree_no_cover():
    return [
        {"id": "n_toc", "type": "toc", "title_ne": "विषयसूची", "content": "", "children": []},
        {"id": "n_1", "type": "section", "title_ne": "परिचय",
         "content": "{{forest_name}}", "children": []},
    ]


def test_create_template_auto_adds_cover(client, designer_headers):
    h = designer_headers
    r = client.post(f"{PREFIX}/templates", json={
        "name": f"t-{uuid.uuid4().hex[:6]}", "description": "x", "tree": _tree_no_cover(),
    }, headers=h)
    assert r.status_code == 201, r.text
    tree = r.json()["tree"]
    assert sum(1 for n in tree if n.get("is_cover")) == 1


def test_validation_errors_when_cover_removed(client, designer_headers):
    h = designer_headers
    created = client.post(f"{PREFIX}/templates", json={
        "name": f"t-{uuid.uuid4().hex[:6]}", "description": "x", "tree": _tree_no_cover(),
    }, headers=h).json()
    # strip every is_cover flag and save
    stripped = []
    for n in created["tree"]:
        n = dict(n)
        n.pop("is_cover", None)
        n["is_cover"] = False
        stripped.append(n)
    client.put(f"{PREFIX}/templates/{created['id']}", json={"tree": stripped}, headers=h)

    r = client.post(f"{PREFIX}/templates/{created['id']}/validate", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert "no_cover_node" in {e["code"] for e in body["errors"]}

    # ...and submit is blocked
    r = client.post(f"{PREFIX}/templates/{created['id']}/submit", headers=h)
    assert r.status_code == 422
    assert "no_cover_node" in {i["code"] for i in r.json()["detail"]["issues"]}


# ── DOCX build uses the cover node ───────────────────────────────────────

def test_build_op_document_renders_cover_node(monkeypatch):
    from app.services.operational_plan import op_docx_builder as B
    from app.services.operational_plan.tree_models import TreeNode

    calls = {"builtin": 0, "node": 0, "walked": None}
    monkeypatch.setattr(B, "_add_cover_page", lambda *a, **k: calls.__setitem__("builtin", calls["builtin"] + 1))
    orig_node = B._add_cover_node_page
    monkeypatch.setattr(B, "_add_cover_node_page",
                        lambda *a, **k: (calls.__setitem__("node", calls["node"] + 1), orig_node(*a, **k))[1])
    monkeypatch.setattr(B, "_add_toc_field", lambda *a, **k: None)
    monkeypatch.setattr(B, "_build_table_cache", lambda *a, **k: {})
    monkeypatch.setattr(B, "_build_calc_cache", lambda *a, **k: {})
    monkeypatch.setattr(B, "_walk_tree",
                        lambda doc, nodes, *a, **k: calls.__setitem__("walked", [n.id for n in nodes]))

    class _R:
        def get_raw_data(self):
            return {"basic_info": {"forest_name": "Test CF"}}

    tree = [
        TreeNode.from_dict({"id": "c", "type": "preamble", "title_ne": "आवरण",
                            "content": "Test CF\nSindhuli", "is_cover": True, "children": []}),
        TreeNode.from_dict({"id": "s1", "type": "section", "title_ne": "परिचय",
                            "content": "body text", "children": []}),
    ]
    buf = B.build_op_document(
        plan={"forest_name": "Test CF", "plan_metadata": {}},
        tree=tree, resolver=_R(), calculation_id=uuid.uuid4(), db=None,
    )
    assert buf.getbuffer().nbytes > 0
    assert calls["node"] == 1 and calls["builtin"] == 0
    # the cover node is NOT walked as a body section
    assert calls["walked"] == ["s1"]
