"""Does a dropped file lie inside THIS forest? (UPLOAD_EXPERIENCE_PLAN.md, UP-4)

A sample-plot, block or road file that belongs to another forest used to travel through the whole import before anything complained, or got through
altogether when it was within 10 km. This reads the file's geometry with the same reader the import uses and counts how many features touch the
forest boundary, so the Add-data row can say so the moment the file is dropped.

Read-only: nothing is saved.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_FEATURES = 3000  # a sample is enough to tell; the import validates the rest


def overlap_with_forest(db, calculation_id, geometries: List[Any]) -> Dict[str, Any]:
    """``{status, features, inside, outside, distance_km}``; status is ``inside`` | ``partial`` | ``outside`` | ``unknown`` (no boundary / no geometry)."""
    from sqlalchemy import text

    geoms = [g for g in (geometries or []) if g is not None and not g.is_empty][:MAX_FEATURES]
    if not geoms:
        return {"status": "unknown", "features": 0, "inside": 0, "outside": 0, "distance_km": None}
    row = db.execute(
        text(
            "SELECT count(*) AS n, "
            "       count(*) FILTER (WHERE ST_Intersects(g.geom, c.boundary_geom)) AS inside, "
            "       min(ST_Distance(g.geom::geography, c.boundary_geom::geography)) FILTER (WHERE NOT ST_Intersects(g.geom, c.boundary_geom)) AS gap "
            "FROM calculations c "
            "CROSS JOIN LATERAL (SELECT ST_SetSRID(ST_GeomFromText(w), 4326) AS geom FROM unnest(CAST(:wkts AS text[])) AS w) g "
            "WHERE c.id = :cid AND c.boundary_geom IS NOT NULL"
        ),
        {"wkts": [g.wkt for g in geoms], "cid": str(calculation_id)},
    ).first()
    if not row or not row.n:
        return {"status": "unknown", "features": len(geoms), "inside": 0, "outside": 0, "distance_km": None}
    n, inside = int(row.n), int(row.inside or 0)
    status = "inside" if inside == n else ("outside" if inside == 0 else "partial")
    gap = float(row.gap) / 1000.0 if row.gap is not None else None
    return {"status": status, "features": n, "inside": inside, "outside": n - inside, "distance_km": round(gap, 1) if gap is not None else None}


async def read_overlap(db, calculation_id, content: bytes, filename: str) -> Dict[str, Any]:
    """Read ``content`` like the import does and compare it with the forest. Never raises: an unreadable or unplaceable file is ``unknown``."""
    from app.services.file_processor import read_upload_geometries

    try:
        geometries, _attrs, _crs = await read_upload_geometries(content, filename)
    except Exception:  # noqa: BLE001 -- advisory check; the import itself explains an unreadable file
        logger.debug("overlap check: %s could not be read", filename, exc_info=True)
        return {"status": "unknown", "features": 0, "inside": 0, "outside": 0, "distance_km": None}
    try:
        return overlap_with_forest(db, calculation_id, list(geometries))
    except Exception:  # noqa: BLE001 -- advisory check
        logger.warning("overlap check failed for %s", filename, exc_info=True)
        db.rollback()
        return {"status": "unknown", "features": 0, "inside": 0, "outside": 0, "distance_km": None}
