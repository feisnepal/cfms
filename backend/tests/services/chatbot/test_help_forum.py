"""C1.4a: accepted forum answers become help passages; a deleted, held or un-accepted post is never quoted, and no author data is copied."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.models.forum import ForumPost
from app.services.chatbot import help_search

NOW = datetime.now(timezone.utc)


@pytest.fixture()
def forum(db):
    db.execute(text("TRUNCATE chat_help_chunks"))
    db.commit()
    created = []

    def make(title, answer, accepted=True, **flags):
        q = ForumPost(kind="question", title=title, body_md="the question body", **{k[2:]: v for k, v in flags.items() if k.startswith("q_")})
        db.add(q)
        db.flush()
        a = ForumPost(kind="answer", body_md=answer, parent_id=q.id, root_id=q.id, accepted_at=NOW if accepted else None,
                      **{k: v for k, v in flags.items() if not k.startswith("q_")})
        db.add(a)
        db.flush()
        created.extend([a, q])
        return q, a

    yield make
    for p in created:
        db.delete(db.get(ForumPost, p.id)) if db.get(ForumPost, p.id) else None
    db.commit()


def _found(db, word):
    return [h.id for h in help_search.search(db, word, limit=10)]


def test_accepted_answer_is_indexed_and_found(db, forum):
    _, a = forum("Zorblax pruning rule", "Zorblax means remove the lower branches in winter.")
    assert help_search.sync_forum(db) == 1
    hits = help_search.search(db, "zorblax")
    assert [h.id for h in hits] == [f"forum:{a.id}"] and hits[0].source == "forum" and "lower branches" in hits[0].text


def test_unaccepted_answer_is_not_indexed(db, forum):
    forum("Quuxel question", "Quuxel answer text", accepted=False)
    assert help_search.sync_forum(db) == 0
    assert _found(db, "quuxel") == []


def test_deleted_or_held_answer_stops_being_found_at_once_without_a_refresh(db, forum):
    _, a = forum("Flimflam topic", "Flimflam is explained here.")
    help_search.sync_forum(db)
    assert _found(db, "flimflam")
    a.pending_review = True
    db.commit()
    assert _found(db, "flimflam") == []
    a.pending_review, a.deleted_at = False, NOW
    db.commit()
    assert _found(db, "flimflam") == []


def test_deleted_question_hides_its_answer(db, forum):
    q, _ = forum("Blorptastic matter", "Blorptastic details.")
    help_search.sync_forum(db)
    q.deleted_at = NOW
    db.commit()
    assert _found(db, "blorptastic") == []


def test_refresh_switches_off_a_chunk_whose_answer_is_gone(db, forum):
    _, a = forum("Snarfle matter", "Snarfle details.")
    help_search.sync_forum(db)
    a.deleted_at = NOW
    db.commit()
    assert help_search.sync_forum(db) == 0
    assert db.execute(text("SELECT active FROM chat_help_chunks WHERE source='forum'")).scalar() is False


def test_long_answer_is_clipped_and_no_author_or_vote_is_stored(db, forum):
    forum("Wibble length", "wibble " + "word " * 1000)
    help_search.sync_forum(db)
    row = db.execute(text("SELECT body, source_ref, keywords, title_ne FROM chat_help_chunks WHERE source='forum'")).one()
    assert len(row.body) <= help_search.FORUM_BODY_CHARS + 3 and row.keywords == "" and row.title_ne is None


# ── owner-approved guideline question-and-answer pairs ──────────────────────────────────────────────────────

def _pairs():
    import json
    return json.loads(help_search.GUIDELINE_PATH.read_text(encoding="utf-8"))["pairs"]


def test_guideline_loads_twenty_passages_and_every_question_finds_its_own_in_the_top_three(db):
    db.execute(text("TRUNCATE chat_help_chunks"))
    db.commit()
    assert help_search.load_guideline(db) == 20
    missed = []
    for p in _pairs():
        for lang in ("en", "ne"):
            ids = [h.id for h in help_search.search(db, p[f"q_{lang}"], limit=3)]
            if f"guideline:{p['id']}-{lang}" not in ids:
                missed.append((p["id"], lang, ids))
    assert not missed, missed


def test_guideline_reload_is_idempotent_and_switches_off_removed_pairs(db, tmp_path):
    import json
    db.execute(text("TRUNCATE chat_help_chunks"))
    db.commit()
    help_search.load_guideline(db)
    help_search.load_guideline(db)
    assert db.execute(text("SELECT count(*) FROM chat_help_chunks WHERE source='guideline' AND active")).scalar() == 20
    one = tmp_path / "g.json"
    one.write_text(json.dumps({"pairs": _pairs()[:1]}, ensure_ascii=False), encoding="utf-8")
    assert help_search.load_guideline(db, one) == 2
    assert db.execute(text("SELECT count(*) FROM chat_help_chunks WHERE source='guideline' AND active")).scalar() == 2
