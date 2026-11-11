"""Value types of the units module."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class Branch(str, Enum):
    """Which branch of the rule a unit belongs to."""

    BLOCK = "block"  # Forest -> Blocks -> Sub-blocks
    COMPARTMENT = "compartment"  # Forest -> Compartments -> Sub-compartments


class Stream(str, Enum):
    """The branch a whole forest uses. UNDECIDED = a boundary with no units yet."""

    BLOCK = "block"
    COMPARTMENT = "compartment"
    UNDECIDED = "undecided"


# Depth numbers, post depth-model migration 094 (FS-1c.2): the top level is 1 in BOTH branches, sub-units are
# >= 2, and 0 is the outer boundary only (never a row). These are the only place the numbers are written.
DEPTH_ROOT = 0  # the outer boundary - never a row
DEPTH_TOP_BLOCK = 1  # Forest -> Blocks -> Sub-blocks
DEPTH_TOP_COMPARTMENT = 1  # Forest -> Compartments -> Sub-compartments
DEPTH_SUB = 2
DEPTH_STEP = 1  # every subdivision adds one to the depth (a child is always parent depth + 1)


def depth_top(branch: Branch) -> int:
    return DEPTH_TOP_COMPARTMENT if branch is Branch.COMPARTMENT else DEPTH_TOP_BLOCK


@dataclass(frozen=True)
class Unit:
    """One block / compartment / sub-block / sub-compartment, as the rest of the app should see it."""

    id: uuid.UUID
    name: str
    block_name: str
    branch: Branch
    depth: int
    parent_id: Optional[uuid.UUID]
    geometry: (
        Any  # the stored geometry (a geoalchemy2 WKBElement); use .shape for shapely
    )
    area_ha: float
    working_circle: str
    is_locked: bool
    index: int

    @property
    def shape(self):
        from geoalchemy2.shape import to_shape

        return to_shape(self.geometry)

    @property
    def is_top_level(self) -> bool:
        return self.parent_id is None

    @property
    def is_protection(self) -> bool:
        return self.working_circle == "protection"


def unit_from_row(row) -> Unit:
    """Build a Unit from a ``ForestBlock`` ORM row."""
    return Unit(
        id=row.id,
        name=row.name,
        block_name=row.block_name or row.name,
        branch=Branch.COMPARTMENT if row.is_compartment else Branch.BLOCK,
        depth=row.division_level if row.division_level is not None else 0,
        parent_id=row.parent_block_id,
        geometry=row.geometry,
        area_ha=float(row.area_hectares or 0.0),
        working_circle=row.working_circle or "production",
        is_locked=bool(row.is_locked),
        index=row.index if row.index is not None else 0,
    )
