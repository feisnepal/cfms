"""A plan's text follows the forest's data until the user edits it (owner decision 2026-10-17)."""
from types import SimpleNamespace

from app.services.operational_plan import plan_live
from app.services.operational_plan.tree_models import TreeNode


def _res(values):
    def resolve(text):
        for k, v in values.items():
            text = text.replace("{{%s}}" % k, v)
        return text
    return resolve


def _node(content, **kw):
    return TreeNode(id="a", content=content, **kw)


def test_populating_remembers_the_template_text_and_marks_the_section_live():
    n = _node("Area {{area}} ha")
    plan_live.populate_node(n, _res({"area": "250"}))
    assert n.content == "Area 250 ha" and n.source_content == "Area {{area}} ha"
    assert plan_live.is_live(n)


def test_static_text_is_left_alone():
    n = _node("Just words.")
    plan_live.populate_node(n, _res({}))
    assert n.source_content is None and n.content == "Just words." and not plan_live.is_live(n)


def test_output_reads_a_live_section_fresh():
    n = _node("Area {{area}} ha")
    plan_live.populate_node(n, _res({"area": "250"}))
    plan_live.resolve_for_output([n], _res({"area": "300"}))  # the data changed since
    assert n.content == "Area 300 ha"


def test_an_edited_section_is_never_rewritten():
    n = _node("Area {{area}} ha")
    plan_live.populate_node(n, _res({"area": "250"}))
    n.content = "Area 250 ha, mostly sal."  # the user typed
    assert not plan_live.is_live(n)
    plan_live.resolve_for_output([n], _res({"area": "300"}))
    assert n.content == "Area 250 ha, mostly sal."


def test_variables_the_user_typed_into_their_own_text_still_resolve():
    n = _node("Area {{area}} ha")
    plan_live.populate_node(n, _res({"area": "250"}))
    n.content = "I write {{area}} myself"
    plan_live.resolve_for_output([n], _res({"area": "300"}))
    assert n.content == "I write 300 myself"


def test_update_values_refills_live_sections_and_keeps_edited_ones():
    live, mine = _node("A {{x}}"), _node("B {{x}}")
    for n in (live, mine):
        plan_live.populate_node(n, _res({"x": "1"}))
    mine.content = "B one, as I wrote it"
    plan_live.populate_node(live, _res({"x": "2"}))
    plan_live.populate_node(mine, _res({"x": "2"}))
    assert live.content == "A 2" and plan_live.is_live(live)
    assert mine.content == "B one, as I wrote it" and not plan_live.is_live(mine)


def test_restoring_the_exact_text_makes_a_section_live_again():
    n = _node("A {{x}}")
    plan_live.populate_node(n, _res({"x": "1"}))
    n.content = "something else"
    n.content = "A 1"
    assert plan_live.is_live(n)


def test_effective_tree_gives_live_sections_their_template_text_and_copies():
    live = {"id": "a", "content": "A 1", "source_content": "A {{x}}", "populated_hash": plan_live.content_hash("A 1"), "children": []}
    mine = {"id": "b", "content": "mine", "source_content": "B {{x}}", "populated_hash": plan_live.content_hash("B 1"), "children": []}
    old = {"id": "c", "content": "legacy 5", "children": [live]}
    tree = [old, mine]
    eff = plan_live.effective_tree(tree)
    assert eff[0]["children"][0]["content"] == "A {{x}}" and eff[1]["content"] == "mine" and eff[0]["content"] == "legacy 5"
    assert tree[0]["children"][0]["content"] == "A 1"  # the stored tree is untouched


def test_non_text_sections_are_not_tracked():
    n = SimpleNamespace(content="{{chart:x}}", content_type="chart", source_content=None, populated_hash=None)
    plan_live.populate_node(n, lambda t: t.upper())
    assert n.content == "{{chart:x}}"


# -- through the API -------------------------------------------------------------

def _plan(client, auth_headers, db, forest_name):
    from app.models.calculation import Calculation
    from app.models.user import User

    user = db.query(User).filter(User.email == "testuser@example.com").first()
    calc = Calculation(user_id=user.id, uploaded_filename="p.csv", forest_name=forest_name)
    db.add(calc)
    db.commit()
    r = client.post("/api/operational-plans", json={"calculation_id": str(calc.id)}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return calc, r.json()


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


def _clear_cache(db, calc):
    from app.models.op_data_cache import OpDataCache

    db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).delete()
    db.commit()


def test_a_new_plan_remembers_the_template_text(client, auth_headers, db):
    calc, plan = _plan(client, auth_headers, db, "Live Forest One")
    live = [n for n in _walk(plan["tree"]) if n.get("source_content")]
    assert live, "no section remembered its template text"
    assert all(plan_live.is_live_dict(n) for n in live)
    assert any("Live Forest One" in n["content"] for n in live)
    assert all("Live Forest One" not in n["source_content"] for n in live)


def test_the_preview_shows_the_new_value_after_the_data_changes(client, auth_headers, db):
    calc, plan = _plan(client, auth_headers, db, "Before The Rename")
    calc.forest_name = "After The Rename"
    db.commit()
    _clear_cache(db, calc)
    html = client.get(f"/api/operational-plans/{plan['id']}/render", headers=auth_headers).text
    body = html.split("</title>", 1)[-1]  # the <title> is the plan row's own copy of the name, a separate matter
    assert "After The Rename" in body and "Before The Rename" not in body


def test_an_edited_section_keeps_its_text_when_the_data_changes(client, auth_headers, db):
    calc, plan = _plan(client, auth_headers, db, "Edit Test Forest")
    target = next(n for n in _walk(plan["tree"]) if plan_live.is_live_dict(n) and "Edit Test Forest" in n["content"])
    mine = target["content"] + " My own sentence about the north slope."
    r = client.put(f"/api/operational-plans/{plan['id']}/tree/nodes/{target['id']}", json={"content": mine}, headers=auth_headers)
    assert r.status_code == 200, r.text
    calc.forest_name = "Renamed Forest"
    db.commit()
    _clear_cache(db, calc)
    html = client.get(f"/api/operational-plans/{plan['id']}/render/section/{target['id']}", headers=auth_headers).text
    assert "My own sentence about the north slope." in html and "Edit Test Forest" in html


def test_update_values_refreshes_stored_text_of_live_sections_only(client, auth_headers, db):
    calc, plan = _plan(client, auth_headers, db, "Refresh Forest Old")
    nodes = list(_walk(plan["tree"]))
    live_ids = [n["id"] for n in nodes if plan_live.is_live_dict(n) and "Refresh Forest Old" in n["content"]]
    edited_id = live_ids[0]
    text = "Typed by me: Refresh Forest Old stays."
    client.put(f"/api/operational-plans/{plan['id']}/tree/nodes/{edited_id}", json={"content": text}, headers=auth_headers)
    calc.forest_name = "Refresh Forest New"
    db.commit()
    _clear_cache(db, calc)
    r = client.post(f"/api/operational-plans/{plan['id']}/auto-populate", headers=auth_headers)
    assert r.status_code == 200, r.text
    after = {n["id"]: n for n in _walk(r.json()["tree"])}
    assert after[edited_id]["content"] == text
    refreshed = [i for i in live_ids[1:] if "Refresh Forest New" in after[i]["content"]]
    assert refreshed, "no live section was refreshed"


def test_the_readiness_check_sees_no_data_in_sections_that_were_printed_with_it(client, auth_headers, db):
    from app.services.operational_plan.plan_readiness import plan_readiness
    from app.models.operational_plan import OperationalPlan

    calc, plan = _plan(client, auth_headers, db, "Readiness Forest")
    row = db.get(OperationalPlan, plan["id"])
    out = plan_readiness(db, calc.id, row)
    # the default template has variables a brand-new forest has no data for; before plan_live.py none were reported
    assert out["total"] > 0 and len(out["missing"]) > 0
