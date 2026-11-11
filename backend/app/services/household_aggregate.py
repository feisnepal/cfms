"""One answer to "what are this forest's household totals?" -- from households OR from a summary.

A forest either has household-wise rows (`household_information`) or, when the crew only has totals, one
`household_summary_data` row. Every consumer (summary endpoint, OP variables, demand-supply) reads
`get_aggregate` so they cannot disagree. Household rows always win; saving households deletes the summary
(owner decision 2026-10-05), so the two never coexist.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.household_information import HouseholdInformation
from app.models.household_summary_data import HouseholdSummaryData
from app.services.household_calculations import HouseholdCalculations

# Per-household defaults on the household form (timber 5 cft, poles 5) -- used for the auto-calculated summary.
DEFAULT_TIMBER_CFT_PER_HOUSEHOLD = Decimal("5")
DEFAULT_POLES_PER_HOUSEHOLD = 5

SOURCE_HOUSEHOLDS = "households"
SOURCE_SUMMARY = "summary"


def compute_demands(
    total_households: int, male: int, female: int, cow_ox: int, buffalo: int, goat_sheep: int
) -> Dict[str, Any]:
    """Yearly demand totals from population and livestock, with the household form's own formulas.

    The formulas are linear, so applying them to the totals equals summing them over every household.
    """
    d = HouseholdCalculations.calculate_all_demands(female, male, cow_ox, buffalo, goat_sheep)
    return {
        "timber_demand_cft": DEFAULT_TIMBER_CFT_PER_HOUSEHOLD * total_households,
        "pole_demand": DEFAULT_POLES_PER_HOUSEHOLD * total_households,
        "firewood_demand_bhari": d["firewood_bhari"],
        "grass_demand_bhari": d["grass_bhari"],
        "bedding_demand_bhari": d["bedding_bhari"],
    }


def get_summary_row(db: Session, calculation_id: UUID) -> Optional[HouseholdSummaryData]:
    return (
        db.query(HouseholdSummaryData)
        .filter(HouseholdSummaryData.calculation_id == calculation_id)
        .first()
    )


def delete_summary(db: Session, calculation_id: UUID) -> int:
    """Drop the summary (called when household-wise data is saved). Caller commits."""
    return (
        db.query(HouseholdSummaryData)
        .filter(HouseholdSummaryData.calculation_id == calculation_id)
        .delete(synchronize_session=False)
    )


def _from_households(households) -> Dict[str, Any]:
    male = sum(h.male_count or 0 for h in households)
    female = sum(h.female_count or 0 for h in households)
    caste: Dict[str, int] = {}
    prosperity: Dict[str, int] = {}
    for h in households:
        if h.caste_classification_ne:
            caste[h.caste_classification_ne] = caste.get(h.caste_classification_ne, 0) + 1
        prosperity[h.prosperity_level] = prosperity.get(h.prosperity_level, 0) + 1
    lands = [h.land_area for h in households if h.land_area is not None]
    return {
        "source": SOURCE_HOUSEHOLDS,
        "total_households": len(households),
        "total_male": male,
        "total_female": female,
        "total_population": male + female,
        "total_cow_ox": sum(h.cow_ox_count or 0 for h in households),
        "total_buffalo": sum(h.buffalo_count or 0 for h in households),
        "total_goat_sheep": sum(h.goat_sheep_count or 0 for h in households),
        "total_timber_demand_cft": sum((h.timber_demand_cft or 0 for h in households), Decimal(0)),
        "total_pole_demand": sum(h.pole_demand or 0 for h in households),
        "total_firewood_demand_bhari": sum((h.firewood_demand_bhari or 0 for h in households), Decimal(0)),
        "total_grass_demand_bhari": sum((h.grass_demand_bhari or 0 for h in households), Decimal(0)),
        "total_bedding_demand_bhari": sum((h.bedding_demand_bhari or 0 for h in households), Decimal(0)),
        "avg_land_area": (Decimal(sum(lands) / len(lands)) if lands else None),
        "caste_distribution": caste,
        "prosperity_distribution": prosperity,
        "forest_dependent_households": sum(1 for h in households if h.forest_based_occupation),
    }


def _from_summary(s: HouseholdSummaryData) -> Dict[str, Any]:
    z = Decimal(0)
    return {
        "source": SOURCE_SUMMARY,
        "total_households": s.total_households,
        "total_male": s.male_count or 0,
        "total_female": s.female_count or 0,
        "total_population": (s.male_count or 0) + (s.female_count or 0),
        "total_cow_ox": s.cow_ox_count or 0,
        "total_buffalo": s.buffalo_count or 0,
        "total_goat_sheep": s.goat_sheep_count or 0,
        "total_timber_demand_cft": s.timber_demand_cft or z,
        "total_pole_demand": s.pole_demand or 0,
        "total_firewood_demand_bhari": s.firewood_demand_bhari or z,
        "total_grass_demand_bhari": s.grass_demand_bhari or z,
        "total_bedding_demand_bhari": s.bedding_demand_bhari or z,
        "avg_land_area": s.avg_land_area,
        "caste_distribution": dict(s.caste_distribution or {}),
        "prosperity_distribution": dict(s.prosperity_distribution or {}),
        "forest_dependent_households": s.forest_occupation_households or 0,
    }


def get_aggregate(db: Session, calculation_id: UUID) -> Optional[Dict[str, Any]]:
    """Household totals for the forest, or None when there is neither households nor a summary."""
    households = (
        db.query(HouseholdInformation)
        .filter(HouseholdInformation.calculation_id == calculation_id)
        .all()
    )
    if households:
        return _from_households(households)
    s = get_summary_row(db, calculation_id)
    return _from_summary(s) if s else None
