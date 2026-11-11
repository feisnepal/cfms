"""Non-timber forest products (गैरकाष्ठ वन पैदावार, NTFP) among the species recorded for a forest.

A recorded vegetation species counts as an NTFP species when it is on the regulation's designated list: Forest Regulations 2079,
Schedule-7 (``ntfp_schedule7``). The list names the herb or product, the part that is harvested (roots, bark, leaf, flower, fruit,
whole plant, gum) and the price rate per kilogram; a species may appear for several parts. That is the legal meaning of NTFP in a
community forest plan, so it replaces the earlier working rule that guessed from the species' recorded uses (which also counted garden
crops such as chilli and mustard).

The OP table ``ntfp`` and the narrative ``section:ntfp`` both read this module.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from .ntfp_schedule7 import GROUPS, designated_entries

_DIGITS = str.maketrans("0123456789", "०१२३४५६७८९")


def part_ne(group: str) -> str:
    """The part harvested, in Nepali: ``बोक्रा`` for group ख."""
    return GROUPS[group][0].replace(" जाति", "")


def _price_ne(entry: dict) -> str:
    amount = f"{entry['price']:,}".translate(_DIGITS)
    return f"रु. {amount}" + (" प्रतिगोटा" if entry["unit"] == "piece" else "")


def ntfp_species(vegetation: Iterable[dict]) -> List[dict]:
    """The recorded vegetation species that are on the designated list, in the order recorded:
    ``[{name, scientific_name, sub_category, abundance, entries, parts, price_text}]``.

    ``entries`` is every Schedule-7 line the species falls under (group, part, price); ``parts`` and ``price_text`` are the same as
    text for the table (``बोक्रा, फल`` / ``बोक्रा रु. १००; फल रु. १०``)."""
    rows: List[dict] = []
    for rec in vegetation or []:
        entries = designated_entries(rec.get("scientific_name") or "")
        if not entries:
            continue
        seen = set()
        unique = []
        for e in entries:  # the same part and price listed twice (two printed names of one species) counts once
            k = (e["group"], e["price"], e["unit"])
            if k not in seen:
                seen.add(k)
                unique.append(e)
        parts = list(dict.fromkeys(part_ne(e["group"]) for e in unique))
        rows.append({
            "name": rec.get("name", ""),
            "scientific_name": rec.get("scientific_name", ""),
            "sub_category": rec.get("sub_category", ""),
            "abundance": rec.get("abundance", ""),
            "entries": unique,
            "parts": ", ".join(parts),
            "price_text": "; ".join(f"{part_ne(e['group'])} {_price_ne(e)}" for e in unique),
        })
    return rows


def breakdown_by_part(rows: Iterable[dict]) -> Dict[str, int]:
    """How many of the listed species are harvested for each part (a species counts once per part)."""
    out: Dict[str, int] = {}
    for r in rows:
        for part in {part_ne(e["group"]) for e in r["entries"]}:
            out[part] = out.get(part, 0) + 1
    return out
