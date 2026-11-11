"""Forum F1 gate: the public read API and the write rules, through HTTP."""
import uuid

import pytest

from app.core import forum_rules as rules
from app.models.forum import ForumPost, ForumTag
from app.models.user import User, UserRole
from app.services.forum import ledger
from app.utils.auth import create_access_token

SEED_TAGS = ("map", "user-group", "fieldbook", "sampling", "field-inventory", "biodiversity", "household", "sfm", "cost-benefit",
             "operational-plan", "yearly-plan", "ntfp", "hazard", "mobile", "account")


@pytest.fixture(autouse=True)
def _empty_forum(db):
    """`client` commits and the test database lives for the whole session, so start every test from an empty forum with the seed tags."""
    from sqlalchemy import text

    db.execute(text("TRUNCATE forum_posts, forum_profiles, forum_actions, forum_reputation_events, forum_flags, forum_subscriptions, forum_notification_prefs, "
                    "forum_tag_marks, forum_tag_synonyms, forum_post_tags, forum_post_revisions CASCADE"))
    db.execute(text("DELETE FROM forum_tags WHERE name <> ALL(:seed)"), {"seed": list(SEED_TAGS)})
    db.execute(text("UPDATE forum_tags SET used_count = 0"))
    db.commit()
    yield


TITLE = "How do I print the boundary map?"
BODY = "I drew the boundary but the print map shows no labels. What should I check first?"
ANSWER = "Open the map variables page and tick the label option before exporting."


def _member(db, reputation=rules.FORUM_REP_NO_REVIEW, role=UserRole.USER):
    user = User(email=f"f{uuid.uuid4().hex[:10]}@test.com", full_name="Forum Member", role=role, hashed_password="x")
    db.add(user)
    db.flush()
    if reputation:
        ledger.apply_reputation(db, user.id, reputation, None)
    db.commit()
    return user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _ask(client, user, **over):
    body = {"title": TITLE, "body": BODY, "tags": ["map"], **over}
    return client.post("/api/v1/forum/questions", json=body, headers=_h(user))


def test_an_anonymous_reader_can_list_and_open_a_question(client, db):
    asker = _member(db)
    qid = _ask(client, asker).json()["id"]
    listing = client.get("/api/v1/forum/questions")
    assert listing.status_code == 200 and qid in [i["id"] for i in listing.json()["items"]]
    detail = client.get(f"/api/v1/forum/questions/{qid}")
    assert detail.status_code == 200
    assert detail.json()["question"]["title"] == TITLE and detail.json()["question"]["my_vote"] is None


def test_writing_needs_a_login(client, db):
    assert client.post("/api/v1/forum/questions", json={"title": TITLE, "body": BODY, "tags": ["map"]}).status_code in (401, 403)


def test_a_bad_token_is_refused_not_treated_as_anonymous(client):
    r = client.get("/api/v1/forum/questions", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_ask_validates_title_body_and_tags(client, db):
    user = _member(db)
    assert _ask(client, user, title="short").status_code == 422
    assert _ask(client, user, body="too short").status_code == 422
    assert _ask(client, user, tags=[]).status_code == 422
    assert _ask(client, user, tags=["a", "b", "c", "d", "e", "f"]).status_code == 422
    assert _ask(client, user, tags=["Bad Tag!"]).status_code == 422


def test_an_unknown_tag_needs_the_reputation_to_create_it(client, db):
    user = _member(db)
    assert _ask(client, user, tags=["brand-new-tag"]).status_code == 403
    rich = _member(db, reputation=rules.FORUM_REP_CREATE_TAG)
    assert _ask(client, rich, tags=["brand-new-tag"]).status_code == 201
    assert db.query(ForumTag).filter(ForumTag.name == "brand-new-tag").one().used_count == 1


def test_a_new_members_post_is_held_and_hidden_from_others(client, db):
    newcomer = _member(db, reputation=0)
    post = _ask(client, newcomer).json()
    assert post["pending_review"] is True
    qid = post["id"]
    assert client.get(f"/api/v1/forum/questions/{qid}").status_code == 404  # anonymous
    assert client.get(f"/api/v1/forum/questions/{qid}", headers=_h(_member(db))).status_code == 404  # another member
    assert client.get(f"/api/v1/forum/questions/{qid}", headers=_h(newcomer)).status_code == 200  # the author
    assert qid not in [i["id"] for i in client.get("/api/v1/forum/questions").json()["items"]]
    assert db.query(ForumTag).filter(ForumTag.name == "map").one().used_count == 0


def test_a_moderator_approves_a_held_post(client, db):
    newcomer = _member(db, reputation=0)
    qid = _ask(client, newcomer).json()["id"]
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    assert [p["id"] for p in client.get("/api/v1/forum/moderation/held", headers=_h(admin)).json()] == [qid]
    assert client.get("/api/v1/forum/moderation/held", headers=_h(_member(db))).status_code == 403
    # a held post is invisible to other members, so to them it does not exist
    assert client.post(f"/api/v1/forum/posts/{qid}/approve", headers=_h(_member(db))).status_code == 404
    assert client.post(f"/api/v1/forum/posts/{qid}/approve", headers=_h(newcomer)).status_code == 403  # the author cannot approve their own
    assert client.post(f"/api/v1/forum/posts/{qid}/approve", headers=_h(admin)).json()["pending_review"] is False
    assert client.get(f"/api/v1/forum/questions/{qid}").status_code == 200
    assert db.query(ForumTag).filter(ForumTag.name == "map").one().used_count == 1


def test_answer_accept_and_vote_flow(client, db):
    asker, answerer = _member(db), _member(db)
    voter = _member(db, reputation=rules.FORUM_REP_VOTE_UP)
    qid = _ask(client, asker).json()["id"]
    a = client.post(f"/api/v1/forum/questions/{qid}/answers", json={"body": ANSWER}, headers=_h(answerer))
    assert a.status_code == 201
    aid = a.json()["id"]
    # a second answer from the same person is refused
    assert client.post(f"/api/v1/forum/questions/{qid}/answers", json={"body": ANSWER}, headers=_h(answerer)).status_code == 422
    assert client.get(f"/api/v1/forum/questions/{qid}").json()["question"]["answer_count"] == 1

    up = client.post(f"/api/v1/forum/posts/{aid}/vote", json={"direction": "up"}, headers=_h(voter))
    assert up.status_code == 200 and up.json()["score"] == 1 and up.json()["my_vote"] == "up"
    assert client.post(f"/api/v1/forum/posts/{aid}/vote", json={"direction": "up"}, headers=_h(voter)).status_code == 422
    back = client.post(f"/api/v1/forum/posts/{aid}/vote", json={"direction": "none"}, headers=_h(voter))
    assert back.json()["score"] == 0 and back.json()["my_vote"] is None

    assert client.post(f"/api/v1/forum/answers/{aid}/accept", headers=_h(voter)).status_code == 403
    acc = client.post(f"/api/v1/forum/answers/{aid}/accept", headers=_h(asker))
    assert acc.status_code == 200 and acc.json()["accepted"] is True
    detail = client.get(f"/api/v1/forum/questions/{qid}").json()
    assert detail["answers"][0]["accepted"] is True


def test_answers_list_accepted_first_then_by_score(client, db):
    asker = _member(db)
    qid = _ask(client, asker).json()["id"]
    ids = []
    for _ in range(3):
        ids.append(client.post(f"/api/v1/forum/questions/{qid}/answers", json={"body": ANSWER}, headers=_h(_member(db))).json()["id"])
    voter = _member(db, reputation=rules.FORUM_REP_VOTE_UP)
    client.post(f"/api/v1/forum/posts/{ids[1]}/vote", json={"direction": "up"}, headers=_h(voter))
    client.post(f"/api/v1/forum/answers/{ids[2]}/accept", headers=_h(asker))
    order = [a["id"] for a in client.get(f"/api/v1/forum/questions/{qid}").json()["answers"]]
    assert order == [ids[2], ids[1], ids[0]]


def test_comments(client, db):
    asker = _member(db)
    qid = _ask(client, asker).json()["id"]
    assert client.post(f"/api/v1/forum/posts/{qid}/comments", json={"body": "hello there"}, headers=_h(asker)).status_code == 201
    stranger = _member(db, reputation=rules.FORUM_REP_NO_REVIEW)  # below the comment threshold
    assert client.post(f"/api/v1/forum/posts/{qid}/comments", json={"body": "hello there"}, headers=_h(stranger)).status_code == 403
    thread = client.get(f"/api/v1/forum/questions/{qid}").json()
    assert len(thread["comments"][qid]) == 1 and thread["question"]["comment_count"] == 1


def test_edit_writes_a_revision_and_only_the_author_or_the_reputable_may_edit(client, db):
    asker = _member(db)
    qid = _ask(client, asker).json()["id"]
    ok = client.patch(f"/api/v1/forum/posts/{qid}", json={"body": BODY + " (edited)", "summary": "clarified"}, headers=_h(asker))
    assert ok.status_code == 200 and "(edited)" in ok.json()["body_md"]
    assert client.patch(f"/api/v1/forum/posts/{qid}", json={"body": BODY + " hijack"}, headers=_h(_member(db))).status_code == 403
    post = db.get(ForumPost, uuid.UUID(qid))
    db.refresh(post)
    assert post.active_revision == 2 and len(post.revisions) == 2


def test_deleting_and_restoring(client, db):
    asker, answerer = _member(db), _member(db)
    qid = _ask(client, asker).json()["id"]
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    assert client.delete(f"/api/v1/forum/posts/{qid}", headers=_h(_member(db))).status_code == 403
    assert client.delete(f"/api/v1/forum/posts/{qid}", headers=_h(asker)).status_code == 200
    assert client.get(f"/api/v1/forum/questions/{qid}").status_code == 404
    assert db.query(ForumTag).filter(ForumTag.name == "map").one().used_count == 0
    # a deleted post is visible to moderators only: to the author it looks gone, and only a moderator can bring it back
    assert client.post(f"/api/v1/forum/posts/{qid}/restore", headers=_h(asker)).status_code == 404
    assert client.post(f"/api/v1/forum/posts/{qid}/restore", headers=_h(admin)).status_code == 200
    assert client.get(f"/api/v1/forum/questions/{qid}").status_code == 200
    # once it has an answer the author can no longer delete it
    client.post(f"/api/v1/forum/questions/{qid}/answers", json={"body": ANSWER}, headers=_h(answerer))
    assert client.delete(f"/api/v1/forum/posts/{qid}", headers=_h(asker)).status_code == 422


def test_list_filters_sorts_and_search(client, db):
    u = _member(db)
    a = _ask(client, u, title="Landslide map shows no classes at all", body="The hazard tab is empty for my forest, what now?", tags=["hazard"]).json()["id"]
    b = _ask(client, u, title="How to add sample plots to a block", body="I need to add plots by hand to one block of the forest.", tags=["sampling"]).json()["id"]
    c = _ask(client, u, title="समुदायिक वनको नक्सा कसरी छाप्ने", body="नक्सा छाप्दा सिमाना देखिँदैन, के गर्ने होला?", tags=["map"]).json()["id"]
    ids = lambda params: [i["id"] for i in client.get("/api/v1/forum/questions", params=params).json()["items"]]
    assert ids({"tag": "hazard"}) == [a]
    assert ids({"q": "plots"}) == [b]
    assert ids({"q": "नक्सा"}) == [c]
    assert set(ids({"sort": "unanswered"})) >= {a, b, c}
    assert ids({"sort": "newest"})[0] == c
    answerer = _member(db)
    client.post(f"/api/v1/forum/questions/{a}/answers", json={"body": ANSWER}, headers=_h(answerer))
    assert a not in ids({"sort": "unanswered"})
    # a search also finds a question through the text of its answer
    assert a in ids({"q": "label option"})
    assert ids({"mine": True}) == []  # anonymous: no 'mine'
    assert set(i["id"] for i in client.get("/api/v1/forum/questions", params={"mine": True}, headers=_h(u)).json()["items"]) == {a, b, c}


def test_html_in_a_post_is_escaped_in_the_response(client, db):
    u = _member(db)
    post = _ask(client, u, body="<script>alert(1)</script> and enough words to pass the length rule").json()
    assert "<script" not in post["body_html"] and "&lt;script&gt;" in post["body_html"]


def test_tags_endpoint_and_me(client, db):
    names = [t["name"] for t in client.get("/api/v1/forum/tags").json()]
    assert {"map", "ntfp", "operational-plan"} <= set(names)
    user = _member(db, reputation=42)
    me = client.get("/api/v1/forum/me", headers=_h(user)).json()
    assert me["reputation"] == 42 and me["is_moderator"] is False
