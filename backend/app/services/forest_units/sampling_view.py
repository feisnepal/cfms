"""The undivided units as the sampling engines see them: the engine's own name for each, plus what the stratum rule needs.

Lives in the units module because it reads the structure columns and the derived ``result_data['sfm'...]['blocks']`` list, which only
this module may do (``scripts/check_unit_access.py``). Read-only.
"""

from __future__ import annotations

from typing import Any, Dict, List

from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from app.models.calculation import Calculation

from . import queries

SQM_PER_HA = 10_000.0


def sampling_units(db: Session, calculation: Calculation) -> List[Dict[str, Any]]:
    """One dict per undivided unit, in the engine's order. ``name`` is the one ``sampling.db_rows_to_units`` gives the unit
    (``compartment_code or block_name or name or "<Block|Compartment> n"``); keep the two identical."""
    rd = calculation.result_data or {}
    sfm_blocks = (rd.get("sfm_user") or rd.get("sfm") or {}).get("blocks") or []
    sfm_orientation = {b.get("block_name"): b.get("orientation") for b in sfm_blocks}
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(queries.unit_rows(db, calculation.id, queries.View.LEAF)):
        label = "Compartment" if row.is_compartment else "Block"
        name = row.compartment_code or row.block_name or row.name or f"{label} {i + 1}"
        geom = to_shape(row.geometry) if row.geometry is not None else None
        out.append(
            {
                "unit_id": str(row.id),
                "name": name,
                # what the workspace attribute table calls the unit; ``name`` above is only the key sampling files plots under
                "display_name": row.name or name,
                "wkt": geom.wkt if geom is not None else None,
                "area_ha": float(row.area_hectares) if row.area_hectares else (geom.area / SQM_PER_HA if geom is not None else 0.0),
                "working_circle": row.working_circle,
                "management_orientation": row.management_orientation,
                "slope_band": row.dominant_slope_band,
                "sfm_orientation": sfm_orientation.get(name),
            }
        )
    return out
