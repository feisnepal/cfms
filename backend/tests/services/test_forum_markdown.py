"""The forum's markdown renderer must never let user text become markup."""
import re

import pytest

from app.services.forum.markdown_lite import render


@pytest.mark.parametrize("attack", [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "[click](javascript:alert(1))",
    "[click](data:text/html;base64,PHNjcmlwdD4=)",
    '[x](https://a.com" onmouseover="alert(1))',
    "**<b onclick=1>bold</b>**",
    "`<script>`",
    "```\n<script>alert(1)</script>\n```",
    "> <iframe src=//evil>",
    "- <svg onload=1>",
])
def test_no_raw_markup_survives(attack):
    out = render(attack)
    allowed = {"p", "br", "strong", "em", "code", "pre", "ul", "ol", "li", "blockquote", "a"}
    for m in re.finditer(r"<(/?)([a-zA-Z0-9]+)([^>]*)>", out):
        assert m.group(2).lower() in allowed, (m.group(0), out)
        if m.group(2).lower() == "a" and not m.group(1):
            assert re.fullmatch(r' href="(https?://|mailto:)[^"]*" rel="nofollow ugc noopener" target="_blank"', m.group(3)), (m.group(0), out)
        elif m.group(2).lower() != "a":
            assert m.group(3).strip() == "", (m.group(0), out)  # no attributes on any other tag


def test_basic_formatting():
    out = render("Hello **bold** and *italic* and `code`.\n\n- one\n- two\n\n1. first\n2. second")
    assert "<strong>bold</strong>" in out and "<em>italic</em>" in out and "<code>code</code>" in out
    assert out.count("<li>") == 4 and "<ul>" in out and "<ol>" in out


def test_links_are_nofollow_and_http_only():
    out = render("[site](https://example.org/a?b=1&c=2) and [mail](mailto:a@b.org)")
    assert 'href="https://example.org/a?b=1&amp;c=2"' in out
    assert 'rel="nofollow ugc noopener"' in out and 'href="mailto:a@b.org"' in out


def test_devanagari_and_empty_input():
    assert "समुदायिक वन" in render("समुदायिक वन")
    assert render(None) == "" and render("   ") == ""


def test_code_block_is_escaped_and_unclosed_fence_still_renders():
    assert "&lt;b&gt;" in render("```\n<b>\n```")
    assert "<pre><code>" in render("```\nno end")
