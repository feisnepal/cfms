from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from ..services.forest_units.model import DEPTH_TOP_COMPARTMENT

from sqlalchemy.orm import Session


class ForestDimension(str, Enum):
    BLOCK = "block"
    COMPARTMENT = "compartment"


def get_forest_dimension(
    db: Session,
    calculation_id: UUID,
) -> ForestDimension:
    """Determine whether a calculation uses blocks or compartments.

    Delegates to ``forest_units.mode.forest_stream`` (the one place that knows): the unit rows decide, then the
    ``result_data`` snapshot of an upload-mode forest. A forest with no units yet (UNDECIDED) reads as BLOCK,
    which is what every caller of this function has always assumed.
    """
    from app.services.forest_units.mode import forest_stream
    from app.services.forest_units.model import Stream

    if forest_stream(db, calculation_id) is Stream.COMPARTMENT:
        return ForestDimension.COMPARTMENT
    return ForestDimension.BLOCK


def dimension_label(dimension: ForestDimension, nepali: bool = False) -> str:
    if dimension == ForestDimension.COMPARTMENT:
        return "कम्पार्टमेन्ट" if nepali else "Compartment"
    return "ब्लक" if nepali else "Block"


def dimension_label_plural(dimension: ForestDimension, nepali: bool = False) -> str:
    if dimension == ForestDimension.COMPARTMENT:
        return "कम्पार्टमेन्टहरू" if nepali else "Compartments"
    return "ब्लकहरू" if nepali else "Blocks"


def dimension_label_lower(dimension: ForestDimension) -> str:
    return "compartment" if dimension == ForestDimension.COMPARTMENT else "block"


def dimension_label_plural_lower(dimension: ForestDimension) -> str:
    return "compartments" if dimension == ForestDimension.COMPARTMENT else "blocks"


def dimension_name_header_np(dimension: ForestDimension) -> str:
    if dimension == ForestDimension.COMPARTMENT:
        return "कम्पार्टमेन्टको नाम"
    return "ब्लकको नाम"


def dimension_name_header_np_plural(dimension: ForestDimension) -> str:
    if dimension == ForestDimension.COMPARTMENT:
        return "कम्पार्टमेन्टको नामहरू"
    return "ब्लकको नामहरू"


def dimension_name_header_en(dimension: ForestDimension) -> str:
    return "Compartment Name" if dimension == ForestDimension.COMPARTMENT else "Block Name"


def dimension_abbreviation(dimension: ForestDimension) -> str:
    return "Cmp" if dimension == ForestDimension.COMPARTMENT else "Blk"


def _branch_of(dimension: ForestDimension):
    from app.services.forest_units.model import Branch

    return Branch.COMPARTMENT if dimension == ForestDimension.COMPARTMENT else Branch.BLOCK


def dimension_label_for_level(
    dimension: ForestDimension,
    division_level: int = DEPTH_TOP_COMPARTMENT,
    nepali: bool = False,
) -> str:
    """FS-4a.1: delegates to ``forest_units.labels`` -- previously a block forest read
    "Block" at every depth, including a sub-block, because only the compartment side
    branched on the depth parameter. Sub-blocks now get their own term here too."""
    from app.services.forest_units import labels as unit_labels

    return unit_labels.unit_label(_branch_of(dimension), division_level, nepali=nepali)


def dimension_label_for_level_plural(
    dimension: ForestDimension,
    division_level: int = DEPTH_TOP_COMPARTMENT,
    nepali: bool = False,
) -> str:
    from app.services.forest_units import labels as unit_labels

    return unit_labels.unit_label_plural(
        _branch_of(dimension), division_level, nepali=nepali
    )


@dataclass
class NarrationContext:
    dimension: ForestDimension

    @property
    def unit_label_np(self) -> str:
        return dimension_label(self.dimension, nepali=True)

    @property
    def unit_label_en(self) -> str:
        return dimension_label(self.dimension, nepali=False)

    @property
    def unit_label_plural_np(self) -> str:
        return dimension_label_plural(self.dimension, nepali=True)

    @property
    def unit_name_header_np(self) -> str:
        return dimension_name_header_np(self.dimension)

    def unit_label_np_for_level(self, division_level: int) -> str:
        return dimension_label_for_level(self.dimension, division_level, nepali=True)

    def unit_label_en_for_level(self, division_level: int) -> str:
        return dimension_label_for_level(self.dimension, division_level, nepali=False)

    def unit_label_plural_np_for_level(self, division_level: int) -> str:
        return dimension_label_for_level_plural(self.dimension, division_level, nepali=True)
