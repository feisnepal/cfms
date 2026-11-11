"""One name per species: ``app.core.species_synonyms`` and its effect on the Schedule-7 matcher."""
import pytest

from app.core.ntfp_schedule7 import designated_entries
from app.core.species_synonyms import SYNONYMS, aliases_of, canonical_key, canonical_name


def test_a_synonym_reads_as_its_canonical_name():
    assert canonical_name("Nardostachys grandiflora") == "Nardostachys jatamansi"
    assert canonical_name("nardostachys  GRANDIFLORA (DC.) Kitam.") == "Nardostachys jatamansi"  # case, spacing, author ignored
    assert canonical_key("Valeriana jatamansii Jones") == "valeriana jatamansi"
    assert canonical_name("Juglans regia") == "Juglans regia"                                    # not listed: unchanged
    assert canonical_key("Berberis spp.") == "berberis"


def test_aliases_are_listed_per_canonical_name():
    assert aliases_of("Nardostachys jatamansi") == ["Nardostachys grandiflora"]
    assert aliases_of("Cinnamomum tenuipile") == ["Cinnamomum glaucescens"]


def test_no_canonical_name_is_itself_an_alias_and_there_are_no_chains():
    canon = {c.lower() for c in SYNONYMS.values()}
    assert not canon & {a.lower() for a in SYNONYMS}


@pytest.mark.parametrize("recorded", ["Nardostachys jatamansi", "Nardostachys grandiflora", "nardostachys grandiflora DC."])
def test_the_regulation_matcher_finds_spikenard_under_either_name(recorded):
    entries = designated_entries(recorded)
    assert entries and entries[0]["price"] == 75   # Schedule-7 क 30


def test_the_matcher_still_does_not_sweep_in_unrelated_species():
    assert designated_entries("Nardostachys nonexistent") == []
    assert designated_entries("Valeriana officinalis") == []
