"""
Household Information model
Stores household survey data for community forest user groups
"""
from sqlalchemy import (Index, Column, String, DateTime, Integer, ForeignKey, Numeric,
                        BigInteger, text,
                        Boolean, Text, CheckConstraint, UniqueConstraint)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from ..core.database import Base


class HouseholdInformation(Base):
    """
    Household Information model
    Stores detailed household data for community forest management
    One dataset per calculation (community forest)
    """
    __tablename__ = "household_information"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)

    # Basic Info
    # H8.2 / S2-63: optimistic-lock counter. Bumped ONLY by
    # services/optimistic_lock.py, in the same statement that checks it -- a
    # separate read-then-write is the lost update it exists to prevent.
    version = Column(BigInteger, nullable=False, default=0, server_default=text("0"),
                     comment=("H8.2/S2-63 optimistic-lock counter. Bumped only by "
                             "services/optimistic_lock.py, in the same statement that "
                             "checks it."))

    house_no = Column(Integer, nullable=False)
    surname = Column(String(100), nullable=False)  # थर
    household_head_male = Column(String(200), nullable=True)  # घरमुली पुरूष
    household_head_female = Column(String(200), nullable=True)  # घरमुली महिला
    address_tole = Column(String(200), nullable=True)  # टोल ठेगाना
    latitude = Column(Numeric(10, 8), nullable=True)  # अक्षाँस
    longitude = Column(Numeric(11, 8), nullable=True)  # देशान्तर

    # Population
    female_count = Column(Integer, nullable=False, default=0)  # महिला संख्या
    male_count = Column(Integer, nullable=False, default=0)  # पुरूष संख्या
    # total_population computed in service layer

    # Land & Occupation
    land_area = Column(Numeric(10, 4), nullable=True)  # जमिन
    land_unit = Column(String(20), nullable=True)  # 'ropani' or 'kaththa'
    forest_based_occupation = Column(Boolean, default=False)  # पेशा (वनमा आश्रीत)
    other_occupation = Column(Boolean, default=False)  # पेशा (अन्य)

    # Livestock
    cow_ox_count = Column(Integer, default=0)  # गाइ गोरू
    buffalo_count = Column(Integer, default=0)  # भैसी राँगा
    goat_sheep_count = Column(Integer, default=0)  # बाख्रा भेडा

    # Forest Product Demands
    timber_demand_cft = Column(Numeric(10, 2), default=5)  # बन पैदाबारको माग (काठ क्यू.फि.)
    pole_demand = Column(Integer, default=5)  # बन पैदाबारको माग (पोल)
    firewood_demand_bhari = Column(Numeric(10, 2), nullable=True)  # बन पैदाबारको माग (दाउरा) भारी
    grass_demand_bhari = Column(Numeric(10, 2), nullable=True)  # बन पैदाबारको माग (घाँस)
    bedding_demand_bhari = Column(Numeric(10, 2), nullable=True)  # बन पैदाबारको माग (सोत्तर)

    # Flags to track if values were auto-calculated or manually entered
    firewood_auto_calculated = Column(Boolean, default=True)
    grass_auto_calculated = Column(Boolean, default=True)
    bedding_auto_calculated = Column(Boolean, default=True)

    # Classification
    caste_classification_ne = Column(String(100), nullable=True)  # जातिय वर्गिकरण
    caste_classification_en = Column(String(100), nullable=True)
    caste_classification_manual = Column(Boolean, default=False)  # If user overrode auto-lookup

    # Other Info
    other_group_membership = Column(Boolean, nullable=True)  # अन्य समूहमा सदस्यता
    prosperity_level = Column(String(50), default='मध्यम')  # सम्पन्नताको स्तर
    prosperity_auto_suggested = Column(Boolean, default=True)  # If auto-suggested
    remarks = Column(Text, nullable=True)  # कैफियत

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Relationships
    calculation = relationship("Calculation", back_populates="household_data")
    created_by_user = relationship("User", foreign_keys=[created_by])

    # Constraints
    __table_args__ = (
        # H8.6 / S2-67. `house_no` was already NOT NULL and already the key the
        # upload path upserts on -- it was simply never declared, so nothing
        # stopped a second route, or a replayed sync, from writing house #14
        # twice. 298 live rows, 0 duplicates, so this cost no cleanup.
        #
        # It belongs in THIS tuple and not a second one earlier in the class:
        # a class body is executed top to bottom, so a second `__table_args__`
        # silently replaces the first. That is how it was written the first
        # time, and the constraint reached the database through the migration
        # while the model carried nothing -- `check_schema_drift.py` was what
        # caught it.
        UniqueConstraint('calculation_id', 'house_no',
                         name='uq_household_calculation_house_no'),
        Index('idx_household_calculation_id', 'calculation_id'),
        Index('idx_household_surname', 'surname'),
        CheckConstraint('female_count >= 0', name='check_female_count_positive'),
        CheckConstraint('male_count >= 0', name='check_male_count_positive'),
        CheckConstraint('cow_ox_count >= 0', name='check_cow_ox_count_positive'),
        CheckConstraint('buffalo_count >= 0', name='check_buffalo_count_positive'),
        CheckConstraint('goat_sheep_count >= 0', name='check_goat_sheep_count_positive'),
        CheckConstraint('timber_demand_cft >= 0', name='check_timber_positive'),
        CheckConstraint('pole_demand >= 0', name='check_pole_positive'),
        CheckConstraint("land_unit IN ('ropani', 'kaththa') OR land_unit IS NULL", name='check_land_unit_valid'),
        CheckConstraint(
            "prosperity_level IN ('सम्पन्न', 'मध्यम', 'विपन्न', 'अति विपन्न')",
            name='check_prosperity_level_valid'
        ))

    def __repr__(self):
        return f"<HouseholdInformation(id={self.id}, house_no={self.house_no}, surname={self.surname})>"
