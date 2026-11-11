"""The NTFP method profiles: Resource Survey Guideline 2069, Annex 1 and 2, Tables 3 and 4 (``app.core.ntfp_methods``)."""
import glob
import re

import pytest

from app.core.ntfp_methods import ANNEX1, regulation_name, CARDS, GROWTH_FORMS, area_band, intensity_pct, profiles, species_key
from app.core.ntfp_schedule7 import designated_entries

PDF = glob.glob(r"D:\forest_management\testData\Document\NTFP_survey.pdf")
_DIGITS = str.maketrans(")!@#$%^&*(", "0123456789")  # the guideline is typeset in the Preeti font: its text layer holds these ASCII keys


@pytest.fixture(scope="module")
def pages():
    if not PDF:
        pytest.skip("the guideline PDF is not on this machine")
    from pypdf import PdfReader

    return [p.extract_text() or "" for p in PdfReader(PDF[0]).pages]


def test_annex_1_lists_30_species_numbered_1_to_30_and_annex_2_has_33_cards():
    assert [r[0] for r in ANNEX1] == list(range(1, 31))
    assert len(CARDS) == 35


def test_each_species_is_one_profile_and_the_merge_keeps_both_annexes():
    rows = profiles()
    keys = [r["species_key"] for r in rows]
    assert len(keys) == len(set(keys))
    both = [r for r in rows if r["priority_serial"] and r["has_method_card"]]
    assert {r["species_key"] for r in both} >= {"nardostachys jatamansi", "valeriana jatamansi", "zanthoxylum armatum"}
    assert sum(1 for r in rows if r["priority_serial"]) == 30
    assert sum(1 for r in rows if r["has_method_card"]) == 35


def test_a_species_without_a_latin_name_is_keyed_by_its_nepali_name():
    assert species_key(None, "माइकोपिला") == "np:माइकोपिला"
    assert [r["species_key"] for r in profiles() if r["species_key"].startswith("np:")] == ["np:माइकोपिला"]
    assert species_key("Berberis spp.", "चुत्रो") == "berberis"


def test_every_card_is_consistent():
    for sci, nepali, _life, growth, _part, groups, method, pmin, pmax, _m, nmin, nmax, pct, cf, proc in CARDS:
        assert growth in GROWTH_FORMS, nepali
        assert method in ("destructive", "semi_destructive", "non_destructive"), nepali
        assert 0 < pmin <= pmax, nepali
        assert groups and set(groups) <= set("कखगघङच"), nepali
        assert (nmin is None) == (nmax is None) and (nmin is None or nmin <= nmax), nepali
        assert pct is None or 0 < pct <= 100, nepali
        assert cf is None or 0 < cf < 1, nepali
        assert proc, nepali


def test_the_profile_joins_the_regulations_price_lines_where_the_regulation_lists_the_plant():
    unlisted = {r["scientific_name"] for r in profiles() if r["scientific_name"] and not r["regulation_name"]}
    assert unlisted == {"Edgeworthia gardneri", "Daphne bholua", "Girardinia diversifolia", "Tagetes minuta", "Lichens"}
    assert regulation_name("Nardostachys grandiflora") == "Nardostachys jatamansi"
    assert designated_entries(regulation_name("Valeriana jatamansii"))
    assert regulation_name("Cinnamomum glaucescens") == "Cinnamomum tenuipile"


def test_one_canonical_name_per_species_with_the_guidelines_spelling_kept_as_an_alias():
    by = {r["species_key"]: r for r in profiles()}
    assert "nardostachys grandiflora" not in by and "valeriana jatamansii" not in by and "cinnamomum glaucescens" not in by
    assert by["nardostachys jatamansi"]["scientific_name"] == "Nardostachys jatamansi"
    assert by["nardostachys jatamansi"]["aliases"] == ["Nardostachys grandiflora"]
    assert by["cinnamomum tenuipile"]["aliases"] == ["Cinnamomum glaucescens"]
    assert by["zanthoxylum armatum"]["aliases"] == []


def test_table_4_intensity_by_forest_size():
    assert [area_band(a) for a in (99.9, 100, 500, 500.1)] == ["lt100", "100_500", "100_500", "gt500"]
    assert intensity_pct("tree", 50) == (1.0, 1.0)
    assert intensity_pct("herb", 50) == (0.05, 0.1)
    assert intensity_pct("shrub", 300) == (0.5, 0.5)
    assert intensity_pct("climber", 300) == (0.5, 0.5)  # climbers follow the shrubs
    assert intensity_pct("tree", 800) == (0.1, 0.5)
    assert intensity_pct("lichen", 800) == (0.01, 0.01)


def test_table_3_plot_sizes():
    assert GROWTH_FORMS["tree"][1:] == (100.0, 500.0)
    assert GROWTH_FORMS["shrub"][1:] == (25.0, 25.0)
    assert GROWTH_FORMS["herb"][1:] == (4.0, 25.0)


# ── checked against the PDF's text layer ─────────────────────────────────────────────────────────────────────────────────────────

def _plain(text):
    """Lower case letters and dots only: the italic font's text layer splits a word at its ligatures (``grandifl ora``) and breaks lines
    inside names, so spaces are ignored on both sides."""
    return re.sub(r"[^a-z.]", "", text.lower())


# The guideline prints no Latin name for these; Schedule-7 prints them against the same Nepali name.
FROM_THE_REGULATION = {"Prinsepia utilis": "ढटेलो", "Polypodiodes amoena": "विषफेज"}


def test_the_names_filled_in_from_the_regulation_are_the_regulations_for_that_nepali_name():
    from app.core.ntfp_schedule7 import ROWS

    for sci, nepali in FROM_THE_REGULATION.items():
        assert any(r[3] == sci and nepali in r[2] for r in ROWS), sci
        assert designated_entries(sci), sci


def test_every_latin_name_is_in_the_guideline(pages):
    text = _plain(" ".join(pages))
    printed = [a[1] for a in ANNEX1] + [c[0] for c in CARDS if c[0]]  # the guideline's own spelling, not the canonical name
    for sci in printed:
        if sci == "Lichens" or sci in FROM_THE_REGULATION:
            continue
        words = sci.replace(" spp.", "").split()
        # the guideline abbreviates a genus it has just named ("H. tibetana"), and its text layer loses the genus of a few names
        assert _plain(" ".join(words)) in text or (len(words) == 2 and (_plain(f"{words[0][0]}. {words[1]}") in text or _plain(words[1]) in text)), sci


def test_annex_1_altitudes_match_the_text_layer(pages):
    decoded = []
    for n in (53, 54):
        for a, b in re.findall(r"([)!@#$%^&*(]{3,4})\W([)!@#$%^&*(]{3,4})", pages[n - 1]):
            decoded.append((int(a.translate(_DIGITS)), int(b.translate(_DIGITS))))
    expected = [(r[3], r[4]) for r in ANNEX1 if r[3]]
    assert decoded == expected


def test_conversion_factors_match_the_text_layer(pages):
    found = []
    for n in range(55, 67):
        found += [float(m.translate(_DIGITS)) for m in re.findall(r"^\)\.[)!@#$%^&*(]{2,4}", pages[n - 1], re.M)]
    assert sorted(found) == sorted(c[13] for c in CARDS if c[13])


def test_every_seed_key_is_a_column_of_the_table():
    from app.models.ntfp_method import NtfpMethodProfile

    cols = {c.name for c in NtfpMethodProfile.__table__.columns}
    for row in profiles():
        assert set(row) <= cols, set(row) - cols


def test_an_intensity_under_the_guidelines_lowest_figure_is_marked():
    from app.core.ntfp_methods import below_guideline

    assert below_guideline("shrub", 300, 0.25) is True          # Table 4 gives shrubs of 100-500 ha exactly 0.5 %
    assert below_guideline("shrub", 300, 0.5) is False and below_guideline("shrub", 300, 1.0) is False
    assert below_guideline("tree", 800, 0.2) is False           # over 500 ha trees take 0.1-0.5 %: anywhere inside the range is fine
    assert below_guideline("tree", 800, 0.05) is True
    assert below_guideline("herb", 50, 0.05) is False and below_guideline("herb", 50, 0.04) is True
