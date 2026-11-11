"""A small, safe markdown renderer for forum posts.

Safe by construction: the whole text is HTML-escaped FIRST, and only then are a few markers turned into tags the renderer itself writes, so
no user text can reach the page as markup. Supported: paragraphs, line breaks, ``**bold**``, ``*italic*``, ``code``, fenced code blocks,
``-`` / ``1.`` lists, ``>`` quotes, and ``[text](url)`` links with an http(s) or mailto target. Links carry ``rel="nofollow ugc noopener"`` so a
public, indexed forum is not a place to buy search ranking. Anything else (images, raw HTML, headings) stays as plain text.
"""
from __future__ import annotations

import html
import re

_LINK = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^\s)]{1,500}|mailto:[^\s)]{1,200})\)")
_BOLD = re.compile(r"\*\*([^*\n]+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*([^*\n]+?)\*(?![*\w])")
_CODE = re.compile(r"`([^`\n]+?)`")
_UL = re.compile(r"^\s*[-*]\s+(.*)$")
_OL = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s*&gt;\s?(.*)$")  # '>' is already escaped when this runs
_FENCE = "```"


def _inline(escaped: str) -> str:
    codes: list[str] = []

    def keep_code(m: re.Match) -> str:
        codes.append(f"<code>{m.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(keep_code, escaped)
    # the url was escaped with the rest: '&' is '&amp;' in the attribute, which is what HTML wants
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}" rel="nofollow ugc noopener" target="_blank">{m.group(1)}</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def render(markdown: str | None) -> str:
    """Markdown source to safe HTML."""
    if not markdown:
        return ""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    in_fence = False
    fence: list[str] = []

    def end_paragraph() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(_inline(html.escape(p)) for p in paragraph) + "</p>")
            paragraph.clear()

    def end_list() -> None:
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    for raw in lines:
        if raw.strip().startswith(_FENCE):
            if in_fence:
                out.append("<pre><code>" + html.escape("\n".join(fence)) + "</code></pre>")
                fence.clear()
                in_fence = False
            else:
                end_paragraph()
                end_list()
                in_fence = True
            continue
        if in_fence:
            fence.append(raw)
            continue
        if not raw.strip():
            end_paragraph()
            end_list()
            continue
        escaped = html.escape(raw)
        quote = _QUOTE.match(escaped)
        ul, ol = _UL.match(raw), _OL.match(raw)
        if quote:
            end_paragraph()
            end_list()
            out.append("<blockquote>" + _inline(quote.group(1)) + "</blockquote>")
        elif ul or ol:
            end_paragraph()
            kind = "ul" if ul else "ol"
            if list_kind != kind:
                end_list()
                out.append(f"<{kind}>")
                list_kind = kind
            out.append("<li>" + _inline(html.escape((ul or ol).group(1))) + "</li>")
        else:
            end_list()
            paragraph.append(raw)
    if in_fence:  # an unclosed fence still shows its code
        out.append("<pre><code>" + html.escape("\n".join(fence)) + "</code></pre>")
    end_paragraph()
    end_list()
    return "\n".join(out)
