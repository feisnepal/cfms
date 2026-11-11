"""'Check my document': what an owner's edits would leave wrong in the printed plan."""
from unittest.mock import MagicMock

from app.services.operational_plan.plan_validity import broken_tokens, plan_validity


def _n(nid, content="", title="T", **kw):
    return {"id": nid, "type": "section", "title_en": title, "title_ne": title, "content_type": "richtext",
            "content": content, "children": [], "deleted": False, "hidden_in_export": False, **kw}


def test_well_formed_tokens_are_fine():
    assert broken_tokens("{{forest_name}} and {{chart:biomass}} and {{inline_table:0}}") == []


def test_spaced_unbalanced_and_lone_braces_are_found():
    assert broken_tokens("{{ forest_name }}")
    assert broken_tokens("{{forest_name}")
    assert broken_tokens("a {{ b")
    assert broken_tokens("x }} y")


def test_plain_text_with_single_braces_is_not_flagged():
    assert broken_tokens("set {a, b} of species") == []


def test_unknown_variable_and_broken_token_are_errors_with_the_section_title():
    tree = [_n("a", "{{forest_nam}} and {{ district }}", title="Intro")]
    r = plan_validity(MagicMock(), tree)
    codes = {(i["code"], i["title"]) for i in r["errors"]}
    assert ("unknown_token", "Intro") in codes and ("broken_token", "Intro") in codes
    assert r["ok"] is False


def test_hidden_and_removed_sections_are_not_reported():
    tree = [_n("a", "{{nope_nope}}", hidden_in_export=True), _n("b", "{{nope_two}}", deleted=True), _n("c", "fine text")]
    r = plan_validity(MagicMock(), tree)
    assert all(i["node_id"] not in ("a", "b") for i in r["errors"] + r["warnings"])


def test_children_of_a_hidden_section_are_not_reported():
    tree = [_n("a", "x", hidden_in_export=True, children=[_n("a1", "{{nope_nope}}")])]
    r = plan_validity(MagicMock(), tree)
    assert not any(i.get("node_id") == "a1" for i in r["errors"])


def test_empty_section_is_a_warning_not_an_error():
    r = plan_validity(MagicMock(), [_n("a", "")])
    assert any(i["code"] == "empty_section" for i in r["warnings"])


def test_endpoint_is_owner_only(client, auth_headers, db):
    from app.models.calculation import Calculation
    from app.models.user import User

    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc = Calculation(user_id=user.id, uploaded_filename="v.csv", forest_name="V")
    db.add(calc)
    db.commit()
    plan = client.post("/api/operational-plans", json={"calculation_id": str(calc.id)}, headers=auth_headers).json()
    r = client.get(f"/api/operational-plans/{plan['id']}/validity", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"ok", "errors", "warnings"}
