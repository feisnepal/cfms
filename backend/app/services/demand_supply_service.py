"""
Demand and Supply Service
Computes forest product demand vs. supply from multiple sources
# business: CFMG §4.3 — household demand-supply calculation
"""
from typing import Dict, Optional
from sqlalchemy.orm import Session
from uuid import UUID
from decimal import Decimal
import logging

from ..models.calculation import Calculation
from .forest_units import queries as forest_unit_queries
from ..models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventoryBlockSummary
)
from ..models.household_information import HouseholdInformation

logger = logging.getLogger(__name__)

# Conversion constants — single source in app.core.constants
# constraint: firewood in bhari (~30 kg), timber in cft
from app.core.constants import (
    BHARI_KG,
    CFT_PER_M3,
    WOOD_DENSITY_KG_PER_M3,
    AAH_MULTIPLIER,
    PRIVATE_MAI_PCT,
    PRIVATE_SHRUB_MAI_PCT,
    PRIVATE_TIMBER_FRACTION,
    PRIVATE_FIREWOOD_FRACTION,
    PRIVATE_AVG_POLE_VOLUME_M3,
    PRIVATE_CROPLAND_GRASS_YIELD_KG_HA_YR,
    PRIVATE_LAND_GROWING_STOCK_M3_HA,
    PRIVATE_SHRUBLAND_GROWING_STOCK_M3_HA,
    PRIVATE_GRASSLAND_BEDDING_YIELD_KG_HA_YR,
    SATELLITE_AGB_TO_VOLUME_FACTOR,
)
from app.core.units import m3_to_bhari  # SSOT: firewood m³ -> bhari

PER_100SQM_TO_HA = 100  # 100 sqm → 1 ha multiplier

# Private land assumptions
PRIVATE_AAH_MULTIPLIER = AAH_MULTIPLIER["Moderate"]  # AAH multiplier % (moderate)
PRIVATE_TIMBER_FRACTION = 0.60  # 60% of growing stock = timber
PRIVATE_FIREWOOD_FRACTION = 0.40  # 40% = firewood
PRIVATE_AVG_POLE_VOLUME_M3 = 0.05  # avg volume per pole
PRIVATE_CROPLAND_GRASS_YIELD_KG_HA_YR = 12000  # kg/ha/yr agricultural residue
PRIVATE_GRASSLAND_BEDDING_YIELD_KG_HA_YR = 8000  # kg/ha/yr for grass+beding


def _fetch_block_areas(db: Session, calculation_id: UUID) -> Dict[str, float]:
    """{unit name: area in hectares} for the forest's units.

    The leaf view of ``forest_units`` (FS-1a.9): every unit that is not divided further, so a compartment
    forest is no longer invisible (it read the blocks array of ``result_data``, which is empty for one). A forest
    with no unit rows (upload-mode, JSONB only) falls back to that array."""
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


def get_demand(db: Session, calculation_id: UUID) -> Dict[str, Optional[float]]:
    """Yearly demand from household rows, or from the entered summary when there are none."""
    from .household_aggregate import get_aggregate

    agg = get_aggregate(db, calculation_id)
    if agg is None:
        return {
            "firewood_bhari": 0,
            "grass_bhari": 0,
            "bedding_bhari": 0,
            "timber_cft": 0,
            "poles_count": 0,
        }

    return {
        "firewood_bhari": float(agg["total_firewood_demand_bhari"]),
        "grass_bhari": float(agg["total_grass_demand_bhari"]),
        "bedding_bhari": float(agg["total_bedding_demand_bhari"]),
        "timber_cft": float(agg["total_timber_demand_cft"]),
        "poles_count": int(agg["total_pole_demand"]),
    }


def get_community_forest_regular_supply(
    db: Session, calculation_id: UUID
) -> Dict[str, Optional[float]]:
    """
    Compute regular collection supply from community forest.
    Uses kg/100sqm → kg/ha → bhari conversion for firewood, grass, bedding.
    """
    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.calculation_id == calculation_id
    ).first()

    if not fi:
        return {
            "firewood_bhari": None,
            "grass_bhari": None,
            "bedding_bhari": None,
            "timber_cft": None,
            "poles_count": None,
        }

    block_areas = _fetch_block_areas(db, calculation_id)
    if not block_areas:
        return {
            "firewood_bhari": None,
            "grass_bhari": None,
            "bedding_bhari": None,
            "timber_cft": None,
            "poles_count": None,
        }

    block_summaries = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == fi.id
    ).all()

    total_fw_bhari = 0.0
    total_gr_bhari = 0.0
    total_bd_bhari = 0.0

    for bs in block_summaries:
        area_ha = block_areas.get(bs.block_name, 0)
        if area_ha <= 0:
            continue

        fw_kg_ha = float(bs.firewood_kg_per_ha_per_year or 0)
        gr_kg_ha = float(bs.grass_kg_per_ha_per_year or 0)
        bd_kg_ha = float(bs.bedding_material_kg_per_ha_per_year or 0)

        total_fw_bhari += (fw_kg_ha * area_ha) / BHARI_KG
        total_gr_bhari += (gr_kg_ha * area_ha) / BHARI_KG
        total_bd_bhari += (bd_kg_ha * area_ha) / BHARI_KG

    return {
        "firewood_bhari": round(total_fw_bhari, 2),
        "grass_bhari": round(total_gr_bhari, 2),
        "bedding_bhari": round(total_bd_bhari, 2),
        "timber_cft": None,
        "poles_count": None,
    }


def get_community_forest_aah_supply(
    db: Session, calculation_id: UUID
) -> Dict[str, Optional[float]]:
    """
    Compute AAH-based harvest supply from community forest for timber and poles.
    Uses block summaries to compute MAI/AAH per block then sum.
    # why: AAH supply capped at 80% of growing stock per CFMG sustainability rule
    """
    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.calculation_id == calculation_id
    ).first()

    if not fi:
        return {
            "firewood_bhari": None,
            "grass_bhari": None,
            "bedding_bhari": None,
            "timber_cft": None,
            "poles_count": None,
        }

    block_areas = _fetch_block_areas(db, calculation_id)
    if not block_areas:
        return {
            "firewood_bhari": None,
            "grass_bhari": None,
            "bedding_bhari": None,
            "timber_cft": None,
            "poles_count": None,
        }

    # Default AAH multipliers by forest condition — single source in app.core.constants.
    from app.core.constants import AAH_MULTIPLIER as aah_mult_map  # noqa: F401

    block_summaries = db.query(FieldInventoryBlockSummary).filter(
        FieldInventoryBlockSummary.field_inventory_calculation_id == fi.id
    ).all()

    total_aah_m3 = 0.0
    total_poles = 0

    for bs in block_summaries:
        area_ha = block_areas.get(bs.block_name, 0)
        if area_ha <= 0:
            continue

        # MAI = growing_stock × MAI%
        mai_percent = float(bs.mai_percent or 0) / 100.0
        growing_stock = float(bs.total_growing_stock_m3_per_ha or 0)
        mai_m3_per_ha = growing_stock * mai_percent

        # AAH = MAI × multiplier (based on forest condition)
        condition = bs.forest_condition or "Moderate"
        aah_mult = aah_mult_map.get(condition, 60.0) / 100.0
        aah_m3_per_ha = mai_m3_per_ha * aah_mult

        total_aah_m3 += aah_m3_per_ha * area_ha

        # Poles (pole_per_ha count is for the whole growing stock,
        # we use pole count as-is from the extrapolation)
        pole_count = int((bs.pole_per_ha or 0) * area_ha * mai_percent * aah_mult)
        total_poles += pole_count

    return {
        "firewood_bhari": None,
        "grass_bhari": None,
        "bedding_bhari": None,
        "timber_cft": round(total_aah_m3 * CFT_PER_M3, 2),
        "poles_count": total_poles,
    }


def _class_area(result_data: Dict, class_name: str, total_area_ha: float) -> float:
    """Get area in hectares for a land cover class from result_data percentages"""
    pcts = result_data.get("landcover_percentages", {})
    pct = float(pcts.get(class_name, 0))
    return (pct / 100.0) * total_area_ha if pct else 0.0


def _total_calc_area(
    result_data: Dict,
    db: Optional[Session] = None,
    calculation_id: Optional[UUID] = None,
) -> float:
    """Total area of the forest's units (leaf view - FS-1a.9); the ``result_data`` blocks only when the forest
    has no unit rows."""
    if db is not None and calculation_id is not None:
        leaf = forest_unit_queries.units(db, calculation_id, forest_unit_queries.View.LEAF)
        if leaf:
            return sum(u.area_ha for u in leaf)
    return sum(
        float(b.get("area_hectares", 0))
        for b in result_data.get("blocks", [])
    )


def _fallback_gs_from_agb(rd: dict) -> float:
    """Estimate growing stock from satellite AGB raster when field inventory is unavailable."""
    try:
        agb_mean = rd.get("raster_analysis", {}).get("biomass", {}).get("agb_mean")
        if agb_mean and agb_mean > 0:
            return float(agb_mean) * SATELLITE_AGB_TO_VOLUME_FACTOR
    except (TypeError, ValueError):
        pass
    return PRIVATE_LAND_GROWING_STOCK_M3_HA


def get_private_supply(
    db: Session, calculation_id: UUID
) -> Dict[str, Optional[float]]:
    """
    Estimate supply from private land (user boundary, outside forest).
    Uses land cover classification data from calculation result_data.
    """
    calc = db.query(Calculation).filter(
        Calculation.id == calculation_id
    ).first()

    if not calc or not calc.result_data:
        return {
            "firewood_bhari": None,
            "grass_bhari": None,
            "bedding_bhari": None,
            "timber_cft": None,
            "poles_count": None,
        }

    rd = calc.result_data
    total_area_ha = _total_calc_area(rd, db, calculation_id)
    if total_area_ha <= 0:
        return {
            "firewood_bhari": None,
            "grass_bhari": None,
            "bedding_bhari": None,
            "timber_cft": None,
            "poles_count": None,
        }

    # Get per-class areas from landcover_percentages in result_data
    tree_cover_area_ha = _class_area(rd, "Tree cover", total_area_ha)
    shrub_area_ha = _class_area(rd, "Shrubland", total_area_ha)
    grassland_area_ha = _class_area(rd, "Grassland", total_area_ha)
    cropland_area_ha = _class_area(rd, "Cropland", total_area_ha)

    # --- Estimate tree cover growing stock ---
    # Try average from field inventory; fall back to AGB raster estimate;
    # then to Nepal-average default.
    fi = db.query(FieldInventoryCalculation).filter(
        FieldInventoryCalculation.calculation_id == calculation_id
    ).first()
    if fi:
        bs_list = db.query(FieldInventoryBlockSummary).filter(
            FieldInventoryBlockSummary.field_inventory_calculation_id == fi.id
        ).all()
        gs_vals = [float(b.total_growing_stock_m3_per_ha or 0) for b in bs_list if b.total_growing_stock_m3_per_ha]
        if gs_vals:
            avg_gs = sum(gs_vals) / len(gs_vals)
        else:
            avg_gs = _fallback_gs_from_agb(rd)
    else:
        avg_gs = _fallback_gs_from_agb(rd)

    tree_cover_volume_m3 = tree_cover_area_ha * avg_gs

    # --- Timber & Firewood from tree cover ---
    # Private MAI = growing_stock × MAI%
    # Private AAH = MAI × AAH_multiplier
    mai_decimal = float(PRIVATE_MAI_PCT) / 100.0
    aah_decimal = PRIVATE_AAH_MULTIPLIER / 100.0

    private_mai_m3 = tree_cover_volume_m3 * mai_decimal
    private_aah_m3 = private_mai_m3 * aah_decimal

    private_timber_m3 = private_aah_m3 * PRIVATE_TIMBER_FRACTION
    private_firewood_m3 = private_aah_m3 * PRIVATE_FIREWOOD_FRACTION

    # Shrubland firewood (lower rate)
    shrub_vol_est = shrub_area_ha * 20  # assume 20 m³/ha growing stock
    shrub_mai = shrub_vol_est * (float(PRIVATE_SHRUB_MAI_PCT) / 100.0)
    shrub_aah = shrub_mai * aah_decimal
    shrub_firewood_m3 = shrub_aah  # all shrub = firewood

    total_firewood_m3 = private_firewood_m3 + shrub_firewood_m3
    firewood_bhari = m3_to_bhari(total_firewood_m3, None)

    # Poles from private timber
    private_poles = int((private_timber_m3) / PRIVATE_AVG_POLE_VOLUME_M3) if private_timber_m3 > 0 else 0

    # --- Grass from cropland ---
    grass_bhari = (cropland_area_ha * PRIVATE_CROPLAND_GRASS_YIELD_KG_HA_YR) / BHARI_KG

    # --- Bedding from grassland ---
    bedding_bhari = (grassland_area_ha * PRIVATE_GRASSLAND_BEDDING_YIELD_KG_HA_YR) / BHARI_KG

    return {
        "firewood_bhari": round(firewood_bhari, 2),
        "grass_bhari": round(grass_bhari, 2),
        "bedding_bhari": round(bedding_bhari, 2),
        "timber_cft": round(private_timber_m3 * CFT_PER_M3, 2),
        "poles_count": private_poles,
    }


def build_nepali_description(
    demand: Dict,
    supply_cf_reg: Dict,
    supply_cf_aah: Dict,
    supply_pvt: Dict,
    total_supply: Dict,
    deficit: Dict,
) -> str:
    """Generate Devanagari description paragraph explaining the table"""
    fw_surplus = deficit.get("firewood_bhari", 0)
    gr_surplus = deficit.get("grass_bhari", 0)
    bd_surplus = deficit.get("bedding_bhari", 0)
    tm_surplus = deficit.get("timber_cft", 0)
    pl_surplus = deficit.get("poles_count", 0)

    def _status(val, unit_np):
        if val is None:
            return "—"
        if val > 0:
            return f"{abs(val):,.1f} {unit_np} बचत"
        elif val < 0:
            return f"{abs(val):,.1f} {unit_np} अभाव"
        return "सन्तुलित"

    desc = (
        "यस तालिकाले उपभोक्ता समूहका घरधुरीहरूको वन पैदावार माग र आपूर्ति अवस्था देखाउँदछ। "
        "मागको गणना घरधुरी सर्वेक्षण (Household Survey) का आधारमा गरिएको छ। "
        "सामुदायिक वनबाट हुने आपूर्ति दुई भागमा विभाजन गरिएको छ: "
        "(क) नियमित सङ्कलन — दाउरा, घाँस र सोतर जस्ता वर्षभरि सङ्कलन हुने सामान्य वन पैदावारहरू, "
        "जुन क्षेत्र सर्वेक्षणमा उल्लेख गरिएको प्रति १ सय वर्गमिटर वार्षिक उपज (केजी) लाई प्रति हेक्टरमा "
        "रूपान्तरण (× १००) गरी वन ब्लकको क्षेत्रफलले गुणन गरी ३० केजी = १ भारी का दरले भारीमा "
        "गणना गरिएको छ। "
        "(ख) वार्षिक स्वीकार्य कटान (AAH) — काठ र खाँवाको लागि वन अवस्था र वृद्धि दरमा आधारित दिगो उपज। "
        "निजी क्षेत्रबाट हुने आपूर्ति जमिन वर्गीकरण (Land Cover) का आधारमा अनुमान गरिएको छ। "
        f"आपूर्ति र माग बीचको अन्तर: दाउरा ({_status(fw_surplus, 'भारी')}), "
        f"घाँस ({_status(gr_surplus, 'भारी')}), "
        f"सोतर ({_status(bd_surplus, 'भारी')}), "
        f"काठ ({_status(tm_surplus, 'क्यू.फि.')}), "
        f"खाँवा ({_status(pl_surplus, 'संख्या')})."
    )
    return desc
