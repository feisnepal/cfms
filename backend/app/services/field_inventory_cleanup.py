"""What must go with a field inventory when it is deleted (owner rule 2026-10-10: an inventory can be deleted and replaced).

Deleting the inventory rows already removes its plots, measurements and per-unit summaries. Things DERIVED from the inventory
live elsewhere and would otherwise keep describing data that no longer exists:

* the Sustainable-FM result cached on the calculation, and the suggested orientation (+ justification) written onto the units from it;
* the Biodiversity species the inventory listed automatically (their note starts with ``From field inventory:``) -- species recorded
  by hand, or whose note the user edited, are kept;
* the "already listed" marker, so the replacement inventory lists its own species;
* cached documents and rendered maps built from the old numbers.

A management orientation is a decision (it may have been defaulted from the suggestion, then confirmed or changed by the user), so it
is left alone; the table already flags a confirmed value that differs from the latest suggestion.

Does not commit: the caller does, in the same transaction as the delete.
"""
from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)

AUTO_NOTE_PREFIX = "From field inventory:"


def clear_derived_after_delete(db: Session, calculation_id: UUID) -> Dict[str, Any]:
    from app.models.biodiversity import CalculationBiodiversity
    from app.models.calculation import Calculation
    from app.models.op_data_cache import OpDataCache
    from app.services.biodiversity_inventory_import import SYNC_MARKER
    from app.services.field_inventory_service import invalidate_render_caches

    species = (
        db.query(CalculationBiodiversity)
        .filter(
            CalculationBiodiversity.calculation_id == calculation_id,
            CalculationBiodiversity.notes.like(AUTO_NOTE_PREFIX + "%"),
        )
        .delete(synchronize_session=False)
    )

    calc = db.get(Calculation, calculation_id)
    dropped = []
    if calc is not None:
        rd = dict(calc.result_data or {})
        for key in (SYNC_MARKER, "sfm", "sfm_user"):
            if rd.pop(key, None) is not None:
                dropped.append(key)
        calc.result_data = rd
        flag_modified(calc, "result_data")

    oriented = db.execute(
        text(
            "UPDATE forest_blocks SET suggested_orientation = NULL, orientation_justification_en = NULL, "
            "orientation_justification_ne = NULL WHERE calculation_id = :c AND suggested_orientation IS NOT NULL"
        ),
        {"c": str(calculation_id)},
    ).rowcount

    db.query(OpDataCache).filter(OpDataCache.calculation_id == calculation_id).delete(synchronize_session=False)
    invalidate_render_caches(db, calculation_id)
    return {"species_removed": species, "orientation_cleared": oriented, "cache_keys_dropped": dropped}
