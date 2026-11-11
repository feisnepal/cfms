"""Household SUMMARY (totals only) for a forest that has no household-wise data.

One row per calculation. It exists only while there are no `household_information` rows: uploading or
entering households deletes it (owner decision 2026-10-05), so the two never disagree.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ..core.database import Base


class HouseholdSummaryData(Base):
    __tablename__ = "household_summary_data"
    __table_args__ = (UniqueConstraint("calculation_id", name="uq_household_summary_calculation"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)

    total_households = Column(Integer, nullable=False)
    male_count = Column(Integer, nullable=False, default=0)
    female_count = Column(Integer, nullable=False, default=0)
    forest_occupation_households = Column(Integer, nullable=False, default=0)
    other_occupation_households = Column(Integer, nullable=False, default=0)
    cow_ox_count = Column(Integer, nullable=False, default=0)
    buffalo_count = Column(Integer, nullable=False, default=0)
    goat_sheep_count = Column(Integer, nullable=False, default=0)
    avg_land_area = Column(Numeric(10, 4), nullable=True)
    land_unit = Column(String(20), nullable=True)  # 'ropani' | 'kaththa'

    # Yearly demand totals. When *_auto is true the value is recomputed from population / livestock with
    # the same formulas the household form uses (HouseholdCalculations); otherwise it is the typed total.
    timber_demand_cft = Column(Numeric(12, 2), nullable=True)
    pole_demand = Column(Integer, nullable=True)
    firewood_demand_bhari = Column(Numeric(12, 2), nullable=True)
    grass_demand_bhari = Column(Numeric(12, 2), nullable=True)
    bedding_demand_bhari = Column(Numeric(12, 2), nullable=True)
    demands_auto_calculated = Column(Boolean, nullable=False, default=True)

    caste_distribution = Column(JSONB, nullable=False, default=dict)      # {classification: households}
    prosperity_distribution = Column(JSONB, nullable=False, default=dict)  # {level: households}

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
