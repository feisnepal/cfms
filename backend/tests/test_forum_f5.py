"""Forum F5 gate: who is told about what, nothing for held or deleted posts, digests, and the member's own settings."""
import uuid

import pytest
from sqlalchemy import text

from app.models.forum import ForumNotification
from app.models.user import User, UserRole
from app.services.forum import ledger, notifications
from app.utils.auth import create_access_token

API = "/api/v1/forum"
BODY = "I drew the boundary but the print map shows no labels. What should I check first?"
ANSWER = "Open the layer menu and tick the label layer before printing the map."
COMMENT = "Did you also tick the label layer on the print preview?"


@pytest.fixture(autouse=True)
def _empty_forum(db):
    db.execute(text("TRUNCATE forum_posts, forum_profiles, forum_actions, forum_reputation_events, forum_flags, forum_subscriptions, forum_notification_prefs, "
                    "forum_tag_marks, forum_tag_synonyms, forum_post_tags, forum_post_revisions, forum_attachments, forum_notifications CASCADE"))
    db.execute(text("UPDATE forum_tags SET used_count = 0"))
    db.commit()
    yield


@pytest.fixture
def mails(monkeypatch):
    """Every message the forum tries to send. The background send runs for real; nothing leaves the machine."""
    sent = []
    monkeypatch.setattr(notifications, "send_mail", lambda to, subject, body: (sent.append((to, subject, body)), True)[1])
    return sent


def _member(db, reputation=60, moderator=False):
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


def _ask(client, user, title="How do I print the boundary map?", tags=("map",)):
    r = client.post(f"{API}/questions", json={"title": title, "body": BODY, "tags": list(tags)}, headers=_h(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _answer(client, user, q):
    r = client.post(f"{API}/questions/{q}/answers", json={"body": ANSWER}, headers=_h(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _to(mails, user):
    return [m for m in mails if m[0] == user.email]


def _unsent(db):
    db.expire_all()
    return db.query(ForumNotification).filter(ForumNotification.emailed_at.is_(None)).count()


# ── who is told ────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_asker_gets_an_email_for_an_answer_and_the_answerer_does_not(client, db, mails):
    asker, helper = _member(db), _member(db)
    q = _ask(client, asker)
    _answer(client, helper, q)
    assert len(_to(mails, asker)) == 1 and _to(mails, helper) == []
    _, subject, body = _to(mails, asker)[0]
    assert "New answer" in subject and "How do I print the boundary map?" in subject
    assert f"/forum/q/{q}" in body and "/forum/settings" in body


def test_a_follower_hears_about_new_answers_and_stops_when_they_unfollow(client, db, mails):
    asker, follower, helper = _member(db), _member(db), _member(db)
    q = _ask(client, asker)
    assert client.put(f"{API}/questions/{q}/following", json={"following": True}, headers=_h(follower)).json() == {"following": True}
    assert client.get(f"{API}/questions/{q}", headers=_h(follower)).json()["following"] is True
    _answer(client, helper, q)
    assert len(_to(mails, follower)) == 1
    client.put(f"{API}/questions/{q}/following", json={"following": False}, headers=_h(follower))
    assert client.get(f"{API}/questions/{q}", headers=_h(follower)).json()["following"] is False
    _answer(client, _member(db), q)
    assert len(_to(mails, follower)) == 1


def test_an_answerer_automatically_follows_and_hears_about_the_next_answer(client, db, mails):
    asker, first, second = _member(db), _member(db), _member(db)
    q = _ask(client, asker)
    _answer(client, first, q)
    _answer(client, second, q)
    assert len(_to(mails, first)) == 1


def test_a_comment_reaches_the_post_author_and_earlier_commenters_but_not_the_commenter(client, db, mails):
    asker, a, b = _member(db), _member(db), _member(db)
    q = _ask(client, asker)
    client.post(f"{API}/posts/{q}/comments", json={"body": COMMENT}, headers=_h(a))
    client.post(f"{API}/posts/{q}/comments", json={"body": COMMENT + " Second."}, headers=_h(b))
    assert len(_to(mails, asker)) == 2          # both comments
    assert len(_to(mails, a)) == 1              # told about b's comment, not about their own
    assert _to(mails, b) == []


def test_accepting_tells_the_answerer_only_if_they_chose_to_hear_it(client, db, mails):
    asker, helper = _member(db), _member(db)
    q = _ask(client, asker)
    a = _answer(client, helper, q)
    client.put(f"{API}/me/notifications", json={"on_accepted": True}, headers=_h(helper))
    assert client.post(f"{API}/answers/{a}/accept", headers=_h(asker)).status_code == 200
    got = _to(mails, helper)
    assert len(got) == 1 and "accepted" in got[0][1]


def test_a_new_question_reaches_those_watching_its_tag(client, db, mails):
    watcher, author = _member(db), _member(db)
    client.put(f"{API}/me/notifications", json={"on_new_in_watched_tags": True}, headers=_h(watcher))
    assert client.put(f"{API}/me/tags/sampling", json={"following": True}, headers=_h(watcher)).status_code == 200
    assert client.put(f"{API}/me/tags/no-such-tag", json={"following": True}, headers=_h(watcher)).status_code == 404
    _ask(client, author, "A question about the print", ("map",))
    assert _to(mails, watcher) == []
    _ask(client, author, "How many plots does a block need?", ("sampling",))
    assert len(_to(mails, watcher)) == 1


# ── nothing for what nobody may see ────────────────────────────────────────────────────────────────────────────

def test_a_held_post_tells_nobody_until_a_moderator_approves_it(client, db, mails):
    asker, newbie, mod = _member(db), _member(db, reputation=0), _member(db, moderator=True)
    q = _ask(client, asker)
    held = _answer(client, newbie, q)                      # held: below the no-review reputation
    assert mails == [] and db.query(ForumNotification).count() == 0
    assert client.post(f"{API}/posts/{held}/approve", headers=_h(mod)).status_code == 200
    assert len(_to(mails, asker)) == 1


def test_a_post_deleted_before_the_email_goes_out_is_dropped(client, db, mails):
    asker, helper = _member(db), _member(db)
    client.put(f"{API}/me/notifications", json={"email_frequency": "daily"}, headers=_h(asker))
    q = _ask(client, asker)
    a = _answer(client, helper, q)
    client.delete(f"{API}/posts/{a}", headers=_h(helper))
    assert notifications.send_pending(db, "daily") == 0
    assert mails == []
    assert _unsent(db) == 0   # settled, not left to retry


def test_no_email_to_someone_who_opted_out_or_wants_none(client, db, mails):
    asker, helper = _member(db), _member(db)
    client.put(f"{API}/me/notifications", json={"enabled": False}, headers=_h(asker))
    q = _ask(client, asker)
    _answer(client, helper, q)
    assert _to(mails, asker) == [] and db.query(ForumNotification).filter_by(user_id=asker.id).count() == 0
    client.put(f"{API}/me/notifications", json={"enabled": True, "email_frequency": "never"}, headers=_h(asker))
    _answer(client, _member(db), q)
    assert _to(mails, asker) == []


# ── digests ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_daily_member_gets_one_message_for_everything(client, db, mails):
    asker = _member(db)
    client.put(f"{API}/me/notifications", json={"email_frequency": "daily"}, headers=_h(asker))
    q = _ask(client, asker)
    _answer(client, _member(db), q)
    _answer(client, _member(db), q)
    assert _to(mails, asker) == []                      # nothing at once
    assert notifications.send_pending(db, "weekly") == 0
    assert notifications.send_pending(db, "daily") == 1
    got = _to(mails, asker)
    assert len(got) == 1 and "2 updates" in got[0][1] and got[0][2].count(f"/forum/q/{q}") == 2
    assert notifications.send_pending(db, "daily") == 0   # sent once only


def test_a_failed_send_stays_pending_for_the_next_run(client, db, monkeypatch):
    asker = _member(db)
    client.put(f"{API}/me/notifications", json={"email_frequency": "daily"}, headers=_h(asker))
    q = _ask(client, asker)
    _answer(client, _member(db), q)
    monkeypatch.setattr(notifications, "send_mail", lambda *a: False)
    assert notifications.send_pending(db, "daily") == 0
    assert _unsent(db) == 1
    ok = []
    monkeypatch.setattr(notifications, "send_mail", lambda to, s, b: (ok.append(to), True)[1])
    assert notifications.send_pending(db, "daily") == 1 and ok == [asker.email]


def test_a_mail_error_never_breaks_the_request_or_loses_the_row(client, db, monkeypatch):
    asker = _member(db)
    q = _ask(client, asker)

    def boom(*a):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(notifications, "send_mail", boom)
    assert client.post(f"{API}/questions/{q}/answers", json={"body": ANSWER}, headers=_h(_member(db))).status_code == 201
    assert _unsent(db) == 1


# ── settings ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_settings_start_with_the_defaults_and_can_be_changed(client, db):
    me = _member(db)
    first = client.get(f"{API}/me/notifications", headers=_h(me)).json()
    assert first == {"enabled": True, "on_answer_to_mine": True, "on_comment_reply": True, "on_accepted": False,
                     "on_new_in_watched_tags": False, "email_frequency": "immediate", "watched_tags": []}
    changed = client.put(f"{API}/me/notifications", json={"email_frequency": "weekly", "on_accepted": True}, headers=_h(me)).json()
    assert changed["email_frequency"] == "weekly" and changed["on_accepted"] is True and changed["on_comment_reply"] is True
    assert client.put(f"{API}/me/notifications", json={"email_frequency": "hourly"}, headers=_h(me)).status_code == 422
    assert client.get(f"{API}/me/notifications").status_code in (401, 403)


def test_following_a_held_or_missing_question_is_refused_like_any_other_read(client, db):
    me = _member(db)
    held = _ask(client, _member(db, reputation=0), "A held question nobody else can see yet")
    assert client.put(f"{API}/questions/{held}/following", json={"following": True}, headers=_h(me)).status_code == 404
    assert client.put(f"{API}/questions/{uuid.uuid4()}/following", json={"following": True}, headers=_h(me)).status_code == 404
