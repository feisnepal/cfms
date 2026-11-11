"""OP preview/render — token-preserving mode + non-destructive template preview.

OP_TEMPLATE_MANAGEMENT_PLAN.md T2:
  - VariableResolver(render_mode="tokens") leaves every {{token}} verbatim.
  - GET /{plan_id}/render (alias of /preview) + ?mode=values|tokens, read-only.
  - GET /templates/{id}/preview?calculation_id= renders a template against a
    forest without creating a plan.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.calculation import Calculation
from app.models.operational_plan import OperationalPlan
from app.models.user import User, UserRole
from app.services.operational_plan.variable_resolver import VariableResolver

PREFIX = "/api/v1/operational-plans"
_PW = "TestPass123!"


def _uniq(p: str) -> str:
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


# ── resolver unit ───────────────────────────────────────────────────────


class _StubPlan:
    plan_metadata: dict = {}


def _resolver(mode: str) -> VariableResolver:
    return VariableResolver(
        db=None, calculation_id=uuid.uuid4(), plan=_StubPlan(), render_mode=mode
    )


def test_render_mode_defaults_to_values():
    r = VariableResolver(db=None, calculation_id=uuid.uuid4(), plan=_StubPlan())
    assert r.render_mode == "values"


def test_tokens_mode_leaves_content_verbatim():
    src = "क्षेत्रफल {{total_area_hectares}} हे. — {{forest_name}} {{chart:species_pie}}"
    assert _resolver("tokens").resolve_node_content(src) == src


def test_tokens_mode_never_touches_the_database():
    # db=None would raise on any query; tokens mode must short-circuit.
    _resolver("tokens").resolve_node_content("{{forest_name}} {{blocks_count}}")


# ── endpoint: mode validation (runs before any DB lookup) ────────────────


def test_render_alias_rejects_bad_mode(client, db):
    headers, _ = _user(client, db)
    r = client.get(f"{PREFIX}/{uuid.uuid4()}/render?mode=sideways", headers=headers)
    assert r.status_code == 422, r.text


def test_template_preview_rejects_bad_mode(client, db):
    headers, _ = _user(client, db)
    r = client.get(
        f"{PREFIX}/templates/{uuid.uuid4()}/preview"
        f"?calculation_id={uuid.uuid4()}&mode=nope",
        headers=headers,
    )
    assert r.status_code == 422, r.text


# ── endpoint: full render, tokens vs values ─────────────────────────────


@pytest.fixture()
def plan_with_forest(client, db):
    headers, u = _user(client, db, prefix="owner")
    calc = Calculation(user_id=u.id, forest_name=f"CF {uuid.uuid4().hex[:6]}")
    db.add(calc)
    db.flush()
    plan = OperationalPlan(
        calculation_id=calc.id,
        forest_name=calc.forest_name,
        created_by=u.id,
        sections={
            "tree": [
                {
                    "id": "c",
                    "type": "preamble",
                    "title_ne": "आवरण",
                    "content": "{{forest_name}}",
                    "is_cover": True,
                    "children": [],
                },
                {
                    "id": "toc",
                    "type": "toc",
                    "title_ne": "विषयसूची",
                    "content": "",
                    "children": [],
                },
                {
                    "id": "s1",
                    "type": "section",
                    "title_ne": "परिचय",
                    "content": "यस वनको नाम {{forest_name}} हो।",
                    "children": [],
                },
            ]
        },
        plan_metadata={"language": "NP"},
    )
    db.add(plan)
    db.commit()
    return headers, str(plan.id)


def test_render_tokens_keeps_braces_values_does_not(client, plan_with_forest):
    headers, pid = plan_with_forest

    rt = client.get(f"{PREFIX}/{pid}/render?mode=tokens", headers=headers)
    assert rt.status_code == 200, rt.text
    assert "{{forest_name}}" in rt.text

    rv = client.get(f"{PREFIX}/{pid}/render?mode=values", headers=headers)
    assert rv.status_code == 200, rv.text
    assert "{{forest_name}}" not in rv.text

    # /preview is the same handler and still defaults to values
    rp = client.get(f"{PREFIX}/{pid}/preview", headers=headers)
    assert rp.status_code == 200
    assert "{{forest_name}}" not in rp.text


def test_render_section_alias_tokens_mode(client, plan_with_forest):
    headers, pid = plan_with_forest
    r = client.get(f"{PREFIX}/{pid}/render/section/s1?mode=tokens", headers=headers)
    assert r.status_code == 200, r.text
    assert "{{forest_name}}" in r.text


def test_template_preview_node_id_renders_one_section(client, db, plan_with_forest):
    """The designer's in-editor section preview: ?node_id= renders just that
    subtree against a real forest, no plan created."""
    headers, pid = plan_with_forest
    plan = db.query(OperationalPlan).filter(OperationalPlan.id == pid).one()
    calc_id = str(plan.calculation_id)

    dh, _ = _user(client, db, UserRole.TEMPLATE_DESIGNER, "designer")
    sysr = client.get(f"{PREFIX}/templates/system", headers=dh)
    tid = sysr.json()["template"]["id"]
    tree = sysr.json()["template"]["tree"]

    # first real section node
    def _first_section(nodes):
        for n in nodes:
            if n.get("type") == "section":
                return n
            r = _first_section(n.get("children") or [])
            if r:
                return r
        return None

    sec = _first_section(tree)
    assert sec is not None

    r = client.get(
        f"{PREFIX}/templates/{tid}/preview"
        f"?calculation_id={calc_id}&node_id={sec['id']}&mode=tokens",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert sec["title_ne"] in r.text

    r2 = client.get(
        f"{PREFIX}/templates/{tid}/preview"
        f"?calculation_id={calc_id}&node_id=no-such-node",
        headers=headers,
    )
    assert r2.status_code == 404, r2.text


def test_template_preview_creates_no_plan(client, db, plan_with_forest):
    """A designer previews a published template against someone's forest;
    no operational_plans row appears for that calc beyond the one already there."""
    headers, pid = plan_with_forest
    plan = db.query(OperationalPlan).filter(OperationalPlan.id == pid).one()
    calc_id = str(plan.calculation_id)

    dh, _ = _user(client, db, UserRole.TEMPLATE_DESIGNER, "designer")
    # a published template to preview — reuse the system template
    sysr = client.get(f"{PREFIX}/templates/system", headers=dh)
    assert sysr.status_code == 200
    tid = sysr.json()["template"]["id"]

    before = db.query(OperationalPlan).count()
    r = client.get(
        f"{PREFIX}/templates/{tid}/preview?calculation_id={calc_id}&mode=tokens",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert "{{" in r.text  # tokens mode
    db.expire_all()
    assert db.query(OperationalPlan).count() == before
