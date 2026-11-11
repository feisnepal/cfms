"""One name per species: the Latin synonyms the system resolves to a single canonical name (owner, 2026-10-22).

A plant is written under different Latin names in different sources (the regulation, the species master, the NTFP guideline, a field sheet).
The system keeps ONE canonical name per species and reads every synonym as that name. The canonical name is the one the species master
(``biodiversity_species``) and the Forest Regulations 2079 Schedule-7 already use, so nothing in the data has to move: the synonyms
are what is mapped, never the master.

Add a pair only when the two names are the same plant AND the canonical one is the name the master / regulation prints. Each entry says
why. ``canonical_name`` returns its input unchanged for a name that is not listed.

Not here: Cinnamomum glaucescens is mapped to C. tenuipile because the species master gives सुगन्धकोकिला to *tenuipile* (and बनकाफोर to
C. glanduliferum). That is one source, not a flora; confirm it with the Department of Plant Resources before relying on it.
"""
from __future__ import annotations

import re
from typing import Dict

# alias -> canonical (display form). Aliases are matched case-insensitively, ignoring author names and punctuation.
SYNONYMS: Dict[str, str] = {
    # Spikenard: the regulation and the master print N. jatamansi; the guideline and CITES use N. grandiflora.
    "Nardostachys grandiflora": "Nardostachys jatamansi",
    # Valeriana: a spelling of the same epithet (V. jatamansi Jones).
    "Valeriana jatamansii": "Valeriana jatamansi",
    # Sugandhakokila: the species master names Cinnamomum tenuipile सुगन्धकोकिला.
    "Cinnamomum glaucescens": "Cinnamomum tenuipile",
    # Atis: the guideline's Table 5 prints it as a Delphinium, its Annex 1 and the master as Aconitum heterophyllum.
    "Delphinium heterophyllum": "Aconitum heterophyllum",
    # Atis again: ANSAB writes Delphinium himalayai; the species master gives अतिस to both names. To be confirmed against a flora.
    "Delphinium himalayai": "Aconitum heterophyllum",
    # Yarsagumba: the fungus was renamed Ophiocordyceps sinensis (ANSAB still writes Cordyceps).
    "Cordyceps sinensis": "Ophiocordyceps sinensis",
    # Kutki: Picrorhiza was split; the regulation and the guideline print Neopicrorhiza. (ANSAB writes the spelling without the second i.)
    "Picrorhiza scrophulariiflora": "Neopicrorhiza scrophulariiflora",
    "Picrorhiza scrophulariflora": "Neopicrorhiza scrophulariiflora",
    # Chiuri: Bassia butyracea is an old name of Diploknema butyracea.
    "Bassia butyracea": "Diploknema butyracea",
    # Rudraksha: a spelling of the same epithet.
    "Elaeocarpus sphericus": "Elaeocarpus sphaericus",
}


def _norm(name: str) -> str:
    """Lower case letters and single spaces (the same rule ``ntfp_schedule7`` applies)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", (name or "").lower().replace("-", ""))).strip()


_CANON = {_norm(a): c for a, c in SYNONYMS.items()}


def canonical_name(name: str) -> str:
    """The canonical display name of a Latin name; the name itself when it has no listed synonym."""
    words = _norm(name).split()
    key = " ".join(words[:2])
    return _CANON.get(key, name)


def canonical_key(name: str) -> str:
    """The normalised canonical name (``genus epithet``, or the genus alone for a ``spp.`` entry)."""
    words = _norm(canonical_name(name)).split()
    if len(words) >= 2 and words[1] not in ("spp", "sp"):
        return " ".join(words[:2])
    return words[0] if words else ""


def aliases_of(canonical: str) -> list:
    """Every listed synonym of a canonical name."""
    return [a for a, c in SYNONYMS.items() if _norm(c) == _norm(canonical)]
