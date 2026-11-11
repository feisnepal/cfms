"""NTFP price by part, with labelled estimates where Schedule-7 has no line (``app.core.ntfp_price``)."""
import pytest

from app.core.ntfp_methods import profiles
from app.core.ntfp_price import groups_for, part_median, prices_for


def _for(key):
    r = next(p for p in profiles() if p["species_key"] == key)
    return prices_for(key, r["scientific_name"], r["regulation_name"], r.get("part_groups"), r.get("parts_used_ne"))


def test_the_part_median_not_the_mean():
    assert part_median("ख") == 10   # bark: median 10 (mean 16.3)
    assert part_median("च") == 5    # whole plant: median 5 (mean 688, skewed by a few very dear lines)
    assert part_median("ग") == 3


def test_a_listed_species_takes_its_schedule_7_line_for_the_part_it_is_harvested_for():
    (p,) = _for("zanthoxylum armatum")
    assert (p["group"], p["basis"], p["estimated"]) == ("ङ", "schedule7", False) and p["price"] > 0
    (p,) = _for("nardostachys jatamansi")  # the guideline spells it grandiflora: an alias
    assert (p["group"], p["price"], p["estimated"]) == ("क", 75, False)


def test_lichen_takes_its_schedule_7_line():
    (p,) = _for("lichens")
    assert (p["group"], p["price"], p["basis"]) == ("च", 50, "schedule7")


def test_allo_is_estimated_from_its_nettle_relative_and_says_so():
    (p,) = _for("girardinia diversifolia")
    assert (p["group"], p["price"], p["basis"], p["estimated"]) == ("ख", 15, "relative", True)
    assert "Boehmeria rugulosa" in p["basis_note"] and "Urticaceae" in p["basis_note"]


@pytest.mark.parametrize("key,group,price", [("daphne bholua", "ख", 10), ("edgeworthia gardneri", "ख", 10), ("tagetes minuta", "च", 5)])
def test_species_with_no_relative_take_the_part_median_and_say_so(key, group, price):
    (p,) = _for(key)
    assert (p["group"], p["price"], p["basis"], p["estimated"]) == (group, price, "part_median", True)
    assert p["basis_note"].startswith("estimated")


def test_parts_are_read_from_the_annex_1_words_when_there_is_no_card():
    assert groups_for(None, "पूरै बिरुवा") == ["च"]
    assert groups_for(None, "जरा, प्रकन्द") == ["क"]
    assert groups_for(None, "फल, बोक्रा, बीउ") == ["ङ", "ख"]
    assert groups_for(["ख"], "जरा") == ["ख"]  # the card wins


def test_every_profile_gets_a_price_for_every_part_and_estimates_are_never_unmarked():
    for r in profiles():
        entries = prices_for(r["species_key"], r["scientific_name"], r["regulation_name"], r.get("part_groups"), r.get("parts_used_ne"))
        assert entries, r["species_key"]
        for e in entries:
            assert e["price"] > 0
            assert e["estimated"] == (e["basis"] != "schedule7")
            assert e["estimated"] is False or e["basis_note"].startswith("estimated")
