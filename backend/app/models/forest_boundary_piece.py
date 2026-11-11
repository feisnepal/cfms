"""
ForestBoundaryPiece model - one row per disjoint piece of a forest's outer boundary.

BOUNDARY_PIECES_PLAN.md P1. Purely additive: `Calculation.boundary_geom` keeps its
exact current meaning (the union of every piece, read by
`app/services/forest_units/area_model.py::outer_boundary_geom()` and everything
downstream of it) -- this table only gives each piece an identity (name, own area)
that a MultiPolygon union on its own cannot carry. `boundary_geom` is derived FROM
these rows by every write path (P2), never the other way around, so the two can
never drift apart.
"""
import logging
from sqlalchemy import Index, Column, String, DateTime, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import validates
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape, from_shape
from datetime import datetime
import uuid

from ..core.database import Base
from ..utils.single_part_geometry import ensure_single_polygon

logger = logging.getLogger(__name__)


class ForestBoundaryPiece(Base):
    """
    One disjoint piece of a forest's outer boundary, with its own identity.

    A forest always has >=1 piece once it has a boundary at all (a single-polygon
    forest is one piece, same as everything else); `Calculation.boundary_geom` is
    always the union of this forest's pieces. See BOUNDARY_PIECES_PLAN.md D3: the
    first cut is deliberately minimal (name + area only) -- easy to extend later.
    """
    __tablename__ = "forest_boundary_pieces"
    __table_args__ = (
        Index('idx_forest_boundary_pieces_calculation_id', 'calculation_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    geometry = Column(Geometry(srid=4326), nullable=False)
    area_hectares = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    @validates("geometry")
    def _validate_single_part_geometry(self, key, value):
        """One row = one piece — mirrors the identical guard on
        `ForestSubArea.geometry` / `ForestBlock.geometry`
        (`app/utils/single_part_geometry.py`). Only a `WKBElement` is checked; a
        raw SQL/driver value passes through untouched.
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
        return f"<ForestBoundaryPiece(id={self.id}, name={self.name})>"
