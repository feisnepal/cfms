"""
Data collector for report generation
Gathers all relevant data from database for each report section
"""
# why: report data collector aggregates from 15+ models
# constraint: Decimal → float conversion required for JSON
# NOTE: separate from op/data_collector.py (operational plan)
import json
from decimal import Decimal
from typing import Dict, Any, Optional, List
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock
from app.models.forest_sub_area import ForestSubArea
from app.models.inventory import InventoryCalculation, InventoryTree
from app.models.sampling import SamplingDesign
from app.models.household_information import HouseholdInformation
from app.models.forest_committee import ForestUserCommittee, AdvisoryCommittee, FinancialCommittee
from app.models.yearly_activities import ProposedYearlyActivity, ActivityYearDetail
from app.models.biodiversity import CalculationBiodiversity, BiodiversitySpecies
from app.models.user_group import UserGroupExtent, UserGroupBuilding

import logging

logger = logging.getLogger(__name__)


def _convert_decimals(obj):
    """Recursively convert Decimal objects to float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_decimals(item) for item in obj]
    elif isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def get_calculation_basic_info(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get basic calculation information"""
    from sqlalchemy.orm import load_only
    calc = db.query(Calculation).options(
        load_only(
            Calculation.forest_name, Calculation.block_name,
            Calculation.status, Calculation.created_at,
            Calculation.completed_at, Calculation.result_data,
        )
    ).filter(Calculation.id == calculation_id).first()
    if not calc:
        return {}

    result_data = calc.result_data or {}

    # Fallback: query admin.admin_nepal for Nepali names if missing from result_data
    if not result_data.get("whole_division_n"):
        try:
            fn_query = text("""
                SELECT province_ne, division_n, subdivis_n, palika_n,
                       type_nep, ward_ne, physiography_ne, juridiction_ne
                FROM admin.admin_nepal
                WHERE ST_Contains(geom, ST_Centroid(ST_GeomFromText(:wkt, 4326)))
                LIMIT 1
            """)
            wkt = db.execute(
                text("SELECT ST_AsText(boundary_geom) FROM public.calculations WHERE id = :cid"),
                {"cid": str(calc.id)}
            ).scalar()
            if wkt:
                row = db.execute(fn_query, {"wkt": wkt}).first()
                if row:
                    result_data.setdefault("whole_province_ne", row[0])
                    result_data.setdefault("whole_division_n", row[1])
                    result_data.setdefault("whole_subdivis_n", row[2])
                    result_data.setdefault("whole_municipality_n", row[3])
                    result_data.setdefault("whole_municipality_type_nep", row[4])
                    result_data.setdefault("whole_ward_ne", row[5])
                    result_data.setdefault("whole_physiography_ne", row[6])
                    result_data.setdefault("whole_juridiction_ne", row[7])
        except Exception:
            logger.exception(
                "administrative lookup failed - province, division and palika "
                "will be blank on the report cover"
            )

    return {
        "forest_name": calc.forest_name or "",
        "block_name": calc.block_name or "",
        "status": calc.status,
        "created_at": calc.created_at.isoformat() if calc.created_at else "",
        "completed_at": calc.completed_at.isoformat() if calc.completed_at else "",
        "total_area_sqm": result_data.get("area_sqm", 0),
        "total_area_hectares": result_data.get("area_hectares", 0),
        "effective_area_hectares": result_data.get("effective_area_hectares", 0),
        "excluded_area_hectares": result_data.get("excluded_area_hectares", 0),
        "province": result_data.get("whole_province_ne", "") or result_data.get("whole_province", ""),
        "district": result_data.get("whole_division_n", "") or result_data.get("whole_district", ""),
        "municipality": result_data.get("whole_municipality_n", "") or result_data.get("whole_municipality", ""),
        "municipality_type": result_data.get("whole_municipality_type_nep", "") or result_data.get("whole_municipality_type", ""),
        "ward": result_data.get("whole_ward_ne", "") or result_data.get("whole_ward", ""),
        "watershed": result_data.get("whole_watershed", ""),
        "major_river_basin": result_data.get("whole_major_river_basin", ""),
        "total_blocks": result_data.get("total_blocks", 0),
        "utm_zone": result_data.get("utm_zone", 0),
    }


def get_boundary_info(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get boundary geometry and fieldbook data"""
    from sqlalchemy.orm import load_only
    calc = db.query(Calculation).options(
        load_only(Calculation.result_data)
    ).filter(Calculation.id == calculation_id).first()
    if not calc:
        return {}

    result_data = calc.result_data or {}
    # The unit set the analysis ran on - blocks OR compartments, the leaf view (FS-1a.12). Reading only the
    # blocks array gave a compartment forest zero units.
    from app.services.analysis_polygon_source import PolygonSource

    blocks = PolygonSource.for_result_data(result_data).get_polygons()

    block_info = []
    for block in blocks:
        block_info.append({
            "name": block.get("block_name", ""),
            "area_hectares": block.get("area_hectares", 0),
            "effective_area_hectares": block.get("effective_area_hectares", 0),
            "centroid": block.get("centroid", {}),
        })

    features = {
        "north": result_data.get("whole_features_north") or [],
        "east": result_data.get("whole_features_east") or [],
        "south": result_data.get("whole_features_south") or [],
        "west": result_data.get("whole_features_west") or [],
    }

    return {
        "total_blocks": len(blocks),
        "blocks": block_info,
        "boundary_type": "MultiPolygon" if len(blocks) > 1 else "Polygon",
        "features": features,
        "whole_forest_extent": result_data.get("whole_forest_extent") or {},
    }


def get_species_info(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get species data from analysis results"""
    from sqlalchemy.orm import load_only
    calc = db.query(Calculation).options(
        load_only(Calculation.result_data)
    ).filter(Calculation.id == calculation_id).first()
    if not calc:
        return {}

    result_data = calc.result_data or {}
    species_list = result_data.get("potential_species", [])
    removed_species = result_data.get("removed_species", [])
    confirmed_species = result_data.get("confirmed_species", [])

    filtered_species = [s for s in species_list if s.get("scientific_name") not in removed_species]

    species_by_role = {}
    for s in filtered_species:
        role = s.get("role", "Other")
        if role not in species_by_role:
            species_by_role[role] = []
        species_by_role[role].append({
            "scientific_name": s.get("scientific_name", ""),
            "local_name": s.get("local_name", ""),
            "nepali_name": s.get("nepali_name", ""),
            "altitude_range": s.get("altitude_range", ""),
            "growth_rate": s.get("growth_rate", ""),
            "economic_value": s.get("economic_value", ""),
        })

    return {
        "total_species": len(filtered_species),
        "species_list": filtered_species,
        "removed_species": removed_species,
        "confirmed_species": confirmed_species,
        "species_by_role": species_by_role,
        "species_count": result_data.get("species_count", 0),
    }


def get_raster_analysis(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get all raster analysis results"""
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        return {}

    result_data = calc.result_data or {}

    return {
        "elevation": {
            "min_m": result_data.get("elevation_min_m", 0),
            "max_m": result_data.get("elevation_max_m", 0),
            "mean_m": result_data.get("elevation_mean_m", 0),
        },
        "slope": {
            "dominant_class": result_data.get("slope_dominant_class", ""),
            "percentages": result_data.get("slope_percentages", {}),
        },
        "aspect": {
            "dominant": result_data.get("aspect_dominant", ""),
            "percentages": result_data.get("aspect_percentages", {}),
        },
        "canopy": {
            "dominant_class": result_data.get("canopy_dominant_class", ""),
            "percentages": result_data.get("canopy_percentages", {}),
            "mean_m": result_data.get("canopy_mean_m", 0),
        },
        "biomass": {
            "agb_mean": result_data.get("agb_mean", 0),
            "agb_total": result_data.get("agb_total", 0),
            "carbon_stock": result_data.get("carbon_stock", 0),
        },
        "forest_health": {
            "dominant": result_data.get("forest_health_dominant", ""),
            "percentages": result_data.get("forest_health_percentages", {}),
        },
        "forest_type": {
            "dominant": result_data.get("forest_type_dominant", ""),
            "percentages": result_data.get("forest_type_percentages", {}),
        },
        "landcover": {
            "dominant": result_data.get("landcover_dominant", ""),
            "percentages": result_data.get("landcover_percentages", {}),
        },
        "forest_loss_gain": {
            "loss_hectares": result_data.get("forest_loss_hectares", 0),
            "gain_hectares": result_data.get("forest_gain_hectares", 0),
            "loss_by_year": result_data.get("forest_loss_by_year", {}),
        },
        "temperature": {
            "mean_c": result_data.get("temperature_mean_c", 0),
            "min_c": result_data.get("temperature_min_c", 0),
            "max_c": result_data.get("temperature_max_c", 0),
        },
        "precipitation": {
            "mean_mm": result_data.get("precipitation_mean_mm", 0),
            "min_mm": result_data.get("precipitation_min_mm", 0),
            "max_mm": result_data.get("precipitation_max_mm", 0),
        },
        "soil": {
            "dominant_type": result_data.get("soil_dominant_type", ""),
            "percentages": result_data.get("soil_percentages", {}),
        },
        "geology": {
            "percentages": result_data.get("whole_geology_percentages", {}),
        },
        "physiography": {
            "percentages": result_data.get("whole_physiography_percentages", {}),
        },
        "ecoregion": {
            "percentages": result_data.get("whole_ecoregion_percentages", {}),
        },
        "landcover_historical": {
            "landcover_1984_dominant": result_data.get("landcover_1984_dominant", ""),
            "landcover_1984_percentages": result_data.get("landcover_1984_percentages", {}),
            "hansen2000_dominant": result_data.get("hansen2000_dominant", ""),
            "hansen2000_percentages": result_data.get("hansen2000_percentages", {}),
        },
    }


def get_block_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get block-wise data from database"""
    # The leaf view (FS-1a.12): every unit that is not divided further. It returned every row at every depth, so a
    # divided block or compartment was counted next to its own pieces.
    from sqlalchemy.orm import load_only
    from app.services.forest_units import queries as forest_unit_queries

    blocks = forest_unit_queries.unit_rows(db, calculation_id, forest_unit_queries.View.LEAF)

    sub_areas = db.query(ForestSubArea).options(
        load_only(
            ForestSubArea.block_id, ForestSubArea.name,
            ForestSubArea.category, ForestSubArea.area_hectares,
            ForestSubArea.is_excluded,
        )
    ).filter(
        ForestSubArea.calculation_id == calculation_id
    ).all()

    block_results = []
    for block in blocks:
        block_data = {
            "id": str(block.id),
            "name": block.name,
            "area_hectares": block.area_hectares,
            "area_sqm": block.area_sqm,
            "index": block.index,
            "is_compartment": block.is_compartment,
            "sub_areas": [],
        }

        for sa in sub_areas:
            if sa.block_id == block.id:
                block_data["sub_areas"].append({
                    "name": sa.name,
                    "category": sa.category,
                    "area_hectares": sa.area_hectares,
                    "is_excluded": sa.is_excluded,
                })

        block_results.append(block_data)

    sub_area_summary = {}
    for sa in sub_areas:
        cat = sa.category
        if cat not in sub_area_summary:
            sub_area_summary[cat] = {"count": 0, "total_area_hectares": 0}
        sub_area_summary[cat]["count"] += 1
        sub_area_summary[cat]["total_area_hectares"] += sa.area_hectares

    return {
        "blocks": block_results,
        "total_blocks": len(blocks),
        "sub_areas": sub_area_summary,
        "total_sub_areas": len(sub_areas),
    }


def get_inventory_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get tree inventory data"""
    from sqlalchemy.orm import load_only

    inv_calc = db.query(InventoryCalculation).options(
        load_only(
            InventoryCalculation.total_trees, InventoryCalculation.mother_trees_count,
            InventoryCalculation.felling_trees_count, InventoryCalculation.seedling_count,
            InventoryCalculation.total_volume_m3, InventoryCalculation.total_net_volume_m3,
            InventoryCalculation.total_net_volume_cft, InventoryCalculation.total_firewood_m3,
            InventoryCalculation.total_firewood_chatta,
        )
    ).filter(
        InventoryCalculation.calculation_id == calculation_id
    ).first()

    if not inv_calc:
        return {"available": False}

    trees = db.query(InventoryTree).options(
        load_only(
            InventoryTree.species, InventoryTree.dbh_class,
            InventoryTree.block_name, InventoryTree.net_volume,
        )
    ).filter(
        InventoryTree.inventory_calculation_id == inv_calc.id
    ).all()

    species_summary = {}
    dbh_summary = {}
    block_summary = {}

    for tree in trees:
        sp = tree.species
        species_summary[sp] = species_summary.get(sp, 0) + 1

        dbh_class = tree.dbh_class or "Unknown"
        dbh_summary[dbh_class] = dbh_summary.get(dbh_class, 0) + 1

        bn = tree.block_name or "Unassigned"
        if bn not in block_summary:
            block_summary[bn] = {"count": 0, "total_volume": 0}
        block_summary[bn]["count"] += 1
        # H6.2: `net_volume` is Numeric as of migration 060. Accumulating
        # Decimals here would make this dict unserialisable by json.dumps
        # and would raise on any later arithmetic against a float.
        block_summary[bn]["total_volume"] += float(tree.net_volume or 0)

    return {
        "available": True,
        "total_trees": inv_calc.total_trees or 0,
        "mother_trees_count": inv_calc.mother_trees_count or 0,
        "felling_trees_count": inv_calc.felling_trees_count or 0,
        "seedling_count": inv_calc.seedling_count or 0,
        "total_volume_m3": round(inv_calc.total_volume_m3 or 0, 2),
        "total_net_volume_m3": round(inv_calc.total_net_volume_m3 or 0, 2),
        "total_net_volume_cft": round(inv_calc.total_net_volume_cft or 0, 2),
        "total_firewood_m3": round(inv_calc.total_firewood_m3 or 0, 2),
        "total_firewood_chatta": round(inv_calc.total_firewood_chatta or 0, 2),
        "species_summary": dict(sorted(species_summary.items(), key=lambda x: x[1], reverse=True)),
        "dbh_summary": dbh_summary,
        "block_summary": block_summary,
    }


def get_sampling_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get sampling design data"""
    designs = db.query(SamplingDesign).filter(
        SamplingDesign.calculation_id == calculation_id
    ).all()

    if not designs:
        return {"available": False}

    design_list = []
    for d in designs:
        rd = d.result_data or {}
        design_list.append({
            "id": str(d.id),
            "sampling_type": d.sampling_type,
            "total_points": d.total_points,
            "plot_shape": d.plot_shape,
            "plot_radius_meters": float(d.plot_radius_meters) if d.plot_radius_meters else 0,
            "intensity_per_hectare": float(d.intensity_per_hectare) if d.intensity_per_hectare else 0,
            "total_blocks": rd.get("total_blocks", 0),
            "forest_area_hectares": rd.get("forest_area_hectares", 0),
            "requested_intensity_percent": rd.get("requested_intensity_percent", 0),
            "sampling_percentage": rd.get("sampling_percentage", 0),
            "actual_intensity_per_hectare": rd.get("actual_intensity_per_hectare", 0),
            "plot_area_sqm": rd.get("plot_area_sqm", 0),
            "total_sampled_area_hectares": rd.get("total_sampled_area_hectares", 0),
            "blocks_info": rd.get("blocks_info", []),
        })

    return {
        "available": True,
        "designs": design_list,
    }


def _household_data_from_summary(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Same shape as `get_household_data`, built from the entered totals (no per-household records)."""
    from app.services.household_aggregate import get_aggregate
    from app.utils.number_format import format_devanagari

    agg = get_aggregate(db, calculation_id)
    if agg is None:
        return {"available": False}
    timber = float(agg["total_timber_demand_cft"])
    firewood = float(agg["total_firewood_demand_bhari"])
    return {
        "available": True,
        "data_source": "summary",
        "total_households": agg["total_households"],
        "total_population": agg["total_population"],
        "total_male": agg["total_male"],
        "total_female": agg["total_female"],
        "prosperity_distribution": agg["prosperity_distribution"],
        "caste_distribution": agg["caste_distribution"],
        "timber_demand_cft": round(timber, 2),
        "firewood_demand_bhari": round(firewood, 2),
        "forest_based_occupation": agg["forest_dependent_households"],
        "livestock": {
            "cow_ox": agg["total_cow_ox"], "buffalo": agg["total_buffalo"], "goat_sheep": agg["total_goat_sheep"],
        },
        "_ne": {
            "total_households": format_devanagari(agg["total_households"], 0),
            "total_population": format_devanagari(agg["total_population"], 0),
            "total_male": format_devanagari(agg["total_male"], 0),
            "total_female": format_devanagari(agg["total_female"], 0),
            "timber_demand_cft": format_devanagari(round(timber, 2), 2),
            "firewood_demand_bhari": format_devanagari(round(firewood, 2), 2),
            "forest_based_occupation": format_devanagari(agg["forest_dependent_households"], 0),
        },
        "hh_records": [],  # a summary has no per-household records
    }


def get_household_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get household information data"""
    households = db.query(HouseholdInformation).filter(
        HouseholdInformation.calculation_id == calculation_id
    ).all()

    if not households:
        return _household_data_from_summary(db, calculation_id)

    total_male = sum(h.male_count or 0 for h in households)
    total_female = sum(h.female_count or 0 for h in households)

    prosperity = {}
    for h in households:
        p = h.prosperity_level or "Unknown"
        prosperity[p] = prosperity.get(p, 0) + 1

    caste = {}
    for h in households:
        c = h.caste_classification_ne or "Unknown"
        caste[c] = caste.get(c, 0) + 1

    total_timber_demand = sum(float(h.timber_demand_cft or 0) for h in households)
    total_firewood_demand = sum(float(h.firewood_demand_bhari or 0) for h in households)

    total_population = total_male + total_female
    forest_occ = sum(1 for h in households if h.forest_based_occupation)
    livestock = {
        "cow_ox": sum(h.cow_ox_count or 0 for h in households),
        "buffalo": sum(h.buffalo_count or 0 for h in households),
        "goat_sheep": sum(h.goat_sheep_count or 0 for h in households),
    }

    from app.utils.number_format import format_devanagari
    _ne = {
        "total_households": format_devanagari(len(households), 0),
        "total_population": format_devanagari(total_population, 0),
        "total_male": format_devanagari(total_male, 0),
        "total_female": format_devanagari(total_female, 0),
        "timber_demand_cft": format_devanagari(round(total_timber_demand, 2), 2),
        "firewood_demand_bhari": format_devanagari(round(total_firewood_demand, 2), 2),
        "forest_based_occupation": format_devanagari(forest_occ, 0),
    }

    hh_records = []
    for h in households:
        hh_records.append({
            "घर_नं": h.house_no,
            "पुरुष_मुखिया": h.household_head_male or "",
            "महिला_मुखिया": h.household_head_female or "",
            "जात_वर्गीकरण": h.caste_classification_ne or "",
            "पुरुष": h.male_count or 0,
            "महिला": h.female_count or 0,
            "ठेगाना": h.address_tole or "",
            "गाई_गोरु": h.cow_ox_count or 0,
            "भैंसी": h.buffalo_count or 0,
            "बाख्रा_भेडा": h.goat_sheep_count or 0,
            "जग्गा_क्षेत्रफल": float(h.land_area or 0),
            "जग्गा_एकाइ": h.land_unit or "",
            "घाँस_भारी": float(h.grass_demand_bhari or 0),
            "पोल": h.pole_demand or 0,
            "काठ_cft": float(h.timber_demand_cft or 0),
            "दाउरा_भारी": float(h.firewood_demand_bhari or 0),
            "ओछ्यान_भारी": float(h.bedding_demand_bhari or 0),
            "समृद्धि_स्तर": h.prosperity_level or "",
            "वन_पेशा": "छ" if h.forest_based_occupation else "छैन",
        })

    return {
        "available": True,
        "total_households": len(households),
        "total_population": total_population,
        "total_male": total_male,
        "total_female": total_female,
        "prosperity_distribution": prosperity,
        "caste_distribution": caste,
        "timber_demand_cft": round(total_timber_demand, 2),
        "firewood_demand_bhari": round(total_firewood_demand, 2),
        "forest_based_occupation": forest_occ,
        "livestock": livestock,
        "_ne": _ne,
        "hh_records": hh_records,
    }


def get_committee_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get forest committee data"""
    user_committee = db.query(ForestUserCommittee).filter(
        ForestUserCommittee.calculation_id == calculation_id
    ).order_by(ForestUserCommittee.serial_no).all()

    advisory = db.query(AdvisoryCommittee).filter(
        AdvisoryCommittee.calculation_id == calculation_id
    ).order_by(AdvisoryCommittee.serial_no).all()

    financial = db.query(FinancialCommittee).filter(
        FinancialCommittee.calculation_id == calculation_id
    ).order_by(FinancialCommittee.serial_no).all()

    from app.utils.number_format import format_devanagari
    uc_total = len(user_committee)
    ac_total = len(advisory)
    fc_total = len(financial)

    _ne = {
        "user_committee_total": format_devanagari(uc_total, 0),
        "advisory_committee_total": format_devanagari(ac_total, 0),
        "financial_committee_total": format_devanagari(fc_total, 0),
    }

    members = [
        {
            "name": m.name,
            "position": m.position,
            "gender": m.gender,
            "caste_category": m.caste_category,
            "address": m.address,
            "mobile": m.mobile,
        }
        for m in user_committee
    ]

    gender_distribution: Dict[str, int] = {}
    position_distribution: Dict[str, int] = {}
    caste_distribution: Dict[str, int] = {}
    for m in members:
        g = m["gender"] or "अन्य"
        gender_distribution[g] = gender_distribution.get(g, 0) + 1
        p = m["position"] or "अन्य"
        position_distribution[p] = position_distribution.get(p, 0) + 1
        c = m["caste_category"] or "अन्य"
        caste_distribution[c] = caste_distribution.get(c, 0) + 1

    return {
        "user_committee": {
            "total_members": uc_total,
            "members": members,
            "gender_distribution": gender_distribution,
            "position_distribution": position_distribution,
            "caste_distribution": caste_distribution,
        },
        "advisory_committee": {
            "total_members": ac_total,
            "members": [{"name": m.name, "address": m.address} for m in advisory],
        },
        "financial_committee": {
            "total_members": fc_total,
            "members": [{"name": m.name, "address": m.address} for m in financial],
        },
        "_ne": _ne,
    }


def get_biodiversity_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get biodiversity records with enriched summary data"""
    records = db.query(CalculationBiodiversity).filter(
        CalculationBiodiversity.calculation_id == calculation_id
    ).all()

    if not records:
        return {"available": False}

    vegetation = []
    animals = []

    species_ids = [r.species_id for r in records]
    species_map = {s.id: s for s in db.query(BiodiversitySpecies).filter(
        BiodiversitySpecies.id.in_(species_ids)
    ).all()}

    protected_count = 0
    invasive_count = 0
    iucn_breakdown: Dict[str, int] = {}
    sub_category_breakdown: Dict[str, int] = {}

    for r in records:
        species = species_map.get(r.species_id)
        if not species:
            continue

        iucn = species.iucn_status or "DD"
        is_protected = bool(species.is_protected) or iucn in ("CR", "EN", "VU")
        is_invasive = bool(species.is_invasive)

        if is_protected:
            protected_count += 1
        if is_invasive:
            invasive_count += 1

        iucn_breakdown[iucn] = iucn_breakdown.get(iucn, 0) + 1
        sub_cat = species.sub_category or "other"
        sub_category_breakdown[sub_cat] = sub_category_breakdown.get(sub_cat, 0) + 1

        record = {
            "name": species.nepali_name or "",
            "scientific_name": species.scientific_name or "",
            "sub_category": species.sub_category or "",
            "primary_use": species.primary_use or "",
            "secondary_uses": species.secondary_uses or "",
            "presence_status": r.presence_status,
            "abundance": r.abundance or "",
            "iucn_status": iucn,
            "is_protected": is_protected,
            "is_invasive": is_invasive,
            "cites_appendix": species.cites_appendix or "",
        }

        if species.category == "vegetation":
            vegetation.append(record)
        else:
            animals.append(record)

    # Ensure all IUCN categories exist
    for code in ("CR", "EN", "VU", "NT", "LC", "DD"):
        iucn_breakdown.setdefault(code, 0)

    return {
        "available": True,
        "total_species": len(records),
        "vegetation_count": len(vegetation),
        "animal_count": len(animals),
        "protected_count": protected_count,
        "invasive_count": invasive_count,
        "iucn_breakdown": iucn_breakdown,
        "sub_category_breakdown": sub_category_breakdown,
        "vegetation": vegetation,
        "animals": animals,
    }


def get_activities_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get proposed yearly activities"""
    activities = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.calculation_id == calculation_id
    ).all()

    if not activities:
        return {"available": False}

    activity_list = []
    total_budget = 0

    from collections import defaultdict
    activity_ids = [a.id for a in activities]
    all_year_details = defaultdict(list)
    for yd in db.query(ActivityYearDetail).filter(
        ActivityYearDetail.proposed_activity_id.in_(activity_ids)
    ).order_by(ActivityYearDetail.year_number).all():
        all_year_details[yd.proposed_activity_id].append(yd)

    for act in activities:
        year_details = all_year_details.get(act.id, [])

        yearly_budgets = []
        for yd in year_details:
            yearly_budgets.append({
                "year": yd.year_number,
                "quantity": float(yd.quantity or 0),
                "budget": float(yd.yearly_budget or 0),
            })
            total_budget += float(yd.yearly_budget or 0)

        activity_list.append({
            "activity_id": act.potential_activity_id,
            "notes": act.notes,
            "default_quantity": float(act.default_quantity or 0),
            "yearly_details": yearly_budgets,
        })

    return {
        "available": True,
        "total_activities": len(activities),
        "activities": activity_list,
        "total_budget": round(total_budget, 2),
    }


def get_user_group_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get user group extent, buildings data with size breakdown"""
    extents = db.query(UserGroupExtent).filter(
        UserGroupExtent.calculation_id == calculation_id
    ).all()

    if not extents:
        return {"available": False}

    from collections import defaultdict
    extent_ids = [ext.id for ext in extents]
    ext_buildings_map = defaultdict(list)
    for b in db.query(UserGroupBuilding).filter(
        UserGroupBuilding.extent_id.in_(extent_ids)
    ).all():
        ext_buildings_map[b.extent_id].append(b)

    buildings = []
    total_buildings = 0
    total_building_area = 0.0
    total_small = 0
    total_medium = 0
    total_large = 0

    for ext in extents:
        for b in ext_buildings_map.get(ext.id, []):
            geo = b.buildings_geojson or []
            small_count = sum(1 for bg in geo if bg.get('area', 0) < 50)
            medium_count = sum(1 for bg in geo if 50 <= bg.get('area', 0) <= 150)
            large_count = sum(1 for bg in geo if bg.get('area', 0) > 150)
            bc = b.building_count or 0
            ta = float(b.total_building_area_m2 or 0)
            avg_size = ta / bc if bc > 0 else 0

            total_buildings += bc
            total_building_area += ta
            total_small += small_count
            total_medium += medium_count
            total_large += large_count

            buildings.append({
                "settlement_name": b.settlement_name,
                "building_count": bc,
                "small_buildings": small_count,
                "medium_buildings": medium_count,
                "large_buildings": large_count,
                "avg_building_size_m2": round(avg_size, 2),
                "direction_from_forest": b.direction_from_forest,
                "total_area_m2": ta,
            })

    avg_building_size = total_building_area / total_buildings if total_buildings > 0 else 0
    small_pct = round(total_small / total_buildings * 100, 1) if total_buildings > 0 else 0
    medium_pct = round(total_medium / total_buildings * 100, 1) if total_buildings > 0 else 0
    large_pct = round(total_large / total_buildings * 100, 1) if total_buildings > 0 else 0

    return {
        "available": True,
        "total_settlements": len(buildings),
        "total_buildings": total_buildings,
        "total_building_area_m2": round(total_building_area, 2),
        "avg_building_size_m2": round(avg_building_size, 2),
        "small_buildings": total_small,
        "medium_buildings": total_medium,
        "large_buildings": total_large,
        "small_pct": small_pct,
        "medium_pct": medium_pct,
        "large_pct": large_pct,
        "buildings": buildings,
    }


def get_user_group_landcover_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Get user group land cover and biomass analysis data from calculation result_data"""
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if not calc:
        return {"available": False}

    result_data = calc.result_data or {}
    lc_data = result_data.get("user_group_land_cover")
    if not lc_data:
        return {
            "available": False,
            "user_group_area_ha": 0,
            "forest_overlap_area_ha": 0,
            "net_analysis_area_ha": 0,
            "total_biomass_mg": 0,
            "total_volume_m3": 0,
            "avg_biomass_mg_per_ha": 0,
            "avg_volume_m3_per_ha": 0,
            "has_forest_overlap": False,
            "analysis_date": "",
            "land_cover_classes": [],
        }

    classes = lc_data.get("land_cover_classes", [])
    area_val = lc_data.get("user_group_area_ha", 0)

    return {
        "available": True,
        "user_group_area_ha": lc_data.get("user_group_area_ha", 0),
        "forest_overlap_area_ha": lc_data.get("forest_overlap_area_ha", 0),
        "net_analysis_area_ha": lc_data.get("net_analysis_area_ha", 0),
        "total_biomass_mg": lc_data.get("total_biomass_mg", 0),
        "total_volume_m3": lc_data.get("total_volume_m3", 0),
        "avg_biomass_mg_per_ha": lc_data.get("avg_biomass_mg_per_ha", 0),
        "avg_volume_m3_per_ha": lc_data.get("avg_volume_m3_per_ha", 0),
        "has_forest_overlap": lc_data.get("has_forest_overlap", False),
        "analysis_date": lc_data.get("analysis_date", ""),
        "land_cover_classes": classes,
    }


def collect_all_data(db: Session, calculation_id: str) -> Dict[str, Any]:
    """Collect all data needed for the full report"""
    raw_data = {
        "basic_info": get_calculation_basic_info(db, calculation_id),
        "boundary": get_boundary_info(db, calculation_id),
        "species": get_species_info(db, calculation_id),
        "raster_analysis": get_raster_analysis(db, calculation_id),
        "blocks": get_block_data(db, calculation_id),
        "inventory": get_inventory_data(db, calculation_id),
        "sampling": get_sampling_data(db, calculation_id),
        "households": get_household_data(db, calculation_id),
        "committees": get_committee_data(db, calculation_id),
        "biodiversity": get_biodiversity_data(db, calculation_id),
        "activities": get_activities_data(db, calculation_id),
        "user_group": get_user_group_data(db, calculation_id),
        "user_group_landcover": get_user_group_landcover_data(db, calculation_id),
    }
    return _convert_decimals(raw_data)
