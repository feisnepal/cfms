"""
ForestSubArea model - stores sub-areas within forest blocks
"""
import logging
from sqlalchemy import Index, Column, String, DateTime, Integer, ForeignKey, Float, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, validates
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape, from_shape
from datetime import datetime
import uuid

from ..core.database import Base
from ..utils.single_part_geometry import ensure_single_polygon

logger = logging.getLogger(__name__)


class ForestSubArea(Base):
    """
    ForestSubArea model - stores sub-areas within forest blocks.
    
    Sub-areas include: Protected Zone, Plantation Area, Pro-Poor, Religious,
    Biodiversity, Tourist, Office, and Private Land (excluded).
    
    Private land sub-areas are excluded from calculations (treated as doughnut holes).
    Sub-areas can span multiple blocks (block_id can be null, with area tracked per block).
    """
    __tablename__ = "forest_sub_areas"
    __table_args__ = (
        Index('idx_forest_sub_areas_block_id', 'block_id'),
        Index('idx_forest_sub_areas_calculation_id', 'calculation_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)
    block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False)
    geometry = Column(Geometry(srid=4326), nullable=False)
    area_hectares = Column(Float, nullable=False)
    is_excluded = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    @validates("geometry")
    def _validate_single_part_geometry(self, key, value):
        """One row = one selectable map feature — see
        `app/utils/single_part_geometry.py` and the identical guard on
        `ForestBlock.geometry`. Only a `WKBElement` is checked; a raw SQL/
        driver value passes through untouched.
        """
        if not isinstance(value, WKBElement):
            return value
        try:
            geom = to_shape(value)
        except Exception:
            logger.warning(
                "single-part-geometry guard: WKB decode failed - passing "
                "the value through unchecked", exc_info=True,
            )
            return value
        fixed = ensure_single_polygon(geom)
        if fixed is geom:
            return value
        return from_shape(fixed, srid=value.srid or 4326)

    def __repr__(self):
        return f"<ForestSubArea(id={self.id}, name={self.name}, category={self.category})>"