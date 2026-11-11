"""Species per unit, from the field inventory's own tree measurements (poles and trees).

Feeds two print map variables (and so the workspace): ``unit__species_dominant`` (the dominant species of each unit) and
``unit__species_composition__pie`` (each unit's species shares). A unit's shares are by NET VOLUME of its poles and trees, or by
stem COUNT when no volumes were calculated — the same rule the Sustainable-FM species assemblage uses, so the two never disagree
about what a unit is dominated by.

The species is identified by its SCIENTIFIC name (a stable Latin key, safe to save a colour against); the local name is what is
shown when there is one. Nothing is computed here beyond a grouped sum over stored measurements.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

TOP_N = 5  # species named on a pie; the rest are "Other species"
OTHER_KEY = "other_species"


def species_key(scientific: str) -> str:
    """A short, stable, Latin-safe key for a species (what a saved colour is keyed by)."""
    k = re.sub(r"[^A-Za-z0-9]+", "_", (scientific or "").strip()).strip("_").lower()
    return k[:40] or "unknown"


def shares_from_rows(rows: list[dict]) -> list[dict]:
    """``[{key, sci, name, value}]`` sorted by share, ``value`` in percent. Volume-based when any volume exists, else by count."""
    vol_total = sum(float(r.get("vol") or 0.0) for r in rows)
    by = "vol" if vol_total > 0 else "n"
    total = sum(float(r.get(by) or 0.0) for r in rows)
    if total <= 0:
        return []
    out = []
    for r in rows:
        v = float(r.get(by) or 0.0)
        if v <= 0 or not r.get("sci"):
            continue
        sci = str(r["sci"]).strip()
        out.append({"key": species_key(sci), "sci": sci, "name": (r.get("local") or sci).split(",")[0].strip() or sci, "value": round(100.0 * v / total, 2)})
    out.sort(key=lambda s: (-s["value"], s["sci"]))
    return out


def shares_by_unit(db: Any, calculation_id: UUID) -> dict[str, list[dict]]:
    """``{unit name: species shares}`` for every unit that has sample plots. Never raises (a failure means no species maps)."""
    from sqlalchemy import text

    try:
        rows = db.execute(
            text(
                """
                SELECT p.block_name AS bk, m.species_scientific AS sci, m.species_local AS local,
                       COUNT(*) AS n, COALESCE(SUM(m.net_volume), 0) AS vol
                FROM field_inventory_measurements m
                JOIN field_inventory_sample_plots p ON p.id = m.sample_plot_id
                JOIN field_inventory_calculations fc ON fc.id = p.field_inventory_calculation_id
                WHERE fc.calculation_id = :cid AND m.stand_type IN ('Pole', 'Tree')
                GROUP BY p.block_name, m.species_scientific, m.species_local
                """
            ),
            {"cid": str(calculation_id)},
        ).fetchall()
    except Exception:  # noqa: BLE001 -- species maps degrade to "no data"; the rest of the page must still work
        logger.warning("species-by-unit query failed for %s", calculation_id, exc_info=True)
        return {}
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault((r.bk or "").strip(), []).append({"sci": r.sci, "local": r.local, "n": r.n, "vol": r.vol})
    # one scientific name can carry two local names in different rows: merge by key
    out: dict[str, list[dict]] = {}
    for bk, rs in grouped.items():
        merged: dict[str, dict] = {}
        for r in rs:
            k = species_key(r["sci"] or "")
            m = merged.setdefault(k, {"sci": r["sci"], "local": r["local"], "n": 0, "vol": 0.0})
            m["n"] += int(r["n"] or 0)
            m["vol"] += float(r["vol"] or 0.0)
            m["local"] = m["local"] or r["local"]
        shares = shares_from_rows(list(merged.values()))
        if bk and shares:
            out[bk] = shares
    return out


def scheme(values: dict) -> list[dict]:
    """The forest-wide species classes in a stable order (largest total share first), each with its default colour. At most ten
    named species; everything else is "Other species" in grey. ``[{key, sci, name, color}]``."""
    from app.core import semantic_palettes as sp

    palette = list(sp.CATEGORICAL.get("species_qual", {}).values()) or sp.sample_ramp("species_qual", 10)
    totals: dict[str, float] = {}
    names: dict[str, tuple[str, str]] = {}
    for rec in values.values():
        for s in rec.get("species_shares") or []:
            totals[s["key"]] = totals.get(s["key"], 0.0) + float(s["value"])
            names.setdefault(s["key"], (s["sci"], s["name"]))
    order = sorted(totals, key=lambda k: (-totals[k], k))[: len(palette)]
    return [{"key": k, "sci": names[k][0], "name": names[k][1], "color": palette[i]} for i, k in enumerate(order)]
