"""The designated NTFP list: Forest Regulations 2079, Schedule-7 (अनुसूची-७), pages 120-130 of the Law Commission text."""
import glob
import re
from collections import Counter

import pytest

from app.core.ntfp import ntfp_species, part_ne
from app.core.ntfp_schedule7 import GROUPS, ROWS, designated_entries, designated_names, scientific_names

PDF = glob.glob(r"D:\forest_management\testData\Document\वन-नियमावली-*.pdf")


def test_the_list_has_the_regulations_318_entries_in_eight_groups():
    assert len(ROWS) == 318
    assert dict(Counter(r[0] for r in ROWS)) == {"क": 74, "ख": 33, "ग": 46, "घ": 18, "ङ": 90, "च": 47, "छ": 10}
    assert set(GROUPS) == {"क", "ख", "ग", "घ", "ङ", "च", "छ"}


def test_serial_numbers_run_1_to_n_within_each_group_with_no_gaps():
    for g, n in {"क": 74, "ख": 33, "ग": 46, "घ": 18, "ङ": 90, "च": 47, "छ": 10}.items():
        assert [r[1] for r in ROWS if r[0] == g] == list(range(1, n + 1)), g


def test_every_entry_has_a_name_and_a_price_and_only_the_piece_price_is_not_per_kilogram():
    assert all(r[2].strip() and r[4] > 0 for r in ROWS)
    assert [(r[2], r[4]) for r in ROWS if r[5] != "kg"] == [("पाँच औंले", 500)]
    assert max(r[4] for r in ROWS) == 31000  # yarsagumba


@pytest.mark.skipif(not PDF, reason="the Law Commission PDF is not on this machine")
def test_the_transcription_matches_the_published_text():
    import pymupdf

    doc = pymupdf.open(PDF[0])
    text = " ".join(doc[i].get_text() for i in range(119, 130))
    digits = str.maketrans("०१२३४५६७८९", "0123456789")
    prices = [int(x.translate(digits).replace(",", "")) for x in re.findall(r"([0-9०-९][0-9०-९,]*)\s*[।]", text)]
    assert prices == [r[4] for r in ROWS]  # all 318 prices, in order
    flat = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", text.lower().replace("-", "")))
    for g, n, ne, sci, price, unit in ROWS:
        for part in re.split(r"[/,]", sci):
            words = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", part.lower().replace("-", ""))).strip().split()
            if len(words) < 2 or part.lower().startswith("insect gall"):
                continue
            key = " ".join(words[:2]) if words[1] != "spp" else words[0]
            assert key in flat, f"{g}{n}: {sci!r} is not in the published text"


def test_printed_scientific_names_are_split_and_spelling_slips_corrected_for_matching():
    assert scientific_names("Alstonia scholaris/A.neriifolia") == ["alstonia scholaris", "alstonia neriifolia"]
    assert scientific_names("Viscum album , V. articulatum") == ["viscum album", "viscum articulatum"]
    assert scientific_names("Pinus spp.") == ["pinus"]
    assert scientific_names("Pitax nirgundi") == ["vitex negundo"]  # printed with a slip
    assert scientific_names("Delphinium denudatum/Aconitum palmatum/Aconitum orochryseum") == [
        "delphinium denudatum", "aconitum palmatum", "aconitum orochryseum"]
    for not_a_plant in ("", "Orchid", "Lichen", "Wild mushroom", "Bee honey", "Lac gum", "Rock exudate/Asphaltum", "Rdix tinosporae"):
        assert scientific_names(not_a_plant) == []


def test_a_species_on_the_list_matches_only_itself_and_a_genus_on_the_list_matches_the_whole_genus():
    walnut = designated_entries("Juglans regia L.")
    assert sorted((e["group"], e["price"]) for e in walnut) == [("ख", 100), ("ङ", 5), ("ङ", 10)]
    # Acacia concinna is listed as a species; Acacia sinuata is not, and must not be swept in through the genus
    assert designated_entries("Acacia concinna") and designated_entries("Acacia sinuata") == []
    # Pinus is listed as a genus (bark, resin) and Pinus roxburghii as a species (seed)
    assert {e["group"] for e in designated_entries("Pinus wallichiana")} == {"ख", "छ"}
    assert {e["group"] for e in designated_entries("Pinus roxburghii")} == {"ख", "छ", "ङ"}
    # a record kept only at genus level matches the genus entries, not the species-level ones
    assert {e["group"] for e in designated_entries("Pinus spp.")} == {"ख", "छ"}
    assert designated_entries("Quercus semecarpifolia") == []


def test_the_table_text_for_a_listed_species():
    herb = ntfp_species([{"name": "पाँचऔंले", "scientific_name": "Dactylorhiza hatagirea", "abundance": "rare"}])[0]
    assert herb["parts"] == "जरा तथा गानो" and herb["price_text"] == "जरा तथा गानो रु. ५०० प्रतिगोटा"
    assert part_ne("छ") == "गम, रेजिन, लोहावन"


def test_every_name_on_the_list_can_be_recorded_in_the_species_master(db):
    """Migration 127 added what the master lacked: every species the list names, and every genus it names that the master had no
    species of. Rows already in the master were left as they were."""
    from sqlalchemy import text

    rows = db.execute(text("SELECT scientific_name FROM biodiversity_species WHERE category = 'vegetation'")).fetchall()
    species, genera = set(), set()
    for (sci,) in rows:
        w = re.sub(r"[^a-z ]", " ", sci.lower().replace("-", "")).split()
        if len(w) >= 2 and w[1] not in ("spp", "sp"):
            species.add(" ".join(w[:2]))
        if w:
            genera.add(w[0])
    missing = [n for n in designated_names() if (n in species if " " in n else n in genera)]
    assert len(missing) == len(designated_names()), [n for n in designated_names() if n not in species and n not in genera][:10]


def test_the_added_rows_are_unique_and_say_where_they_came_from(db):
    from sqlalchemy import text

    added = db.execute(text("SELECT scientific_name, nepali_name, sub_category, primary_use FROM biodiversity_species WHERE notes LIKE :n"),
                       {"n": "%अनुसूची-७%"}).fetchall()
    assert len(added) > 100
    names = [a.scientific_name.lower() for a in added]
    assert len(names) == len(set(names))
    assert all(a.nepali_name.strip() for a in added)
    assert all(a.sub_category is None and a.primary_use is None for a in added)  # nothing else about them is guessed


def test_a_species_price_overrides_the_genus_price_for_the_same_part():
    # Aconitum heterophyllum is priced by name for the roots (Rs 15); "Aconitum spp." (Rs 10, also roots) is for the other species
    herb = designated_entries("Aconitum heterophyllum")
    assert [(e["group"], e["price"]) for e in herb if e["group"] == "क"] == [("क", 15)]
    other = designated_entries("Aconitum violaceum")
    assert [(e["group"], e["price"]) for e in other] == [("क", 10)]
    # a part the species is not priced for still falls back to the genus: Pinus roxburghii seed by name, bark and resin by genus
    assert sorted((e["group"], e["price"]) for e in designated_entries("Pinus roxburghii")) == [("ख", 2), ("ङ", 200), ("छ", 12)]
