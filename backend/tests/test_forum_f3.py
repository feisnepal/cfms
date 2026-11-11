"""Forum F3 gate: questions asked from a workflow step - the step id is validated, counted per step, and the frontend's step-to-tag map agrees with the seeded tags."""
import importlib.util
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core import forum_rules as rules
from app.models.user import User, UserRole
from app.services.forum import ledger
from app.utils.auth import create_access_token

API = "/api/v1/forum"
BODY = "I drew the boundary but the print map shows no labels. What should I check first?"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _empty_forum(db):
    db.execute(text("TRUNCATE forum_posts, forum_profiles, forum_actions, forum_reputation_events, forum_flags, forum_subscriptions, forum_notification_prefs, "
                    "forum_tag_marks, forum_tag_synonyms, forum_post_tags, forum_post_revisions, forum_attachments CASCADE"))
    db.execute(text("UPDATE forum_tags SET used_count = 0"))
    db.commit()
    yield


def _member(db, reputation=rules.FORUM_REP_NO_REVIEW):
    user = User(email=f"f{uuid.uuid4().hex[:10]}@test.com", full_name="Forum Member", role=UserRole.USER, hashed_password="x")
    db.add(user)
    db.flush()
    if reputation:
        ledger.apply_reputation(db, user.id, reputation, None)
    db.commit()
    return user


def _h(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id), 'email': user.email})}"}


def _ask(client, user, step=None, title="How do I print the boundary map?"):
    body = {"title": title, "body": BODY, "tags": ["map"]}
    if step is not None:
        body["workflow_step"] = step
    return client.post(f"{API}/questions", json=body, headers=_h(user))


def test_a_question_keeps_the_step_it_was_asked_from_and_can_be_listed_by_it(client, db):
    user = _member(db)
    r = _ask(client, user, "fieldbook")
    assert r.status_code == 201 and r.json()["workflow_step"] == "fieldbook"
    _ask(client, user, "sampling", "How many sample plots does a block need?")
    only = client.get(f"{API}/questions", params={"step": "fieldbook"}).json()["items"]
    assert [q["workflow_step"] for q in only] == ["fieldbook"]


@pytest.mark.parametrize("bad", ["<script>", "Field Book", "UPPER", "1step", "a" * 41, "step/../x", "step;drop", "x y"])
def test_a_step_that_is_not_an_id_is_refused(client, db, bad):
    assert _ask(client, _member(db), bad).status_code == 422
    assert client.get(f"{API}/questions", params={"step": bad}).status_code == 422


def test_step_counts_include_only_what_anyone_can_read(client, db):
    author = _member(db)
    q1 = _ask(client, author, "cba").json()["id"]
    _ask(client, author, "cba", "A second question about the cost benefit tab")
    _ask(client, author, "yearly", "How do I add a road to the yearly plan?")
    _ask(client, author, None, "A question not asked from any step at all")
    _ask(client, _member(db, reputation=0), "cba", "A held question that nobody else can see")  # held
    gone = _ask(client, author, "cba", "A question that will be deleted soon enough").json()["id"]
    client.delete(f"{API}/posts/{gone}", headers=_h(author))
    answerer = _member(db)
    client.post(f"{API}/questions/{q1}/answers", json={"body": "Open the base scenario and press calculate before reading the results."}, headers=_h(answerer))
    counts = client.get(f"{API}/steps").json()   # anonymous
    assert counts["cba"] == {"questions": 2, "unanswered": 1}
    assert counts["yearly"] == {"questions": 1, "unanswered": 1}
    assert set(counts) == {"cba", "yearly"}


def test_the_frontends_step_tags_are_tags_the_migration_seeds():
    """`stepTags.ts` mirrors the seeded tags: a tag renamed in one place only would leave a step prefilling a tag that does not exist."""
    spec = importlib.util.spec_from_file_location("m144", ROOT / "backend" / "alembic" / "versions" / "144_forum_search_and_tags.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeded = {name for name, _ in module.STARTING_TAGS}
    source = (ROOT / "frontend" / "src" / "features" / "forum" / "stepTags.ts").read_text(encoding="utf-8")
    listed = set(re.findall(r"'([a-z-]+)'", source.split("export const FORUM_TAGS")[1].split("] as const")[0]))
    assert listed == seeded
    used = set(re.findall(r"^\s+\w+: '([a-z-]+)',$", source.split("export const STEP_TAGS")[1].split("};")[0], re.M))
    assert used and used <= seeded


# ── "has this been asked already?" ─────────────────────────────────────────────────────────────────────────────

def _similar(client, q, **extra):
    r = client.get(f"{API}/questions", params={"q": q, "match": "any", **extra})
    assert r.status_code == 200, r.text
    return [i["title"] for i in r.json()["items"]]


def test_a_similar_title_is_found_even_when_it_has_extra_words(client, db):
    user = _member(db)
    _ask(client, user, title="How do I print the boundary map with labels?")
    _ask(client, user, title="How many sample plots does a block need?")
    typed = "How do I print the boundary map with the labels shown"
    assert _similar(client, typed)[0] == "How do I print the boundary map with labels?"
    # the normal search wants every word, so the same text finds nothing
    assert client.get(f"{API}/questions", params={"q": typed}).json()["items"] == []


def test_the_best_match_comes_first(client, db):
    user = _member(db)
    _ask(client, user, title="Boundary labels are missing from the print")
    _ask(client, user, title="The boundary will not snap to the neighbour")
    assert _similar(client, "print boundary labels")[0] == "Boundary labels are missing from the print"


def test_a_query_of_only_filler_words_matches_nothing(client, db):
    _ask(client, _member(db), title="How do I print the boundary map with labels?")
    assert _similar(client, "how do I the and of") == []


def test_similar_matching_works_in_nepali(client, db):
    _ask(client, _member(db), title="समुदायिक वनको नक्सा कसरी छाप्ने", )
    assert _similar(client, "वनको नक्सा छाप्ने तरिका") == ["समुदायिक वनको नक्सा कसरी छाप्ने"]


def test_similar_matching_does_not_show_held_or_deleted_questions(client, db):
    _ask(client, _member(db, reputation=0), title="A held question about printing the boundary map")
    author = _member(db)
    gone = _ask(client, author, title="A deleted question about printing the boundary map").json()["id"]
    client.delete(f"{API}/posts/{gone}", headers=_h(author))
    assert _similar(client, "printing the boundary map") == []


@pytest.mark.parametrize("hostile", ["a'; DROP TABLE forum_posts; --", "x & y | !z", "foo:* <-> bar", "((((", "\\"])
def test_hostile_text_cannot_break_the_search(client, db, hostile):
    _ask(client, _member(db))
    assert client.get(f"{API}/questions", params={"q": hostile, "match": "any"}).status_code == 200
    assert client.get(f"{API}/questions", params={"q": hostile}).status_code == 200
    assert db.execute(text("select count(*) from forum_posts")).scalar() == 1
