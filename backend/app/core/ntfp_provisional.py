"""Provisional method cards for the Schedule-7 species that have no documented card (NTFP inventory, owner requirement 2026-10-22).

Schedule-7 names 262 plants; the Nepal guideline describes 35 of them in Annex 2. The rest get a card DERIVED by stated rules so that every species can be
designed and recorded, and each derived value says so:

* growth form: the species master's sub-category when it has one (derived, source MASTER); else a climber word in the Nepali name; else a guess from the part
  harvested (root / whole plant -> herb, bark / flower / fruit / resin -> tree, leaf -> shrub): PROVISIONAL, because it is a guess;
* plot size: the guideline's Table 3 for that growth form (``ntfp_sources.GROWTH_PLOT``);
* sampling method: from the part harvested (``PART_METHOD``);
* individuals to weigh: India's Working Plan Code para 71 (``GROWTH_SAMPLES``).

Maturity sign, conversion factor and sample fraction are NOT guessed: they stay empty until a reviewer supplies them. Every card made here has
``card_status = "provisional"`` and is meant to be reviewed (scripts/export_ntfp_card_review.py).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .ntfp_schedule7 import GROUPS, ROWS, designated_entries, scientific_names
from .ntfp_sources import GROWTH_PLOT, GROWTH_SAMPLES, PART_METHOD, _v
from .species_synonyms import canonical_key

#: species master sub-category -> growth class (None: not a growth form we can use)
MASTER_FORM = {"Tree": "tree", "Medicinal Herb": "herb", "Fern": "herb", "Grass": "herb", "Sedge": "herb", "Climber": "climber", "Shrub/Bamboo": "shrub",
               "Orchid": "herb", "Aquatic": "herb", "Invasive Plant": None}
#: a Nepali name that says "climber"
CLIMBER_WORDS = ("लहरा", "लता", "बेली", "बल्ली", "लहरे")
#: growth form guessed from the Schedule-7 group of the first part when nothing better is known
FORM_BY_PART = {"क": "herb", "च": "herb", "ख": "tree", "ग": "shrub", "घ": "tree", "ङ": "tree", "छ": "tree"}
#: Devanagari names for species the Nepal sources name only in Latin (local names as ANSAB gives them)
LOCAL_NE = {"amomum subulatum": "अलैंची", "aegle marmelos": "बेल", "ziziphus buddhensis": "बोधिचित्त", "choerospondias axillaris": "लप्सी",
            "elaeocarpus sphaericus": "रुद्राक्ष", "lindera neesiana": "सिल्टिमुर", "polygonatum cirrhifolium": "सेतकचिनी"}


def display_name(key: str) -> str:
    """``Zanthoxylum armatum`` from the key ``zanthoxylum armatum``; a genus key (``berberis``) reads ``Berberis spp.``."""
    words = key.split()
    if len(words) == 1:
        return f"{words[0].capitalize()} spp."
    return f"{words[0].capitalize()} {' '.join(words[1:])}"


def schedule7_species() -> Dict[str, Dict[str, Any]]:
    """Every plant the regulation names, by canonical key: Nepali name, parts (groups in order of first appearance), the printed Latin names."""
    out: Dict[str, Dict[str, Any]] = {}
    for g, serial, nepali, printed, _price, _unit in ROWS:
        for name in scientific_names(printed):
            k = canonical_key(name)
            rec = out.setdefault(k, {"species_key": k, "nepali_name": nepali, "groups": [], "printed": [], "lines": []})
            if g not in rec["groups"]:
                rec["groups"].append(g)
            if printed not in rec["printed"]:
                rec["printed"].append(printed)
            if (g, serial) not in rec["lines"]:  # one printed line may name the species under several Latin names
                rec["lines"].append((g, serial))
    return out


def _form(key: str, nepali: str, groups: List[str], master: Callable[[str], Optional[str]]) -> Tuple[str, str, str, str]:
    """(growth class, status, source, why)."""
    sub = master(key)
    if sub and MASTER_FORM.get(sub):
        return MASTER_FORM[sub], "derived", "MASTER", f"the species master lists it as '{sub}'"
    if any(w in nepali for w in CLIMBER_WORDS):
        return "climber", "provisional", "RULE", "the Nepali name says climber; confirm"
    first = groups[0] if groups else "क"
    return FORM_BY_PART[first], "provisional", "RULE", f"guessed from the part harvested ({GROUPS[first][1].lower()}); confirm"


def procedure_text(method: str, part_en: str, n: Tuple[int, Optional[int]]) -> str:
    take = {"destructive": "lift", "semi_destructive": "take part of the", "non_destructive": "take the"}[method]
    count = f"{n[0]}" if n[1] is None else f"{n[0]}-{n[1]}"
    return (f"Count the plants in the plot; for {count} mature individuals {take} {part_en.lower()}, weigh it fresh and dry. "
            f"Provisional card derived from the growth form and the part harvested: no species-specific method has been documented.")


def derive(master: Callable[[str], Optional[str]], existing: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """``(profiles, values)`` for every Schedule-7 species without a documented card. A profile row carries ``op``: ``insert`` (no profile yet) or ``update`` (a
    profile exists without a card: an Annex-1 species). ``existing`` maps species_key -> the profile dict of the documented cards (those are skipped)."""
    profiles: List[Dict[str, Any]] = []
    values: List[Dict[str, Any]] = []
    for key, rec in sorted(schedule7_species().items()):
        have = existing.get(key)
        if have is not None and have.get("has_method_card"):
            continue
        groups = rec["groups"]
        growth, gstatus, gsource, why = _form(key, rec["nepali_name"], groups, master)
        method = PART_METHOD[groups[0]][0]
        lo, hi = GROWTH_PLOT[growth]
        n = GROWTH_SAMPLES[growth]
        part_ne = ", ".join(GROUPS[g][0].replace(" जाति", "") for g in groups)
        sci = display_name(key)
        reg = sci if designated_entries(sci) else None
        row = {
            "op": "update" if have is not None else "insert", "species_key": key, "scientific_name": sci, "regulation_name": reg, "nepali_name": (have or {}).get("nepali_name") or rec["nepali_name"],
            "growth_class": growth, "part_groups": groups, "part_ne": part_ne, "sampling_method": method, "plot_min_sqm": lo, "plot_max_sqm": hi,
            "n_individuals_min": n[0], "n_individuals_max": n[1], "procedure_en": procedure_text(method, GROUPS[groups[0]][1], n),
            "has_method_card": True, "card_status": "provisional",
        }
        profiles.append(row)
        values += [
            _v(key, "growth_class", gsource, "growth-form rule", gstatus, text=growth, note=why),
            _v(key, "part_groups", "S7-2079", "Schedule-7 lines " + ", ".join(f"{g} {s}" for g, s in rec["lines"]), "documented", text=",".join(groups),
               note="the groups the regulation prices this species under"),
            _v(key, "sampling_method", "RULE", "part-based default", "derived", text=method, note=f"from the part harvested ({GROUPS[groups[0]][1].lower()})"),
            _v(key, "plot_area_sqm", "RULE", f"Table 3 default for a {growth}", "derived" if gstatus == "derived" else "provisional", num=lo, num2=hi if hi != lo else None, unit="m2",
               note="the Nepal guideline's plot size for this growth form"),
            _v(key, "n_individuals", "RULE", "Working Plan Code para 71 default", "derived" if gstatus == "derived" else "provisional", num=n[0], num2=n[1],
               note="India's national code: at least 3 trees, 5 shrubs, 10-20 herbs"),
        ]
    return profiles, values


def stub_profiles(values: List[Dict[str, Any]], known: set) -> List[Dict[str, Any]]:
    """A minimal profile (no card) for a species that only appears in sourced values (an ANSAB or guideline season row) and has no profile yet."""
    out: Dict[str, Dict[str, Any]] = {}
    for v in values:
        k = v["species_key"]
        if k in known or k in out or ":" in k:
            continue
        sci = display_name(k)
        out[k] = {"op": "insert", "species_key": k, "scientific_name": sci, "regulation_name": sci if designated_entries(sci) else None, "nepali_name": LOCAL_NE.get(k, sci),
                  "growth_class": None, "part_groups": [], "has_method_card": False, "card_status": None}
    return list(out.values())
