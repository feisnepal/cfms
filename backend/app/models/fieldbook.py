"""
Fieldbook model for boundary vertices and interpolated points
"""
from sqlalchemy import Index, Column, String, Integer, Numeric, Boolean, Text, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
import uuid

from ..core.database import Base


class Fieldbook(Base):
    """
    Fieldbook entries for boundary verification.
    Stores vertices extracted from polygon boundaries plus interpolated points
    at 20m intervals for field verification.
    """
    __tablename__ = "fieldbook"
    __table_args__ = (
        Index('idx_fieldbook_block_number', 'block_number'),
        Index('idx_fieldbook_calc_id', 'calculation_id'),
        Index('idx_fieldbook_calculation', 'calculation_id'),
        Index('idx_fieldbook_geometry', 'point_geometry', postgresql_using='gist'),
        Index('idx_fieldbook_point_number', 'calculation_id', 'point_number'),
        Index('idx_fieldbook_boundary_class', 'calculation_id', 'boundary_class'),
        UniqueConstraint('calculation_id', 'point_number', name='uq_fieldbook_calc_point'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey('calculations.id', ondelete='CASCADE'), nullable=False)

    # Point identification
    point_number = Column(Integer, nullable=False)  # Running order 1..N: all outer points, then internal
    point_type = Column(String(20), nullable=False)  # 'vertex' or 'interpolated'

    # Where the point sits (services/fieldbook_sequence.py). Outer points are numbered first, clockwise from
    # the north-west-most vertex, labelled O1, O2, ...; internal points follow as I1, I2, ...
    point_label = Column(String(12), nullable=True)         # 'O1', 'I14' (the number shown to people)
    boundary_class = Column(String(10), nullable=True)      # 'outer' | 'internal'
    junction_degree = Column(Integer, nullable=True)        # how many units meet at this point
    is_junction = Column(Boolean, nullable=True)            # outer: boundary + 2 units; internal: 3+ units
    adjacent_units = Column(JSONB, nullable=True)           # names of the units this point separates
    next_point_label = Column(String(12), nullable=True)    # the point to walk to next (azimuth/distance point there)
    # Lines (services/fieldbook_lines.py): the outer points close into a ring (O-1); each internal edge is an
    # open line (I-3) that never closes or joins another; a free-standing loop is L-1. `line_id` is the line that
    # first reached the point, `lines` every line it is on with its place in each ({"I-2": 5, "O-1": 12}).
    line_id = Column(String(12), nullable=True)
    lines = Column(JSONB, nullable=True)

    # Block information (for multi-block forests)
    block_number = Column(Integer, nullable=True)  # Which block this point belongs to (1, 2, 3...)
    block_name = Column(String(100), nullable=True)  # Optional block name (e.g., "Ward 5", "North Block")

    # Sub-area information (for excluded zones, special areas)
    sub_area_name = Column(String(100), nullable=True)  # Name if point is on sub-area boundary
    is_excluded = Column(Boolean, nullable=True)         # True if on excluded zone boundary (private land)
    sub_area_category = Column(String(50), nullable=True)  # Sub-area category (e.g. "religious", "plantation")

    # Coordinates
    longitude = Column(Numeric(10, 7), nullable=False)  # WGS84 longitude
    latitude = Column(Numeric(10, 7), nullable=False)   # WGS84 latitude
    easting_utm = Column(Numeric(12, 3), nullable=True)  # UTM Easting
    northing_utm = Column(Numeric(12, 3), nullable=True) # UTM Northing
    utm_zone = Column(Integer, nullable=True)            # UTM Zone (44N or 45N for Nepal)

    # Navigation data
    azimuth_to_next = Column(Numeric(5, 2), nullable=True)    # Bearing to next point (degrees)
    distance_to_next = Column(Numeric(8, 2), nullable=True)   # Distance to next point (meters)

    # Terrain data
    elevation = Column(Numeric(8, 2), nullable=True)  # Elevation from DEM (meters)

    # Field verification
    remarks = Column(Text, nullable=True)
    is_verified = Column(Boolean, default=False, nullable=False)  # GPS verified in field

    # Geometry for spatial queries
    point_geometry = Column(Geometry('POINT', srid=4326), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    slope_code = Column(Integer, nullable=True)
    slope_class = Column(String(20), nullable=True)
    aspect_code = Column(Integer, nullable=True)
    aspect_class = Column(String(20), nullable=True)

    # Relationships
    calculation = relationship("Calculation", back_populates="fieldbook_points")

    def __repr__(self):
        return f"<Fieldbook(id={self.id}, calc={self.calculation_id}, point={self.point_number}, type={self.point_type})>"
