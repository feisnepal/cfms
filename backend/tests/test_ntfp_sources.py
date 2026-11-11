"""The sourced method-card values (``app.core.ntfp_sources``, ``ntfp_provisional``): their invariants, and the figures checked against the documents they cite."""
import collections
import glob
import re

import pytest

from app.core import ntfp_provisional as prov
from app.core import ntfp_sources as src
from app.core.ntfp_methods import profiles
from app.core.ntfp_schedule7 import ROWS

DOCS = r"D:\forest_management\testData\Document\sources\\"
PROFILES = {p["species_key"]: p for p in profiles()}


@pytest.fixture(scope="module")
def values():
    return src.all_documented_values(list(PROFILES.values()))


def _groups(vals):
    g = collections.defaultdict(list)
    for v in vals:
        g[(v["species_key"], v["field"], v["part_group"])].append(v)
    return g


# ── invariants ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_value_names_a_known_source_field_and_status(values):
    for v in values:
        assert v["source_key"] in src.SOURCES and v["field"] in src.FIELDS and v["status"] in src.STATUSES, v
        assert v["locator"], v                       # the table or page is always given
        assert v["value_num"] is not None or v["value_text"] is not None, v


def test_exactly_one_value_is_chosen_for_every_fact(values):
    for key, rows in _groups(values).items():
        assert sum(r["chosen"] for r in rows) == 1, key


def test_a_lead_gives_no_values_and_a_read_source_gives_at_least_one(values):
    used = collections.Counter(v["source_key"] for v in values)
    for k, s in src.SOURCES.items():
        if s["read_status"] == "lead":
            assert used[k] == 0, k
    for k in ("DOF2069", "ANSAB2010", "ANSAB2022", "NWPC2014", "FSI-NFI", "RULE"):
        assert used[k] > 0, k


def test_the_choice_prefers_status_then_authority_then_the_newer_source():
    mk = lambda source, status: src._v("x", "aah_pct", source, "t", status, num=1)
    rows = [mk("ANSAB2010", "documented"), mk("ANSAB2022", "documented"), mk("DOF2069", "provisional")]
    src.finalize_chosen(rows)
    assert [r["chosen"] for r in rows] == [False, True, False]     # documented beats provisional; the newer of two equals wins
    rows = [mk("ANSAB2022", "documented"), mk("DOF2069", "documented")]
    src.finalize_chosen(rows)
    assert [r["chosen"] for r in rows] == [False, True]            # the Nepal guideline outranks an NGO manual


# ── what the sources say, where they disagree ───────────────────────────────────────────────────────────────────────────────

def test_the_shrub_plot_is_25_in_the_nepal_guideline_and_the_other_sizes_are_kept_beside_it(values):
    rows = _groups(values)[("form:shrub", "plot_area_sqm", None)]
    by = {r["source_key"]: r for r in rows}
    assert float(by["DOF2069"]["value_num"]) == 25 and by["DOF2069"]["chosen"]
    assert float(by["ANSAB2010"]["value_num"]) == 100 and not by["ANSAB2010"]["chosen"]
    assert float(by["FSI-NFI"]["value_num"]) == 9 and not by["FSI-NFI"]["chosen"]


def test_the_annual_allowable_harvest_values(values):
    g = _groups(values)
    assert float(next(r for r in g[("neopicrorhiza scrophulariiflora", "aah_pct", "क")] if r["chosen"])["value_num"]) == 80
    bark = next(r for r in g[("cinnamomum tamala", "aah_pct", "ख")] if r["chosen"])
    leaf = next(r for r in g[("cinnamomum tamala", "aah_pct", "ग")] if r["chosen"])
    assert (float(bark["value_num"]), float(leaf["value_num"])) == (20, 70)
    assert float(next(r for r in g[("cinnamomum tamala", "rotation_years", "ख")] if r["chosen"])["value_num"]) == 3
    taxus = next(r for r in g[("taxus wallichiana", "aah_pct", "ग")] if r["chosen"])
    assert (float(taxus["value_num"]), float(taxus["value_num2"])) == (50, 60)
    assert next(r for r in g[("tinospora sinensis", "aah_pct", "ग")])["status"] == "provisional"     # ANSAB's species name differs: identity unconfirmed


def test_every_documented_card_value_is_sourced_to_the_guideline_annex(values):
    cards = [p for p in PROFILES.values() if p["has_method_card"]]
    assert len(cards) == 35
    for p in cards:
        rows = _groups(values)
        method = next(r for r in rows[(p["species_key"], "sampling_method", None)] if r["chosen"])
        assert (method["source_key"], method["status"]) == ("DOF2069", "documented"), p["species_key"]


def test_the_seasons_of_the_guideline_are_provisional_and_the_ansab_ones_documented(values):
    seasons = [v for v in values if v["field"] == "season"]
    assert {v["status"] for v in seasons if v["source_key"] == "DOF2069"} == {"provisional"}
    assert {v["calendar"] for v in seasons if v["source_key"] == "DOF2069"} == {"BS"}
    assert {v["calendar"] for v in seasons if v["source_key"] == "ANSAB2022"} == {"AD"}
    jat = _groups(values)[("nardostachys jatamansi", "season", "क")]
    assert next(r for r in jat if r["chosen"])["source_key"] == "ANSAB2022"       # documented outranks an unreviewed reading


# ── provisional cards ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_provisional_cards_cover_every_schedule_7_plant_without_a_documented_card():
    master = lambda key: {"azadirachta indica": "Tree", "acorus calamus": "Medicinal Herb"}.get(key)
    profs, vals = prov.derive(master, PROFILES)
    keys = {p["species_key"] for p in profs}
    s7 = set(prov.schedule7_species())
    documented = {k for k, p in PROFILES.items() if p["has_method_card"]}
    assert keys == s7 - documented
    assert all(p["card_status"] == "provisional" and p["has_method_card"] for p in profs)
    assert all(v["status"] != "documented" or v["source_key"] == "S7-2079" for v in vals)    # nothing derived is passed off as documented


def test_the_growth_form_comes_from_the_master_else_a_flagged_guess():
    master = lambda key: {"azadirachta indica": "Tree"}.get(key)
    profs, vals = prov.derive(master, PROFILES)
    by = {p["species_key"]: p for p in profs}
    growth = {v["species_key"]: v for v in vals if v["field"] == "growth_class"}
    neem = growth["azadirachta indica"]
    assert (by["azadirachta indica"]["growth_class"], neem["status"], neem["source_key"]) == ("tree", "derived", "MASTER")
    guessed = [v for v in growth.values() if v["source_key"] == "RULE"]
    assert guessed and all(v["status"] == "provisional" and "confirm" in v["note"] for v in guessed)


def test_the_plot_size_and_sample_count_follow_the_growth_form_rules():
    profs, _ = prov.derive(lambda k: None, PROFILES)
    for p in profs:
        lo, hi = src.GROWTH_PLOT[p["growth_class"]]
        assert (p["plot_min_sqm"], p["plot_max_sqm"]) == (lo, hi)
        assert (p["n_individuals_min"], p["n_individuals_max"]) == src.GROWTH_SAMPLES[p["growth_class"]]
        assert p["sampling_method"] == src.PART_METHOD[p["part_groups"][0]][0]
        # maturity, conversion factor and sample fraction are never guessed
        assert "conversion_factor" not in p and "maturity_ne" not in p


def test_a_part_group_always_has_a_method_and_the_names_are_readable():
    assert set(src.PART_METHOD) == set("कखगघङचछ")
    assert prov.display_name("berberis") == "Berberis spp." and prov.display_name("zanthoxylum armatum") == "Zanthoxylum armatum"


# ── checked against the documents ──────────────────────────────────────────────────────────────────────────────────────────

def _text(name):
    files = glob.glob(DOCS + name)
    if not files:
        pytest.skip(f"{name} is not on this machine (testData/Document/sources)")
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(files[0]).pages)


def _aah_rows(text, start_marker, end_marker):
    seg = text[text.find(start_marker): text.find(end_marker, text.find(start_marker))]
    out = []
    for line in seg.splitlines():
        m = re.match(r"^\S.*?\s(\d{2})(?:\s*-\s*(\d{2}))?\s*$", line.strip())
        if m and re.search(r"[A-Z][a-z]+ [a-z]+", line):
            out.append((int(m.group(1)), int(m.group(2)) if m.group(2) else None))
    return out


def test_the_ansab_2010_aah_table_matches_the_pdf():
    t = _text("ANSAB2010*.pdf")
    pdf = _aah_rows(t, "LOCAL NAmE SCIENTIFIC NAmE AAh", "TABLE 18")
    code = [(int(a), int(b) if b else None) for k, p, a, b, s, loc, n in src.AAH if s == "ANSAB2010" and loc == "Table 18"]
    assert len(pdf) == 16 and sorted(pdf, key=str) == sorted(code, key=str)


def test_the_ansab_2022_aah_table_matches_the_pdf():
    t = _text("ANSAB2022*.pdf")
    pdf = _aah_rows(t, "AAH (%) from specific block", "Table: Annual allowable harvest")
    code = [(int(a), int(b) if b else None) for k, p, a, b, s, loc, n in src.AAH if s == "ANSAB2022" and loc.startswith("Annex 3, AAH table")]
    assert len(pdf) == 17 and sorted(pdf, key=str) == sorted(code, key=str)


def test_the_ansab_2022_season_texts_are_in_the_pdf():
    t = re.sub(r"\s+", "", _text("ANSAB2022*.pdf"))
    for key, part, a, b, text, note in src._SEASONS:
        if text == "Whole year":
            continue
        assert re.sub(r"\s+", "", text) in t, (key, text)


def test_the_ansab_2010_wintergreen_example_and_tejpat_bark_rule_are_in_the_pdfs():
    inv = re.sub(r"\s+", " ", _text("ANSAB2010*.pdf"))
    assert "75%) IN kg" in inv and "25% leaves undisturbed" in inv and "6 month-1 year" in inv
    harv = re.sub(r"\s+", " ", _text("ANSAB2022*.pdf"))
    assert "Harvest only 20% of bark from a tree in an interval of 3 years" in harv and "Harvest only 70% of the total fruits" in harv


def test_the_indian_figures_are_in_the_working_plan_code_and_the_inventory_slides():
    code = re.sub(r"\s+", " ", _text("NWPC2014*.pdf"))
    assert "at least three trees of different diameter class" in code and "at least five plants" in code and "10 to 20 numbers of each species" in code
    assert "closed season" in code and "sustainable harvesting limits" in code
    assert "relative frequency and relative density" in code and "maximum IVI value is 300" in code
    nfi = re.sub(r"\s+", " ", _text("FSI_NFI*.pdf"))
    assert "Herbs: 1m x 1m" in nfi and "Shrubs: 3m x 3m" in nfi and "0.1 ha" in nfi


def test_the_fao_booklet_states_the_regeneration_principle_the_part_rule_cites():
    gacp = re.sub(r"\s+", " ", _text("FAO_GACP2010*.pdf"))
    assert "regenerate much more easily than roots and barks" in gacp


def _squash(text):
    return re.sub(r"\s+", "", text)


@pytest.mark.parametrize("source,pattern", [("ICFRE-2020", "ICFRE2020*.pdf"), ("MP-ESIP-2022", "MP_ESIP*.pdf")])
def test_the_indian_figures_are_sentences_of_the_documents_they_cite(source, pattern):
    t = _squash(_text(pattern))
    rows = [r for r in src.india_cited() if r[2] == source]
    assert rows
    for species, field, _s, locator, part, num, num2, unit, quote in rows:
        assert _squash(quote) in t, (species, quote)


def test_the_indian_sources_rank_below_the_nepal_ones_and_never_win_over_them():
    assert src.SOURCES["ICFRE-2020"]["read_status"] == "read" and src.SOURCES["MP-ESIP-2022"]["read_status"] == "read"
    assert min(src.SOURCES[k]["tier"] for k in ("ICFRE-2020", "MP-ESIP-2022")) > max(src.SOURCES[k]["tier"] for k in ("DOF2069", "ANSAB2022", "ANSAB2010", "NWPC2014"))
    mk = lambda source: src._v("x", "aah_pct", source, "t", "documented", num=1)
    rows = [mk("MP-ESIP-2022"), mk("ANSAB2010")]
    src.finalize_chosen(rows)
    assert [r["chosen"] for r in rows] == [False, True]
