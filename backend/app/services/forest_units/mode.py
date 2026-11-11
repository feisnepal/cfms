"""Which branch of the rule does a forest use?"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.forest_block import ForestBlock

from .model import Stream


def forest_stream(db: Session, calc_id) -> Stream:
    """BLOCK, COMPARTMENT, or UNDECIDED (a boundary with no units yet).

    Order of evidence: a stored mode (once ``calculations.structure_mode`` exists, P2) -> the unit rows
    (authoritative) -> the ``result_data`` snapshot of an upload-mode forest. On every forest that follows the
    rule this is the same answer ``utils.forest_dimension.get_forest_dimension`` gave; a legacy MIXED forest
    (blocks and compartments together) still answers COMPARTMENT, as before, until the mixed shape is removed.
    A forest that is one block or one compartment answers BLOCK or COMPARTMENT like any other.
    """
    calc_id = calc_id if isinstance(calc_id, UUID) else UUID(str(calc_id))
    calc = db.query(Calculation).filter(Calculation.id == calc_id).first()

    stored = getattr(calc, "structure_mode", None) if calc is not None else None
    if stored in (Stream.BLOCK.value, Stream.COMPARTMENT.value):
        return Stream(stored)

    has_compartment_rows = (
        db.query(ForestBlock.id)
        .filter(
            ForestBlock.calculation_id == calc_id, ForestBlock.is_compartment.is_(True)
        )
        .first()
        is not None
    )
    if has_compartment_rows:
        return Stream.COMPARTMENT
    has_block_rows = (
        db.query(ForestBlock.id)
        .filter(
            ForestBlock.calculation_id == calc_id, ForestBlock.is_compartment.is_(False)
        )
        .first()
        is not None
    )
    if has_block_rows:
        return Stream.BLOCK

    # No unit rows: an upload-mode forest may still describe its units in result_data.
    rd = (calc.result_data or {}) if calc is not None else {}
    if not isinstance(rd, dict):
        rd = {}
    if rd.get("compartments") or rd.get("polygon_type") == "compartment":
        return Stream.COMPARTMENT
    if rd.get("blocks") or rd.get("polygon_type") == "block":
        return Stream.BLOCK
    return Stream.UNDECIDED
