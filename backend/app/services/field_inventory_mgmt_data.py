"""
Management Plan Data Aggregation Service
Collects all 9 datasets from existing data sources.
Single source of truth for Excel sheets, DOCX charts, and frontend visualizations.
"""
# business: CFMG §X.Y — management plan data aggregator
# why: bundles 9 datasets into single payload for plan generator
# NOTE: per-ha values computed before aggregation
import logging
from typing import Dict, List, Optional, Any
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..core.dbh_classifier import DbhClassRegistry
from ..models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventoryBlockSummary,
    FieldInventoryMeasurement,
    FieldInventorySamplePlot,
)

logger = logging.getLogger(__name__)

# AAH multiplier by forest condition — single source of truth in app.core.constants.
from app.core.constants import AAH_MULTIPLIER as AAH_MAP  # noqa: E402,F401

DBH_CLASS_ALL = [
    (c.key, c.label_np)
    for c in DbhClassRegistry.get_system("guideline_2061")
]

DBH_CLASS_POLETREE = DBH_CLASS_ALL[2:]

PRODUCTIVITY_THRESHOLDS = [
    ("High", 200, float('inf'), "High intensity management: commercial timber harvesting"),
    ("Medium", 100, 200, "Moderate intensity: selective harvesting, enrichment planting"),
    ("Low", 0, 100, "Protection oriented: natural regeneration, firewood only"),
]


def _fetch_block_areas(db: Session, calculation_id: UUID) -> Dict[str, float]:
    from ..models.calculation import Calculation
    from .forest_units import queries as forest_unit_queries

    # The leaf view (FS-1a.13): blocks OR compartments, every unit not divided further. Only an upload-mode
    # forest with no unit rows falls back to the result_data blocks array.
    areas = forest_unit_queries.leaf_areas_by_name(db, calculation_id)
    if areas:
        return areas
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc or not calc.result_data:
        return {}
    blocks = calc.result_data.get("blocks", [])
    return {
        b.get("block_name", ""): float(b.get("area_hectares", 0))
        for b in blocks if b.get("block_name")
    }


def _fetch_species_coefficients(db: Session) -> Dict[str, Dict]:
    query = text("""
        SELECT scientific_name, growth_rate, wood_density_gm_cm3
        FROM public.tree_species_coefficients
        WHERE is_active = TRUE
    """)
    rows = db.execute(query).fetchall()
    result = {}
    for r in rows:
        result[r.scientific_name] = {
            "growth_rate": r.growth_rate or "Moderate",
            "wood_density": float(r.wood_density_gm_cm3 or 0.65),
        }
    return result


def _get_species_breakdown(db: Session, field_inventory_id: UUID) -> List[Dict]:
    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id
    ).first()
    if not fi:
        return []
    regen_area = float(fi.regeneration_area_sqm)
    sapling_area = float(fi.sapling_area_sqm)
    pole_area = float(fi.pole_area_sqm)
    tree_area = float(fi.tree_area_sqm)

    query = text("""
        WITH plot_species AS (
            SELECT
                sp.block_name,
                m.species_scientific,
                m.species_local,
                m.stand_type,
                COUNT(DISTINCT sp.id) as total_plots_in_block,
                SUM(m.count) as total_count,
                SUM(COALESCE(m.net_volume, 0)) as total_timber,
                SUM(COALESCE(m.firewood_m3, 0)) as total_firewood,
                SUM(COALESCE(m.basal_area_m2, 0) * m.count) as total_basal_area
            FROM public.field_inventory_sample_plots sp
            JOIN public.field_inventory_measurements m ON m.sample_plot_id = sp.id
            WHERE sp.field_inventory_calculation_id = :fid
            GROUP BY sp.block_name, m.species_scientific, m.species_local, m.stand_type
        )
        SELECT
            block_name,
            species_scientific,
            species_local,
            SUM(CASE WHEN stand_type = 'Regeneration' THEN total_count ELSE 0 END) as regen_count,
            SUM(CASE WHEN stand_type = 'Sapling' THEN total_count ELSE 0 END) as sapling_count,
            SUM(CASE WHEN stand_type = 'Pole' THEN total_count ELSE 0 END) as pole_count,
            SUM(CASE WHEN stand_type = 'Tree' THEN total_count ELSE 0 END) as tree_count,
            SUM(CASE WHEN stand_type = 'Pole' THEN total_basal_area ELSE 0 END) as pole_basal_area,
            SUM(CASE WHEN stand_type = 'Tree' THEN total_basal_area ELSE 0 END) as tree_basal_area,
            SUM(CASE WHEN stand_type = 'Pole' THEN total_timber ELSE 0 END) as pole_timber,
            SUM(CASE WHEN stand_type = 'Pole' THEN total_firewood ELSE 0 END) as pole_firewood,
            SUM(CASE WHEN stand_type = 'Tree' THEN total_timber ELSE 0 END) as tree_timber,
            SUM(CASE WHEN stand_type = 'Tree' THEN total_firewood ELSE 0 END) as tree_firewood,
            MAX(total_plots_in_block) as total_plots
        FROM plot_species
        GROUP BY block_name, species_scientific, species_local
        ORDER BY block_name, species_scientific
    """)
    results = db.execute(query, {"fid": str(field_inventory_id)}).fetchall()
    rows = []
    for row in results:
        total_plots = row.total_plots or 1
        rp = (
            float(row.regen_count or 0) / total_plots / regen_area * SQM_PER_HA
            if row.regen_count else 0
        )
        sp = (
            float(row.sapling_count or 0) / total_plots / sapling_area * SQM_PER_HA
            if row.sapling_count else 0
        )
        pp = (
            float(row.pole_count or 0) / total_plots / pole_area * SQM_PER_HA
            if row.pole_count else 0
        )
        tp_count = (
            float(row.tree_count or 0) / total_plots / tree_area * SQM_PER_HA
            if row.tree_count else 0
        )
        tp = (
            float(row.pole_timber or 0) / total_plots / pole_area * SQM_PER_HA
            if row.pole_timber else 0
        )
        tf = (
            float(row.pole_firewood or 0) / total_plots / pole_area * SQM_PER_HA
            if row.pole_firewood else 0
        )
        tt = (
            float(row.tree_timber or 0) / total_plots / tree_area * SQM_PER_HA
            if row.tree_timber else 0
        )
        ttf = (
            float(row.tree_firewood or 0) / total_plots / tree_area * SQM_PER_HA
            if row.tree_firewood else 0
        )
        pb = (
            float(row.pole_basal_area or 0) / total_plots / pole_area * SQM_PER_HA
            if row.pole_basal_area else 0
        )
        tb = (
            float(row.tree_basal_area or 0) / total_plots / tree_area * SQM_PER_HA
            if row.tree_basal_area else 0
        )
        net_timber = tp + tt
        fuelwood = tf + ttf
        rows.append({
            "block_name": row.block_name,
            "species_scientific": row.species_scientific,
            "species_local": row.species_local or "",
            "count_per_ha": int(rp + sp + pp + tp_count),
            "regen_count_per_ha": round(rp, 2),
            "sapling_count_per_ha": round(sp, 2),
            "pole_count_per_ha": round(pp, 2),
            "tree_count_per_ha": round(tp_count, 2),
            # stage-split values (additive - the Rambhadevi-style per-stage species tables read them)
            "pole_basal_area_m2_per_ha": round(pb, 2),
            "tree_basal_area_m2_per_ha": round(tb, 2),
            "pole_timber_m3_per_ha": round(tp, 2),
            "pole_firewood_m3_per_ha": round(tf, 2),
            "tree_timber_m3_per_ha": round(tt, 2),
            "tree_firewood_m3_per_ha": round(ttf, 2),
            "basal_area_m2_per_ha": round(pb + tb, 2),
            "growing_stock_m3_per_ha": round(net_timber, 2),
            "net_timber_m3_per_ha": round(net_timber, 2),
            "fuelwood_m3_per_ha": round(fuelwood, 2),
            "total_volume_m3_per_ha": round(net_timber + fuelwood, 2),
        })
    return rows


from app.core.constants import MAI_PCT_MATRIX, MAI_PCT_DEFAULT, SQM_PER_HA, CFT_PER_M3


def _compute_mai_pct(dominant_growth_rate: Optional[str], forest_condition: Optional[str]) -> float:
    return MAI_PCT_MATRIX.get(
        (dominant_growth_rate or "Moderate", forest_condition or "Moderate"),
        MAI_PCT_DEFAULT,
    )


def _compute_ideal_reverse_j(total_nha: float, dbh_class_count: float, class_index: int) -> float:
    """Compute ideal reverse-J distribution: N_i = N_total * q^i / sum(q^i)"""
    q = 0.55
    n_classes = 6
    total = 0
    for i in range(n_classes):
        total += q ** i
    return total_nha * (q ** class_index) / total


def get_management_plan_data(
    db: Session,
    field_inventory_id: UUID,
    calculation_id: UUID,
    aah_good: float = 75.0,
    aah_moderate: float = 60.0,
    aah_weak: float = 40.0,
) -> Dict[str, Any]:
    """Collect all management plan data (block summaries, species, volumes, MAI/AAH) for DOCX export."""
    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.id == field_inventory_id
    ).first()
    if not fi:
        raise ValueError("Field inventory not found")

    block_summaries: List[FieldInventoryBlockSummary] = db.query(
        FieldInventoryBlockSummary
    ).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
    ).order_by(FieldInventoryBlockSummary.block_name).all()

    if not block_summaries:
        raise ValueError("No block summaries found. Process the field inventory first.")

    coef_cache = _fetch_species_coefficients(db)
    species_rows = _get_species_breakdown(db, field_inventory_id)
    block_areas = _fetch_block_areas(db, calculation_id)

    aah_pct_map = {"Good": aah_good, "Moderate": aah_moderate, "Weak": aah_weak}

    bs_map: Dict[str, FieldInventoryBlockSummary] = {}
    for bs in block_summaries:
        bs_map[bs.block_name.strip()] = bs

    # ========================================================================
    # 1. SPECIES COMPOSITION (forest-wide)
    # ========================================================================
    species_agg: Dict[str, Dict] = {}
    for sr in species_rows:
        sci = sr["species_scientific"]
        if sci not in species_agg:
            coef = coef_cache.get(sci, {"growth_rate": "Moderate", "wood_density": 0.65})
            species_agg[sci] = {
                "scientific_name": sci,
                "local_name": sr["species_local"],
                "total_volume_m3_per_ha": 0,
                "total_count_per_ha": 0,
                "total_basal_area_m2_per_ha": 0,
                "growth_rate": coef["growth_rate"],
                "blocks": set(),
            }
        species_agg[sci]["total_volume_m3_per_ha"] += sr["total_volume_m3_per_ha"]
        species_agg[sci]["total_count_per_ha"] += sr["count_per_ha"]
        species_agg[sci]["total_basal_area_m2_per_ha"] += sr["basal_area_m2_per_ha"]
        species_agg[sci]["blocks"].add(sr["block_name"])

    total_volume_all = sum(s["total_volume_m3_per_ha"] for s in species_agg.values())
    total_count_all = sum(s["total_count_per_ha"] for s in species_agg.values())

    species_list = sorted(species_agg.values(), key=lambda x: x["total_volume_m3_per_ha"], reverse=True)
    top_10 = species_list[:10]
    others_volume = sum(s["total_volume_m3_per_ha"] for s in species_list[10:])
    others_count = sum(s["total_count_per_ha"] for s in species_list[10:])

    forest_wide_species = []
    for s in top_10:
        forest_wide_species.append({
            "scientific_name": s["scientific_name"],
            "local_name": s["local_name"],
            "total_volume_m3_per_ha": round(s["total_volume_m3_per_ha"], 2),
            "volume_pct": round(s["total_volume_m3_per_ha"] / total_volume_all * 100, 1) if total_volume_all else 0,
            "total_count_per_ha": int(s["total_count_per_ha"]),
            "count_pct": round(s["total_count_per_ha"] / total_count_all * 100, 1) if total_count_all else 0,
            "growth_rate": s["growth_rate"],
            "block_count": len(s["blocks"]),
        })
    if species_list[10:]:
        forest_wide_species.append({
            "scientific_name": "Others",
            "local_name": "अन्य प्रजाती",
            "total_volume_m3_per_ha": round(others_volume, 2),
            "volume_pct": round(others_volume / total_volume_all * 100, 1) if total_volume_all else 0,
            "total_count_per_ha": int(others_count),
            "count_pct": round(others_count / total_count_all * 100, 1) if total_count_all else 0,
            "growth_rate": "-",
            "block_count": 0,
        })

    species_composition = {
        "forest_wide": forest_wide_species,
        "total_volume_m3_per_ha": round(total_volume_all, 2),
        "total_count_per_ha": int(total_count_all),
    }

    # ========================================================================
    # 2. BLOCK COMPARISON
    # ========================================================================
    block_comparison_list = []
    for bs in block_summaries:
        blk = bs.block_name.strip()
        area_ha = block_areas.get(blk, 0)
        nt_m3 = float(bs.tree_timber_m3_per_ha or 0) + float(bs.pole_timber_m3_per_ha or 0)
        fw_m3 = float(bs.tree_firewood_m3_per_ha or 0) + float(bs.pole_firewood_m3_per_ha or 0)
        mai_pct = float(bs.mai_percent) if bs.mai_percent else _compute_mai_pct(bs.dominant_growth_rate, bs.forest_condition)
        cond = bs.forest_condition or "Moderate"
        aah_pct = aah_pct_map.get(cond, aah_moderate)
        mai_t = nt_m3 * mai_pct / 100.0
        mai_f = fw_m3 * mai_pct / 100.0
        aah_t = mai_t * aah_pct / 100.0
        aah_f = mai_f * aah_pct / 100.0

        block_comparison_list.append({
            "name": blk,
            "area_ha": round(area_ha, 2),
            "growing_stock_m3ha": round(float(bs.total_growing_stock_m3_per_ha or 0), 2),
            "basal_area_m2ha": round(float(bs.basal_area_m2_per_ha or 0), 2),
            "carbon_tcha": round(float(bs.carbon_stock_tc_per_ha or 0), 2),
            "aah_timber_m3yr": round(aah_t, 2),
            "aah_fuelwood_m3yr": round(aah_f, 2),
            "mai_pct": round(mai_pct, 1),
            "aah_pct": round(aah_pct, 1),
            "condition": cond,
            "regeneration_condition": bs.regeneration_condition or "Weak",
        })

    ranked = sorted(block_comparison_list, key=lambda x: x["growing_stock_m3ha"], reverse=True)
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    block_comparison = {
        "blocks": block_comparison_list,
        "ranked": ranked,
    }

    # ========================================================================
    # 3. ANNUAL HARVEST PLAN
    # ========================================================================
    harvest_blocks = []
    forest_total = {"area_ha": 0, "growing_stock_m3ha": 0, "aah_timber_m3yr": 0, "aah_fuelwood_m3yr": 0}
    for bs in block_summaries:
        blk = bs.block_name.strip()
        area_ha = block_areas.get(blk, 0)
        gs = float(bs.total_growing_stock_m3_per_ha or 0)
        nt_m3 = float(bs.tree_timber_m3_per_ha or 0) + float(bs.pole_timber_m3_per_ha or 0)
        fw_m3 = float(bs.tree_firewood_m3_per_ha or 0) + float(bs.pole_firewood_m3_per_ha or 0)
        mai_pct = float(bs.mai_percent) if bs.mai_percent else _compute_mai_pct(bs.dominant_growth_rate, bs.forest_condition)
        cond = bs.forest_condition or "Moderate"
        aah_pct = aah_pct_map.get(cond, aah_moderate)
        mai_t = nt_m3 * mai_pct / 100.0
        mai_f = fw_m3 * mai_pct / 100.0
        aah_t = mai_t * aah_pct / 100.0
        aah_f = mai_f * aah_pct / 100.0
        coupe_area = aah_t / gs if gs > 0 else 0
        rotation = area_ha / coupe_area if coupe_area > 0 else 0

        harvest_blocks.append({
            "name": blk,
            "area_ha": round(area_ha, 2),
            "growing_stock_m3ha": round(gs, 2),
            "net_timber_m3ha": round(nt_m3, 2),
            "fuelwood_m3ha": round(fw_m3, 2),
            "mai_pct": round(mai_pct, 1),
            "aah_pct": round(aah_pct, 1),
            "mai_timber_m3yr": round(mai_t, 2),
            "mai_fuelwood_m3yr": round(mai_f, 2),
            "aah_timber_m3yr": round(aah_t, 2),
            "aah_fuelwood_m3yr": round(aah_f, 2),
            "aah_timber_cftyr": round(aah_t * CFT_PER_M3, 2),
            "coupe_area_ha": round(coupe_area, 2),
            "rotation_yrs": round(rotation, 1),
            "condition": cond,
        })
        forest_total["area_ha"] += area_ha
        forest_total["growing_stock_m3ha"] += gs * area_ha
        forest_total["aah_timber_m3yr"] += aah_t * area_ha
        forest_total["aah_fuelwood_m3yr"] += aah_f * area_ha

    if forest_total["area_ha"] > 0:
        forest_total["growing_stock_m3ha"] = round(forest_total["growing_stock_m3ha"] / forest_total["area_ha"], 2)
        forest_total["aah_timber_m3yr"] = round(forest_total["aah_timber_m3yr"], 2)
        forest_total["aah_fuelwood_m3yr"] = round(forest_total["aah_fuelwood_m3yr"], 2)
    else:
        forest_total["growing_stock_m3ha"] = 0

    annual_harvest_plan = {
        "blocks": harvest_blocks,
        "forest_total": forest_total,
    }

    # ========================================================================
    # 4. FOREST CONDITION SUMMARY
    # ========================================================================
    condition_agg: Dict[str, Dict] = {}
    for bs in block_summaries:
        cond = bs.forest_condition or "Moderate"
        blk = bs.block_name.strip()
        area_ha = block_areas.get(blk, 0)
        if cond not in condition_agg:
            condition_agg[cond] = {"condition": cond, "block_count": 0, "area_ha": 0, "volume_m3": 0}
        condition_agg[cond]["block_count"] += 1
        condition_agg[cond]["area_ha"] += area_ha
        condition_agg[cond]["volume_m3"] += float(bs.total_growing_stock_m3_per_ha or 0) * area_ha

    by_condition = []
    for cond_data in condition_agg.values():
        area = cond_data["area_ha"]
        by_condition.append({
            "condition": cond_data["condition"],
            "block_count": cond_data["block_count"],
            "area_ha": round(area, 2),
            "total_volume_m3": round(cond_data["volume_m3"], 2),
            "avg_volume_m3ha": round(cond_data["volume_m3"] / area, 2) if area > 0 else 0,
        })

    total_area_all = sum(c["area_ha"] for c in by_condition)
    for c in by_condition:
        c["area_pct"] = round(c["area_ha"] / total_area_all * 100, 1) if total_area_all > 0 else 0

    regeneration_list = []
    for bs in block_summaries:
        blk = bs.block_name.strip()
        dbh_data = bs.dbh_class_breakdown or {}
        regen_cls = dbh_data.get("0_4", {})
        sapling_cls = dbh_data.get("4_10", {})
        regen_n = float(regen_cls.get("count_per_ha", 0))
        sapling_n = float(sapling_cls.get("count_per_ha", 0))
        rc = bs.regeneration_condition or "Weak"

        if regen_n >= 5000 and sapling_n >= 2000:
            rec = "Natural regeneration sufficient"
        elif regen_n >= 2000 and sapling_n >= 800:
            rec = "Enrichment planting recommended in gaps"
        else:
            rec = "Active regeneration intervention required"

        regeneration_list.append({
            "block": blk,
            "condition": rc,
            "seedling_nha": int(regen_n),
            "sapling_nha": int(sapling_n),
            "total_nha": int(regen_n + sapling_n),
            "recommendation": rec,
        })

    forest_condition_summary = {
        "by_condition": by_condition,
        "regeneration": regeneration_list,
        "total_area_ha": round(total_area_all, 2),
    }

    # ========================================================================
    # 5. DBH CLASS VOLUME
    # ========================================================================
    dbh_class_volume_blocks = []
    for bs in block_summaries:
        blk = bs.block_name.strip()
        dbh_data = bs.dbh_class_breakdown or {}
        classes = []
        for key, nepali_name in DBH_CLASS_POLETREE:
            cls_row = dbh_data.get(key, {})
            cnt = float(cls_row.get("count_per_ha", 0))
            tbr = float(cls_row.get("timber_m3_per_ha", 0))
            fw = float(cls_row.get("firewood_m3_per_ha", 0))
            if cnt > 0 or tbr > 0 or fw > 0:
                classes.append({
"dbh_class": "60+" if key == "60_plus" else key.replace("_", "-"),
                    "nepali_name": nepali_name,
                    "count_nha": round(cnt, 2),
                    "timber_m3ha": round(tbr, 2),
                    "fuelwood_m3ha": round(fw, 2),
                    "total_m3ha": round(tbr + fw, 2),
                })
        dbh_class_volume_blocks.append({
            "block": blk,
            "classes": classes,
        })

    # ========================================================================
    # 6. CARBON PER BLOCK
    # ========================================================================
    carbon_blocks = []
    carbon_total = {"agb_t": 0, "bgb_t": 0, "c_stock_t": 0, "co2e_t": 0}
    for bs in block_summaries:
        blk = bs.block_name.strip()
        area_ha = block_areas.get(blk, 0)
        agb = float(bs.agb_t_per_ha or 0)
        bgb = float(bs.bgb_t_per_ha or 0)
        c_stock = float(bs.carbon_stock_tc_per_ha or 0)
        co2e = float(bs.co2_equivalent_tco2_per_ha or 0)
        carbon_blocks.append({
            "block": blk,
            "area_ha": round(area_ha, 2),
            "agb_tha": round(agb, 2),
            "bgb_tha": round(bgb, 2),
            "total_biomass_tha": round(agb + bgb, 2),
            "c_stock_tcha": round(c_stock, 2),
            "co2e_tha": round(co2e, 2),
            "total_co2e_t": round(co2e * area_ha, 2),
        })
        carbon_total["agb_t"] += agb * area_ha
        carbon_total["bgb_t"] += bgb * area_ha
        carbon_total["c_stock_t"] += c_stock * area_ha
        carbon_total["co2e_t"] += co2e * area_ha

    for k in carbon_total:
        carbon_total[k] = round(carbon_total[k], 2)

    carbon_per_block = {
        "blocks": carbon_blocks,
        "forest_total": carbon_total,
    }

    # ========================================================================
    # 7. GROWTH RATE CLASSIFICATION
    # ========================================================================
    growth_agg: Dict[str, Dict] = {}
    for s in species_agg.values():
        gr = s["growth_rate"]
        if gr not in growth_agg:
            growth_agg[gr] = {"rate": gr, "species_count": 0, "volume_m3_per_ha": 0, "species_list": []}
        growth_agg[gr]["species_count"] += 1
        growth_agg[gr]["volume_m3_per_ha"] += s["total_volume_m3_per_ha"]
        growth_agg[gr]["species_list"].append(s["local_name"] or s["scientific_name"])

    total_gr_volume = sum(g["volume_m3_per_ha"] for g in growth_agg.values())
    growth_classes = []
    for gr_data in growth_agg.values():
        growth_classes.append({
            "rate": gr_data["rate"],
            "species_count": gr_data["species_count"],
            "volume_m3_per_ha": round(gr_data["volume_m3_per_ha"], 2),
            "volume_pct": round(gr_data["volume_m3_per_ha"] / total_gr_volume * 100, 1) if total_gr_volume > 0 else 0,
            "species": ", ".join(gr_data["species_list"][:5]),
        })

    growth_rate_classification = {
        "classes": growth_classes,
        "total_volume_m3_per_ha": round(total_gr_volume, 2),
    }

    # ========================================================================
    # 8. STAND STRUCTURE PROFILE
    # ========================================================================
    structure_blocks = []
    overall_assessment = "Sustainable"
    total_deficiency = 0
    for bs in block_summaries:
        blk = bs.block_name.strip()
        dbh_data = bs.dbh_class_breakdown or {}
        total_pole_tree_nha = sum(
            float(dbh_data.get(key, {}).get("count_per_ha", 0))
            for key, _ in DBH_CLASS_POLETREE
        )
        classes = []
        for i, (key, nepali_name) in enumerate(DBH_CLASS_POLETREE):
            actual = float(dbh_data.get(key, {}).get("count_per_ha", 0))
            ideal = _compute_ideal_reverse_j(total_pole_tree_nha, actual, i) if total_pole_tree_nha > 0 else 0
            diff = actual - ideal
            if diff < -10:
                status = "Deficient"
                total_deficiency += abs(diff)
            elif diff < -3:
                status = "Slightly deficient"
            elif diff > 10:
                status = "Overstocked"
            elif diff > 3:
                status = "Slightly overstocked"
            else:
                status = "Balanced"
            classes.append({
                "dbh_class": key.replace("_", "–"),
                "nepali_name": nepali_name,
                "actual_nha": round(actual, 2),
                "ideal_nha": round(ideal, 2),
                "difference": round(diff, 2),
                "status": status,
            })
        structure_blocks.append({
            "block": blk,
            "classes": classes,
        })

    if total_deficiency > 100:
        overall_assessment = "Over-harvested in large DBH classes — recruitment deficit"
    elif total_deficiency > 30:
        overall_assessment = "Slightly unbalanced — monitoring recommended"

    stand_structure = {
        "blocks": structure_blocks,
        "assessment": overall_assessment,
    }

    # ========================================================================
    # 9. PRODUCTIVITY CLASSIFICATION
    # ========================================================================
    prod_classes = []
    for class_name, lo, hi, rec in PRODUCTIVITY_THRESHOLDS:
        matched = []
        total_area = 0
        total_vol = 0
        for bs in block_summaries:
            blk = bs.block_name.strip()
            gs = float(bs.total_growing_stock_m3_per_ha or 0)
            if lo <= gs < hi:
                area_ha = block_areas.get(blk, 0)
                matched.append(blk)
                total_area += area_ha
                total_vol += gs * area_ha
        prod_classes.append({
            "class": class_name,
            "threshold": f"{'>' if hi == float('inf') else f'{int(lo)}–{int(hi)}'} m³/ha",
            "blocks": matched,
            "block_count": len(matched),
            "area_ha": round(total_area, 2),
            "volume_m3": round(total_vol, 2),
            "recommendation": rec,
        })

    productivity_classification = {
        "classes": prod_classes,
    }

    # ========================================================================
    # RASTER ANALYSIS DATA (from calculation result_data)
    # ========================================================================
    from ..models.calculation import Calculation
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    raster_analysis: Dict = {}
    blocks_raster: List[Dict] = []
    if calc and calc.result_data:
        rd = calc.result_data
        for key in [
            "slope_percentages", "aspect_percentages", "canopy_percentages",
            "forest_health_percentages", "forest_type_percentages", "landcover_percentages",
            "forest_loss_by_year", "forest_loss_hectares", "forest_gain_hectares",
            "fire_loss_hectares", "fire_loss_by_year",
            "landcover_1984_percentages", "hansen2000_percentages",
            "nasa_forest_2020_percentages",
            "soil_texture", "fertility_class", "fertility_score",
            "carbon_stock_t_ha", "compaction_status",
            "whole_geology_percentages", "whole_physiography_percentages", "whole_ecoregion_percentages",
            "temperature_mean_c", "temperature_min_c", "temperature_max_c",
            "precipitation_mean_mm", "precipitation_min_mm", "precipitation_max_mm",
            "elevation_min_m", "elevation_max_m", "elevation_mean_m", "canopy_mean_m",
        ]:
            if key in rd:
                raster_analysis[key] = rd[key]

        # 1984 land use: recompute fresh from the vector polygons every time
        # (the stored value only exists if `run_landcover_1984` was enabled at
        # analysis time, and the old computation was per-polygon-not-per-class).
        try:
            from .operational_plan.data_collector import (
                _enrich_landcover_1984_from_polygons,
            )

            _enrich_landcover_1984_from_polygons(db, calculation_id, raster_analysis)
        except Exception:
            logger.warning(
                "landcover_1984 enrichment failed for calc=%s", calculation_id,
                exc_info=True,
            )

        for blk in rd.get("blocks", []):
            br: Dict = {"block_name": blk.get("block_name", "")}
            for key in [
                "slope_percentages", "aspect_percentages", "canopy_percentages",
                "forest_health_percentages", "forest_type_percentages", "landcover_percentages",
                "nasa_forest_2020_percentages", "forest_loss_hectares", "forest_gain_hectares",
            ]:
                if key in blk:
                    br[key] = blk[key]
            blocks_raster.append(br)

    # ========================================================================
    # RETURN
    # ========================================================================
    return {
        "species_composition": species_composition,
        "block_comparison": block_comparison,
        "annual_harvest_plan": annual_harvest_plan,
        "forest_condition_summary": forest_condition_summary,
        "dbh_class_volume": {"blocks": dbh_class_volume_blocks},
        "carbon_per_block": carbon_per_block,
        "growth_rate_classification": growth_rate_classification,
        "stand_structure": stand_structure,
        "productivity_classification": productivity_classification,
        "raster_analysis": raster_analysis,
        "blocks_raster": blocks_raster,
    }
