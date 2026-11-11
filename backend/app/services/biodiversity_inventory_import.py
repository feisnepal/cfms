"""List the unique tree species of a forest's field inventory in its Biodiversity record (owner rule 2026-10-10).

The species identity comes from ``tree_species_coefficients`` -- the table every inventory species must already be in to get a
volume. The Biodiversity tab picks from ``biodiversity_species`` (a smaller, curated list), so an inventory species is:

* ``in_list``   -- already in the Biodiversity list (matched by scientific name, authors and variety ignored): just recorded;
* ``new``       -- only in the coefficient table: a Biodiversity entry is created from it (category vegetation, sub-category Tree)
                   and recorded. Its Nepali name is the coefficient table's local name (romanised) until someone reviews it;
* ``unresolved``-- in neither: shown, but it cannot be added (nothing reliable to build the entry from).

Nothing is written without the user's confirmation (``preview`` is read-only), species already recorded are skipped and a
recorded species' abundance / notes are never overwritten.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SOURCE_NOTE = "Created from tree_species_coefficients (field inventory import); Nepali name to be reviewed."


# Inventory (coefficient-table) name -> the accepted synonym the Biodiversity list carries it under. Kept to names that are
# unambiguous synonyms; anything else is simply a new species.
SYNONYMS = {"terminalia alata": "terminalia tomentosa"}

SYNC_MARKER = "biodiversity_inventory_sync"


def normalize(name: Any) -> str:
    """``"Shorea robusta Roxb. var. x"`` -> ``"shorea robusta"``: lower case, punctuation dropped, genus + species only."""
    s = unicodedata.normalize("NFKC", str(name or "")).lower()
    s = re.sub(r"[^a-z\s.]", " ", s).replace(".", " ")
    parts = s.split()
    return " ".join(parts[:2])


def abundance_for(plots_with: int, total_plots: int) -> str:
    """How widespread the species is across the sample plots: the share of plots it occurs in."""
    if total_plots <= 0:
        return "rare"
    share = plots_with / total_plots
    if share >= 0.5:
        return "abundant"
    if share >= 0.25:
        return "common"
    if share >= 0.1:
        return "occasional"
    return "rare"


def inventory_species(db: Session, calculation_id: UUID) -> Dict[str, Any]:
    """``{total_plots, species: [{scientific, local, stems, plots, stands}]}`` -- one row per unique scientific name."""
    total = db.execute(
        text(
            "SELECT count(*) FROM field_inventory_sample_plots p JOIN field_inventory_calculations f "
            "ON f.id = p.field_inventory_calculation_id WHERE f.calculation_id = :c"
        ),
        {"c": str(calculation_id)},
    ).scalar() or 0
    rows = db.execute(
        text(
            """
            SELECT m.species_scientific, max(m.species_local), sum(COALESCE(m.count, 1)),
                   count(DISTINCT m.sample_plot_id), array_agg(DISTINCT m.stand_type)
            FROM field_inventory_measurements m
            JOIN field_inventory_sample_plots p ON p.id = m.sample_plot_id
            JOIN field_inventory_calculations f ON f.id = p.field_inventory_calculation_id
            WHERE f.calculation_id = :c AND m.species_scientific IS NOT NULL AND btrim(m.species_scientific) <> ''
            GROUP BY m.species_scientific
            ORDER BY sum(COALESCE(m.count, 1)) DESC, m.species_scientific
            """
        ),
        {"c": str(calculation_id)},
    ).fetchall()
    merged: Dict[str, Dict[str, Any]] = {}
    for sci, local, stems, plots, stands in rows:
        key = normalize(sci)
        if not key:
            continue
        cur = merged.setdefault(key, {"scientific": str(sci).strip(), "local": local, "stems": 0, "plots": 0, "stands": set()})
        cur["stems"] += int(stems or 0)
        cur["plots"] = max(cur["plots"], int(plots or 0))  # same species spelled two ways: plots overlap, so the larger is the floor
        cur["stands"].update(stands or [])
    species = [{**v, "stands": sorted(v["stands"])} for v in merged.values()]
    return {"total_plots": int(total), "species": species}


def _master_index(db: Session) -> Dict[str, str]:
    return {
        normalize(sci): sid
        for sid, sci in db.execute(text("SELECT id::text, scientific_name FROM biodiversity_species")).fetchall()
        if normalize(sci)
    }


def _coefficient_index(db: Session) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for sci, local, aliases in db.execute(
        text("SELECT scientific_name, local_name, aliases FROM tree_species_coefficients")
    ).fetchall():
        rec = {"scientific": sci, "local": local, "aliases": list(aliases or [])}
        out.setdefault(normalize(sci), rec)
    return out


def _recorded(db: Session, calculation_id: UUID) -> set:
    return {
        normalize(sci)
        for (sci,) in db.execute(
            text(
                "SELECT s.scientific_name FROM calculation_biodiversity b JOIN biodiversity_species s ON s.id = b.species_id "
                "WHERE b.calculation_id = :c"
            ),
            {"c": str(calculation_id)},
        ).fetchall()
    }


def preview(db: Session, calculation_id: UUID) -> Dict[str, Any]:
    """Read-only: what the inventory holds and what adding it would do. ``rows[].status`` is ``already_recorded`` | ``in_list`` |
    ``new`` | ``unresolved``."""
    inv = inventory_species(db, calculation_id)
    master, coef, recorded = _master_index(db), _coefficient_index(db), _recorded(db, calculation_id)
    rows: List[Dict[str, Any]] = []
    for s in inv["species"]:
        key = SYNONYMS.get(normalize(s["scientific"]), normalize(s["scientific"]))
        if key in recorded:
            status = "already_recorded"
        elif key in master:
            status = "in_list"
        elif key in coef:
            status = "new"
        else:
            status = "unresolved"
        c = coef.get(normalize(s["scientific"])) or {}
        rows.append({
            "scientific": s["scientific"],
            "local": s["local"] or c.get("local"),
            "stems": s["stems"],
            "plots": s["plots"],
            "stands": s["stands"],
            "abundance": abundance_for(s["plots"], inv["total_plots"]),
            "status": status,
        })
    # A "new" species may be a synonym of one already in the list (Terminalia alata = T. tomentosa); same-genus entries are
    # shown as a hint so the user can leave it out instead of creating a near-duplicate.
    by_genus: Dict[str, List[str]] = {}
    for (sci,) in db.execute(text("SELECT scientific_name FROM biodiversity_species WHERE sub_category = 'Tree'")).fetchall():
        k = normalize(sci)
        if k:
            by_genus.setdefault(k.split()[0], []).append(sci)
    for r in rows:
        r["similar"] = by_genus.get(normalize(r["scientific"]).split()[0], []) if r["status"] == "new" else []
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("already_recorded", "in_list", "new", "unresolved")}
    return {"total_plots": inv["total_plots"], "rows": rows, "counts": counts}


def apply(db: Session, calculation_id: UUID, scientific_names: Iterable[str], user_id: Optional[UUID]) -> Dict[str, Any]:
    """Record the chosen inventory species (creating a Biodiversity entry for those only in the coefficient table). Skips species
    already recorded; never touches an existing record. Returns ``{added, created, skipped, unresolved}``."""
    from app.models.biodiversity import BiodiversitySpecies, CalculationBiodiversity

    wanted = {normalize(n) for n in scientific_names if normalize(n)}
    pv = preview(db, calculation_id)
    master = _master_index(db)
    coef = _coefficient_index(db)
    added = created = skipped = unresolved = 0
    for r in pv["rows"]:
        raw_key = normalize(r["scientific"])
        key = SYNONYMS.get(raw_key, raw_key)
        if raw_key not in wanted:
            continue
        if r["status"] == "already_recorded":
            skipped += 1
            continue
        if r["status"] == "unresolved":
            unresolved += 1
            continue
        species_id = master.get(key)
        if species_id is None:  # status "new": build the Biodiversity entry from the coefficient table
            c = coef[raw_key]
            local = (c.get("local") or "").strip() or c["scientific"]
            english = (c.get("aliases") or [None])[0] or c["scientific"]
            sp = BiodiversitySpecies(
                category="vegetation", sub_category="Tree", nepali_name=local, english_name=english,
                scientific_name=c["scientific"], notes=SOURCE_NOTE,
            )
            db.add(sp)
            db.flush()
            species_id = str(sp.id)
            master[key] = species_id
            created += 1
        db.add(CalculationBiodiversity(
            calculation_id=calculation_id,
            species_id=UUID(str(species_id)),
            presence_status="present",
            abundance=r["abundance"],
            notes=f"From field inventory: {r['stems']} stems in {r['plots']} of {pv['total_plots']} sample plots.",
            recorded_by=user_id,
        ))
        added += 1
    db.commit()
    return {"added": added, "created": created, "skipped": skipped, "unresolved": unresolved}


def sync_from_inventory(db: Session, calculation_id: UUID, user_id: Optional[UUID] = None) -> Dict[str, Any]:
    """Automatic import (no confirmation): record every inventory species that can be recorded -- once per processed inventory.

    A marker (the inventory's ``completed_at``) is kept on the calculation, so opening the Biodiversity tab again does nothing and a
    species the user then removes stays removed until the inventory is processed again. Returns ``{added, created, ...}`` or
    ``{"up_to_date": True}``.
    """
    from sqlalchemy.orm.attributes import flag_modified

    from app.models.calculation import Calculation

    done_at = db.execute(
        text(
            "SELECT completed_at FROM field_inventory_calculations "
            "WHERE calculation_id = :c AND lower(status) IN ('completed', 'complete')"
        ),
        {"c": str(calculation_id)},
    ).scalar()
    if done_at is None:
        return {"up_to_date": True, "no_inventory": True}
    calc = db.get(Calculation, calculation_id)
    marker = ((calc.result_data or {}).get(SYNC_MARKER) or {}) if calc else {}
    if marker.get("completed_at") == done_at.isoformat():
        return {"up_to_date": True}

    names = [r["scientific"] for r in preview(db, calculation_id)["rows"] if r["status"] in ("in_list", "new")]
    result = apply(db, calculation_id, names, user_id) if names else {"added": 0, "created": 0, "skipped": 0, "unresolved": 0}
    rd = dict(calc.result_data or {})
    rd[SYNC_MARKER] = {"completed_at": done_at.isoformat(), **{k: result[k] for k in ("added", "created")}}
    calc.result_data = rd
    flag_modified(calc, "result_data")
    db.commit()
    return result
