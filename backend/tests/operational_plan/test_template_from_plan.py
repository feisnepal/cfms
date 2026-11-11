"""A plan saved as a template must not carry the forest's own values (owner, 2026-10-17)."""
from app.services.operational_plan import no_data
from app.services.operational_plan.template_from_plan import build_template_tree, is_unedited, value_tokens


def _node(nid, content, **kw):
    return {"id": nid, "title_en": nid, "title_ne": nid, "content_type": "richtext", "content": content, "children": [], **kw}


VALUES = {"{{forest_name}}": "Rambhadevi CF", "{{district}}": "Kaski", "{{area_ha}}": "250.5", "{{ward}}": "7"}


def _resolve(text):
    for k, v in VALUES.items():
        text = text.replace(k, v)
    return text


def test_only_text_values_become_tokens_never_numbers():
    vals = value_tokens(["forest_name", "district", "area_ha", "ward", "chart:x"], _resolve)
    shown = dict(vals)
    assert shown == {"Rambhadevi CF": "{{forest_name}}", "Kaski": "{{district}}"} or shown == {"Kaski": "{{district}}", "Rambhadevi CF": "{{forest_name}}"}
    assert "250.5" not in shown and "7" not in shown
    assert vals[0][0] == "Rambhadevi CF"  # longest first


def test_a_value_with_no_data_is_not_treated_as_a_value():
    vals = value_tokens(["x"], lambda _t: no_data.marked("EN"))
    assert vals == []


def test_unedited_section_gets_the_templates_own_text_back():
    parent = [_node("a", "{{forest_name}} lies in {{district}}.")]
    plan = [_node("a", "Rambhadevi CF lies in Kaski.")]
    tree, rep = build_template_tree(plan, parent, value_tokens(["forest_name", "district"], _resolve))
    assert tree[0]["content"] == "{{forest_name}} lies in {{district}}."
    assert rep["restored"] == 1 and rep["edited"] == [] and rep["new"] == []


def test_unedited_still_recognised_when_the_data_changed_since():
    assert is_unedited("Old Name lies in Elsewhere.", "{{forest_name}} lies in {{district}}.")
    assert not is_unedited("Old Name sits in Elsewhere.", "{{forest_name}} lies in {{district}}.")


def test_edited_section_keeps_the_authors_words_but_loses_forest_names():
    parent = [_node("a", "{{forest_name}} lies in {{district}}.")]
    plan = [_node("a", "Rambhadevi CF is a hill forest in Kaski. Area 250.5 ha.")]
    tree, rep = build_template_tree(plan, parent, value_tokens(["forest_name", "district"], _resolve))
    assert tree[0]["content"] == "{{forest_name}} is a hill forest in {{district}}. Area 250.5 ha."
    assert rep["edited"] == [{"id": "a", "title": "a"}] and rep["values_turned_into_tokens"] == 2


def test_a_section_the_author_added_is_reported_as_new():
    parent = [_node("a", "x")]
    plan = [_node("a", "x"), _node("b", "Notes about Kaski")]
    tree, rep = build_template_tree(plan, parent, value_tokens(["district"], _resolve))
    assert tree[1]["content"] == "Notes about {{district}}"
    assert rep["new"] == [{"id": "b", "title": "b"}]


def test_children_are_walked_and_the_plan_is_not_mutated():
    parent = [_node("a", "{{district}}", children=[_node("a1", "in {{district}}")])]
    plan = [_node("a", "Kaski", children=[_node("a1", "in Kaski")])]
    before = repr(plan)
    tree, rep = build_template_tree(plan, parent, value_tokens(["district"], _resolve))
    assert tree[0]["children"][0]["content"] == "in {{district}}" and rep["restored"] == 2
    assert repr(plan) == before


def test_without_a_parent_everything_counts_as_new():
    tree, rep = build_template_tree([_node("a", "Kaski")], None, value_tokens(["district"], _resolve))
    assert tree[0]["content"] == "{{district}}" and rep["parent_found"] is False and len(rep["new"]) == 1


# ── through the API ──────────────────────────────────────────────────────────

def test_endpoint_saves_a_private_template_that_points_at_no_forest(client, auth_headers, db):
    from app.models.calculation import Calculation
    from app.models.op_template import OPTemplate
    from app.models.user import User

    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc = Calculation(user_id=user.id, uploaded_filename="x.csv", forest_name="Secret Forest Name")
    db.add(calc)
    db.commit()

    r = client.post("/api/operational-plans", json={"calculation_id": str(calc.id)}, headers=auth_headers)
    assert r.status_code == 201, r.text
    plan_id = r.json()["id"]
    # the premise: the stored plan really does carry this forest's name in place of the tokens
    assert "Secret Forest Name" in str(r.json()["tree"]), "premise failed: the plan did not bake the forest name in"

    r = client.post(f"/api/operational-plans/{plan_id}/save-as-my-template",
                    json={"name": "My version", "description": "d"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    t = body["template"]
    assert t["status"] == "draft" and t["name"] == "My version"
    row = db.get(OPTemplate, t["id"])
    assert row.created_by == user.id
    assert row.source_calculation_id is None, "a template must not point at a forest"
    assert "Secret Forest Name" not in str(row.tree), "the forest's own name leaked into the template"
    assert body["report"]["parent_found"] is True


def test_endpoint_refuses_another_users_plan(client, auth_headers, db):
    from app.models.calculation import Calculation
    from app.models.user import User

    other = User(email="someone-else@example.com", hashed_password="x", full_name="Other")
    db.add(other)
    db.commit()
    calc = Calculation(user_id=other.id, uploaded_filename="y.csv", forest_name="Not yours")
    db.add(calc)
    db.commit()
    from app.models.operational_plan import OperationalPlan

    plan = OperationalPlan(calculation_id=calc.id, sections={"tree": []}, plan_metadata={})
    db.add(plan)
    db.commit()
    r = client.post(f"/api/operational-plans/{plan.id}/save-as-my-template", json={"name": "x"}, headers=auth_headers)
    assert r.status_code == 403
