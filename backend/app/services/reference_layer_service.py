"""Reference-data layers cut to one forest's neighbourhood (``app.core.reference_layers`` says what each layer is).

The neighbourhood is the forest's bounding box widened by a buffer. A line or polygon layer is intersected with that box, so a municipality of hundreds of square kilometres
comes back as the piece that matters; a point or footprint layer is taken whole. Reading is by the layers' spatial indexes (``&&`` first), so a forest costs milliseconds
however big the national table is. Nothing is written and nothing is cached here: the data is shared and static, the query is cheap.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import reference_layers as ref

logger = logging.getLogger(__name__)

#: metres to degrees of latitude; longitude degrees are shorter, so the box is a little generous east-west, which is the safe way to be wrong
METRES_PER_DEGREE = 111_320.0


class ReferenceLayerError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def catalogue() -> List[Dict[str, Any]]:
    return [{
        "key": l.key, "label_en": l.label_en, "label_ne": l.label_ne, "geometry": l.geometry, "style": l.style, "group": l.group,
        "source": l.source, "licence": l.licence, "licence_note": l.licence_note, "max_features": l.max_features,
        "default_buffer_m": ref.DEFAULT_BUFFER_M, "max_buffer_m": ref.MAX_BUFFER_M,
    } for l in ref.LAYERS]


def _geometry_expression(l: ref.ReferenceLayer) -> str:
    g = f"t.{l.geom_column}"
    if l.clip == ref.CLIP_POLYGON:
        expr = f"ST_Multi(ST_CollectionExtract(ST_Intersection(ST_MakeValid({g}), b.box), 3))"
    elif l.clip == ref.CLIP_LINE:
        expr = f"ST_Multi(ST_CollectionExtract(ST_Intersection({g}, b.box), 2))"
    else:
        expr = g
    if l.simplify_deg > 0:
        expr = f"ST_SimplifyPreserveTopology({expr}, {float(l.simplify_deg)!r})"
    return expr


def _plain(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def features(db: Session, calculation_id: UUID, key: str, buffer_m: Optional[float] = None) -> Dict[str, Any]:
    """The layer's features in the forest's neighbourhood as a GeoJSON FeatureCollection, with how many there were and whether it was cut short."""
    l = ref.get(key)
    if l is None:
        raise ReferenceLayerError("unknown_layer", f"There is no reference layer named {key!r}.")
    buf = ref.DEFAULT_BUFFER_M if buffer_m is None else float(buffer_m)
    if not 0 <= buf <= ref.MAX_BUFFER_M:
        raise ReferenceLayerError("bad_buffer", f"The buffer must be between 0 and {int(ref.MAX_BUFFER_M)} m.")
    has_boundary = db.execute(text("SELECT boundary_geom IS NOT NULL FROM calculations WHERE id = :id"), {"id": str(calculation_id)}).scalar()
    if not has_boundary:
        raise ReferenceLayerError("no_boundary", "The forest has no boundary yet.")

    geom = _geometry_expression(l)
    props = ", ".join(f"{expr} AS p_{name}" for name, expr in l.properties.items())
    label = f"{l.label_expr} AS p__label" if l.label_expr else "NULL AS p__label"
    sql = text(f"""
        WITH b AS (SELECT ST_Expand(ST_Envelope(boundary_geom::geometry), :deg) AS box FROM calculations WHERE id = :id)
        SELECT {props}, {label}, ST_AsGeoJSON(t.ref_geom, 5) AS geojson
        FROM (
            SELECT t.*, {geom} AS ref_geom FROM {l.table} t, b
            WHERE t.{l.geom_column} && b.box AND ST_Intersects(t.{l.geom_column}, b.box)
            LIMIT :lim
        ) t
        WHERE t.ref_geom IS NOT NULL AND NOT ST_IsEmpty(t.ref_geom)
    """)
    rows = db.execute(sql, {"deg": buf / METRES_PER_DEGREE, "id": str(calculation_id), "lim": l.max_features + 1}).mappings().all()
    truncated = len(rows) > l.max_features
    out = []
    for i, r in enumerate(rows[: l.max_features]):
        properties = {name: _plain(r[f"p_{name}"]) for name in l.properties}
        properties["_label"] = r["p__label"]
        properties["_ref"] = f"{l.key}-{i}"
        out.append({"type": "Feature", "id": f"{l.key}-{i}", "geometry": json.loads(r["geojson"]), "properties": properties})
    return {"type": "FeatureCollection", "features": out, "key": l.key, "count": len(out), "truncated": truncated, "buffer_m": buf, "max_features": l.max_features}
