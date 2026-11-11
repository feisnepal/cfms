"""
Biodiversity models for species inventory tracking
"""
from sqlalchemy import Index, Column, String, Text, Boolean, DateTime, ForeignKey, Numeric, UUID, func
from sqlalchemy.orm import relationship
from ..core.database import Base


class BiodiversitySpecies(Base):
    """Master species data - pre-populated from CSV"""
    __tablename__ = "biodiversity_species"
    __table_args__ = (
        Index('idx_biodiversity_category', 'category', 'sub_category'),
        Index('idx_biodiversity_invasive', 'is_invasive'),
        Index('idx_biodiversity_protected', 'is_protected'),
    )
    id = Column(UUID, primary_key=True, server_default=func.gen_random_uuid())
    category = Column(String(50), nullable=False)  # 'vegetation', 'animal'
    sub_category = Column(String(50))  # 'tree', 'mammal', 'bird', etc.
    nepali_name = Column(String(255), nullable=False)
    english_name = Column(String(255), nullable=False)
    scientific_name = Column(String(255), nullable=False)
    primary_use = Column(String(100))
    secondary_uses = Column(Text)
    iucn_status = Column(String(10))  # 'LC', 'VU', 'EN', 'CR', 'DD', 'NT'
    cites_appendix = Column(String(20))  # 'Appendix I', 'Appendix II', etc.
    distribution = Column(String(255))
    notes = Column(Text)
    is_invasive = Column(Boolean, default=False, server_default='false')
    is_protected = Column(Boolean, default=False, server_default='false')
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationship
    calculation_records = relationship("CalculationBiodiversity", back_populates="species")


class CalculationBiodiversity(Base):
    """User selections of species per calculation/CFOP"""
    __tablename__ = "calculation_biodiversity"
    __table_args__ = (
        Index('idx_calc_biodiversity', 'calculation_id'),
        Index('idx_species_biodiversity', 'species_id'),
    )
    id = Column(UUID, primary_key=True, server_default=func.gen_random_uuid())
    calculation_id = Column(UUID, ForeignKey('calculations.id', ondelete='CASCADE'), nullable=False)
    species_id = Column(UUID, ForeignKey('biodiversity_species.id'), nullable=False)
    presence_status = Column(String(20), default='present')  # 'present', 'abundant', 'rare', 'common'
    abundance = Column(String(20))  # 'rare', 'occasional', 'common', 'abundant'
    notes = Column(Text)  # Forester's field notes
    photo_url = Column(String(500))  # Photo evidence
    latitude = Column(Numeric(10, 8))  # GPS coordinates
    longitude = Column(Numeric(11, 8))
    recorded_by = Column(UUID, ForeignKey('users.id'))
    recorded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    calculation = relationship("Calculation", back_populates="biodiversity_records")
    species = relationship("BiodiversitySpecies", back_populates="calculation_records")
    recorder = relationship("User")
