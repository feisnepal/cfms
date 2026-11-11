"""RasterLayer model (RASTER_SOURCES P2.5, RS-2.16, migration 107).

One row per Auto-Block layer a forest has created from a raster source. A
layer is a self-contained set of `forest_blocks` rows carrying only that
source's attributes (D51) -- it does not join the structural hierarchy until
`promoted_as` is set, at which point it becomes the calculation's authoritative
blocks/compartments stream. See RASTER_SOURCES_TRACKER.md "P2.5" for the full
model; this file is schema only -- promotion/read-side filtering is RS-2.17/2.18.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from ..core.database import Base
import uuid

# Same vocabulary `commit_blocks(level=...)` already uses -- promotion does not
# introduce a second one.
PROMOTED_AS_VALUES = {"blocks", "compartments"}


class RasterLayer(Base):
    __tablename__ = "raster_layers"
    __table_args__ = (
        Index("idx_raster_layers_calculation_id", "calculation_id"),
        {"extend_existing": True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("calculations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Auto-Block source that carved this layer -- same strings as
    # `PREVIEW_FN_BY_SOURCE` keys in auto_block_service.py (D33/RS-0.3 is the
    # SSOT for the set of valid values; this column does not duplicate it).
    source = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    # NULL = unpromoted (non-counting overlay). Non-NULL is the ONLY signal
    # that this layer is the calculation's real structure -- do not add a
    # second "is_active"-style flag that could disagree with this one.
    promoted_as = Column(String(20), nullable=True)
    promoted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    blocks = relationship(
        "ForestBlock",
        backref="raster_layer",
        passive_deletes=True,
    )

    def __repr__(self):
        return (
            f"<RasterLayer(id={self.id}, source={self.source}, "
            f"promoted_as={self.promoted_as})>"
        )
