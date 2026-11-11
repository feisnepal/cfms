"""Forum F4 gate: flags (a report never hides anything), moderator resolution, closing and reopening, duplicates."""
import uuid

import pytest
from sqlalchemy import text

from app.core import forum_rules as rules
from app.models.forum import ForumProfile
from app.models.user import User, UserRole
from app.services.forum import ledger
from app.utils.auth import create_access_token

API = "/api/v1/forum"
BODY = "I drew the boundary but the print map shows no labels. What should I check first?"
ANSWER = "Open the layer menu and tick the label layer before printing the map."


@pytest.fixture(autouse=True)
def _empty_forum(db):
    db.execute(text("TRUNCATE forum_posts, forum_profiles, forum_actions, forum_reputation_events, forum_flags, forum_subscriptions, forum_notification_prefs, "
                    "forum_tag_marks, forum_tag_synonyms, forum_post_tags, forum_post_revisions, forum_attachments CASCADE"))
    db.execute(text("UPDATE forum_tags SET used_count = 0"))
    db.commit()
    yield


def _member(db, reputation=rules.FORUM_REP_FLAG, moderator=False):
    user = User(email=f"f{uuid.uuid4().hex[:10]}@test.com", full_name="Forum Member", role=UserRole.USER, hashed_password="x")
    db.add(user)
    db.flush()
    if reputation:
        ledger.apply_reputation(db, user.id, reputation, None)
    if moderator:
        ledger.get_profile(db, user.id).is_moderator = True
    db.commit()
    return user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _ask(client, user, title="How do I print the boundary map?"):
    r = client.post(f"{API}/questions", json={"title": title, "body": BODY, "tags": ["map"]}, headers=_h(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _rep(db, user):
    db.expire_all()
    return db.get(ForumProfile, user.id).reputation if db.get(ForumProfile, user.id) else 0


def _flag(client, who, post_id, reason="This is spam and sells something"):
    return client.post(f"{API}/posts/{post_id}/flag", json={"reason": reason}, headers=_h(who))


# ── flags ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_flag_leaves_the_post_visible_and_counts_for_moderators_only(client, db):
    author, flagger, mod = _member(db), _member(db), _member(db, moderator=True)
    q = _ask(client, author)
    r = _flag(client, flagger, q)
    assert r.status_code == 200 and r.json()["my_flag"] is True and r.json()["flag_count"] == 0   # a member never sees the count
    assert client.get(f"{API}/questions/{q}").status_code == 200                                   # still readable by anyone
    assert client.get(f"{API}/questions/{q}", headers=_h(mod)).json()["question"]["flag_count"] == 1


def test_who_may_flag(client, db):
    author = _member(db)
    q = _ask(client, author)
    assert _flag(client, _member(db, reputation=rules.FORUM_REP_FLAG - 1), q).status_code == 403   # not enough reputation
    assert _flag(client, author, q).status_code == 422                                              # not your own post
    assert _flag(client, _member(db), q, "no").status_code == 422                                   # a reason is needed
    assert client.post(f"{API}/posts/{q}/flag", json={"reason": "spam spam spam"}).status_code in (401, 403)  # anonymous
    twice = _member(db)
    assert _flag(client, twice, q).status_code == 200
    assert _flag(client, twice, q).status_code == 422                                               # one live flag per member


def test_a_member_has_a_daily_flag_limit(client, db):
    author, flagger = _member(db), _member(db)
    for i in range(rules.FORUM_MAX_FLAGS_PER_DAY):
        assert _flag(client, flagger, _ask(client, author, f"A question number {i} about the boundary map")).status_code == 200
    assert _flag(client, flagger, _ask(client, author, "One question more than the limit allows")).status_code == 422


def test_the_flagged_queue_is_for_moderators_and_orders_by_flag_count(client, db):
    author, mod = _member(db), _member(db, moderator=True)
    one, two = _ask(client, author, "A question that gets one flag only"), _ask(client, author, "A question that gets two flags in all")
    _flag(client, _member(db), one)
    _flag(client, _member(db), two)
    _flag(client, _member(db), two)
    assert client.get(f"{API}/moderation/flagged", headers=_h(_member(db))).status_code == 403
    queue = client.get(f"{API}/moderation/flagged", headers=_h(mod)).json()
    assert [i["post"]["id"] for i in queue] == [two, one]
    assert len(queue[0]["flags"]) == 2 and queue[0]["flags"][0]["reason"]


def test_dismissing_flags_costs_nobody_anything(client, db):
    author, mod = _member(db, reputation=20), _member(db, moderator=True)
    q = _ask(client, author)
    _flag(client, _member(db), q)
    r = client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "dismissed"}, headers=_h(mod))
    assert r.status_code == 200 and client.get(f"{API}/moderation/flagged", headers=_h(mod)).json() == []
    assert _rep(db, author) == 20
    assert client.get(f"{API}/questions/{q}", headers=_h(mod)).json()["question"]["flag_count"] == 0


def test_a_warning_costs_the_author_and_keeps_the_post(client, db):
    author, mod = _member(db, reputation=25), _member(db, moderator=True)
    q = _ask(client, author)
    _flag(client, _member(db), q)
    assert client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "user_warned"}, headers=_h(mod)).status_code == 200
    assert _rep(db, author) == 25 + rules.REP_FLAG_UPHELD
    assert client.get(f"{API}/questions/{q}").status_code == 200
    assert ledger.reputation_from_events(db, author.id) == _rep(db, author)


def test_deleting_through_a_flag_hides_the_post_and_costs_the_author(client, db):
    author, mod = _member(db, reputation=12), _member(db, moderator=True)
    q = _ask(client, author)
    _flag(client, _member(db), q)
    assert client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "deleted"}, headers=_h(mod)).status_code == 200
    assert client.get(f"{API}/questions/{q}").status_code == 404
    assert _rep(db, author) == max(0, 12 + rules.REP_FLAG_UPHELD)   # the balance never goes below zero
    assert ledger.reputation_from_events(db, author.id) == _rep(db, author)


def test_only_moderators_resolve_and_only_open_flags(client, db):
    author, mod = _member(db), _member(db, moderator=True)
    q = _ask(client, author)
    _flag(client, _member(db), q)
    assert client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "dismissed"}, headers=_h(_member(db))).status_code == 403
    assert client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "hidden"}, headers=_h(mod)).status_code == 422
    assert client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "dismissed"}, headers=_h(mod)).status_code == 200
    assert client.post(f"{API}/moderation/posts/{q}/resolve", json={"resolution": "dismissed"}, headers=_h(mod)).status_code == 422  # nothing left


def test_held_and_deleted_posts_cannot_be_flagged(client, db):
    author = _member(db)
    held = _ask(client, _member(db, reputation=0), "A held question nobody else may see yet")
    gone = _ask(client, author, "A question that will be deleted shortly")
    client.delete(f"{API}/posts/{gone}", headers=_h(author))
    flagger = _member(db)
    assert _flag(client, flagger, held).status_code == 404
    assert _flag(client, flagger, gone).status_code == 404


# ── closing ────────────────────────────────────────────────────────────────────────────────────────────────────

def _close(client, who, q, reason="off_topic", dup=None):
    body = {"reason": reason}
    if dup:
        body["duplicate_of"] = dup
    return client.post(f"{API}/questions/{q}/close", json=body, headers=_h(who))


def test_closing_stops_new_answers_and_reopening_allows_them(client, db):
    asker, other = _member(db), _member(db)
    q = _ask(client, asker)
    r = _close(client, asker, q, "resolved")
    assert r.status_code == 200 and r.json()["closed"] is True and r.json()["closed_reason"] == "resolved"
    assert client.post(f"{API}/questions/{q}/answers", json={"body": ANSWER}, headers=_h(other)).status_code == 422
    assert client.post(f"{API}/questions/{q}/reopen", headers=_h(asker)).json()["closed"] is False
    assert client.post(f"{API}/questions/{q}/answers", json={"body": ANSWER}, headers=_h(other)).status_code == 201


def test_who_may_close(client, db):
    q = _ask(client, _member(db))
    assert _close(client, _member(db), q).status_code == 403                                         # a stranger with little reputation
    assert _close(client, _member(db, reputation=rules.FORUM_REP_CLOSE_OTHERS), q).status_code == 200
    assert client.post(f"{API}/questions/{q}/reopen", headers=_h(_member(db))).status_code == 403
    assert client.post(f"{API}/questions/{q}/reopen", headers=_h(_member(db, moderator=True))).status_code == 200


def test_a_duplicate_names_an_existing_original(client, db):
    asker = _member(db)
    original, copy = _ask(client, asker, "How do I print the boundary map with labels"), _ask(client, asker, "Printing the boundary map and the labels")
    r = _close(client, asker, copy, "duplicate", original)
    assert r.status_code == 200 and r.json()["duplicate_of"]["id"] == original
    assert r.json()["duplicate_of"]["title"] == "How do I print the boundary map with labels"
    assert client.get(f"{API}/questions/{copy}").json()["question"]["duplicate_of"]["id"] == original
    # reopening clears the link
    assert client.post(f"{API}/questions/{copy}/reopen", headers=_h(asker)).json()["duplicate_of"] is None


def test_duplicate_rules(client, db):
    asker = _member(db)
    a, b, c = (_ask(client, asker, t) for t in ("First question about the print", "Second question about the print", "Third question about the print"))
    assert _close(client, asker, a, "duplicate").status_code == 422                                   # must name one
    assert _close(client, asker, a, "duplicate", a).status_code == 422                                # not itself
    assert _close(client, asker, a, "duplicate", str(uuid.uuid4())).status_code == 422                # must exist
    assert _close(client, asker, a, "off_topic", b).status_code == 422                                # only a duplicate names one
    assert _close(client, asker, b, "duplicate", a).status_code == 200
    assert _close(client, asker, c, "duplicate", b).status_code == 422                                # b is itself a duplicate: name the original
    assert _close(client, asker, b, "off_topic").status_code == 422                                   # already closed


def test_a_duplicate_cannot_point_at_a_held_or_deleted_question(client, db):
    asker = _member(db)
    mine = _ask(client, asker, "A real question about the print")
    held = _ask(client, _member(db, reputation=0), "A held question about the print")
    gone = _ask(client, asker, "A deleted question about the print")
    client.delete(f"{API}/posts/{gone}", headers=_h(asker))
    assert _close(client, asker, mine, "duplicate", held).status_code == 422
    assert _close(client, asker, mine, "duplicate", gone).status_code == 422


def test_me_lists_the_flag_privilege(client, db):
    me = client.get(f"{API}/me", headers=_h(_member(db))).json()
    assert me["thresholds"]["flag"] == rules.FORUM_REP_FLAG and me["can"]["flag"] is True
    assert client.get(f"{API}/me", headers=_h(_member(db, reputation=0))).json()["can"]["flag"] is False


# ── who moderates ──────────────────────────────────────────────────────────────────────────────────────────────

def _super(db):
    user = User(email=f"s{uuid.uuid4().hex[:10]}@test.com", full_name="Super Boss", role=UserRole.SUPER_ADMIN, hashed_password="x")
    db.add(user)
    db.commit()
    return user


def test_a_super_admin_makes_and_removes_a_moderator(client, db):
    boss, target = _super(db), _member(db, reputation=0)
    target_id = str(target.id)
    r = client.put(f"{API}/moderation/moderators/{target_id}", json={"is_moderator": True}, headers=_h(boss))
    assert r.status_code == 200 and r.json()["is_moderator"] is True
    assert client.get(f"{API}/moderation/flagged", headers=_h(target)).status_code == 200      # now a moderator
    assert [m["id"] for m in client.get(f"{API}/moderation/members", params={"moderators_only": True}, headers=_h(boss)).json()] == [target_id]
    assert client.put(f"{API}/moderation/moderators/{target_id}", json={"is_moderator": False}, headers=_h(boss)).json()["is_moderator"] is False
    assert client.get(f"{API}/moderation/flagged", headers=_h(target)).status_code == 403


def test_nobody_else_can_choose_moderators(client, db):
    target = _member(db)
    for who in (_member(db), _member(db, moderator=True)):   # not even a moderator
        assert client.put(f"{API}/moderation/moderators/{target.id}", json={"is_moderator": True}, headers=_h(who)).status_code == 403
        assert client.get(f"{API}/moderation/members", params={"q": "forum"}, headers=_h(who)).status_code == 403
    assert client.put(f"{API}/moderation/moderators/{target.id}", json={"is_moderator": True}).status_code in (401, 403)


def test_member_search_matches_name_or_email_and_treats_wildcards_literally(client, db):
    boss = _super(db)
    a = _member(db)
    a.full_name = "Sita Gurung"
    db.commit()
    names = lambda q: [m["name"] for m in client.get(f"{API}/moderation/members", params={"q": q}, headers=_h(boss)).json()]
    assert "Sita Gurung" in names("gurung") and "Sita Gurung" in names(a.email[:6])
    assert names("%") == [] and names("_") == []        # a wildcard is just a character
    assert names("") == []                              # no search, no list of everyone
    assert client.put(f"{API}/moderation/moderators/{uuid.uuid4()}", json={"is_moderator": True}, headers=_h(boss)).status_code == 422
