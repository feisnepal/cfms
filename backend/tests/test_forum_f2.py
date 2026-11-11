"""Forum F2 gate: what reputation lets a member do, how it is shown, the edit history, and that the cached balance is always the ledger's."""
import uuid

import pytest
from sqlalchemy import text

from app.core import forum_rules as rules
from app.models.forum import ForumProfile
from app.models.user import User, UserRole
from app.services.forum import ledger, reputation
from app.utils.auth import create_access_token

SEED_TAGS = ("map", "user-group", "fieldbook", "sampling", "field-inventory", "biodiversity", "household", "sfm", "cost-benefit",
             "operational-plan", "yearly-plan", "ntfp", "hazard", "mobile", "account")
BODY = "I drew the boundary but the print map shows no labels. What should I check first?"
ANSWER = "Open the map variables page and tick the label option before exporting."
API = "/api/v1/forum"


@pytest.fixture(autouse=True)
def _empty_forum(db):
    db.execute(text("TRUNCATE forum_posts, forum_profiles, forum_actions, forum_reputation_events, forum_flags, forum_subscriptions, forum_notification_prefs, "
                    "forum_tag_marks, forum_tag_synonyms, forum_post_tags, forum_post_revisions, forum_attachments CASCADE"))
    db.execute(text("DELETE FROM forum_tags WHERE name <> ALL(:seed)"), {"seed": list(SEED_TAGS)})
    db.execute(text("UPDATE forum_tags SET used_count = 0"))
    db.commit()
    yield


def _member(db, reputation_=rules.FORUM_REP_NO_REVIEW, role=UserRole.USER, name="Forum Member"):
    user = User(email=f"f{uuid.uuid4().hex[:10]}@test.com", full_name=name, role=role, hashed_password="x")
    db.add(user)
    db.flush()
    if reputation_:
        ledger.apply_reputation(db, user.id, reputation_, None)
    db.commit()
    return user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _ask(client, user, **over):
    r = client.post(f"{API}/questions", json={"title": "How do I print the boundary map?", "body": BODY, "tags": ["map"], **over}, headers=_h(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _answer(client, user, qid):
    r = client.post(f"{API}/questions/{qid}/answers", json={"body": ANSWER}, headers=_h(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── what reputation allows ──────────────────────────────────────────────────────────────────────────────────────

def test_me_says_what_the_member_may_do_and_what_each_thing_needs(client, db):
    low = _member(db, reputation_=0)
    me = client.get(f"{API}/me", headers=_h(low)).json()
    assert me["can"]["vote_up"] is False and me["can"]["comment"] is False
    assert me["thresholds"]["vote_up"] == rules.FORUM_REP_VOTE_UP and me["thresholds"]["edit_others"] == rules.FORUM_REP_EDIT_OTHERS
    assert me["votes_left_today"] == rules.FORUM_MAX_VOTES_PER_DAY
    mid = _member(db, reputation_=rules.FORUM_REP_VOTE_UP)
    assert client.get(f"{API}/me", headers=_h(mid)).json()["can"]["vote_up"] is True
    assert client.get(f"{API}/me", headers=_h(mid)).json()["can"]["vote_down"] is False


def test_a_moderator_may_do_everything_and_has_no_vote_cap(client, db):
    admin = _member(db, reputation_=0, role=UserRole.SUPER_ADMIN)
    me = client.get(f"{API}/me", headers=_h(admin)).json()
    assert all(me["can"].values()) and me["votes_left_today"] is None and me["is_moderator"] is True


def test_votes_left_today_counts_down(client, db):
    author = _member(db)
    voter = _member(db, reputation_=rules.FORUM_REP_VOTE_UP)
    qid = _ask(client, author)
    client.post(f"{API}/posts/{qid}/vote", json={"direction": "up"}, headers=_h(voter))
    assert client.get(f"{API}/me", headers=_h(voter)).json()["votes_left_today"] == rules.FORUM_MAX_VOTES_PER_DAY - 1
    client.post(f"{API}/posts/{qid}/vote", json={"direction": "none"}, headers=_h(voter))  # taking the vote back gives it back
    assert client.get(f"{API}/me", headers=_h(voter)).json()["votes_left_today"] == rules.FORUM_MAX_VOTES_PER_DAY


# ── how reputation came about ───────────────────────────────────────────────────────────────────────────────────

def test_the_reputation_history_names_each_change_and_its_question(client, db):
    author = _member(db, reputation_=0)
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    qid = _ask(client, author)
    client.post(f"{API}/posts/{qid}/approve", headers=_h(admin))
    voter = _member(db, reputation_=rules.FORUM_REP_VOTE_UP)
    client.post(f"{API}/posts/{qid}/vote", json={"direction": "up"}, headers=_h(voter))
    events = client.get(f"{API}/me/reputation", headers=_h(author)).json()
    assert [(e["value"], e["action_type"], e["by_cancel"]) for e in events] == [(rules.REP_QUESTION_UPVOTED, "vote_up", False)]
    assert events[0]["question_id"] == qid and events[0]["question_title"] == "How do I print the boundary map?"
    client.post(f"{API}/posts/{qid}/vote", json={"direction": "none"}, headers=_h(voter))
    after = client.get(f"{API}/me/reputation", headers=_h(author)).json()
    assert sorted((e["value"], e["by_cancel"]) for e in after) == [(-rules.REP_QUESTION_UPVOTED, True), (rules.REP_QUESTION_UPVOTED, False)]
    assert client.get(f"{API}/me", headers=_h(author)).json()["reputation"] == 0


def test_the_history_is_private(client, db):
    assert client.get(f"{API}/me/reputation").status_code in (401, 403)


def test_a_public_profile_counts_only_what_anyone_can_see(client, db):
    author = _member(db, name="Sita Rai")
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    q1 = _ask(client, author)
    q2 = _ask(client, author, title="A second question about sample plots")
    client.delete(f"{API}/posts/{q2}", headers=_h(author))                       # deleted: not counted
    held = _ask(client, _member(db, reputation_=0))                               # someone else's held post
    answerer = _member(db, name="Ram Thapa")
    a = _answer(client, answerer, q1)
    client.post(f"{API}/answers/{a}/accept", headers=_h(author))
    p = client.get(f"{API}/users/{answerer.id}").json()                           # anonymous
    assert (p["name"], p["questions"], p["answers"], p["accepted_answers"]) == ("Ram Thapa", 0, 1, 1)
    assert p["reputation"] == rules.FORUM_REP_NO_REVIEW + rules.REP_ANSWER_ACCEPTED
    assert client.get(f"{API}/users/{author.id}").json()["questions"] == 1
    assert client.get(f"{API}/users/{uuid.uuid4()}").status_code == 404
    assert held and admin


# ── edit history ────────────────────────────────────────────────────────────────────────────────────────────────

def test_edits_leave_a_history_newest_first(client, db):
    author = _member(db)
    qid = _ask(client, author)
    client.patch(f"{API}/posts/{qid}", json={"body": BODY + " (second)", "summary": "added a note"}, headers=_h(author))
    client.patch(f"{API}/posts/{qid}", json={"title": "How do I print the boundary map with labels?", "tags": ["map", "operational-plan"], "summary": "title and tags"}, headers=_h(author))
    revs = client.get(f"{API}/posts/{qid}/revisions").json()   # anonymous
    assert [r["revision"] for r in revs] == [3, 2, 1]
    assert revs[0]["summary"] == "title and tags" and revs[0]["title"].endswith("with labels?") and set(revs[0]["tag_names"].split()) == {"map", "operational-plan"}
    assert revs[1]["body_md"].endswith("(second)") and revs[2]["body_md"] == BODY and revs[2]["author_name"] == "Forum Member"


def test_the_history_of_a_hidden_post_is_hidden(client, db):
    qid = _ask(client, _member(db, reputation_=0))   # held
    assert client.get(f"{API}/posts/{qid}/revisions").status_code == 404


def test_history_text_is_escaped(client, db):
    author = _member(db)
    qid = _ask(client, author, body=BODY + " <script>alert(1)</script>")
    assert "<script" not in client.get(f"{API}/posts/{qid}/revisions").json()[0]["body_html"]


# ── a moderator deleting an accepted answer ─────────────────────────────────────────────────────────────────────

def test_removing_an_accepted_answer_takes_back_what_it_paid(client, db):
    asker, answerer = _member(db), _member(db)
    admin = _member(db, role=UserRole.SUPER_ADMIN)
    qid = _ask(client, asker)
    aid = _answer(client, answerer, qid)
    client.post(f"{API}/answers/{aid}/accept", headers=_h(asker))
    before = client.get(f"{API}/users/{answerer.id}").json()["reputation"]
    assert client.delete(f"{API}/posts/{aid}", headers=_h(answerer)).status_code == 422   # the author cannot
    assert client.delete(f"{API}/posts/{aid}", headers=_h(admin)).status_code == 200
    assert client.get(f"{API}/users/{answerer.id}").json()["reputation"] == before - rules.REP_ANSWER_ACCEPTED
    assert client.get(f"{API}/users/{asker.id}").json()["reputation"] == rules.FORUM_REP_NO_REVIEW
    assert reputation.reconcile(db) == []
    # restoring the answer does not accept it again
    client.post(f"{API}/posts/{aid}/restore", headers=_h(admin))
    thread = client.get(f"{API}/questions/{qid}").json()
    assert thread["answers"][0]["accepted"] is False


# ── the ledger and the balance ──────────────────────────────────────────────────────────────────────────────────

def test_a_busy_forum_keeps_every_balance_equal_to_its_ledger(client, db):
    people = [_member(db, reputation_=rules.FORUM_REP_VOTE_DOWN) for _ in range(4)]
    asker = _member(db)
    qid = _ask(client, asker)
    answers = [_answer(client, p, qid) for p in people[:3]]
    for i, p in enumerate(people):
        for j, a in enumerate(answers):
            if people[j].id == p.id:
                continue
            client.post(f"{API}/posts/{a}/vote", json={"direction": "up" if (i + j) % 2 else "down"}, headers=_h(p))
    client.post(f"{API}/answers/{answers[0]}/accept", headers=_h(asker))
    client.post(f"{API}/answers/{answers[1]}/accept", headers=_h(asker))      # moves the mark
    client.post(f"{API}/posts/{answers[2]}/vote", json={"direction": "none"}, headers=_h(people[3]))
    client.post(f"{API}/posts/{answers[0]}/vote", json={"direction": "down"}, headers=_h(people[3]))  # flips a vote
    # the people were given their starting reputation through the ledger, so every balance must equal its events
    assert reputation.reconcile(db) == []
    for u in people + [asker]:
        assert ledger.get_profile(db, u.id).reputation == ledger.reputation_from_events(db, u.id) >= 0


def test_reconcile_finds_and_repairs_a_balance_written_by_hand(client, db):
    user = _member(db, reputation_=40)
    assert reputation.reconcile(db) == []
    db.execute(text("UPDATE forum_profiles SET reputation = 999 WHERE user_id = :u"), {"u": user.id})
    db.commit()
    found = reputation.reconcile(db)
    assert found == [{"user_id": user.id, "cached": 999, "ledger": 40}]
    assert reputation.reconcile(db, fix=True) == found
    db.commit()
    assert db.get(ForumProfile, user.id).reputation == 40 and reputation.reconcile(db) == []


def test_reconcile_catches_a_balance_with_no_events(client, db):
    user = _member(db, reputation_=0)
    ledger.get_profile(db, user.id).reputation = 7   # nothing in the ledger paid this
    db.commit()
    assert reputation.reconcile(db) == [{"user_id": user.id, "cached": 7, "ledger": 0}]
