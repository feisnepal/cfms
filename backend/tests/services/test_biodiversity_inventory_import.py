"""Listing the field inventory's unique tree species in the Biodiversity record (owner rule 2026-10-10)."""
from app.services.biodiversity_inventory_import import abundance_for, normalize


def test_names_are_compared_on_genus_and_species_only():
    assert normalize("Shorea robusta Roxb.") == "shorea robusta"
    assert normalize("  SHOREA   robusta var. x ") == "shorea robusta"
    assert normalize("Macrobrachium spp.") == "macrobrachium spp"
    assert normalize(None) == "" and normalize("") == ""


def test_abundance_follows_how_widespread_the_species_is_across_the_plots():
    assert abundance_for(30, 48) == "abundant"   # 62%
    assert abundance_for(15, 48) == "common"     # 31%
    assert abundance_for(6, 48) == "occasional"  # 12.5%
    assert abundance_for(2, 48) == "rare"
    assert abundance_for(0, 0) == "rare"          # no plots: never a division by zero


def test_a_known_synonym_is_recorded_under_the_name_the_list_uses():
    from app.services.biodiversity_inventory_import import SYNONYMS

    assert SYNONYMS[normalize("Terminalia alata Heyne")] == normalize("Terminalia tomentosa")
