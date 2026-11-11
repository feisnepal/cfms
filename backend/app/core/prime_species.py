"""Prime species for Stem Mapping -- the 21 species that get a permanent colour.

SSOT. The ids are ``tree_species_coefficients.species_code`` (1..21), so a prime
species is identified by the same code the rest of the system already uses.
Mirrored in ``frontend/src/lib/primeSpecies.ts``; ``tests/core/test_prime_species.py``
and the frontend parity test keep the two copies identical.

Colours are PERMANENT: fixed per species, never assigned by frequency, so a species
looks the same in every forest and every export. They were chosen by farthest-point
sampling in CIELAB (min pairwise dE76 = 25.8; min distance to ``OTHER_COLOR`` = 55),
with the clearest colours given to the species that actually occur in the community
forests (Shorea, Schima, Pinus roxburghii, Terminalia alata, Bombax, Alnus, Albizia).
Twenty-one hues cannot all be told apart at a glance, so the map also encodes the
tree group by SHAPE and offers a legend click to isolate one species.

Every species that is not one of these 21 gets the single ``OTHER_COLOR``.
"""
from __future__ import annotations

import re
from typing import Dict, List, NamedTuple, Optional

OTHER_COLOR = "#9E9E9E"


class PrimeSpecies(NamedTuple):
    code: int          # tree_species_coefficients.species_code
    name: str          # scientific name as listed by the owner
    genus_group: bool  # True for "<Genus> spp": every species of the genus matches
    color: str


PRIME_SPECIES: List[PrimeSpecies] = [
    PrimeSpecies(1, "Abies spp", True, "#1BE0B5"),
    PrimeSpecies(2, "Acacia catechu", False, "#D492EE"),
    PrimeSpecies(3, "Adina cardifolia", False, "#0CE46A"),
    PrimeSpecies(4, "Albizia spp", True, "#E86489"),
    PrimeSpecies(5, "Alnus nepalensis", False, "#FBBA62"),
    PrimeSpecies(6, "Anogeissus latifolia", False, "#924C02"),
    PrimeSpecies(7, "Bombax ceiba", False, "#1B5CB6"),
    PrimeSpecies(8, "Cedrela toona", False, "#7D7B07"),
    PrimeSpecies(9, "Dalbergia sissoo", False, "#755FF2"),
    PrimeSpecies(10, "Syzygium cumini", False, "#99D777"),
    PrimeSpecies(11, "Hymenodictyon excelsum", False, "#FF8B6B"),
    PrimeSpecies(12, "Lagerstroemia parviflora", False, "#9D357F"),
    PrimeSpecies(13, "Michelia champaca", False, "#BD0A34"),
    PrimeSpecies(14, "Pinus roxburghii", False, "#A6D71B"),
    PrimeSpecies(15, "Pinus wallichiana", False, "#FD3EC1"),
    PrimeSpecies(16, "Quercus spp", True, "#D7C939"),
    PrimeSpecies(17, "Schima wallichii", False, "#DC3C07"),
    PrimeSpecies(18, "Shorea robusta", False, "#A608AB"),
    PrimeSpecies(19, "Terminalia alata", False, "#0D6E20"),
    PrimeSpecies(20, "Trewia nudiflora", False, "#21A707"),
    PrimeSpecies(21, "Tsuga spp", True, "#D07D07"),
]

# Spellings / accepted-name synonyms of an EXACT prime species that field data uses.
# (Genus groups need none: any "<Genus> ..." already matches.)
_ALIASES: Dict[str, int] = {
    "adina cordifolia": 3,       # the owner's list carries the misspelling "cardifolia"
    "anogeissus latifolius": 6,
    "toona ciliata": 8,          # accepted name of Cedrela toona
}


def _norm(name: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


_EXACT: Dict[str, int] = {_norm(s.name): s.code for s in PRIME_SPECIES if not s.genus_group}
_EXACT.update(_ALIASES)
_GENUS: Dict[str, int] = {_norm(s.name).split(" ")[0]: s.code for s in PRIME_SPECIES if s.genus_group}


def prime_species_code(species: Optional[str]) -> Optional[int]:
    """The prime species code (1..21) for a species string, or None for 'other'.

    Exact scientific name first (case/space-insensitive, with the aliases above),
    then the genus rule for the four "spp" groups.
    """
    key = _norm(species)
    if not key:
        return None
    if key in _EXACT:
        return _EXACT[key]
    return _GENUS.get(key.split(" ")[0])


# Tree group by the inventory ``remark``. Drives the map SHAPE.
TREE_GROUPS = ("felling", "mother", "seedling", "other")


def tree_group(remark: Optional[str]) -> str:
    """'felling' | 'mother' | 'seedling' | 'other' from ``inventory_trees.remark``."""
    key = _norm(remark)
    if key.startswith("mother"):
        return "mother"
    if key.startswith("felling"):
        return "felling"
    if key.startswith("seedling"):
        return "seedling"
    return "other"
