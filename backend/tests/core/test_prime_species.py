"""Prime species for Stem Mapping: ids, matching and colours (core/prime_species.py)."""
import re

import pytest
from sqlalchemy import text

from app.core.prime_species import (
    OTHER_COLOR,
    PRIME_SPECIES,
    prime_species_code,
    tree_group,
)


def test_there_are_21_unique_codes_names_and_colours():
    assert [s.code for s in PRIME_SPECIES] == list(range(1, 22))
    assert len({s.name for s in PRIME_SPECIES}) == 21
    colours = [s.color.upper() for s in PRIME_SPECIES]
    assert len(set(colours)) == 21
    assert OTHER_COLOR.upper() not in colours
    assert all(re.fullmatch(r"#[0-9A-F]{6}", c) for c in colours)


def test_codes_are_the_species_table_species_code(db):
    """The owner's ids ARE tree_species_coefficients.species_code -- if the species
    table is seeded, every prime name must sit on its own code."""
    rows = db.execute(
        text("SELECT scientific_name, species_code FROM tree_species_coefficients WHERE species_code BETWEEN 1 AND 21")
    ).all()
    if not rows:
        pytest.skip("species table not seeded in the test DB")
    in_db = {r.scientific_name.strip().lower(): r.species_code for r in rows}
    for s in PRIME_SPECIES:
        if s.name.lower() in in_db:
            assert in_db[s.name.lower()] == s.code, s.name


@pytest.mark.parametrize("name,code", [
    ("Shorea robusta", 18),
    ("  shorea   ROBUSTA ", 18),            # case / spacing
    ("Albizia lebbeck", 4),                  # genus group "Albizia spp"
    ("Albizia chinensis", 4),
    ("Quercus semecarpifolia", 16),
    ("Abies pindrow", 1),
    ("Tsuga dumosa", 21),
    ("Adina cordifolia", 3),                # correct spelling of the listed "cardifolia"
    ("Toona ciliata", 8),                   # accepted name of Cedrela toona
    ("Pinus roxburghii", 14),
    ("Pinus wallichiana", 15),
])
def test_matching_exact_alias_and_genus_group(name, code):
    assert prime_species_code(name) == code


@pytest.mark.parametrize("name", [
    "Castanopsis indica", "Artocarpus lakoocha", "Pinus armandii",   # Pinus is NOT a genus group
    "Terminalia chebula", "Acacia nilotica", "Schima", "", None,
])
def test_everything_else_is_other(name):
    assert prime_species_code(name) is None


@pytest.mark.parametrize("remark,group", [
    ("Mother Tree", "mother"), ("mother tree", "mother"),
    ("Felling Tree", "felling"), ("Seedling", "seedling"),
    (None, "other"), ("", "other"), ("something else", "other"),
])
def test_tree_group(remark, group):
    assert tree_group(remark) == group
