"""The "original updated" notice for a template copy: it is told, it may add the new sections, nothing of its own is lost."""
from tests.test_op_template_lifecycle import PREFIX, _create_template, _tree
from tests.test_op_template_sharing import LONG_DESC, _share, _user


def _new_section(nid="n_new", title="Fire lines"):
    return {"id": nid, "type": "section", "title_ne": title, "title_en": title, "content_type": "richtext",
            "content": "text", "children": []}


def _republish_with(client, headers, tid, extra):
    """The author takes the original off the shelf, adds sections, and shares it again: a new published version."""
    assert _share(client, headers, tid, "private").status_code == 200
    tree = _tree() + extra
    assert client.put(f"{PREFIX}/templates/{tid}", json={"tree": tree}, headers=headers).status_code == 200
    assert _share(client, headers, tid, "public").status_code == 200


def _setup(client, db):
    author, _ = _user(client, db, "author")
    copier, _ = _user(client, db, "copier")
    orig = _create_template(client, author, description=LONG_DESC)
    assert _share(client, author, orig["id"], "public").status_code == 200
    copy = client.post(f"{PREFIX}/templates/{orig['id']}/clone", json={}, headers=copier).json()
    return author, copier, orig, copy


def test_a_fresh_copy_has_no_update(client, db):
    _, copier, orig, copy = _setup(client, db)
    r = client.get(f"{PREFIX}/templates/{copy['id']}/parent-status", headers=copier)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_parent"] and body["parent_name"] == orig["name"]
    assert body["based_on_version"] == 1 and body["update_available"] is False and body["added"] == []


def test_new_sections_in_the_original_are_announced_and_added_without_touching_the_copy(client, db):
    author, copier, orig, copy = _setup(client, db)
    # the copier writes in their own copy and deletes nothing
    mine = _tree()
    mine[2]["content"] = "my own words"
    mine.append(_new_section("n_mine", "My chapter"))
    assert client.put(f"{PREFIX}/templates/{copy['id']}", json={"tree": mine}, headers=copier).status_code == 200

    _republish_with(client, author, orig["id"], [_new_section()])
    st = client.get(f"{PREFIX}/templates/{copy['id']}/parent-status", headers=copier).json()
    assert st["update_available"] is True and st["added"] == ["Fire lines"] and st["parent_version"] == 2

    r = client.post(f"{PREFIX}/templates/{copy['id']}/add-parent-updates", headers=copier)
    assert r.status_code == 200 and r.json()["added"] == ["Fire lines"]
    tree = client.get(f"{PREFIX}/templates/{copy['id']}", headers=copier).json()["tree"]
    ids = [n["id"] for n in tree]
    assert ids.count("n_new") == 1 and "n_mine" in ids
    assert next(n for n in tree if n["id"] == "n_1")["content"] == "my own words"

    again = client.get(f"{PREFIX}/templates/{copy['id']}/parent-status", headers=copier).json()
    assert again["update_available"] is False and again["based_on_version"] == 2


def test_a_section_the_copier_deleted_does_not_come_back(client, db):
    author, copier, orig, copy = _setup(client, db)
    without_intro = [n for n in _tree() if n["id"] != "n_1"]
    assert client.put(f"{PREFIX}/templates/{copy['id']}", json={"tree": without_intro}, headers=copier).status_code == 200
    _republish_with(client, author, orig["id"], [_new_section()])
    r = client.post(f"{PREFIX}/templates/{copy['id']}/add-parent-updates", headers=copier)
    assert r.json()["added"] == ["Fire lines"]
    ids = [n["id"] for n in client.get(f"{PREFIX}/templates/{copy['id']}", headers=copier).json()["tree"]]
    assert "n_1" not in ids and "n_new" in ids


def test_only_the_owner_of_the_copy_may_ask_or_merge(client, db):
    _, copier, orig, copy = _setup(client, db)
    other, _ = _user(client, db, "other")
    assert client.get(f"{PREFIX}/templates/{copy['id']}/parent-status", headers=other).status_code == 403
    assert client.post(f"{PREFIX}/templates/{copy['id']}/add-parent-updates", headers=other).status_code == 403


def test_a_template_with_no_original_says_so(client, db):
    author, _ = _user(client, db, "author")
    t = _create_template(client, author, description=LONG_DESC)
    assert client.get(f"{PREFIX}/templates/{t['id']}/parent-status", headers=author).json() == {"has_parent": False}
