"""Where the roads inside a forest come from (FIRELINE_RIVERBANK_PLAN.md section 20, FL-4b).

A road inside the forest is an existing fire line. The sources are ADDITIVE: each is a function
``(db, calc, area_wgs) -> [RoadReach]`` listed in :data:`SOURCES` in priority order (earlier keeps the ground where two sources
describe the same road). A new source is one more function and one more entry here; nothing else changes.

* ``user`` -- the forest's own imported layers whose purpose is ``roads`` (``workspace_layers.layer_data``).
* ``osm``  -- ``infrastructure.road`` (OpenStreetMap, all of Nepal).

Every reach is already clipped to the forest area and is a single line.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from shapely import wkb as shp_wkb
from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.constants import IMPORT_PURPOSE_ROADS

logger = logging.getLogger(__name__)

OSM_TABLE = "infrastructure.road"
#: a width outside this range (metres) is a typo in the source, not a road
MIN_WIDTH_M, MAX_WIDTH_M = 0.5, 30.0


@dataclass(frozen=True)
class RoadReach:
    source: str        # "user" | "osm"
    ref: str           # the id inside that source
    name: str
    highway: str       # the OSM class ("track", "path"), or whatever the import called it
    width_m: Optional[float]   # the road's total width when the source says so
    line: LineString   # WGS84, inside the forest area


def parse_width(raw: Any) -> Optional[float]:
    """'4', '3.5 m', 4 -> metres; anything else (or a value out of range) -> None."""
    if raw is None:
        return None
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", str(raw))
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value if MIN_WIDTH_M <= value <= MAX_WIDTH_M else None


def lines_of(geom: Optional[BaseGeometry]) -> List[LineString]:
    """The lines in a geometry (a clip can leave points and collections), connected pieces joined, longest first."""
    if geom is None or geom.is_empty:
        return []
    found: List[LineString] = []

    def walk(g: BaseGeometry) -> None:
        if g.geom_type == "LineString":
            if g.length > 0:
                found.append(g)
        elif hasattr(g, "geoms"):
            for part in g.geoms:
                walk(part)

    walk(geom)
    if not found:
        return []
    merged = linemerge(found) if len(found) > 1 else found[0]
    out = [merged] if merged.geom_type == "LineString" else [g for g in merged.geoms if g.length > 0]
    return sorted(out, key=lambda ln: (-ln.length, ln.coords[0]))


# ---------------------------------------------------------------- the sources
def _user_roads(db: Session, calc: Any, area_wgs: BaseGeometry) -> List[RoadReach]:
    from app.models.workspace_layer import WorkspaceLayer

    out: List[RoadReach] = []
    layers = (
        db.query(WorkspaceLayer)
        .filter(WorkspaceLayer.calculation_id == calc.id, WorkspaceLayer.purpose == IMPORT_PURPOSE_ROADS,
                WorkspaceLayer.deleted_at.is_(None))
        .order_by(WorkspaceLayer.id)
        .all()
    )
    for layer in layers:
        for idx, feat in enumerate((layer.layer_data or {}).get("features") or []):
            props = feat.get("properties") or {}
            try:
                geom = shape(feat["geometry"]).intersection(area_wgs)
            except Exception:  # noqa: BLE001 -- one unreadable feature must not hide the other roads
                logger.warning("road_sources: feature %s of layer %s is unreadable", idx, layer.id, exc_info=True)
                continue
            for n, line in enumerate(lines_of(geom), start=1):
                out.append(RoadReach("user", f"{layer.id}:{idx}:{n}", str(props.get("name") or props.get("Name") or "").strip(),
                                     str(props.get("highway") or props.get("type") or "").strip(),
                                     parse_width(props.get("width")), line))
    return out


def _osm_roads(db: Session, calc: Any, area_wgs: BaseGeometry) -> List[RoadReach]:
    if not db.execute(text("SELECT to_regclass(:t)"), {"t": OSM_TABLE}).scalar():
        return []  # a database without the national road layer: no reaches, not an error
    rows = db.execute(
        text(
            f"SELECT r.id, r.osm_id, r.name, r.name_ne, r.name_en, r.highway, r.width, "  # noqa: S608 -- constant identifier
            f"ST_AsBinary(ST_Intersection(r.geom, ST_GeomFromText(:wkt, 4326))) AS g "
            f"FROM {OSM_TABLE} r "
            f"WHERE r.geom && ST_GeomFromText(:wkt, 4326) AND ST_Intersects(r.geom, ST_GeomFromText(:wkt, 4326)) "
            f"ORDER BY r.id"
        ),
        {"wkt": area_wgs.wkt},
    ).all()
    out: List[RoadReach] = []
    for row in rows:
        if row.g is None:
            continue
        geom = shp_wkb.loads(bytes(row.g))
        name = (row.name_ne or row.name or row.name_en or "").strip()
        ref = str(row.osm_id or row.id)
        for n, line in enumerate(lines_of(geom), start=1):
            out.append(RoadReach("osm", f"{ref}:{n}" if n > 1 else ref, name, (row.highway or "").strip(), parse_width(row.width), line))
    return out


Source = Callable[[Session, Any, BaseGeometry], List[RoadReach]]

#: priority order: where two sources describe the same road, the earlier one keeps the ground
SOURCES: Sequence[Source] = (_user_roads, _osm_roads)


def road_reaches(db: Session, calc: Any, area_wgs: BaseGeometry, sources: Sequence[Source] = SOURCES) -> List[RoadReach]:
    """Every road reach inside ``area_wgs`` from every source, in priority order. A source that fails is logged and skipped:
    one broken source must not take the fire lines down."""
    out: List[RoadReach] = []
    for source in sources:
        try:
            with db.begin_nested():
                out.extend(source(db, calc, area_wgs))
        except Exception:  # noqa: BLE001 -- see docstring
            logger.exception("road_sources: %s failed for calculation %s", getattr(source, "__name__", source), calc.id)
    return out
