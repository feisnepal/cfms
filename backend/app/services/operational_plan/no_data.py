"""The one place that says "No data" in the operational plan.

Owner rule 2026-10-16: wherever a figure, table, chart or map has nothing behind it, the document prints
"No data" in red bold so the user can find it by eye (and by searching for it) and fix it before
issuing the plan. Before this module the same situation printed a blank (a variable that failed to
resolve), or one of six differently worded, English-only, non-bold messages that carried internal ids.

Inline variables are substituted into text before the document builder sees it, so the substitution is
wrapped in two invisible markers. The builder splits on them and colours that stretch of text; any
consumer that does not know about them (a footer, a plain-text preview) still shows the readable words.
"""
from __future__ import annotations

import re
from contextvars import ContextVar
from typing import List, Tuple

# The plan's language for the document being built; set once by the builders so every placeholder
# (table, chart, map, variable) uses the same words without a parameter on each helper.
_LANG: ContextVar[str | None] = ContextVar("op_no_data_language", default=None)


def set_language(language: str | None) -> None:
    _LANG.set(language)

NO_DATA_EN = "No data"
NO_DATA_NE = "डाटा उपलब्ध छैन"

# ND-7 (owner decision 2026-10-18): an empty list is not missing data - the owner may simply not have
# designated any (e.g. protected trees). The document says so in grey, not in the red "No data" that
# means "go and collect this".
EMPTY_LIST_EN = "List is empty"
EMPTY_LIST_NE = "सूची खाली छ"

# The grey used by add_paragraph's "(what)" tail; the empty-list note borrows it so it reads as a remark,
# not as an alarm.
GREY = (120, 120, 120)

# WORD JOINER / INVISIBLE SEPARATOR: zero width, never typed by a user, and not touched by the Devanagari digit converter.
OPEN = "⁠⁣"
CLOSE = "⁣⁠"
_MARKED = re.compile(re.escape(OPEN) + r"(.*?)" + re.escape(CLOSE), re.S)

RED = (200, 0, 0)


def label(language: str | None) -> str:
    """The words, by plan language. The plan language is stored as 'NP' or 'EN'; Nepali is the default."""
    language = language or _LANG.get()
    return NO_DATA_EN if str(language or "").upper().startswith("EN") else NO_DATA_NE


def marked(language: str | None = None) -> str:
    """The text a failed inline variable is replaced with."""
    return f"{OPEN}{label(language)}{CLOSE}"


def has_marker(text: str) -> bool:
    return OPEN in (text or "")


def split(text: str) -> List[Tuple[str, bool]]:
    """``[(piece, is_no_data), ...]`` in order; pieces are never empty."""
    out: List[Tuple[str, bool]] = []
    pos = 0
    for m in _MARKED.finditer(text or ""):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text or ""):
        out.append((text[pos:], False))
    return out


def strip(text: str) -> str:
    """Remove the markers, keep the words."""
    return (text or "").replace(OPEN, "").replace(CLOSE, "")


def add_runs(paragraph, text: str, *, size=None, font_name: str | None = None, fix=lambda s: s):
    """Write ``text`` into a python-docx paragraph; every No-data stretch is red and bold."""
    from docx.shared import Length, Pt, RGBColor

    for piece, is_nd in split(text):
        run = paragraph.add_run(piece if is_nd else fix(piece))
        if size is not None:
            # A python-docx Length (Pt(11)) is a subclass of int: testing "is it a number" first turned Pt(11) into Pt(Pt(11)),
            # a font size of about 140,000 points that Word draws as giant glyphs (black boxes instead of text).
            run.font.size = size if isinstance(size, Length) else Pt(size)
        if font_name:
            run.font.name = font_name
        if is_nd:
            run.font.bold = True
            run.font.color.rgb = RGBColor(*RED)
    return paragraph


def add_paragraph(doc, language: str | None = None, what: str | None = None):
    """A stand-alone 'No data' line for a table, chart or map that could not be drawn.

    ``what`` is a short human name ('Field inventory table'); it is printed small and grey after the red words so the
    user knows which one it is. Internal ids are for the log, not for the reader.
    """
    from docx.shared import Pt, RGBColor

    p = doc.add_paragraph()
    run = p.add_run(label(language))
    run.font.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(*RED)
    if what:
        extra = p.add_run(f"  ({what})")
        extra.font.size = Pt(9)
        extra.font.color.rgb = RGBColor(120, 120, 120)
    return p


def html(language: str | None = None, what: str | None = None) -> str:
    """The same thing for the HTML preview."""
    from html import escape

    tail = f' <small style="color:#777">({escape(what)})</small>' if what else ""
    return f'<span class="no-data" style="color:#c80000;font-weight:700">{escape(label(language))}</span>{tail}'


def empty_list_label(language: str | None) -> str:
    """The words for an empty list, by plan language (English only when the plan is English)."""
    language = language or _LANG.get()
    return EMPTY_LIST_EN if str(language or "").upper().startswith("EN") else EMPTY_LIST_NE


def empty_list_paragraph(doc, language: str | None = None, what: str | None = None):
    """A grey note where a list resolved to ``[]`` (ND-7) - deliberately NOT the red "No data".

    ``add_paragraph`` says the user must go and fix something; an empty list says only that the list has no
    rows yet, which is a legitimate state. Styled like ``add_paragraph``'s ``(what)`` tail: small and grey.
    """
    from docx.shared import Pt, RGBColor

    p = doc.add_paragraph()
    run = p.add_run(empty_list_label(language))
    run.font.size = Pt(9)
    run.font.color.rgb = RGBColor(*GREY)
    if what:
        extra = p.add_run(f"  ({what})")
        extra.font.size = Pt(9)
        extra.font.color.rgb = RGBColor(*GREY)
    return p


def empty_list_html(language: str | None = None, what: str | None = None) -> str:
    """The same grey note for the HTML preview."""
    from html import escape

    tail = f' <small>({escape(what)})</small>' if what else ""
    return f'<span class="empty-list" style="color:#787878">{escape(empty_list_label(language))}</span>{tail}'


def to_html(escaped_text: str) -> str:
    """Turn the markers inside already-escaped text into red bold spans."""
    return _MARKED.sub(lambda m: f'<span class="no-data" style="color:#c80000;font-weight:700">{m.group(1)}</span>', escaped_text)
