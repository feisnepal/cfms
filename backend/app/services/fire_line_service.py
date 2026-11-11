"""Fire lines: the candidates, and keeping the stored strips in step with them (FIRELINE_RIVERBANK_PLAN.md, FL-4).

A fire line is a sub-area entry (``result_data['sub_areas']``, category ``fire_line``). Every boundary the field book walks
is a candidate; all of them are created automatically (owner option B, 2026-10-19) and the user UNTICKS the ones that are not
fire lines. Only the unticks are remembered: ``result_data['fire_line_decisions'] = {unit_key: 'exclude'}``.

* :func:`candidates` -- field-book lines -> named, clipped, trimmed strips (read-only).
* :func:`plan_sync` -- PURE: the stored sub-areas + the candidates + the decisions -> the new list and a report.
* :func:`sync_fire_lines` -- the database shell: lock the calculation, plan, write, clear caches.

Rules in :func:`plan_sync` (idempotent, keyed by ``unit_key``): create a missing candidate; update an unedited auto strip whose
geometry moved; leave an edited one alone (still clipped to the forest area); drop an auto strip whose candidate is gone; never
recreate an excluded name; never touch a drawn strip except to clip it. A strip counts as EDITED when its stored geometry is no
longer the one this service wrote (``geom_sig``), so no editing route has to know about fire lines. A name the user typed is kept
(``auto_name`` is the name this service wrote).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.constants import (
    FIRE_LINE_SIDE_M,
    RIVER_BANK_SIDE_M,
    STRIP_MAX_UNIT_OVERLAP_FRACTION,
    STRIP_MAX_PIECES_PER_PAIR,
    STRIP_MAX_UNRESOLVED_FRACTION,
    STRIP_MIN_AREA_M2,
    STRIP_MIN_LENGTH_M,
    STRIP_SNAP_M,
)
from app.core.sub_area_kinds import FIRE_LINE, RIVER_BANK, real_sub_areas
from app.services import strip_geometry as sg
from app.services.strip_geometry import OUTER_LABEL, Metric, Stretch

logger = logging.getLogger(__name__)



@dataclass(frozen=True)
class StripKind:
    """What differs between the strip kinds: the category and the four keys it keeps in ``result_data``. Everything else (the
    sync plan, the entries, ticking, drawing, widening) is shared."""

    category: str
    decisions_key: str
    signature_key: str
    status_key: str
    catalogue_key: str
    side_m: float
    default_name: str


FIRE_KIND = StripKind(FIRE_LINE, "fire_line_decisions", "fire_line_signature", "fire_line_status", "fire_line_candidates",
                      FIRE_LINE_SIDE_M, "Fire line")
RIVER_KIND = StripKind(RIVER_BANK, "river_bank_decisions", "river_bank_signature", "river_bank_status", "river_bank_candidates",
                       RIVER_BANK_SIDE_M, "River bank")
KINDS = {k.category: k for k in (FIRE_KIND, RIVER_KIND)}

DECISIONS_KEY = FIRE_KIND.decisions_key
SIGNATURE_KEY = FIRE_KIND.signature_key
STATUS_KEY = FIRE_KIND.status_key
CATALOGUE_KEY = FIRE_KIND.catalogue_key
EXCLUDE = "exclude"
#: how an unnamed road reads (बाटो = road); the class goes in brackets
ROAD_LABEL = "\u092c\u093e\u091f\u094b"


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    unit_key: str
    name: str
    pair: Tuple[str, ...]
    tag: str
    centerline: LineString            # WGS84
    geometry: BaseGeometry            # WGS84, one polygon
    geometry_m: BaseGeometry          # metric, for the figures
    length_m: float
    area_ha: float
    segment_widths_m: List[float] = field(default_factory=list)
    source: str = "boundary"   # "boundary" (a unit edge) or "road" (an existing road inside the forest)
    highway: str = ""
    road_ref: str = ""
    origin: str = "auto"       # "auto" (regenerated) or "drawn" (made by the draw tool, never regenerated)
    river_name: str = ""       # a river bank: the river it follows


def unit_overlap_m2(units: Sequence[Any], metric: Metric) -> float:
    """Total area (m2) where one unit lies on top of another. A clean layout is 0."""
    from shapely.strtree import STRtree

    polys = [metric.to_m(u.polygon) for u in units]
    tree = STRtree(polys)
    total = 0.0
    for i, p in enumerate(polys):
        for j in tree.query(p):
            if j > i:
                total += p.intersection(polys[int(j)]).area
    return total


def _pair_key(pair: Sequence[str], number_of: Dict[str, Any]) -> str:
    parts = ["outer" if n == OUTER_LABEL else f"u{number_of.get(n, n)}" for n in pair]
    return "+".join(sorted(parts))


def stretches_from_sequence(seq: Any, metric: Metric) -> Tuple[List[Stretch], int]:
    """The field book's lines -> stretches that each separate the same two things.

    A leg joins two consecutive points of a line; the units it separates are the units BOTH points are adjacent to
    (a junction point is adjacent to three or more, an ordinary point to two, an outer point to one). Consecutive legs with the
    same answer are one stretch. Returns ``(stretches, unresolved_legs)``.
    """
    from shapely.geometry import Point

    by_label = {p["point_label"]: p for p in seq.points}
    stretches: List[Stretch] = []
    unresolved = 0
    for line in seq.lines:
        pts = [by_label[lb] for lb in line["labels"] if lb in by_label]
        if line.get("closed") and len(pts) > 1 and pts[-1] is not pts[0]:
            pts = pts + [pts[0]]
        if len(pts) < 2:
            continue
        xy = [(p["x"], p["y"]) for p in pts]
        mxy = [(pt.x, pt.y) for pt in (metric.to_m(Point(x, y)) for x, y in xy)]

        legs: List[Tuple[Tuple[str, ...], str]] = []
        for a, b in zip(pts, pts[1:]):
            inter = sorted(set(a.get("adjacent_units") or []) & set(b.get("adjacent_units") or []))
            tag = ""
            if line["kind"] == "outer":
                pair = (inter[0], OUTER_LABEL) if len(inter) == 1 else None
            elif len(inter) == 2:
                pair = tuple(inter)
            elif len(inter) == 1:  # an outline lying INSIDE one unit: a sub-area island
                pair = (inter[0],)
                tag = a.get("sub_area_name") or b.get("sub_area_name") or ""
            else:
                pair = None
            if pair is None:
                unresolved += 1
            legs.append((pair, tag))

        order = 0
        run_start = 0
        for i in range(1, len(legs) + 1):
            if i == len(legs) or legs[i] != legs[run_start]:
                pair, tag = legs[run_start]
                if pair is not None:
                    order += 1
                    stretches.append(Stretch(pair, tuple(mxy[run_start : i + 1]), line["id"], order, tag))
                run_start = i
    return stretches, unresolved


def _sub_polygon(raw: Any) -> Optional[BaseGeometry]:
    try:
        geom = shape(raw)
        return None if geom.is_empty else geom
    except Exception:  # noqa: BLE001 -- one unparsable zone must not stop the fire lines; it is simply not used
        logger.warning("fire_line_service: a sub-area geometry could not be read", exc_info=True)
        return None


def _parts_along(line_m: LineString, strip: Optional[BaseGeometry]) -> List[Any]:
    """The single-part polygons of a strip, in the order they lie ALONG its centerline.

    Trimming against a road (or a sharp bend) can cut one strip into several parts. Numbering them by position, not by size,
    keeps ``~1``, ``~2`` ... attached to the same stretch of ground when the geometry changes a little.
    """
    return sorted(sg.explode(strip), key=lambda part: (round(line_m.project(part.centroid), 3), -part.area))


def _project_vertices(geom: BaseGeometry, ref: BaseGeometry, tol: float) -> BaseGeometry:
    """``geom`` with every vertex that lies within ``tol`` of ``ref`` (but not on it) moved onto the nearest point of ``ref``.
    GEOS ``snap`` moves vertices onto vertices only, so a vertex 30 cm off a neighbour's straight edge would stay off it."""
    from shapely.geometry import MultiPolygon, Point, Polygon

    def _ring(coords):
        out = []
        for x, y in coords:
            p = Point(x, y)
            d = ref.distance(p)
            if 0.0 < d <= tol:
                q = ref.interpolate(ref.project(p))
                x, y = q.x, q.y
            out.append((x, y))
        return out

    def _poly(p: Polygon) -> Polygon:
        return Polygon(_ring(p.exterior.coords), [_ring(r.coords) for r in p.interiors])

    if isinstance(geom, Polygon):
        return _poly(geom)
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([_poly(p) for p in geom.geoms])
    return geom


def snap_units(forest: BaseGeometry, units: Sequence[Any], tol_m: float = STRIP_SNAP_M) -> List[Any]:
    """The units with neighbouring edges made to coincide: a vertex within ``tol_m`` of the forest boundary or of an earlier unit moves
    onto it. Real units are cut from rasters or drawn by hand, so shared edges are a few centimetres apart and the field book's 2 cm
    "on this line" test breaks one border into dozens of stretches. Only the working copy is snapped; stored geometry is untouched, and
    a unit whose snapped shape is invalid or changes by more than 0.1 % in area is kept as it was."""
    from dataclasses import replace

    from shapely import make_valid, snap

    tol = tol_m / 111_320.0  # metres -> degrees (the units are WGS84; half a metre is far below any real feature)
    placed: List[BaseGeometry] = [forest.boundary]
    out: List[Any] = []
    for u in sorted(units, key=lambda u: u.number):
        g = u.polygon
        try:
            s = g
            for ref in placed:
                s = _project_vertices(snap(s, ref, tol), ref, tol)
            if not s.is_valid:
                s = make_valid(s)
            if s.is_empty or s.geom_type not in ("Polygon", "MultiPolygon") or abs(s.area - g.area) > 0.001 * g.area:
                s = g
        except Exception:  # noqa: BLE001 -- snapping is an aid; a unit it cannot handle is used as stored
            logger.warning("fire_line_service: could not snap unit %s", u.name, exc_info=True)
            s = g
        out.append(replace(u, polygon=s))
        placed.append(s.boundary)
    return out


def candidates(
    forest: BaseGeometry,
    units: Sequence[Any],
    subareas: Sequence[Any],
    side_m: float = FIRE_LINE_SIDE_M,
    min_length_m: float = STRIP_MIN_LENGTH_M,
    roads: Sequence[Any] = (),
) -> Tuple[List[Candidate], Dict[str, int]]:
    """Every fire-line candidate for a forest, plus a small report. Pure: the inputs are the field book's own
    (``UnitIn`` / ``SubAreaIn`` from ``fieldbook_sequence``; ``forest`` in WGS84) and the road reaches inside the forest area.

    The roads are placed FIRST, in the order given (``road_sources`` priority), then the boundary strips; each is trimmed against
    everything placed before it, so an area is counted once and "to construct" is what the roads do not already cover.
    """
    from app.services.fieldbook_sequence import build_sequence

    units = snap_units(forest, units)
    seq = build_sequence(forest, list(units), list(subareas), spacing=0)
    metric = Metric.for_geometry(forest)
    stretches, unresolved = stretches_from_sequence(seq, metric)
    pieces = sg.build_pieces(stretches, min_length_m)
    names = sg.piece_names(pieces)

    number_of = {u.name: u.number for u in units}
    forest_m = metric.to_m(forest)
    private_m = [metric.to_m(s.polygon) for s in subareas if getattr(s, "category", "") == "private_land"]
    area_m = sg.forest_area(forest_m, private_m)

    # ---- the roads, in priority order
    road_items: List[Dict[str, Any]] = []
    per_ref: Dict[Tuple[str, str], int] = {}
    for reach in roads:
        line_m = metric.to_m(reach.line)
        if line_m.length < min_length_m:
            continue  # a stub of road at the edge of the forest is not a fire line
        side = (reach.width_m / 2.0) if reach.width_m else side_m
        n_seg = len(line_m.coords) - 1
        ref_key = (reach.source, reach.ref)
        per_ref[ref_key] = per_ref.get(ref_key, 0) + 1
        road_items.append({
            "reach": reach, "line_m": line_m, "side": side, "n_seg": n_seg, "n": per_ref[ref_key],
            "strip": sg.clip_to_area(sg.strip_polygon(line_m, [side] * n_seg), area_m),
        })
    seen_names: Dict[str, int] = {}
    for item in road_items:
        r = item["reach"]
        base = r.name or f"{ROAD_LABEL} ({r.highway or 'road'})"
        seen_names[base] = seen_names.get(base, 0) + 1
        item["name"] = base if seen_names[base] == 1 else f"{base} ({seen_names[base]})"

    boundary_strips = []
    for piece in pieces:
        n_seg = len(piece.line.coords) - 1
        boundary_strips.append(sg.clip_to_area(sg.strip_polygon(piece.line, [side_m] * n_seg), area_m))

    trimmed = sg.trim_same_kind([i["strip"] for i in road_items] + boundary_strips)
    road_trimmed, boundary_trimmed = trimmed[: len(road_items)], trimmed[len(road_items):]

    out: List[Candidate] = []

    def add(unit_key, name, pair, tag, line_m, part, side_list, source, highway="", road_ref="", suffix=0):
        if part.area < STRIP_MIN_AREA_M2:
            return
        out.append(Candidate(
            unit_key=unit_key if suffix == 0 else f"{unit_key}~{suffix}",
            name=name if suffix == 0 else f"{name} \u00b7{suffix + 1}",
            pair=pair, tag=tag, centerline=metric.to_wgs(line_m), geometry=metric.to_wgs(part), geometry_m=part,
            length_m=round(sg.length_m(line_m), 2), area_ha=round(sg.area_ha(part), 4), segment_widths_m=side_list,
            source=source, highway=highway, road_ref=road_ref,
        ))

    for item, strip in zip(road_items, road_trimmed):
        r = item["reach"]
        for i, part in enumerate(_parts_along(item["line_m"], strip)):
            add(f"road:{r.source}:{r.ref}|{item['n']}", item["name"], (), "", item["line_m"], part,
                [item["side"]] * item["n_seg"], "road", r.highway, f"{r.source}:{r.ref}", i)

    ordinal: Dict[Tuple[str, str], int] = {}
    for piece, name, strip in zip(pieces, names, boundary_trimmed):
        pk = (_pair_key(piece.pair, number_of), piece.tag)
        ordinal[pk] = ordinal.get(pk, 0) + 1
        n_seg = len(piece.line.coords) - 1
        for i, part in enumerate(_parts_along(piece.line, strip)):
            add(f"{pk[0]}|{pk[1]}|{ordinal[pk]}", name, piece.pair, piece.tag, piece.line, part, [side_m] * n_seg, "boundary", suffix=i)

    report = {"stretches": len(stretches), "pieces": len(pieces), "unresolved_legs": unresolved,
              "pair_groups": len({(p.pair, p.tag) for p in pieces}),
              "road_reaches": len(road_items), "road_candidates": sum(1 for c in out if c.source == "road")}
    return out, report


# ---------------------------------------------------------------------------
# the pure sync plan
# ---------------------------------------------------------------------------
def geometry_signature(geom: Any) -> str:
    """A stable hash of a polygon, to 1e-7 degrees (~1 cm): tells a geometry this service wrote from one a user edited."""
    g = shape(geom) if isinstance(geom, dict) else geom

    def _r(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 7)
        if isinstance(v, (list, tuple)):
            return [_r(x) for x in v]
        return v

    data = mapping(g)
    return hashlib.sha1(json.dumps({"t": data["type"], "c": _r(data["coordinates"])}, sort_keys=True).encode()).hexdigest()[:16]


def is_edited(sa: Dict[str, Any]) -> bool:
    """True when the stored geometry is no longer the one this service wrote."""
    sig = sa.get("geom_sig")
    geom = sa.get("geometry")
    if not sig or not geom:
        return bool(sa.get("edited"))
    try:
        return bool(sa.get("edited")) or geometry_signature(geom) != sig
    except Exception:  # noqa: BLE001 -- unreadable geometry: treat as edited, so it is never overwritten
        return True


MakeEntry = Callable[[Candidate], Dict[str, Any]]


def plan_sync(
    existing: Sequence[Dict[str, Any]],
    cands: Sequence[Candidate],
    decisions: Dict[str, str],
    area_wgs: Optional[BaseGeometry],
    make_entry: MakeEntry,
    category: str = FIRE_LINE,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """The new ``sub_areas`` list and a report ``{created, updated, dropped, kept_edited, reclipped}``. Pure."""
    excluded = {k for k, v in (decisions or {}).items() if v == EXCLUDE}
    wanted = {c.unit_key: c for c in cands if c.unit_key not in excluded}
    report = {"created": 0, "updated": 0, "dropped": 0, "kept_edited": 0, "reclipped": 0}
    out: List[Dict[str, Any]] = []
    seen: set = set()

    for sa in existing:
        if sa.get("category") != category:
            out.append(sa)
            continue
        key = sa.get("unit_key")
        if sa.get("origin") != "auto" or not key:      # drawn: never regenerated, only clipped
            clipped = _reclip(sa, area_wgs)
            report["reclipped"] += int(clipped is not sa)
            out.append(clipped)
            continue
        if key in seen:                                # a duplicate of a key already kept: drop it
            report["dropped"] += 1
            continue
        cand = wanted.get(key)
        if cand is None:
            if is_edited(sa):
                out.append(_reclip(sa, area_wgs))
                report["kept_edited"] += 1
            else:
                report["dropped"] += 1
            continue
        seen.add(key)
        if is_edited(sa):
            clipped = _reclip(sa, area_wgs)
            report["kept_edited"] += 1
            report["reclipped"] += int(clipped is not sa)
            out.append(clipped)
            continue
        updated = _updated(sa, cand, make_entry)
        report["updated"] += int(updated != sa)
        out.append(updated)

    for key, cand in wanted.items():
        if key not in seen:
            out.append(make_entry(cand))
            report["created"] += 1
    return out, report


def _updated(sa: Dict[str, Any], cand: Candidate, make_entry: MakeEntry) -> Dict[str, Any]:
    fresh = make_entry(cand)
    keep_name = sa.get("name") != sa.get("auto_name") and bool(sa.get("name"))  # the user typed a name: it stays
    merged = dict(sa)
    for k, v in fresh.items():
        if k in ("id", "created_at"):
            continue
        if k == "name" and keep_name:
            continue
        merged[k] = v
    if keep_name:
        merged["auto_name"] = cand.name
    return merged if merged != sa else sa


def _wgs_polygons(geom: Optional[BaseGeometry]) -> List[Any]:
    """The polygons of a WGS84 geometry, largest first. (``sg.explode`` is for metres: its noise floor is in m2.)"""
    if geom is None or geom.is_empty:
        return []
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    polys: List[Any] = []
    for part in parts:
        polys.extend(_wgs_polygons(part) if hasattr(part, "geoms") else ([part] if part.geom_type == "Polygon" and part.area > 0 else []))
    return sorted(polys, key=lambda p: -p.area)


def _reclip(sa: Dict[str, Any], area_wgs: Optional[BaseGeometry]) -> Dict[str, Any]:
    """The boundary always wins: a strip is cut to the forest area. Returns ``sa`` itself when nothing changed."""
    if area_wgs is None or not sa.get("geometry"):
        return sa
    try:
        geom = shape(sa["geometry"])
        inside = geom.intersection(area_wgs)
    except Exception:  # noqa: BLE001 -- unreadable geometry is left as it is rather than lost
        logger.warning("fire_line_service: could not clip strip %s", sa.get("id"), exc_info=True)
        return sa
    polys = _wgs_polygons(inside)
    if not polys:
        return sa
    keep = polys[0]
    if abs(keep.area - geom.area) <= geom.area * 1e-6:
        return sa
    out = dict(sa)
    out["geometry"] = mapping(keep)
    out["edited"] = True if sa.get("origin") == "auto" else sa.get("edited", False)
    return out


# ---------------------------------------------------------------------------
# entries
# ---------------------------------------------------------------------------
def entry_factory(
    metric: Metric, units: Sequence[Any], zones_m: Dict[str, List[BaseGeometry]], now: Optional[str] = None,
    category: str = FIRE_LINE,
) -> MakeEntry:
    """Build the ``result_data['sub_areas']`` dict for a candidate (the shape ``add_sub_area`` writes, plus the strip keys)."""
    from app.utils.geometry_utils import compute_geometry_properties

    stamp = now or datetime.now(timezone.utc).isoformat()
    unit_m = [(u.name, metric.to_m(u.polygon)) for u in units]

    def make(c: Candidate) -> Dict[str, Any]:
        # JSON round trip: what is stored comes back with lists where mapping() gives tuples, and an entry that compares
        # unequal to itself would be "updated" on every run
        return json.loads(json.dumps(_entry(c), default=str))

    def _entry(c: Candidate) -> Dict[str, Any]:
        sqm = round(c.geometry_m.area, 2)
        breakdown = []
        for name, poly in unit_m:
            share = c.geometry_m.intersection(poly).area
            if share > 0:
                breakdown.append({"blockId": None, "blockName": name, "area": round(share / 10_000, 4), "percentage": round(100 * share / c.geometry_m.area, 2)})
        breakdown.sort(key=lambda b: -b["area"])
        return {
            "id": str(uuid.uuid4()),
            "name": c.name,
            "category": category,
            "geometry": mapping(c.geometry),
            "area_sqm": sqm,
            "area_hectares": c.area_ha,
            "blockId": None,
            "blockName": breakdown[0]["blockName"] if breakdown else None,
            "blockBreakdown": breakdown,
            "isExcluded": False,
            "is_excluded": False,
            "created_at": stamp,
            **compute_geometry_properties(c.geometry),
            "origin": c.origin,
            "source": c.source,
            "highway": c.highway,
            "road_ref": c.road_ref,
            "river_name": c.river_name,
            "unit_key": c.unit_key,
            "pair": list(c.pair),
            "tag": c.tag,
            "auto_name": c.name,
            "geom_sig": geometry_signature(c.geometry),
            "centerline": mapping(c.centerline),
            "segment_widths_m": list(c.segment_widths_m),
            "length_m": c.length_m,
            "zone_overlap_ha": {cat: round(sum(sg.overlap_ha(c.geometry_m, z) for z in zs), 4) for cat, zs in zones_m.items()},
        }

    return make


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------
def catalogue_entry(c: Candidate) -> Dict[str, Any]:
    """What the tick-list needs about a candidate, kept in ``result_data`` so unticked rows can still be listed (and shown on the map
    when they are ticked: the centreline only, never the strip polygon)."""
    from shapely.geometry import mapping

    line = mapping(c.centerline) if c.centerline is not None else None
    if line:
        line = {"type": line["type"], "coordinates": [[round(x, 6), round(y, 6)] for x, y, *_ in line["coordinates"]]}
    return {"unit_key": c.unit_key, "name": c.name, "source": c.source, "highway": c.highway, "pair": list(c.pair),
            "tag": c.tag, "length_m": c.length_m, "area_ha": c.area_ha, "river_name": c.river_name, "centerline": line}


def _group(sa: Dict[str, Any]) -> str:
    return "road" if sa.get("source") == "road" else ("river" if sa.get("source") == "river" else "boundary")


def summarize(result_data: Dict[str, Any], kind: StripKind = FIRE_KIND) -> Dict[str, Any]:
    """The tick-list, from stored data only (no geometry is computed): one row per candidate, plus the drawn strips.

    ``ticked`` = the candidate is not excluded. ``strip_id`` is the stored strip, if there is one. The totals count the strips that
    exist (their real, possibly edited, length and area), grouped boundary / road / drawn.
    """
    rd = result_data or {}
    excluded = {k for k, v in (rd.get(kind.decisions_key) or {}).items() if v == EXCLUDE}
    strips = [sa for sa in (rd.get("sub_areas") or []) if sa.get("category") == kind.category]
    by_key = {sa["unit_key"]: sa for sa in strips if sa.get("unit_key") and sa.get("origin") == "auto"}
    rows: List[Dict[str, Any]] = []
    known = set()
    for c in rd.get(kind.catalogue_key) or []:
        known.add(c["unit_key"])
        sa = by_key.get(c["unit_key"])
        rows.append({
            "unit_key": c["unit_key"], "name": (sa or {}).get("name") or c["name"], "group": "road" if c["source"] == "road" else ("river" if c["source"] == "river" else "boundary"),
            "highway": c.get("highway", ""), "river_name": c.get("river_name", ""), "ticked": c["unit_key"] not in excluded, "strip_id": (sa or {}).get("id"),
            "length_m": (sa or {}).get("length_m", c["length_m"]), "area_ha": (sa or {}).get("area_hectares", c["area_ha"]),
            "edited": bool(sa and is_edited(sa)),
            "centerline": (sa or {}).get("centerline") or c.get("centerline"), "segment_widths_m": (sa or {}).get("segment_widths_m") or [],
        })
    for key, sa in by_key.items():              # an edited strip whose candidate has gone is still a strip the user has
        if key not in known:
            rows.append({"unit_key": key, "name": sa.get("name"), "group": _group(sa), "river_name": sa.get("river_name", ""),
                         "highway": sa.get("highway", ""), "ticked": True, "strip_id": sa.get("id"), "length_m": sa.get("length_m"),
                         "area_ha": sa.get("area_hectares"), "edited": True,
                         "centerline": sa.get("centerline"), "segment_widths_m": sa.get("segment_widths_m") or []})
    drawn = [{"strip_id": sa.get("id"), "name": sa.get("name"), "length_m": sa.get("length_m"), "area_ha": sa.get("area_hectares"),
              "segment_widths_m": sa.get("segment_widths_m") or [],
              "centerline": sa.get("centerline")}
             for sa in strips if sa.get("origin") != "auto"]
    totals: Dict[str, Dict[str, float]] = {}
    for sa in strips:
        g = "drawn" if sa.get("origin") != "auto" else _group(sa)
        t = totals.setdefault(g, {"count": 0, "km": 0.0, "ha": 0.0})
        t["count"] += 1
        t["km"] += float(sa.get("length_m") or 0) / 1000.0
        t["ha"] += float(sa.get("area_hectares") or 0)
    for t in totals.values():
        t["km"], t["ha"] = round(t["km"], 3), round(t["ha"], 4)
    return {"kind": kind.category, "status": rd.get(kind.status_key) or {"state": "never"}, "rows": rows, "drawn": drawn, "totals": totals,
            "excluded": sorted(excluded)}


def with_decision(result_data: Dict[str, Any], unit_key: str, included: bool, decisions_key: str = DECISIONS_KEY) -> Dict[str, Any]:
    """A copy of ``result_data`` with the decision recorded (unticking = exclude; ticking removes the record)."""
    rd = dict(result_data or {})
    decisions = dict(rd.get(decisions_key) or {})
    if included:
        decisions.pop(unit_key, None)
    else:
        decisions[unit_key] = EXCLUDE
    rd[decisions_key] = decisions
    return rd


# ---------------------------------------------------------------------------
# the database shell
# ---------------------------------------------------------------------------
def _inputs(db: Session, calc: Any, require_units: bool = True) -> Optional[Tuple[BaseGeometry, List[Any], List[Any]]]:
    """(forest, units, sub-areas) exactly as the field book assembles them; None when there is nothing to work on.
    ``require_units=False`` (river banks, drawn lines): a forest with no units still has a boundary to work in."""
    from geoalchemy2.shape import to_shape
    from shapely import wkt
    from shapely.geometry import MultiPolygon, Polygon

    from app.services.fieldbook import extract_subarea_boundaries
    from app.services.fieldbook_sequence import SubAreaIn, UnitIn
    from app.services.sampling import extract_blocks_from_calculation

    if calc.boundary_geom is None:
        return None
    forest = to_shape(calc.boundary_geom)
    units: List[Any] = []
    for number, geom_wkt, name, _area in extract_blocks_from_calculation(db, calc.id) or []:
        try:
            units.append(UnitIn(number, name, wkt.loads(geom_wkt)))
        except Exception:  # noqa: BLE001 -- same tolerance as the field book: skip a unit that cannot be read
            logger.warning("fire_line_service: unit %s has unreadable geometry", name, exc_info=True)
    if not units and require_units:
        return None
    subs: List[Any] = []
    for rings, name, is_excluded, category in extract_subarea_boundaries(db, calc):
        polys = [Polygon(r) for r in rings if len(r) >= 3]
        if polys:
            subs.append(SubAreaIn(name, polys[0] if len(polys) == 1 else MultiPolygon(polys), bool(is_excluded), category or ""))
    return forest, units, subs


def input_signature(
    forest: BaseGeometry, units: Sequence[Any], subs: Sequence[Any], decisions: Dict[str, str], roads: Sequence[Any] = ()
) -> str:
    h = hashlib.sha1()
    h.update(forest.wkb)
    for u in sorted(units, key=lambda u: u.number):
        h.update(f"{u.number}|{u.name}".encode()); h.update(u.polygon.wkb)
    for s in sorted(subs, key=lambda s: (s.name, s.category)):
        h.update(f"{s.name}|{s.category}".encode()); h.update(s.polygon.wkb)
    for r in roads:
        h.update(f"{r.source}|{r.ref}|{r.name}|{r.highway}|{r.width_m}".encode())
        h.update(r.line.wkb)
    h.update(json.dumps(sorted((decisions or {}).items())).encode())
    h.update(f"{FIRE_LINE_SIDE_M}|{RIVER_BANK_SIDE_M}|{STRIP_MIN_LENGTH_M}".encode())
    return h.hexdigest()


def _refuse(db: Session, calc: Any, rd: Dict[str, Any], sig: str, state: str, **why: Any) -> Dict[str, Any]:
    """Create nothing and say why: the stored strips are left exactly as they are."""
    rd = dict(rd)
    rd[SIGNATURE_KEY] = sig  # the same inputs will not be retried until something changes
    rd[STATUS_KEY] = {"state": state, "at": datetime.now(timezone.utc).isoformat(), **why}
    calc.result_data = rd
    flag_modified(calc, "result_data")
    db.commit()
    logger.warning("fire lines not generated for %s: %s %s", calc.id, state, why)
    return {"state": state, **why}


def sync_fire_lines(db: Session, calculation_id: Any, force: bool = False) -> Dict[str, Any]:
    """Bring the stored fire lines in step with the candidates. Commits. Raises nothing the caller's edit should see.

    The slow geometry work runs WITHOUT a lock; the calculation row is locked only for the short read-modify-write at the end,
    on the freshly read ``sub_areas`` and decisions. If the inputs changed while we worked, that change's own commit re-triggers
    a sync, which corrects whatever this one wrote (and a request that wrote ``result_data`` without the lock likewise).
    """
    from app.models.calculation import Calculation
    from app.models.op_data_cache import OpDataCache
    from app.services.workspace_cache import invalidate_layers_cache

    db.info["fire_line_sync"] = True  # our own commit must not schedule another run (fire_line_auto_sync)
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calc is None:
        return {"state": "missing"}
    if getattr(calc, "structure_locked", False):
        return {"state": "locked"}
    inputs = _inputs(db, calc)
    if inputs is None:
        return {"state": "no_inputs"}
    forest, units, subs = inputs

    metric = Metric.for_geometry(forest)
    forest_m = metric.to_m(forest)
    private_m = [metric.to_m(s.polygon) for s in subs if getattr(s, "category", "") == "private_land"]
    from app.services.road_sources import road_reaches

    roads = road_reaches(db, calc, metric.to_wgs(sg.forest_area(forest_m, private_m)))

    rd0 = dict(calc.result_data or {})
    sig = input_signature(forest, units, subs, dict(rd0.get(DECISIONS_KEY) or {}), roads)
    if not force and rd0.get(SIGNATURE_KEY) == sig:
        return {"state": "unchanged"}

    overlap = unit_overlap_m2(units, metric)
    refusal: Optional[Tuple[str, Dict[str, Any]]] = None
    cands: List[Candidate] = []
    cand_report: Dict[str, int] = {}
    if overlap > STRIP_MAX_UNIT_OVERLAP_FRACTION * forest_m.area:
        refusal = ("dirty_units", {"overlap_m2": round(overlap, 1), "forest_m2": round(forest_m.area, 1)})
    else:
        cands, cand_report = candidates(forest, units, subs, roads=roads)
        seen_legs = cand_report["stretches"] + cand_report["unresolved_legs"]
        if seen_legs and cand_report["unresolved_legs"] > STRIP_MAX_UNRESOLVED_FRACTION * seen_legs:
            refusal = ("unresolved_edges", {"unresolved_legs": cand_report["unresolved_legs"], "legs": seen_legs})
        elif cand_report["pair_groups"] and cand_report["pieces"] > STRIP_MAX_PIECES_PER_PAIR * cand_report["pair_groups"]:
            # the neighbours' edges do not line up: the same shared edge would come out as many small pieces (junk)
            refusal = ("fragmented_edges", {"pieces": cand_report["pieces"], "pairs": cand_report["pair_groups"]})

    # ---- short critical section: lock, re-read, write
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).populate_existing().with_for_update().first()
    rd = dict(calc.result_data or {})
    if refusal is not None:
        return _refuse(db, calc, rd, sig, refusal[0], **refusal[1])

    decisions = dict(rd.get(DECISIONS_KEY) or {})
    zones_m: Dict[str, List[BaseGeometry]] = {}
    for sa in real_sub_areas(rd.get("sub_areas")):
        g = _sub_polygon(sa.get("geometry"))
        if g is not None and sa.get("category"):
            zones_m.setdefault(sa["category"], []).append(metric.to_m(g))
    area_wgs = metric.to_wgs(sg.forest_area(forest_m, zones_m.get("private_land", [])))

    new_list, report = plan_sync(rd.get("sub_areas") or [], cands, decisions, area_wgs, entry_factory(metric, units, zones_m))
    changed = any(report[k] for k in ("created", "updated", "dropped", "reclipped"))
    rd[SIGNATURE_KEY] = sig
    rd[STATUS_KEY] = {"state": "ok", "at": datetime.now(timezone.utc).isoformat(), **cand_report, "candidates": len(cands)}
    rd[CATALOGUE_KEY] = [catalogue_entry(c) for c in cands]   # lets the tick-list show unticked rows without recomputing
    if changed:
        rd["sub_areas"] = new_list
        rd["sub_areas_count"] = len(new_list)
    calc.result_data = rd
    flag_modified(calc, "result_data")
    if changed:
        try:
            db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).delete(synchronize_session=False)
        except Exception:  # noqa: BLE001 -- the cache is rebuilt on the next preview; a stale one is the only risk
            logger.warning("fire_line_service: op_data_cache could not be cleared for %s", calc.id, exc_info=True)
    db.commit()
    if changed:
        invalidate_layers_cache(calc.id)
    return {"state": "synced", **report, **cand_report, "candidates": len(cands)}


# ---------------------------------------------------------------------------
# user actions (each commits)
# ---------------------------------------------------------------------------
class FireLineError(ValueError):
    """A request the user can fix; ``code`` is stable for the UI."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


MIN_SIDE_M, MAX_SIDE_M = 0.1, 50.0


def _locked_calc(db: Session, calculation_id: Any) -> Any:
    from app.models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).populate_existing().with_for_update().first()
    if calc is None:
        raise FireLineError("not_found", "Calculation not found")
    return calc


def _commit_rd(db: Session, calc: Any, rd: Dict[str, Any]) -> None:
    from app.models.op_data_cache import OpDataCache
    from app.services.workspace_cache import invalidate_layers_cache

    calc.result_data = rd
    flag_modified(calc, "result_data")
    try:
        db.query(OpDataCache).filter(OpDataCache.calculation_id == calc.id).delete(synchronize_session=False)
    except Exception:  # noqa: BLE001 -- the cache is rebuilt on the next preview
        logger.warning("fire_line_service: op_data_cache could not be cleared for %s", calc.id, exc_info=True)
    db.commit()
    invalidate_layers_cache(calc.id)


def run_sync(kind: StripKind, db: Session, calculation_id: Any, force: bool = False) -> Dict[str, Any]:
    """The sync of one kind (the river bank's lives in its own module and is imported on demand)."""
    if kind.category == RIVER_BANK:
        from app.services.river_bank_service import sync_river_banks

        return sync_river_banks(db, calculation_id, force=force)
    return sync_fire_lines(db, calculation_id, force=force)


def apply_decisions(db: Session, calculation_id: Any, changes: Sequence[Dict[str, Any]], kind: StripKind = FIRE_KIND) -> Dict[str, Any]:
    """Tick / untick candidates. Unticking removes the strip and remembers it; ticking removes the memory and the sync creates it.

    ``changes`` = ``[{"unit_key": ..., "included": bool}]``. Idempotent: the same list twice leaves the same state.
    """
    db.info["fire_line_sync"] = True  # we sync inline below; the background hook must not run a second time
    calc = _locked_calc(db, calculation_id)
    rd = dict(calc.result_data or {})
    sub_areas = list(rd.get("sub_areas") or [])
    include_any = False
    for ch in changes:
        key = ch.get("unit_key")
        if not key:
            raise FireLineError("bad_request", "unit_key is required")
        included = bool(ch.get("included"))
        rd = with_decision(rd, key, included, kind.decisions_key)
        if included:
            include_any = True
        else:
            sub_areas = [sa for sa in sub_areas if not (sa.get("category") == kind.category and sa.get("origin") == "auto" and sa.get("unit_key") == key)]
    rd["sub_areas"] = sub_areas
    rd["sub_areas_count"] = len(sub_areas)
    _commit_rd(db, calc, rd)
    result: Dict[str, Any] = {"state": "decided"}
    if include_any:
        result = run_sync(kind, db, calculation_id, force=True)
    return result


def _drawn_inputs(db: Session, calc: Any, centerline: Dict[str, Any], widths: Any):
    inputs = _inputs(db, calc, require_units=False)
    if inputs is None:
        raise FireLineError("no_forest", "The forest has no boundary or units yet")
    forest, units, subs = inputs
    try:
        line = shape(centerline)
    except Exception as exc:  # noqa: BLE001 -- the caller's geometry; reported, not raised as a 500
        raise FireLineError("bad_geometry", "The line could not be read") from exc
    if line.geom_type != "LineString" or len(line.coords) < 2 or line.length == 0:
        raise FireLineError("bad_geometry", "Draw a line with at least two points")
    metric = Metric.for_geometry(forest)
    line_m = metric.to_m(line)
    n_seg = len(line_m.coords) - 1
    if isinstance(widths, (int, float)):
        sides = [float(widths)] * n_seg
    else:
        sides = [float(w) for w in (widths or [])]
        if len(sides) != n_seg:
            raise FireLineError("bad_widths", f"{n_seg} segments need {n_seg} widths, got {len(sides)}")
    if any(not (MIN_SIDE_M <= w <= MAX_SIDE_M) for w in sides):
        raise FireLineError("bad_widths", f"Each width must be between {MIN_SIDE_M} and {MAX_SIDE_M} metres")
    private_m = [metric.to_m(sa.polygon) for sa in subs if getattr(sa, "category", "") == "private_land"]
    area_m = sg.forest_area(metric.to_m(forest), private_m)
    return forest, units, subs, metric, line_m, sides, area_m


def default_drawn_name(strip_m: BaseGeometry, units: Sequence[Any], metric: Metric, fallback: str = "Fire line") -> str:
    """The units a drawn strip runs along, like a generated one: 'SC1-SC2'; the kind's name when it touches none."""
    hit = []
    for u in units:
        share = strip_m.intersection(metric.to_m(u.polygon)).area
        if strip_m.area and share / strip_m.area >= 0.2:
            hit.append(u.name)
    if not hit:
        return fallback
    hit = sorted(hit, key=sg.natural_key)
    return "-".join(hit[:3]) + ("-\u2026" if len(hit) > 3 else "")


def preview_drawn(db: Session, calculation_id: Any, centerline: Dict[str, Any], widths: Any, kind: StripKind = FIRE_KIND) -> Dict[str, Any]:
    """What a drawn fire line would be. Writes nothing."""
    from app.models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calc is None:
        raise FireLineError("not_found", "Calculation not found")
    forest, units, subs, metric, line_m, sides, area_m = _drawn_inputs(db, calc, centerline, widths)
    strip = sg.clip_to_area(sg.strip_polygon(line_m, sides), area_m)
    parts = _parts_along(line_m, strip)
    warnings = []
    if not parts:
        raise FireLineError("outside_forest", "The line lies outside the forest area")
    if strip.area < sg.strip_polygon(line_m, sides).area * 0.999:
        warnings.append("clipped_to_forest")
    if len(parts) > 1:
        warnings.append("several_parts")
    zones: Dict[str, List[BaseGeometry]] = {}
    for sa in real_sub_areas((calc.result_data or {}).get("sub_areas")):
        g = _sub_polygon(sa.get("geometry"))
        if g is not None and sa.get("category"):
            zones.setdefault(sa["category"], []).append(metric.to_m(g))
    return {
        "name": default_drawn_name(strip, units, metric, kind.default_name),
        "geometry": mapping(metric.to_wgs(unary_union_safe(parts))),
        "parts": len(parts),
        "length_m": round(sg.length_m(line_m), 2),
        "area_ha": round(sum(sg.area_ha(p) for p in parts), 4),
        "segment_widths_m": sides,
        "zone_overlap_ha": {cat: round(sum(sg.overlap_ha(strip, z) for z in zs), 4) for cat, zs in zones.items()},
        "warnings": warnings,
    }


def unary_union_safe(parts: Sequence[BaseGeometry]) -> BaseGeometry:
    from shapely.ops import unary_union

    return unary_union(list(parts))


def create_drawn(db: Session, calculation_id: Any, centerline: Dict[str, Any], widths: Any, name: Optional[str] = None,
                 client_id: Optional[str] = None, kind: StripKind = FIRE_KIND) -> Dict[str, Any]:
    """Create a drawn fire line (one sub-area entry per part). Replaying the same ``client_id`` returns the first result."""
    db.info["fire_line_sync"] = True
    calc = _locked_calc(db, calculation_id)
    rd = dict(calc.result_data or {})
    if client_id:
        made = [sa for sa in rd.get("sub_areas") or [] if str(sa.get("client_id")) == str(client_id)]
        if made:
            return {"created": [sa["id"] for sa in made], "replayed": True}
    forest, units, subs, metric, line_m, sides, area_m = _drawn_inputs(db, calc, centerline, widths)
    strip = sg.clip_to_area(sg.strip_polygon(line_m, sides), area_m)
    parts = _parts_along(line_m, strip)
    if not parts:
        raise FireLineError("outside_forest", "The line lies outside the forest area")
    zones: Dict[str, List[BaseGeometry]] = {}
    for sa in real_sub_areas(rd.get("sub_areas")):
        g = _sub_polygon(sa.get("geometry"))
        if g is not None and sa.get("category"):
            zones.setdefault(sa["category"], []).append(metric.to_m(g))
    make = entry_factory(metric, units, zones, category=kind.category)
    base = (name or "").strip() or default_drawn_name(strip, units, metric, kind.default_name)
    created = []
    new_entries = []
    for i, part in enumerate(parts):
        cand = Candidate(
            unit_key="", name=base if i == 0 else f"{base} \u00b7{i + 1}", pair=(), tag="", centerline=metric.to_wgs(line_m),
            geometry=metric.to_wgs(part), geometry_m=part, length_m=round(sg.length_m(line_m), 2), area_ha=round(sg.area_ha(part), 4),
            segment_widths_m=sides, source="drawn", origin="drawn",
        )
        entry = make(cand)
        entry["unit_key"] = None
        entry["auto_name"] = None
        if client_id:
            entry["client_id"] = str(client_id)
        new_entries.append(entry)
        created.append(entry["id"])
    sub_areas = list(rd.get("sub_areas") or []) + new_entries
    rd["sub_areas"] = sub_areas
    rd["sub_areas_count"] = len(sub_areas)
    _commit_rd(db, calc, rd)
    return {"created": created, "replayed": False, "name": base, "area_ha": round(sum(sg.area_ha(p) for p in parts), 4)}


def update_widths(db: Session, calculation_id: Any, strip_id: str, widths: Any, kind: StripKind = FIRE_KIND) -> Dict[str, Any]:
    """Re-widen a fire line from its stored centerline. The strip becomes 'edited', so a regenerate leaves it alone."""
    db.info["fire_line_sync"] = True
    calc = _locked_calc(db, calculation_id)
    rd = dict(calc.result_data or {})
    sub_areas = list(rd.get("sub_areas") or [])
    idx = next((i for i, sa in enumerate(sub_areas) if str(sa.get("id")) == str(strip_id) and sa.get("category") == kind.category), None)
    if idx is None:
        raise FireLineError("not_found", f"{kind.default_name} not found")
    sa = dict(sub_areas[idx])
    if not sa.get("centerline"):
        raise FireLineError("no_centerline", "This fire line has no stored centerline to widen")
    forest, units, subs, metric, line_m, sides, area_m = _drawn_inputs(db, calc, sa["centerline"], widths)
    strip = sg.clip_to_area(sg.strip_polygon(line_m, sides), area_m)
    parts = _parts_along(line_m, strip)
    if not parts:
        raise FireLineError("outside_forest", "The line lies outside the forest area")
    part = parts[0]
    from app.utils.geometry_utils import compute_geometry_properties

    geom = metric.to_wgs(part)
    sa.update({
        "geometry": mapping(geom), "area_sqm": round(part.area, 2), "area_hectares": round(sg.area_ha(part), 4),
        "segment_widths_m": sides, "edited": True, **compute_geometry_properties(geom),
    })
    sub_areas[idx] = json.loads(json.dumps(sa, default=str))
    rd["sub_areas"] = sub_areas
    _commit_rd(db, calc, rd)
    return {"id": sa["id"], "area_ha": sa["area_hectares"], "segment_widths_m": sides, "parts_dropped": len(parts) - 1}


# ---------------------------------------------------------------------------
# the yearly plan (FL-6)
# ---------------------------------------------------------------------------
def plan_options(db: Session) -> List[Dict[str, Any]]:
    """The master activities a fire line can be planned with (``map_kind = fire_line``): id, name, unit."""
    from app.services import sub_area_plan

    return sub_area_plan.suggested_activities(db, FIRE_LINE)


def plan_fire_lines(
    db: Session, calculation_id: Any, potential_activity_id: int, strip_ids: Optional[Sequence[str]] = None,
    include_roads: bool = False,
) -> Dict[str, Any]:
    """Give each fire line a yearly-plan line for one activity, starting at the strip's own length (km) or area (ha).

    Existing roads are skipped unless ``include_roads`` (they exist; only maintenance would be planned). A strip that already has
    the line keeps it (and its numbers); one that sits in no unit is reported, not guessed. Commits.
    """
    from app.models.calculation import Calculation
    from app.services import sub_area_plan

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    if calc is None:
        raise FireLineError("not_found", "Calculation not found")
    wanted_ids = {str(i) for i in strip_ids} if strip_ids else None
    strips = [sa for sa in (calc.result_data or {}).get("sub_areas", []) or [] if sa.get("category") == FIRE_LINE]
    report: Dict[str, Any] = {"created": 0, "existing": 0, "skipped_roads": 0, "no_unit": [], "strips": 0}
    for sa in strips:
        if wanted_ids is not None and str(sa.get("id")) not in wanted_ids:
            continue
        if sa.get("source") == "road" and not include_roads:
            report["skipped_roads"] += 1
            continue
        try:
            made = sub_area_plan.create_plan_lines(db, calc, sa["id"], [potential_activity_id])
        except LookupError as exc:
            db.rollback()
            raise FireLineError("not_found", "That activity does not exist" if str(exc) == "activity_not_found" else "Fire line not found") from exc
        except ValueError:
            report["no_unit"].append(sa.get("name"))
            continue
        report["strips"] += 1
        for m in made:
            report["created" if m["created"] else "existing"] += 1
    db.commit()
    return report
