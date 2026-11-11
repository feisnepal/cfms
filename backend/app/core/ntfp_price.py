"""The price of an NTFP, by the part harvested, with an estimate where Schedule-7 gives none (NTFP inventory; owner decision 2026-10-22).

Schedule-7 (Forest Regulations 2079, ``ntfp_schedule7``) is the legal royalty rate and the only authoritative price. Where it has no line for
a species' harvested part, the plan still needs a figure (cost-benefit, the harvest plan), so one is estimated and LABELLED as an estimate:

1. ``schedule7``    the species' own line for that part, or the genus entry (``Berberis spp.``) that covers it;
2. ``relative``     a named relative in the same plant family, same part (``RELATIVES``);
3. ``part_median``  the median Schedule-7 rate of that part group (kg lines only). The median, not the mean: the whole-plant group has a
                    few very dear lines that pull its mean to Rs 688 against a median of Rs 5.

An estimate is for planning. It is never a royalty rate: every estimated entry says so (``estimated``) and why (``basis_note``).
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional

from .ntfp_schedule7 import GROUPS, ROWS, designated_entries

#: Nepali word in a "parts used" cell -> Schedule-7 group. First match wins, so the whole-plant words come first.
_PART_WORDS = (
    ("पूरै", "च"), ("सम्पूर्ण", "च"),
    ("बोक्रा", "ख"),
    ("जरा", "क"), ("गानो", "क"), ("प्रकन्द", "क"),
    ("फूल", "घ"), ("भुवा", "घ"),
    ("फल", "ङ"), ("बीउ", "ङ"),
    ("पात", "ग"), ("डाँठ", "ग"), ("टुसा", "ग"), ("लहरा", "ग"),
)

#: A species Schedule-7 does not list by the Latin name the guideline uses -> a named relative that it does list (same family).
RELATIVES: Dict[str, tuple] = {
    "Girardinia diversifolia": ("Boehmeria rugulosa", "Urticaceae: both are nettle-family fibre-bark plants"),
}

#: The lichen line is on Schedule-7 (च 19, झ्याउ, "Lichen") but ``designated_entries`` does not match a plant name to it.
LINE_OVERRIDE: Dict[str, tuple] = {"lichens": ("च", 19)}


def groups_for(part_groups: Optional[List[str]], parts_used_ne: Optional[str]) -> List[str]:
    """The Schedule-7 groups a species is harvested for: the method card's, else read from the Annex-1 "parts used" words."""
    if part_groups:
        return list(part_groups)
    found: List[str] = []
    for chunk in (parts_used_ne or "").replace("/", ",").split(","):
        for word, group in _PART_WORDS:
            if word in chunk:
                if group not in found:
                    found.append(group)
                break
    return found


def part_median(group: str) -> Optional[float]:
    rates = [r[4] for r in ROWS if r[0] == group and r[5] == "kg"]
    if not rates:
        return None
    m = statistics.median(rates)
    return int(m) if float(m).is_integer() else m


def _entry(group: str, price, unit: str, basis: str, note: str) -> dict:
    return {
        "group": group, "group_ne": GROUPS[group][0], "group_en": GROUPS[group][1], "price": price, "unit": unit,
        "basis": basis, "estimated": basis != "schedule7", "basis_note": note,
    }


def _line(group: str, serial: int):
    return next((r for r in ROWS if r[0] == group and r[1] == serial), None)


def prices_for(species_key: str, scientific_name: Optional[str], regulation_name: Optional[str],
               part_groups: Optional[List[str]], parts_used_ne: Optional[str]) -> List[dict]:
    """One price entry per part the species is harvested for."""
    out: List[dict] = []
    own = designated_entries(regulation_name or scientific_name or "")
    for g in groups_for(part_groups, parts_used_ne):
        if species_key in LINE_OVERRIDE and LINE_OVERRIDE[species_key][0] == g:
            row = _line(*LINE_OVERRIDE[species_key])
            out.append(_entry(g, row[4], row[5], "schedule7", f"Schedule-7 {g} {row[1]} ({row[3]}), {row[2]}"))
            continue
        hit = next((e for e in own if e["group"] == g), None)
        if hit is not None:
            out.append(_entry(g, hit["price"], hit["unit"], "schedule7", f"Schedule-7 {g} {hit['serial']}, {hit['nepali']}"))
            continue
        rel = RELATIVES.get(scientific_name or "")
        if rel:
            line = next((e for e in designated_entries(rel[0]) if e["group"] == g), None)
            if line is not None:
                out.append(_entry(g, line["price"], line["unit"], "relative", f"estimated from {rel[0]} (Schedule-7 {g} {line['serial']}); {rel[1]}"))
                continue
        med = part_median(g)
        if med is not None:
            out.append(_entry(g, med, "kg", "part_median", f"estimated: median of the Schedule-7 rates for {GROUPS[g][1].lower()}"))
    return out
