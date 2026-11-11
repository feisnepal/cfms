"""What search engines see of the forum: a question page with its text in the HTML, a sitemap and robots.txt (``FORUM_SPEC.md`` decision 5).

The React app alone would show a crawler an empty shell. ``question_page`` returns the app's own ``index.html`` (so a person still gets the
app) with the question, its answers, a canonical link, a description and ``QAPage`` data written into it; React replaces the content when it
starts. Only posts anyone may read are rendered (a held or deleted post answers 404 before it gets here). Every user string is escaped; the
post bodies come from ``markdown_lite``, which escapes first.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core import forum_rules as rules
from ...core.config import settings
from ...models.forum import ForumPost
from . import markdown_lite
from . import posts as post_service

logger = logging.getLogger(__name__)
_warned_no_shell = False

SITEMAP_MAX_URLS = 50000
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_MARKUP = re.compile(r"[*`>#\[\]()_~-]+|https?://\S+")
_DEFAULT_SHELL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "frontend", "dist", "index.html")


def base_url() -> str:
    return settings.PUBLIC_APP_URL.rstrip("/")


def question_url(question_id) -> str:
    return f"{base_url()}/forum/q/{question_id}"


def plain_text(markdown: str, limit: int) -> str:
    """The post as one line of plain text, cut at a word near ``limit`` characters."""
    text = re.sub(r"\s+", " ", _MARKUP.sub(" ", markdown or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut + "..."


def _spa_shell() -> Optional[str]:
    path = settings.FORUM_SPA_INDEX_PATH or _DEFAULT_SHELL
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        global _warned_no_shell
        if not _warned_no_shell:  # once: the page still works, but a person opening it gets the text and no app
            _warned_no_shell = True
            logger.warning("forum SEO page: the app shell %s is not readable (set FORUM_SPA_INDEX_PATH); question pages carry the text only", path)
        return None


def _json_ld(question: ForumPost, answers: list[ForumPost]) -> str:
    def answer(a: ForumPost) -> dict:
        return {"@type": "Answer", "text": plain_text(a.body_md, 5000), "upvoteCount": a.score, "dateCreated": a.created_at.isoformat(),
                "url": f"{question_url(question.id)}#answer-{a.id}"}
    accepted = [a for a in answers if a.accepted_at is not None]
    data = {
        "@context": "https://schema.org", "@type": "QAPage",
        "mainEntity": {
            "@type": "Question", "name": question.title, "text": plain_text(question.body_md, 5000), "answerCount": len(answers),
            "upvoteCount": question.score, "dateCreated": question.created_at.isoformat(),
            **({"acceptedAnswer": answer(accepted[0])} if accepted else {}),
            **({"suggestedAnswer": [answer(a) for a in answers if a not in accepted]} if len(answers) > len(accepted) else {}),
        },
    }
    # "<" as an escape, so a "</script>" inside a post can never end the data block
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _content(db: Session, question: ForumPost, answers: list[ForumPost]) -> str:
    e = html.escape
    tags = ", ".join(f'<a href="{base_url()}/forum?tag={e(t.name)}">{e(t.name)}</a>' for t in post_service.post_tags(db, question.id))
    parts = [f'<article class="forum-ssr"><h1>{e(question.title or "")}</h1>', f'<p>{tags}</p>' if tags else "", markdown_lite.render(question.body_md)]
    if answers:
        parts.append(f"<h2>{len(answers)} {'answer' if len(answers) == 1 else 'answers'}</h2>")
    for a in answers:
        mark = " (accepted answer)" if a.accepted_at is not None else ""
        parts.append(f'<section id="answer-{a.id}"><h3>Answer{mark}</h3>{markdown_lite.render(a.body_md)}</section>')
    parts.append(f'<p><a href="{base_url()}/forum">All questions</a></p></article>')
    return "\n".join(p for p in parts if p)


def question_page(db: Session, question: ForumPost, answers: list[ForumPost]) -> str:
    e = html.escape
    title = f"{question.title} - Community Forum"
    desc = plain_text(question.body_md, 160)
    lang = "ne" if _DEVANAGARI.search(question.title or "") else "en"
    canonical = question_url(question.id)
    head = "\n".join([
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(desc, quote=True)}">',
        f'<link rel="canonical" href="{canonical}">',
        f'<meta property="og:title" content="{e(question.title or "", quote=True)}">',
        f'<meta property="og:description" content="{e(desc, quote=True)}">',
        f'<meta property="og:url" content="{canonical}">',
        '<meta property="og:type" content="article">',
        f'<script type="application/ld+json">{_json_ld(question, answers)}</script>',
    ])
    content = _content(db, question, answers)
    shell = _spa_shell()
    if shell is None:
        return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1">{head}</head><body><div id="root">{content}</div></body></html>')
    shell = re.sub(r"<title>.*?</title>", "", shell, count=1, flags=re.S)
    shell = re.sub(r'<html\b([^>]*?)\blang="[^"]*"', rf'<html\1lang="{lang}"', shell, count=1)
    shell = shell.replace("</head>", head + "\n</head>", 1)
    return re.sub(r'<div id="root">\s*</div>', lambda _m: f'<div id="root">{content}</div>', shell, count=1)


def sitemap_xml(db: Session) -> str:
    """Every question anyone may read, plus the forum's front page."""
    rows = db.execute(
        select(ForumPost.id, ForumPost.last_activity_at)
        .where(ForumPost.kind == rules.KIND_QUESTION, ForumPost.deleted_at.is_(None), ForumPost.pending_review.is_(False))
        .order_by(ForumPost.last_activity_at.desc()).limit(SITEMAP_MAX_URLS - 1)
    ).all()
    urls = [f"<url><loc>{base_url()}/forum</loc></url>"]
    urls += [f"<url><loc>{question_url(r[0])}</loc><lastmod>{r[1].date().isoformat()}</lastmod></url>" for r in rows]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "\n".join(urls) + "\n</urlset>\n"


def robots_txt() -> str:
    return "\n".join([
        "User-agent: *",
        "Allow: /forum",
        "Allow: /api/forum/attachments/",
        "Disallow: /api/",
        f"Sitemap: {base_url()}/sitemap.xml",
        "",
    ])
