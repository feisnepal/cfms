"""A DIVIDED parent unit's values, rolled up from its sub-units (owner rule 2026-10-10: a polygon must show the value it deserves).

Field inventory and Sustainable FM are worked out on the LEAF stands only, so a parent compartment/block that was divided has no
row of its own and its table cells came out as "-". The honest value for a parent is the area-weighted summary of its leaves:

* per-hectare measures (stock, basal area, regeneration ...) -> mean weighted by the leaves' polygon area;
* counts (sample plots) -> sum;
* the forest / regeneration condition -> the same rule (``core.forest_condition``) applied to the rolled-up numbers;
* a class (SFM type, orientation) -> the one covering the largest area of the leaves, marked as a summary.

Pure functions over a small tree; ``unit_tree`` is the only one that touches the database.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import text


def unit_tree(db: Any, calculation_id: UUID) -> List[Dict[str, Any]]:
    """Every real unit (not an unpromoted trial layer): ``{id, name, block_name, parent_id, area_ha}``."""
    rows = db.execute(
        text(
            "SELECT b.id::text, b.name, b.block_name, b.parent_block_id::text, b.area_hectares "
            "FROM forest_blocks b LEFT JOIN raster_layers l ON l.id = b.raster_layer_id "
            "WHERE b.calculation_id = :c AND (b.raster_layer_id IS NULL OR l.promoted_as IS NOT NULL)"
        ),
        {"c": str(calculation_id)},
    ).fetchall()
    return [
        {"id": r[0], "name": r[1] or "", "block_name": r[2] or "", "parent_id": r[3], "area_ha": float(r[4] or 0)}
        for r in rows
    ]


def leaves_by_parent(tree: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """``{parent_id: [every LEAF descendant]}`` for each unit that has children."""
    children: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for u in tree:
        if u["parent_id"]:
            children[u["parent_id"]].append(u)
    by_id = {u["id"]: u for u in tree}

    def leaves(uid: str) -> List[Dict[str, Any]]:
        kids = children.get(uid) or []
        if not kids:
            return [by_id[uid]] if uid in by_id else []
        out: List[Dict[str, Any]] = []
        for k in kids:
            out.extend(leaves(k["id"]))
        return out

    return {uid: leaves(uid) for uid in children}


def lookup(unit: Dict[str, Any], table: Dict[str, Any]) -> Any:
    """A unit's entry in a table keyed by its block name (leaves) or its name."""
    return table.get(unit["block_name"]) or table.get(unit["name"])


def weighted_mean(pairs: Iterable[tuple]) -> Optional[float]:
    """Mean of ``(weight, value)`` pairs, ignoring missing values; ``None`` when nothing is left. Zero weights fall back to a plain mean."""
    vals = [(float(w or 0), float(v)) for w, v in pairs if v is not None and v != ""]
    if not vals:
        return None
    total = sum(w for w, _ in vals)
    if total <= 0:
        return sum(v for _, v in vals) / len(vals)
    return sum(w * v for w, v in vals) / total


def dominant_by_area(pairs: Iterable[tuple]) -> Any:
    """The value covering the largest total weight among ``(weight, value)`` pairs; ``None`` when there is none."""
    acc: Dict[Any, float] = defaultdict(float)
    for w, v in pairs:
        if v is None or v == "":
            continue
        acc[v] += float(w or 0)
    return max(acc.items(), key=lambda kv: kv[1])[0] if acc else None


# --- field inventory --------------------------------------------------------------------------------------------------------
_FI_MEAN_MEASURES = (
    "total_growing_stock_m3_per_ha", "basal_area_m2_per_ha", "aah_total_m3_per_ha", "mai_total_m3_per_ha", "mai_percent",
    "carbon_stock_tc_per_ha", "total_biomass_t_per_ha", "co2_equivalent_tco2_per_ha", "regeneration_per_ha",
    "sapling_per_ha", "pole_per_ha", "tree_per_ha",
)


def rollup_field_inventory(tree: List[Dict[str, Any]], values: Dict[str, dict]) -> Dict[str, dict]:
    """Add a rolled-up record for every divided parent that has none, keyed by the parent's name. ``values`` is
    ``{unit name: {measure: value}}`` for the leaves (what the inventory stored); it is returned with the parents added."""
    from app.core.forest_condition import assess_conditions

    out = dict(values)
    by_id = {u["id"]: u for u in tree}
    for pid, leaves in leaves_by_parent(tree).items():
        parent = by_id.get(pid)
        if not parent or lookup(parent, out):
            continue
        recs = [(u["area_ha"], lookup(u, values)) for u in leaves]
        recs = [(w, r) for w, r in recs if r]
        if not recs:
            continue
        rec: Dict[str, Any] = {}
        for m in _FI_MEAN_MEASURES:
            v = weighted_mean((w, r.get(m)) for w, r in recs)
            if v is not None:
                rec[m] = v
        plots = [r.get("total_sample_plots") for _, r in recs if r.get("total_sample_plots") is not None]
        if plots:
            rec["total_sample_plots"] = sum(float(p) for p in plots)
        if "regeneration_per_ha" in rec or "sapling_per_ha" in rec or "total_growing_stock_m3_per_ha" in rec:
            rec["regeneration_condition"], rec["forest_condition"] = assess_conditions(
                rec.get("regeneration_per_ha", 0), rec.get("sapling_per_ha", 0), rec.get("total_growing_stock_m3_per_ha", 0)
            )
        out[parent["name"] or parent["block_name"]] = rec
    return out


# --- Sustainable FM -----------------------------------------------------------------------------------------------------
def rollup_sfm_types(tree: List[Dict[str, Any]], types: Dict[str, dict]) -> Dict[str, dict]:
    """Add a summary entry for every divided parent that has none (``get_block_types`` shape). The type, orientation and land
    class are the ones covering the largest leaf area; the state says it is a roll-up so nothing reads it as a field result."""
    out = dict(types)
    by_id = {u["id"]: u for u in tree}
    for pid, leaves in leaves_by_parent(tree).items():
        parent = by_id.get(pid)
        if not parent or lookup(parent, out):
            continue
        infos = [(u["area_ha"], lookup(u, types)) for u in leaves]
        infos = [(w, i) for w, i in infos if i]
        if not infos:
            continue

        def pick(field: str) -> Any:
            return dominant_by_area((w, i.get(field)) for w, i in infos)

        gs = weighted_mean((w, i.get("gs_ge40_m3_per_ha")) for w, i in infos)
        n = len(infos)
        out[parent["name"] or parent["block_name"]] = {
            "area_ha": parent["area_ha"],
            "gs_ge40_m3_per_ha": gs,
            "slope_band": pick("slope_band"),
            "state": "rolled_up",
            "land_class": pick("land_class") or "forest",
            "plot_count": sum(int(i.get("plot_count") or 0) for _, i in infos),
            "type_no": pick("type_no"),
            "proposed_type_no": pick("proposed_type_no"),
            "overridden": False,
            "orientation": pick("orientation"),
            "confidence": None,
            "needs_review": False,
            "reasons_en": f"Summary of {n} sub-unit(s): the type and orientation covering the largest area are shown.",
            "reasons_ne": f"{n} उप-इकाईको सारांश: सबैभन्दा ठूलो क्षेत्रफल ओगट्ने प्रकार र अभिमुखीकरण देखाइएको छ।",
        }
    return out
