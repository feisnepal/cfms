"""Sharing a template: who sees it, who may copy it, what stops it being shared, who grants trust (owner, 2026-10-16/17)."""
import uuid

import pytest

from app.models.calculation import Calculation
from app.models.organization import Organization
from app.models.user import User, UserRole
from tests.test_op_template_lifecycle import (
    PREFIX, _PW, _create_template, _login, _tree, _uniq, _user_with_role,
)

LONG_DESC = "A hill-forest plan layout with the chapters a small user group usually needs; safe to use for any forest."


def _user(client, db, prefix="u", org=None):
    email = _uniq(prefix)
    r = client.post("/api/auth/register", json={"email": email, "password": _PW, "full_name": "Person " + prefix})
    assert r.status_code in (200, 201), r.text
    u = db.query(User).filter(User.email == email).first()
    if org is not None:
        u.organization_id = org.id
    db.commit()
    return _login(client, email), u


def _org(db, name=None):
    o = Organization(name=name or f"DFO {uuid.uuid4().hex[:6]}", contact_email="dfo@example.com")
    db.add(o)
    db.commit()
    return o


def _share(client, headers, tid, scope="public", license="cc_by"):
    return client.post(f"{PREFIX}/templates/{tid}/share", json={"scope": scope, "license": license}, headers=headers)


def _ids(client, headers):
    r = client.get(f"{PREFIX}/templates/public", headers=headers)
    assert r.status_code == 200, r.text
    return {t["id"] for t in r.json()["templates"]}


@pytest.fixture()
def admin_headers(client, db):
    return _user_with_role(client, db, UserRole.SUPER_ADMIN, "super")


def test_sharing_public_publishes_at_once_as_community_and_everyone_sees_it(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    assert t["share_scope"] == "private" and t["tier"] == "community"
    assert t["id"] not in _ids(client, other)

    r = _share(client, author, t["id"], "public")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "published" and body["share_scope"] == "public" and body["tier"] == "community"
    assert body["license"] == "cc_by" and body["approved_by"] is None
    assert t["id"] in _ids(client, other)


def test_private_again_takes_it_off_the_shelf(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    r = _share(client, author, t["id"], "private")
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["share_scope"] == "private"
    assert t["id"] not in _ids(client, other)
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=other).status_code == 403


def test_office_scope_is_visible_only_to_the_same_office(client, db):
    dfo, other_dfo = _org(db), _org(db)
    author, _ = _user(client, db, "author", dfo)
    colleague, _ = _user(client, db, "colleague", dfo)
    stranger, _ = _user(client, db, "stranger", other_dfo)
    nobody, _ = _user(client, db, "nobody")
    t = _create_template(client, author, description=LONG_DESC)
    assert _share(client, author, t["id"], "office").status_code == 200
    assert t["id"] in _ids(client, colleague)
    assert t["id"] not in _ids(client, stranger)
    assert t["id"] not in _ids(client, nobody)
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=stranger).status_code == 403


def test_office_scope_needs_an_office(client, db):
    author, _ = _user(client, db, "author")  # belongs to no office
    t = _create_template(client, author, description=LONG_DESC)
    r = _share(client, author, t["id"], "office")
    assert r.status_code >= 400


def test_view_only_licence_lets_others_use_but_not_copy(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public", "view_only")
    assert client.post(f"{PREFIX}/templates/{t['id']}/clone", json={}, headers=other).status_code == 403
    assert client.post(f"{PREFIX}/templates/{t['id']}/clone", json={}, headers=author).status_code == 200


def test_cc_by_licence_allows_copying(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public", "cc_by")
    r = client.post(f"{PREFIX}/templates/{t['id']}/clone", json={}, headers=other)
    assert r.status_code == 200 and r.json()["source_template_id"] == t["id"]
    assert r.json()["share_scope"] == "private"  # a copy starts private


def test_only_the_author_can_share(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    assert _share(client, other, t["id"], "public").status_code == 403


def test_a_private_template_cannot_be_used_to_build_a_plan_by_someone_else(client, db):
    author, _ = _user(client, db, "author")
    other, other_user = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    calc = Calculation(user_id=other_user.id, uploaded_filename="o.csv", forest_name="Other Forest")
    db.add(calc)
    db.commit()
    r = client.post(f"{PREFIX}?template_id={t['id']}", json={"calculation_id": str(calc.id)}, headers=other)
    assert r.status_code == 403, r.text


# -- the publish check ---------------------------------------------------------

def test_short_description_stops_sharing(client, db):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description="too short")
    r = _share(client, author, t["id"], "public")
    assert r.status_code == 422
    assert "description_short" in {i["code"] for i in r.json()["detail"]["issues"]}


def test_a_forest_name_inside_the_text_stops_sharing(client, db):
    author, author_user = _user(client, db, "author")
    db.add(Calculation(user_id=author_user.id, uploaded_filename="s.csv", forest_name="Sundar Community Forest"))
    db.commit()
    tree = _tree()
    tree[2]["content"] = "Sundar Community Forest lies in the hills. {{total_area_hectares}}"
    t = _create_template(client, author, description=LONG_DESC, tree=tree)
    r = _share(client, author, t["id"], "public")
    assert r.status_code == 422
    issue = [i for i in r.json()["detail"]["issues"] if i["code"] == "forest_name_inside"][0]
    assert issue["name"] == "Sundar Community Forest"


def test_publish_check_endpoint_reports_without_sharing(client, db):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    r = client.post(f"{PREFIX}/templates/{t['id']}/publish-check", headers=author)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=author).json()["status"] == "draft"


def test_typed_numbers_are_a_warning_not_a_block(client, db):
    author, _ = _user(client, db, "author")
    tree = _tree()
    tree[2]["content"] = "The forest covers 250.5 hectares. {{total_area_hectares}}"
    t = _create_template(client, author, description=LONG_DESC, tree=tree)
    chk = client.post(f"{PREFIX}/templates/{t['id']}/publish-check", headers=author).json()
    assert chk["ok"] is True and "typed_numbers" in {w["code"] for w in chk["warnings"]}
    assert _share(client, author, t["id"], "public").status_code == 200


# -- trust ---------------------------------------------------------------------

def test_only_the_super_admin_grants_verified(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    assert client.put(f"{PREFIX}/templates/{t['id']}/tier", json={"tier": "verified"}, headers=author).status_code == 403
    r = client.put(f"{PREFIX}/templates/{t['id']}/tier", json={"tier": "verified"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["tier"] == "verified"


def test_a_private_template_cannot_be_made_verified(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    r = client.put(f"{PREFIX}/templates/{t['id']}/tier", json={"tier": "official"}, headers=admin_headers)
    assert r.status_code >= 400


def test_the_authors_edit_drops_verified_back_to_community(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    client.put(f"{PREFIX}/templates/{t['id']}/tier", json={"tier": "verified"}, headers=admin_headers)
    r = client.put(f"{PREFIX}/templates/{t['id']}", json={"name": "A new name"}, headers=author)
    assert r.status_code == 200, r.text
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=author).json()["tier"] == "community"


def test_the_super_admins_approval_makes_it_verified(client, db, admin_headers):
    designer = _user_with_role(client, db, UserRole.TEMPLATE_DESIGNER, "designer")
    t = _create_template(client, designer)
    client.post(f"{PREFIX}/templates/{t['id']}/submit", headers=designer)
    r = client.post(f"{PREFIX}/templates/{t['id']}/review", json={"action": "approve"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["tier"] == "verified"


# -- credit chain ---------------------------------------------------------------

def test_lineage_lists_the_original_first_and_names_only_shared_authors(client, db):
    a, _ = _user(client, db, "alice")
    b, _ = _user(client, db, "bob")
    c, _ = _user(client, db, "carol")
    t1 = _create_template(client, a, description=LONG_DESC)
    _share(client, a, t1["id"], "public")
    t2 = client.post(f"{PREFIX}/templates/{t1['id']}/clone", json={"name": "Bob's version"}, headers=b).json()
    # Bob keeps his copy private; Carol copies Alice's original, so her chain is Alice -> Carol
    t3 = client.post(f"{PREFIX}/templates/{t1['id']}/clone", json={"name": "Carol's version"}, headers=c).json()
    _share(client, c, t3["id"], "public")

    chain = client.get(f"{PREFIX}/templates/{t3['id']}/lineage", headers=a).json()["chain"]
    assert [x["name"] for x in chain] == [t1["name"], "Carol's version"]
    assert chain[0]["author_name"] == "Person alice" and chain[1]["author_name"] == "Person carol"

    # a viewer who cannot see Bob's private copy sees a gap, not his name
    t4 = client.post(f"{PREFIX}/templates/{t2['id']}/clone", json={"name": "Dave"}, headers=b).json()
    _share(client, b, t4["id"], "public")
    chain = client.get(f"{PREFIX}/templates/{t4['id']}/lineage", headers=c).json()["chain"]
    assert chain[0]["name"] == t1["name"]
    assert chain[1]["visible"] is False and chain[1]["name"] is None and chain[1]["author_name"] is None


def test_author_name_appears_on_shared_templates_only(client, db):
    a, _ = _user(client, db, "alice")
    other, _ = _user(client, db, "other")
    t = _create_template(client, a, description=LONG_DESC)
    mine = {x["id"]: x for x in client.get(f"{PREFIX}/templates?scope=mine", headers=a).json()["templates"]}
    assert mine[t["id"]]["author_name"] == "Person alice"  # the author sees their own
    _share(client, a, t["id"], "public")
    seen = {x["id"]: x for x in client.get(f"{PREFIX}/templates/public", headers=other).json()["templates"]}
    assert seen[t["id"]]["author_name"] == "Person alice"


def test_credit_line_text(client, db):
    from uuid import UUID

    from app.services.operational_plan.template_credit import credit_line

    a, _ = _user(client, db, "alice")
    b, _ = _user(client, db, "bob")
    t1 = _create_template(client, a, description=LONG_DESC, name="Hill plan")
    _share(client, a, t1["id"], "public")
    t2 = client.post(f"{PREFIX}/templates/{t1['id']}/clone", json={"name": "Hill plan, Kaski"}, headers=b).json()
    _share(client, b, t2["id"], "public")
    db.expire_all()
    assert credit_line(db, UUID(t2["id"]), "EN") == "Template: Hill plan (Person alice); adapted by Person bob"
    assert credit_line(db, None, "EN") == ""


def test_credit_line_switch_is_the_plan_owners_and_off_by_default(client, db):
    owner, owner_user = _user(client, db, "owner")
    other, _ = _user(client, db, "other")
    calc = Calculation(user_id=owner_user.id, uploaded_filename="c.csv", forest_name="C")
    db.add(calc)
    db.commit()
    plan = client.post(PREFIX, json={"calculation_id": str(calc.id)}, headers=owner).json()
    assert not (plan["plan_metadata"] or {}).get("show_template_credit")
    assert client.put(f"{PREFIX}/{plan['id']}/credit-line", json={"show": True}, headers=other).status_code == 403
    r = client.put(f"{PREFIX}/{plan['id']}/credit-line", json={"show": True}, headers=owner)
    assert r.status_code == 200 and r.json() == {"show": True}


# -- reports --------------------------------------------------------------------

def test_a_user_can_report_a_shared_template_and_only_once(client, db):
    author, _ = _user(client, db, "author")
    reader, _ = _user(client, db, "reader")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    r = client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "Copied from a government document"}, headers=reader)
    assert r.status_code == 201 and r.json()["already_reported"] is False
    r = client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "Copied from a government document"}, headers=reader)
    assert r.json()["already_reported"] is True


def test_you_cannot_report_your_own_or_an_unseen_template(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    assert client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "this is not right"}, headers=other).status_code == 403
    _share(client, author, t["id"], "public")
    assert client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "this is not right"}, headers=author).status_code == 400


def test_only_the_super_admin_reads_and_handles_reports(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    reader, _ = _user(client, db, "reader")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "wrong advice on slopes"}, headers=reader)
    assert client.get(f"{PREFIX}/templates/reports", headers=reader).status_code == 403
    listing = client.get(f"{PREFIX}/templates/reports", headers=admin_headers).json()
    mine = [x for x in listing["reports"] if x["template_id"] == t["id"]]
    assert len(mine) == 1 and mine[0]["reason"] == "wrong advice on slopes" and mine[0]["status"] == "open"
    assert client.put(f"{PREFIX}/templates/reports/{mine[0]['id']}", json={"action": "dismiss"}, headers=reader).status_code == 403


def test_unpublishing_from_a_report_takes_it_off_the_shelf_and_closes_all_its_reports(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    r1, _ = _user(client, db, "r1")
    r2, _ = _user(client, db, "r2")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "first complaint"}, headers=r1)
    client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "second complaint"}, headers=r2)
    reps = [x for x in client.get(f"{PREFIX}/templates/reports", headers=admin_headers).json()["reports"] if x["template_id"] == t["id"]]
    assert len(reps) == 2
    r = client.put(f"{PREFIX}/templates/reports/{reps[0]['id']}", json={"action": "unpublish", "note": "removed"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "actioned"
    assert t["id"] not in _ids(client, r1)
    left = [x for x in client.get(f"{PREFIX}/templates/reports", headers=admin_headers).json()["reports"] if x["template_id"] == t["id"]]
    assert left == []
    # the author still has it, as a private draft
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=author).json()["share_scope"] == "private"


def test_dismissing_a_report_leaves_the_template_up(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    reader, _ = _user(client, db, "reader")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    client.post(f"{PREFIX}/templates/{t['id']}/report", json={"reason": "I just dislike it"}, headers=reader)
    rep = [x for x in client.get(f"{PREFIX}/templates/reports", headers=admin_headers).json()["reports"] if x["template_id"] == t["id"]][0]
    assert client.put(f"{PREFIX}/templates/reports/{rep['id']}", json={"action": "dismiss", "note": "fine"}, headers=admin_headers).json()["status"] == "dismissed"
    assert t["id"] in _ids(client, reader)


# -- deleting ---------------------------------------------------------------------

def test_a_template_that_was_never_shared_is_really_deleted(client, db):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    r = client.delete(f"{PREFIX}/templates/{t['id']}", headers=author)
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=author).status_code == 404


def test_a_template_that_was_shared_is_withdrawn_not_deleted(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")  # this writes a version snapshot
    r = client.delete(f"{PREFIX}/templates/{t['id']}", headers=author)
    assert r.status_code == 200 and r.json()["status"] == "withdrawn", r.text
    # off everyone's shelf, still there for its author
    assert t["id"] not in _ids(client, other)
    assert client.get(f"{PREFIX}/templates/{t['id']}", headers=other).status_code == 403
    row = client.get(f"{PREFIX}/templates/{t['id']}", headers=author).json()
    assert row["status"] == "retired" and row["share_scope"] == "private"
    # asking again changes nothing
    assert client.delete(f"{PREFIX}/templates/{t['id']}", headers=author).json()["status"] == "withdrawn"


def test_withdrawing_the_original_keeps_its_author_on_every_copy(client, db):
    from uuid import UUID

    from app.services.operational_plan.template_credit import credit_line

    alice, _ = _user(client, db, "alice")
    bob, _ = _user(client, db, "bob")
    carol, _ = _user(client, db, "carol")
    t1 = _create_template(client, alice, description=LONG_DESC, name="Hill plan")
    _share(client, alice, t1["id"], "public")
    t2 = client.post(f"{PREFIX}/templates/{t1['id']}/clone", json={"name": "Hill plan, Kaski"}, headers=bob).json()
    _share(client, bob, t2["id"], "public")

    assert client.delete(f"{PREFIX}/templates/{t1['id']}", headers=alice).json()["status"] == "withdrawn"

    chain = client.get(f"{PREFIX}/templates/{t2['id']}/lineage", headers=carol).json()["chain"]
    assert [c["name"] for c in chain] == ["Hill plan", "Hill plan, Kaski"]
    assert chain[0]["author_name"] == "Person alice" and chain[0]["withdrawn"] is True
    assert chain[0]["id"] is None and chain[0]["openable"] is False  # the credit stays, the template cannot be opened
    db.expire_all()
    assert credit_line(db, UUID(t2["id"]), "EN") == "Template: Hill plan (Person alice); adapted by Person bob"


def test_a_template_with_copies_is_never_hard_deleted(client, db):
    # a template that has copies is never hard-deleted even if (somehow) it was not shared: the chain must not break
    from app.models.op_template import OPTemplate

    author, user = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    child = _create_template(client, author, description=LONG_DESC)
    row = db.get(OPTemplate, child["id"])
    row.source_template_id = t["id"]
    db.commit()
    r = client.delete(f"{PREFIX}/templates/{t['id']}", headers=author)
    assert r.json()["status"] == "withdrawn" and r.json()["copies"] == 1
    assert db.get(OPTemplate, t["id"]) is not None


def test_only_the_author_can_delete(client, db):
    author, _ = _user(client, db, "author")
    other, _ = _user(client, db, "other")
    t = _create_template(client, author, description=LONG_DESC)
    assert client.delete(f"{PREFIX}/templates/{t['id']}", headers=other).status_code == 403


def test_only_the_super_admin_can_delete_a_shared_template_permanently(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    bob, _ = _user(client, db, "bob")
    carol, _ = _user(client, db, "carol")
    t1 = _create_template(client, author, description=LONG_DESC, name="Hill plan")
    _share(client, author, t1["id"], "public")
    t2 = client.post(f"{PREFIX}/templates/{t1['id']}/clone", json={"name": "Hill plan, Kaski"}, headers=bob).json()
    _share(client, bob, t2["id"], "public")

    # the author cannot force it, only withdraw
    assert client.delete(f"{PREFIX}/templates/{t1['id']}?permanent=true", headers=author).status_code == 403
    assert client.get(f"{PREFIX}/templates/{t1['id']}", headers=author).status_code == 200

    r = client.delete(f"{PREFIX}/templates/{t1['id']}?permanent=true", headers=admin_headers)
    assert r.status_code == 200 and r.json()["status"] == "deleted_permanently" and r.json()["copies"] == 1, r.text
    assert client.get(f"{PREFIX}/templates/{t1['id']}", headers=admin_headers).status_code == 404

    # the copy still works; its chain now starts at the copy
    chain = client.get(f"{PREFIX}/templates/{t2['id']}/lineage", headers=carol).json()["chain"]
    assert [c["name"] for c in chain] == ["Hill plan, Kaski"]


def test_the_super_admin_without_the_flag_withdraws_like_anyone(client, db, admin_headers):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    _share(client, author, t["id"], "public")
    r = client.delete(f"{PREFIX}/templates/{t['id']}", headers=admin_headers)
    assert r.json()["status"] == "withdrawn"
