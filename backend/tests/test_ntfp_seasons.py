"""The DRAFT NTFP harvest seasons (``app.core.ntfp_seasons``): what is machine-checked about them."""
import glob
import re

import pytest

from app.core import ntfp_seasons as ns

PDF = glob.glob(r"D:\forest_management\testData\Document\NTFP_survey.pdf")
_DIGITS = str.maketrans(")!@#$%^&*(", "0123456789")
# the PDF pages (not the printed numbers: pdf = printed + 10) that hold each table
PAGES = {"T5": (29, 30), "T7": (34,), "T10": (38,), "T13": (41, 42)}


def test_the_draft_is_marked_unreviewed_and_has_47_rows_in_four_tables():
    assert ns.REVIEWED is False
    assert len(ns.ROWS) == 47
    assert {t: sum(r[0] == t for r in ns.ROWS) for t in PAGES} == {"T5": 20, "T7": 7, "T10": 9, "T13": 11}


def test_seasons_parse_to_months_and_ranges_wrap_past_chaitra():
    assert ns.parse_season("भदौ - असोज") == [(5, 6)]
    assert ns.parse_season("चैत-जेठ, भदौ-कार्तिक") == [(12, 2), (5, 7)]
    assert ns.parse_season("भदौ") == [(5, 5)]
    assert ns.parse_season("माघ–वैशाख") == [(10, 1)]
    assert ns.months_covered([(12, 2), (5, 7)]) == [1, 2, 5, 6, 7, 12]
    assert ns.months_covered([(10, 1)]) == [1, 10, 11, 12]


def test_the_variant_spellings_the_guideline_uses_are_the_same_month():
    assert ns.parse_season("आसोज")[0] == ns.parse_season("असोज")[0] == ns.parse_season("आश्विन")[0] == (6, 6)
    assert ns.parse_season("भाद्र") == ns.parse_season("भदौ") and ns.parse_season("श्रावण") == ns.parse_season("साउन")
    assert ns.parse_season("जेष्ठ") == ns.parse_season("जेठ") and ns.parse_season("वैशाख") == ns.parse_season("बैशाख")


def test_a_misread_is_refused_rather_than_turned_into_a_wrong_month():
    for bad in ("भदौ - ", "", "भदौ - कार्तिकx", "भदौ असोज कार्तिक"):
        with pytest.raises(ValueError):
            ns.parse_season(bad)


def test_every_row_parses_and_the_page_is_inside_its_table():
    for row in ns.seasons():
        assert row["ranges"] and all(1 <= a <= 12 and 1 <= b <= 12 for a, b in row["ranges"]), row["nepali_name"]
        assert row["reviewed"] is False


# ── against the PDF ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pages():
    if not PDF:
        pytest.skip("the guideline PDF is not on this machine")
    from pypdf import PdfReader

    return [p.extract_text() or "" for p in PdfReader(PDF[0]).pages]


def _ranges(page_text):
    """The altitude ranges printed on a page, in order, decoded from the Preeti digits."""
    text = page_text.translate(_DIGITS)
    return [(int(a), int(b)) for a, b in re.findall(r"(?<!\d)(\d{3,4})\s*[\u2013\u2014\-\ufffd]\s*(\d{3,4})(?!\d)", text)]


def test_altitudes_match_the_text_layer_table_by_table(pages):
    for table, pdf_pages in PAGES.items():
        printed = [rg for n in pdf_pages for rg in _ranges(pages[n - 1])]
        expected = [(r[5], r[6]) for r in ns.ROWS if r[0] == table]
        if table == "T13":  # the printed table gives Hippophae's two ranges in one row; page 42's body text has other numbers too
            printed = [rg for rg in printed if rg in expected]
        assert printed == expected, table


def _plain(text):
    return re.sub(r"[^a-z.]", "", text.lower())


def test_every_latin_name_is_on_its_page(pages):
    for row in ns.ROWS:
        table, sci = row[0], re.sub(r"\s+(spp?)\.?$", "", row[4])
        text = _plain(" ".join(pages[n - 1] for n in PAGES[table]))
        words = sci.split()
        assert _plain(sci) in text or _plain(words[-1]) in text, (table, row[4])
