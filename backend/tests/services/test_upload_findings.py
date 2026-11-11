"""The shared upload findings: every catalogue entry is complete in both languages (UPLOAD_EXPERIENCE_PLAN.md, UP-2.1)."""
from __future__ import annotations

import re

import pytest

from app.services.upload.findings import CATALOGUE, finding, upload_error

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("code", sorted(CATALOGUE))
def test_every_entry_has_a_title_and_a_fix_in_both_languages(code):
    entry = CATALOGUE[code]
    assert set(entry) == {"title", "fix"}
    for part in ("title", "fix"):
        assert set(entry[part]) == {"en", "ne"}, f"{code}.{part}"
        assert entry[part]["en"].strip() and entry[part]["ne"].strip(), f"{code}.{part} is empty in a language"


@pytest.mark.parametrize("code", sorted(CATALOGUE))
def test_english_and_nepali_use_the_same_placeholders(code):
    """A placeholder missing from one language means that language shows a hole (or a raw {name})."""
    for part in ("title", "fix"):
        en = set(_PLACEHOLDER.findall(CATALOGUE[code][part]["en"]))
        ne = set(_PLACEHOLDER.findall(CATALOGUE[code][part]["ne"]))
        assert en == ne, f"{code}.{part}: en {sorted(en)} vs ne {sorted(ne)}"


def test_every_nepali_text_really_is_nepali():
    for code, entry in CATALOGUE.items():
        for part in ("title", "fix"):
            assert re.search(r"[ऀ-ॿ]", entry[part]["ne"]), f"{code}.{part} has no Devanagari text"


def test_a_finding_fills_its_placeholders_and_never_leaks_a_raw_one():
    f = finding("household.duplicate_house_no", found=4, rows=[4, 9, 11], file="hh.csv")
    assert "House number 4 appears more than once (rows 4, 9, 11)" in f.title_en
    assert "घर नम्बर 4" in f.title_ne
    assert f.where == {"file": "hh.csv", "rows": [4, 9, 11]} and f.severity == "warning"
    for text in (f.title_en, f.title_ne, f.fix_en, f.fix_ne):
        assert "{" not in text


def test_a_long_row_list_is_shortened_but_counted():
    f = finding("household.row_invalid", found="a negative count", rows=list(range(3, 40)))
    assert "(+" in f.fix_en and f.where["rows"][-1] == 39 and "37 rows have a problem" in f.title_en


def test_upload_error_is_a_read_detail_compatible_400_with_the_findings_inside():
    err = upload_error(400, finding("file.empty"), finding("file.no_rows"))
    d = err.detail
    assert err.status_code == 400 and d["code"] == "file.empty"
    assert "The file is empty." in d["message"] and "फाइल खाली छ" in d["message_np"]
    assert [x["code"] for x in d["findings"]] == ["file.empty", "file.no_rows"]
    assert d["findings"][0]["fix_en"] and d["findings"][0]["fix_ne"]
