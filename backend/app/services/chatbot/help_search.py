"""The assistant's help search: load the fact cards, find the passages that answer a question (CHATBOT_PLAN C1.4).

Search is PostgreSQL full text with the ``simple`` config, as in the forum, so a Devanagari word is kept whole. A question is turned into "any
meaningful word" (a long question rarely contains every word of a card), ranked with the title and keywords weighing more than the body, and
a card written for the step the user is on gets a small lift.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.chat import ChatHelpChunk
from app.services.chatbot import guard

logger = logging.getLogger(__name__)

CARDS_PATH = Path(__file__).with_name("help_corpus") / "cards.json"
GUIDELINE_PATH = Path(__file__).with_name("help_corpus") / "guideline_qa.json"

_WORD = re.compile(r"[\wऀ-ॿ]{2,}")
# words that say nothing about the subject (English as in the forum's similar-question search, plus Nepali question words)
_STOP = frozenset(
    "the a an and or of to in on at for with from by is are was were be do does did how why what when where which who can could should would "
    "this that these those it its my our your you we i me not no have has had there about any some into than then them they their "
    "कसरी किन कहाँ कुन के हो छ छन् भनेको हुन्छ हुन गर्ने गर्नु गर्नुपर्छ मिल्छ मिल्दैन लागि यो त्यो मैले हाम्रो मेरो तपाईं अनि तथा भने पनि "
    "को मा ले लाई बाट सँग".split()
)
STEP_LIFT = 0.1  # added to the rank of a card written for the step the user is on

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Nepali glues its case endings onto the noun (समूह -> समूहको, समूहमा) and the `simple` search config does not stem, so a question word
# would never meet the stored word. The ending is stripped from Devanagari question words and the rest is matched as a prefix.
_NE_SUFFIXES = tuple(sorted(
    ("हरूको", "हरूमा", "हरूले", "हरूलाई", "हरू", "बाट", "लाई", "सँग", "को", "का", "की", "मा", "ले", "मै"), key=len, reverse=True,
))
_MIN_STEM = 3


def _ne_stem(word: str) -> str:
    for suffix in _NE_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            return word[: -len(suffix)]
    return word


@dataclass(frozen=True)
class HelpHit:
    id: str
    title: str
    text: str
    source: str
    rank: float


def help_query(question: str) -> Optional[str]:
    """A tsquery text matching any meaningful word of the question, or None if none is left. Words contain letters and digits only, so
    no tsquery operator can come out of user text."""
    words: List[str] = []
    for w in _WORD.findall((question or "").lower()):
        if w not in _STOP and w not in words:
            words.append(w)
    terms = [f"{_ne_stem(w)}:*" if _DEVANAGARI.search(w) else w for w in words[:16]]
    return " | ".join(terms) or None


def load_cards(db: Session, path: Path = CARDS_PATH) -> int:
    """Put the cards in the table (insert or update by id) and switch off any card that is no longer in the file. Returns the card count."""
    cards = json.loads(path.read_text(encoding="utf-8"))["cards"]
    ids = [c["id"] for c in cards]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate card ids")
    for c in cards:
        keywords = " ".join([c.get("keywords", ""), c.get("keywords_ne", ""), c.get("keywords_roman", "")]).strip()
        row = db.get(ChatHelpChunk, c["id"])
        if row is None:
            row = ChatHelpChunk(id=c["id"])
            db.add(row)
        row.source = "card"
        row.title, row.title_ne, row.body, row.keywords = c["title"], c.get("title_ne"), c["body"], keywords
        row.steps = list(c.get("steps", []))
        row.active = True
    db.flush()
    db.execute(text("UPDATE chat_help_chunks SET active = false WHERE source = 'card' AND id <> ALL(:ids)"), {"ids": ids})
    db.commit()
    logger.info("loaded %d help cards", len(cards))
    return len(cards)


def load_guideline(db: Session, path: Path = GUIDELINE_PATH) -> int:
    """Load the owner-approved question-and-answer pairs: one passage per language per pair (source 'guideline'). Returns the passage count."""
    pairs = json.loads(path.read_text(encoding="utf-8"))["pairs"]
    ids = []
    for p in pairs:
        for lang in ("en", "ne"):
            cid = f"guideline:{p['id']}-{lang}"
            ids.append(cid)
            row = db.get(ChatHelpChunk, cid) or ChatHelpChunk(id=cid)
            db.add(row)
            row.source, row.source_ref = "guideline", path.name
            row.title, row.title_ne = p[f"q_{lang}"], (p["q_ne"] if lang == "ne" else None)
            row.body, row.keywords, row.steps, row.active = p[f"a_{lang}"], "", [], True
    db.flush()
    db.execute(text("UPDATE chat_help_chunks SET active = false WHERE source = 'guideline' AND id <> ALL(:ids)"), {"ids": ids})
    db.commit()
    return len(ids)


FORUM_BODY_CHARS = 1200  # a passage must stay short enough to sit in a prompt three at a time
# A forum chunk counts only while its answer is still accepted, not deleted and not held for review. Checked at search time, so a post a
# moderator removes stops being quoted at once, without waiting for a refresh.
_LIVE = (
    "(source <> 'forum' OR EXISTS (SELECT 1 FROM forum_posts a JOIN forum_posts q ON q.id = a.root_id "
    "WHERE a.id::text = source_ref AND a.kind = 'answer' AND a.accepted_at IS NOT NULL AND a.deleted_at IS NULL AND NOT a.pending_review "
    "AND q.deleted_at IS NULL AND NOT q.pending_review))"
)


def _clip(body: str) -> str:
    body = re.sub(r"\s+", " ", body or "").strip()
    return body if len(body) <= FORUM_BODY_CHARS else body[:FORUM_BODY_CHARS].rsplit(" ", 1)[0] + " …"


def sync_forum(db: Session) -> int:
    """Index every accepted forum answer (with its question's title) and switch off chunks whose answer is no longer eligible. No author, no
    user id and no vote data is copied: only the question title and the answer text. Returns the number of live forum chunks."""
    rows = db.execute(text(
        "SELECT a.id::text AS ref, q.title, a.body_md, q.workflow_step FROM forum_posts a JOIN forum_posts q ON q.id = a.root_id "
        "WHERE a.kind = 'answer' AND a.accepted_at IS NOT NULL AND a.deleted_at IS NULL AND NOT a.pending_review "
        "AND q.deleted_at IS NULL AND NOT q.pending_review"
    )).all()
    live = []
    for r in rows:
        if guard.looks_hostile(f"{r.title or ''} {r.body_md}"):
            logger.warning("forum answer %s not indexed: it looks like an instruction to the model", r.ref)
            continue
        cid = f"forum:{r.ref}"
        live.append(cid)
        row = db.get(ChatHelpChunk, cid) or ChatHelpChunk(id=cid)
        db.add(row)
        row.source, row.source_ref, row.title, row.body, row.keywords = "forum", r.ref, guard.safe_text(r.title or ""), guard.safe_text(_clip(r.body_md)), ""
        row.steps = [r.workflow_step] if r.workflow_step else []
        row.active = True
    db.flush()
    db.execute(text("UPDATE chat_help_chunks SET active = false WHERE source = 'forum' AND id <> ALL(:ids)"), {"ids": live})
    db.commit()
    return len(live)


def search(db: Session, question: str, limit: int = 3, step: Optional[str] = None) -> List[HelpHit]:
    q = help_query(question)
    if q is None:
        return []
    rows = db.execute(
        text(
            "SELECT id, title, body, source, "
            "  ts_rank_cd(search_vector, to_tsquery('simple', :q)) + CASE WHEN :step = ANY(steps) THEN :lift ELSE 0 END AS rank "
            "FROM chat_help_chunks WHERE active AND " + _LIVE + " AND search_vector @@ to_tsquery('simple', :q) "
            "ORDER BY rank DESC, id LIMIT :n"
        ),
        {"q": q, "step": step or "", "lift": STEP_LIFT, "n": limit * 2},  # room for forum passages the guard drops
    ).all()
    kept = guard.screen_passages({"source": r.source, "title": r.title, "text": r.body, "row": r} for r in rows)
    return [HelpHit(k["row"].id, k["row"].title, k["row"].body, k["row"].source, float(k["row"].rank)) for k in kept][:limit]
