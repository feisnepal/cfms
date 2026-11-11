"""The section library: one chapter of a plan, saved and shared on its own (Phase 5)."""
from app.models.calculation import Calculation
from app.services.operational_plan import plan_live
from tests.test_op_template_sharing import LONG_DESC, PREFIX, _ids, _share, _user, admin_headers  # noqa: F401


def _forest_plan(client, db, headers, user, name):
    calc = Calculation(user_id=user.id, uploaded_filename="s.csv", forest_name=name)
    db.add(calc)
    db.commit()
    r = client.post(PREFIX, json={"calculation_id": str(calc.id)}, headers=headers)
    assert r.status_code == 201, r.text
    return calc, r.json()


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n.get("children") or [])


def _chapter_with_forest_name(plan, name):
    """A top-level chapter whose text carries the forest's name (it was a {{forest_name}} variable in the template)."""
    for n in plan["tree"]:
        if n.get("is_cover"):
            continue
        if any(name in (m.get("content") or "") for m in _walk([n])):
            return n
    raise AssertionError("no chapter mentions the forest")


def _save(client, headers, plan_id, node_id, name="My chapter", desc=LONG_DESC):
    return client.post(f"{PREFIX}/{plan_id}/sections/save", json={"node_id": node_id, "name": name, "description": desc}, headers=headers)


def _sections(client, headers, scope="published"):
    r = client.get(f"{PREFIX}/sections?scope={scope}", headers=headers)
    assert r.status_code == 200, r.text
    return {s["id"]: s for s in r.json()["sections"]}


def test_saving_a_chapter_keeps_the_variables_not_the_forests_values(client, db):
    me, user = _user(client, db, "author")
    calc, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    chapter = _chapter_with_forest_name(plan, "Quiet Valley Forest")

    r = _save(client, me, plan["id"], chapter["id"])
    assert r.status_code == 200, r.text
    sec = r.json()["section"]
    assert sec["item_type"] == "section" and sec["status"] == "draft" and sec["share_scope"] == "private"
    text = str(sec["tree"])
    assert "Quiet Valley Forest" not in text and "{{forest_name}}" in text
    assert [n["id"] for n in sec["tree"]] == [chapter["id"]]


def test_a_section_is_in_the_library_and_not_in_the_template_gallery(client, db):
    me, user = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    calc, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], _chapter_with_forest_name(plan, "Quiet Valley Forest")["id"]).json()["section"]

    assert sec["id"] in _sections(client, me, "mine")
    mine_templates = {t["id"] for t in client.get(f"{PREFIX}/templates?scope=mine", headers=me).json()["templates"]}
    assert sec["id"] not in mine_templates and sec["id"] not in _ids(client, me)
    assert sec["id"] not in _sections(client, other)

    assert _share(client, me, sec["id"], "public").status_code == 200
    assert sec["id"] in _sections(client, other)
    assert sec["id"] not in _ids(client, other)  # still not in the template gallery


def test_a_shared_section_can_be_inserted_into_another_users_plan_with_that_forests_values(client, db):
    me, user = _user(client, db, "author")
    other, other_user = _user(client, db, "other")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    chapter = _chapter_with_forest_name(plan, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], chapter["id"]).json()["section"]
    _share(client, me, sec["id"], "public")

    _, their_plan = _forest_plan(client, db, other, other_user, "Hilltop Forest")
    before = len(list(_walk(their_plan["tree"])))
    r = client.post(f"{PREFIX}/{their_plan['id']}/sections/insert", json={"section_id": sec["id"]}, headers=other)
    assert r.status_code == 200, r.text
    body = r.json()
    inserted = [n for n in body["tree"] if n["id"] in body["inserted"]]
    assert len(inserted) == 1 and inserted[0]["id"] != chapter["id"]
    texts = " ".join(m.get("content") or "" for m in _walk(inserted))
    assert "Hilltop Forest" in texts and "Quiet Valley Forest" not in texts
    assert len(list(_walk(body["tree"]))) > before
    # the new text follows the data like any other section
    assert any(plan_live.is_live_dict(m) for m in _walk(inserted))
    # and it can go in again: a fresh copy each time
    again = client.post(f"{PREFIX}/{their_plan['id']}/sections/insert", json={"section_id": sec["id"]}, headers=other).json()
    assert set(again["inserted"]).isdisjoint(body["inserted"])


def test_a_private_section_cannot_be_inserted_by_someone_else(client, db):
    me, user = _user(client, db, "author")
    other, other_user = _user(client, db, "other")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], _chapter_with_forest_name(plan, "Quiet Valley Forest")["id"]).json()["section"]
    _, their_plan = _forest_plan(client, db, other, other_user, "Hilltop Forest")
    r = client.post(f"{PREFIX}/{their_plan['id']}/sections/insert", json={"section_id": sec["id"]}, headers=other)
    assert r.status_code == 403


def test_view_only_licence_inserts_the_section_locked(client, db):
    me, user = _user(client, db, "author")
    other, other_user = _user(client, db, "other")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], _chapter_with_forest_name(plan, "Quiet Valley Forest")["id"]).json()["section"]
    _share(client, me, sec["id"], "public", "view_only")
    _, their_plan = _forest_plan(client, db, other, other_user, "Hilltop Forest")
    body = client.post(f"{PREFIX}/{their_plan['id']}/sections/insert", json={"section_id": sec["id"]}, headers=other).json()
    assert body["locked"] is True
    assert all(m["is_locked"] for m in _walk([n for n in body["tree"] if n["id"] in body["inserted"]]))
    # the author uses their own section freely
    mine = client.post(f"{PREFIX}/{plan['id']}/sections/insert", json={"section_id": sec["id"]}, headers=me).json()
    assert mine["locked"] is False


def test_a_template_is_not_a_section_and_a_section_is_not_a_template(client, db):
    me, user = _user(client, db, "author")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], _chapter_with_forest_name(plan, "Quiet Valley Forest")["id"]).json()["section"]
    calc2 = Calculation(user_id=user.id, uploaded_filename="t.csv", forest_name="Another")
    db.add(calc2)
    db.commit()
    r = client.post(f"{PREFIX}?template_id={sec['id']}", json={"calculation_id": str(calc2.id)}, headers=me)
    assert r.status_code == 400
    tid = client.get(f"{PREFIX}/templates?scope=published", headers=me).json()["templates"][0]["id"]
    r = client.post(f"{PREFIX}/{plan['id']}/sections/insert", json={"section_id": tid}, headers=me)
    assert r.status_code == 400


def test_saving_a_chapter_that_is_not_there_or_the_cover_is_refused(client, db):
    me, user = _user(client, db, "author")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    assert _save(client, me, plan["id"], "no-such-node").status_code == 404
    cover = next((n for n in plan["tree"] if n.get("is_cover")), None)
    if cover:
        assert _save(client, me, plan["id"], cover["id"]).status_code == 404


def test_the_publish_check_applies_to_sections_without_asking_for_a_cover_page(client, db):
    me, user = _user(client, db, "author")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    chapter = _chapter_with_forest_name(plan, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], chapter["id"]).json()["section"]
    chk = client.post(f"{PREFIX}/templates/{sec['id']}/publish-check", headers=me).json()
    assert chk["ok"] is True
    assert not {"no_cover_node", "no_toc_node"} & {i["code"] for i in chk["errors"] + chk["warnings"]}
    short = _save(client, me, plan["id"], chapter["id"], name="Short", desc="too short").json()["section"]
    r = _share(client, me, short["id"], "public")
    assert r.status_code == 422 and "description_short" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_a_shared_section_is_withdrawn_not_deleted_and_the_author_stays_credited(client, db):
    me, user = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    _, plan = _forest_plan(client, db, me, user, "Quiet Valley Forest")
    sec = _save(client, me, plan["id"], _chapter_with_forest_name(plan, "Quiet Valley Forest")["id"]).json()["section"]
    _share(client, me, sec["id"], "public")
    assert client.delete(f"{PREFIX}/templates/{sec['id']}", headers=me).json()["status"] == "withdrawn"
    assert sec["id"] not in _sections(client, other)
    assert sec["id"] in _sections(client, me, "mine")
