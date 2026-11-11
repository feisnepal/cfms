"""Where the rivers inside a forest come from (FIRELINE_RIVERBANK_PLAN.md, RB-2).

``river.river84`` is the primary source (named rivers). ``river.river_line`` is a much finer network (1.15 million segments, most
unnamed) and is used ONLY when ``river84`` has nothing for the forest (owner, 2026-10-19). Connected pieces of one river are joined
into one centerline; a river with no name is called :data:`NO_NAME`.

Every reach is a single line already clipped to the forest area. A source that fails is logged and skipped.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from shapely import wkb as shp_wkb
from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.road_sources import lines_of

logger = logging.getLogger(__name__)

#: how a river with no name in the source reads (owner, 2026-10-19)
NO_NAME = "नाम नखुलेको खोला"


@dataclass(frozen=True)
class RiverReach:
    source: str     # "river84" | "river_line"
    ref: str        # the river's name in that source ("-" when it has none): one river, one ref
    name: str       # as shown: the river's name, or NO_NAME
    line: LineString
    # the same shape a road reach has, so ``fire_line_service.input_signature`` hashes both the same way
    highway: str = ""
    width_m: Optional[float] = None


def _rows_to_reaches(source: str, rows: Sequence[Tuple[Optional[str], Any]]) -> List[RiverReach]:
    """``(river name, geometry)`` rows -> one reach per connected piece of each river, in a stable order."""
    by_name: Dict[str, List[LineString]] = defaultdict(list)
    for name, geom in rows:
        by_name[(name or "").strip()].extend(lines_of(geom))
    out: List[RiverReach] = []
    for name in sorted(by_name, key=lambda n: (n == "", n)):
        pieces = by_name[name]
        if not pieces:
            continue
        from shapely.ops import linemerge

        merged = linemerge(pieces) if len(pieces) > 1 else pieces[0]
        parts = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
        for line in sorted((p for p in parts if p.length > 0), key=lambda p: p.coords[0]):
            out.append(RiverReach(source, name or "-", name or NO_NAME, line))
    return out


def _query(db: Session, table: str, geom_col: str, name_col: str, area_wgs: BaseGeometry) -> List[Tuple[Optional[str], Any]]:
    if not db.execute(text("SELECT to_regclass(:t)"), {"t": table}).scalar():
        return []  # a database without this layer: no reaches, not an error
    sql = (
        f'SELECT r."{name_col}" AS nm, ST_AsBinary(ST_Intersection(r."{geom_col}", ST_GeomFromText(:wkt, 4326))) AS g '  # noqa: S608 -- constant identifiers
        f'FROM {table} r WHERE r."{geom_col}" && ST_GeomFromText(:wkt, 4326) AND ST_Intersects(r."{geom_col}", ST_GeomFromText(:wkt, 4326))'
    )
    return [(row.nm, shp_wkb.loads(bytes(row.g))) for row in db.execute(text(sql), {"wkt": area_wgs.wkt}).all() if row.g is not None]


def _river84(db: Session, calc: Any, area_wgs: BaseGeometry) -> List[RiverReach]:
    return _rows_to_reaches("river84", _query(db, "river.river84", "shape", "river name", area_wgs))


def _river_line(db: Session, calc: Any, area_wgs: BaseGeometry) -> List[RiverReach]:
    return _rows_to_reaches("river_line", _query(db, "river.river_line", "geom", "river_name", area_wgs))


Source = Callable[[Session, Any, BaseGeometry], List[RiverReach]]

#: in order: the first source that has anything for the forest is the only one used
SOURCES: Sequence[Source] = (_river84, _river_line)


def river_reaches(db: Session, calc: Any, area_wgs: BaseGeometry, sources: Optional[Sequence[Source]] = None) -> List[RiverReach]:
    """The rivers inside ``area_wgs`` from the first source that has any. A source that fails is logged and the next is tried."""
    for source in (SOURCES if sources is None else sources):
        try:
            with db.begin_nested():
                found = source(db, calc, area_wgs)
        except Exception:  # noqa: BLE001 -- one broken source must not take the river banks down
            logger.exception("river_sources: %s failed for calculation %s", getattr(source, "__name__", source), calc.id)
            continue
        if found:
            return found
    return []
