"""Field book point sequence: outer ring first, then the internal boundaries -- each edge once.

Why this module exists
----------------------
The first field book walked every block / compartment outline on its own and merged the points that
happened to coincide. That cannot say which points are on the forest's OUTER boundary, cannot give a
walkable route, and walks every shared edge twice (each unit measures its 50 m from its own corner, so
the two sets of interpolated points never coincide).

This builds the sequence from the shared LINE WORK instead:

1. OUTER points -- the forest boundary ring(s), walked clockwise from the north-west-most vertex, numbered
   ``O1, O2, ...``. Every vertex of a unit that lies on the ring is inserted, so a point where a unit
   meets the boundary is always a point of the book.
2. INTERNAL points -- everything inside: the unit and sub-area outlines with the outer ring removed, split at
   junctions into chains. Each chain is generated once, starting from a point that already exists, and
   chains are visited depth-first so the numbering follows a route a person can walk. Numbered ``I1, I2, ...``.
3. Every point records the units it separates (``adjacent_units``), so an outer point reads
   ``outer: ब्लक १, ब्लक २`` and a shared internal point ``internal (junction of 3): A, B, C``.

LINES. Points are grouped into named lines so nothing has to guess which points to join:

* ``O-1, O-2, ...`` -- an outer ring. CLOSED: the last point connects back to the first, so it draws as a polygon outline.
* ``I-1, I-2, ...`` -- an internal edge from one junction (or outer point) to the next. OPEN: it never closes and never
  connects to another edge, even though the numbering ``I5, I6`` runs on from one edge to the next.
* ``L-1, ...`` -- the one internal exception: a free-standing loop that touches nothing (a sub-area inside a unit). It
  has no ends, so it is closed, like the polygon it is.

A junction point belongs to every line that meets there (``lines`` = ``{line_id: order}``); ``line_id`` is the line that
first reached it. ``FieldbookSequence.lines`` lists each line with its ordered point labels.

Spacing is measured from the previous point along each straight leg (the field rule: a 50 m tape from
corner to corner), exactly as the original generator did.

Pure geometry: no database. ``services/fieldbook.generate_fieldbook_points`` feeds it and persists the result.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import shapely
from shapely.geometry import LineString, LinearRing, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import linemerge
from shapely.strtree import STRtree

from app.services.fieldbook import calculate_azimuth, calculate_distance

GRID = 1e-7    # coordinate grid (~1 cm): noise below this is the same point
TOL = 2e-7     # "on this line" tolerance (~2 cm)
SNAP = 1e-6    # chain ends within this of an existing point are that point (~10 cm)
WELD = 3e-7    # neighbouring outlines whose vertices are this close are the same line (~3 cm)


@dataclass
class UnitIn:
    number: int
    name: str
    polygon: Any


@dataclass
class SubAreaIn:
    name: str
    polygon: Any
    is_excluded: bool = False
    category: str = ""


@dataclass
class FieldbookSequence:
    points: List[Dict[str, Any]]
    perimeter_m: float
    # [{"id": "O-1", "kind": "outer"|"internal", "closed": bool, "labels": ["O1", "O2", ...]}]
    lines: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _key(x: float, y: float) -> Tuple[float, float]:
    return (round(x, 7), round(y, 7))


def _snap(geom):
    """Put a geometry on the coordinate grid; None when nothing usable is left."""
    if geom is None or geom.is_empty:
        return None
    g = shapely.set_precision(geom, GRID)
    if g.is_empty:
        return None
    if not g.is_valid:
        g = g.buffer(0)
        if g.is_empty:
            return None
    return g


def _polys(geom) -> List[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [p for g in geom.geoms for p in _polys(g)]
    return []


def _lines_of(geom) -> List[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        return [ln for g in geom.geoms for ln in _lines_of(g)]
    return []


def _nw_score(x: float, y: float, minx: float, maxy: float, kx: float) -> float:
    """Distance from the north-west corner of a bounding box (x scaled by cos(lat) so it is ~metric)."""
    return math.hypot((x - minx) * kx, y - maxy)


def _nw_index(coords: Sequence[Tuple[float, float]]) -> int:
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    minx, maxy = min(xs), max(ys)
    kx = math.cos(math.radians(sum(ys) / len(ys)))
    return min(range(len(coords)), key=lambda i: (round(_nw_score(xs[i], ys[i], minx, maxy, kx), 9), xs[i], -ys[i]))


def _interp_between(a: Tuple[float, float], b: Tuple[float, float], spacing: float) -> List[Tuple[float, float]]:
    """Points every ``spacing`` metres from ``a`` toward ``b`` (the original rule: only on a leg longer than
    ``spacing``, and never one that lands on ``b`` itself)."""
    if spacing <= 0:
        return []
    edge = calculate_distance(a[0], a[1], b[0], b[1])
    if edge <= spacing:
        return []
    out = []
    for j in range(1, int(edge / spacing) + 1):
        f = (j * spacing) / edge
        if f < 1.0:
            # Linear in lon/lat, NOT a great circle: the stored edge is a straight line in degrees, and a
            # great-circle point drifts off it (centimetres on 1 km, decimetres on 5 km), which would put a
            # point outside the unit's outline and lose the units it separates.
            x = a[0] + f * (b[0] - a[0])
            y = a[1] + f * (b[1] - a[1])
            out.append((round(x, 7), round(y, 7)))
    return out


def _weld(geoms: List[Any]) -> List[Any]:
    """Make neighbouring outlines agree on their vertices.

    Rounding to the grid absorbs noise only when both sides land in the same grid cell; two copies of one shared
    edge that straddle a rounding step stay a centimetre apart and come out as a doubled edge. So each geometry
    snaps onto the vertices of the ones already placed (first = the forest boundary), within ``WELD``, and the
    result goes back on the grid. A geometry that would turn invalid is left as it was.
    """
    placed: List[Any] = []
    out: List[Any] = []
    for g in geoms:
        if placed:
            near = STRtree(placed).query(g, predicate="dwithin", distance=WELD).tolist()
            if near:
                ref = shapely.multipoints(np.unique(np.vstack([shapely.get_coordinates(placed[i]) for i in near]), axis=0))
                snapped = _snap(shapely.snap(g, ref, WELD))
                if snapped is not None and snapped.is_valid and not snapped.is_empty:
                    g = snapped
        placed.append(g)
        out.append(g)
    return out


# ---------------------------------------------------------------------------
# outer ring
# ---------------------------------------------------------------------------

def _outer_rings(forest) -> List[List[Tuple[float, float]]]:
    """Forest boundary rings, ready to walk: exteriors clockwise, holes counter-clockwise (so the forest is
    always on the walker's right), each rotated to start at its north-west-most vertex. Exteriors first."""
    exteriors: List[List[Tuple[float, float]]] = []
    holes: List[List[Tuple[float, float]]] = []
    for part in _polys(forest):
        part = orient(part, sign=-1.0)
        exteriors.append([(float(x), float(y)) for x, y in list(part.exterior.coords)[:-1]])
        for ring in part.interiors:
            holes.append([(float(x), float(y)) for x, y in list(ring.coords)[:-1]])

    def order(rings):
        def score(r):
            xs = [c[0] for c in r]
            ys = [c[1] for c in r]
            i = _nw_index(r)
            return (round(-max(ys), 7), round(min(xs), 7), r[i])
        return sorted(rings, key=score)

    return order(exteriors) + order(holes)


def _insert_nodes(ring: List[Tuple[float, float]], nodes: np.ndarray) -> List[Tuple[float, float]]:
    """Add every node that lies ON this ring (a unit vertex, a junction) as a ring vertex, in route order."""
    line = LineString(ring + [ring[0]])
    cum = [0.0]
    for i in range(len(ring)):
        a, b = ring[i], ring[(i + 1) % len(ring)]
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    entries = [(cum[i], ring[i]) for i in range(len(ring))]
    have = {_key(*c) for c in ring}
    if nodes.size:
        near = nodes[shapely.distance(line, shapely.points(nodes)) < TOL]
        for x, y in near:
            k = _key(float(x), float(y))
            if k in have:
                continue
            have.add(k)
            entries.append((line.project(Point(float(x), float(y))), (float(x), float(y))))
    entries.sort(key=lambda e: e[0])
    pts = [e[1] for e in entries]
    start = _nw_index(pts)
    return pts[start:] + pts[:start]


# ---------------------------------------------------------------------------
# the sequence
# ---------------------------------------------------------------------------

def build_sequence(
    forest,
    units: Sequence[UnitIn],
    subareas: Sequence[SubAreaIn],
    spacing: float = 50.0,
) -> FieldbookSequence:
    """Build the ordered field book points. ``forest`` is the forest boundary polygon (WGS84);
    ``units`` are the leaf blocks / compartments; ``subareas`` excluded / special-use pockets."""
    unit_polys = [(u, _snap(u.polygon)) for u in units]
    unit_polys = [(u, g) for u, g in unit_polys if g is not None and _polys(g)]
    sub_polys = [(s, _snap(s.polygon)) for s in subareas]
    sub_polys = [(s, g) for s, g in sub_polys if g is not None and _polys(g)]

    forest_g = _snap(forest)
    if forest_g is None:
        forest_g = _snap(shapely.unary_union([g for _, g in unit_polys])) if unit_polys else None
    if forest_g is None:
        return FieldbookSequence([], 0.0)

    # ---- weld neighbouring outlines together (forest first, then units, then sub-areas)
    welded = _weld([forest_g] + [g for _, g in unit_polys] + [g for _, g in sub_polys])
    forest_g = welded[0]
    unit_polys = [(u, welded[1 + i]) for i, (u, _) in enumerate(unit_polys)]
    sub_polys = [(sa, welded[1 + len(unit_polys) + i]) for i, (sa, _) in enumerate(sub_polys)]

    # ---- every vertex of every unit / sub-area: candidates to become points on the outer ring
    vertex_list: List[Tuple[float, float]] = []
    for _, g in unit_polys + sub_polys:
        for poly in _polys(g):
            vertex_list.extend((float(x), float(y)) for x, y in poly.exterior.coords)
            for hole in poly.interiors:
                vertex_list.extend((float(x), float(y)) for x, y in hole.coords)
    nodes = np.array(sorted({_key(x, y) for x, y in vertex_list}), dtype=float).reshape(-1, 2)

    registry: Dict[Tuple[float, float], Dict[str, Any]] = {}
    outer: List[Dict[str, Any]] = []
    internal: List[Dict[str, Any]] = []
    perimeter = 0.0

    def new_point(x, y, ptype, cls, bucket):
        rec = {"x": x, "y": y, "key": _key(x, y), "point_type": ptype, "boundary_class": cls, "next": None}
        registry[rec["key"]] = rec
        bucket.append(rec)
        return rec

    line_defs: List[Dict[str, Any]] = []   # every line, in the order it is walked

    # ---- 1. outer ring(s)
    for ring_no, ring in enumerate(_outer_rings(forest_g), start=1):
        ring = _insert_nodes(ring, nodes)
        members: List[Dict[str, Any]] = []
        n = len(ring)
        for i in range(n):
            a, b = ring[i], ring[(i + 1) % n]
            perimeter += calculate_distance(a[0], a[1], b[0], b[1])
            if _key(*a) not in registry:
                members.append(new_point(a[0], a[1], "vertex", "outer", outer))
            else:  # a ring touching itself / an earlier ring at one point: keep the first
                members.append(registry[_key(*a)])
            for x, y in _interp_between(a, b, spacing):
                if _key(x, y) not in registry:
                    members.append(new_point(x, y, "interpolated", "outer", outer))
        for i, rec in enumerate(members):
            rec["next"] = members[(i + 1) % len(members)]["key"]
        ring_keys = [m["key"] for i, m in enumerate(members) if i == 0 or m["key"] != members[i - 1]["key"]]
        line_defs.append({"id": f"O-{ring_no}", "kind": "outer", "closed": True, "keys": ring_keys})

    outer_rank = {rec["key"]: i for i, rec in enumerate(outer)}

    # ---- 2. internal chains: unit + sub-area outlines minus the outer ring, split at junctions
    chains = _internal_chains(unit_polys, sub_polys, forest_g, outer)

    minx, miny, maxx, maxy = forest_g.bounds
    kx = math.cos(math.radians((miny + maxy) / 2))

    def chain_nw(ch):
        x, y = ch["coords"][0]
        return _nw_score(x, y, minx, maxy, kx)

    def rank_of(key):
        return outer_rank.get(key, 10 ** 9)

    remaining = list(range(len(chains)))
    current: Optional[Tuple[float, float]] = None
    open_no = loop_no = 0
    while remaining:
        # keep walking from where the last chain ended; otherwise start from the lowest-numbered outer point
        # that still has an unwalked chain (O1 first), falling back to the north-west-most free chain
        here = [i for i in remaining if current in (chains[i]["a"], chains[i]["b"])] if current else []
        if here:
            i = min(here, key=lambda i: (rank_of(chains[i]["a"] if chains[i]["b"] == current else chains[i]["b"]), i))
        else:
            i = min(remaining, key=lambda i: (min(rank_of(chains[i]["a"]), rank_of(chains[i]["b"])), chain_nw(chains[i]), i))
        remaining.remove(i)
        ch = chains[i]
        coords = list(ch["coords"])

        if ch["closed"] and ch["free_ring"]:
            start = _nw_index(coords[:-1])
            ring_c = coords[:-1]
            ring_c = ring_c[start:] + ring_c[:start]
            if LinearRing(ring_c).is_ccw:
                ring_c = [ring_c[0]] + ring_c[:0:-1]
            coords = ring_c + [ring_c[0]]
        else:
            start_key = current if current in (ch["a"], ch["b"]) else None
            if start_key is None:
                a_r, b_r = rank_of(ch["a"]), rank_of(ch["b"])
                if a_r != b_r:
                    start_key = ch["a"] if a_r < b_r else ch["b"]
                else:
                    start_key = ch["a"]
            if _key(*coords[0]) != start_key:
                coords.reverse()

        is_loop = bool(ch["closed"] and ch["free_ring"])
        if is_loop:
            loop_no += 1
            line_id = f"L-{loop_no}"
        else:
            open_no += 1
            line_id = f"I-{open_no}"
        line_keys: List[Tuple[float, float]] = []

        def touch(rec):
            # the points of this line in order; a loop's last vertex IS its first, so it is not listed twice
            if line_keys and line_keys[-1] == rec["key"]:
                return
            if is_loop and line_keys and rec["key"] == line_keys[0]:
                return
            line_keys.append(rec["key"])

        prev: Optional[Dict[str, Any]] = None
        first = _key(*coords[0])
        prev = registry.get(first) or new_point(coords[0][0], coords[0][1], "vertex", "internal", internal)
        touch(prev)

        def link(p, q):
            if p["boundary_class"] == "outer" or p is q or p["next"] is not None:
                return
            p["next"] = q["key"]

        for k in range(len(coords) - 1):
            a, b = coords[k], coords[k + 1]
            for x, y in _interp_between(a, b, spacing):
                rec = registry.get(_key(x, y)) or new_point(x, y, "interpolated", "internal", internal)
                link(prev, rec)
                touch(rec)
                prev = rec
            rec = registry.get(_key(*b)) or new_point(b[0], b[1], "vertex", "internal", internal)
            link(prev, rec)
            touch(rec)
            prev = rec
        current = _key(*coords[-1])
        line_defs.append({"id": line_id, "kind": "internal", "closed": is_loop, "keys": line_keys})

    # ---- 3. attributes: which units / sub-areas each point separates, junction degree, remark text
    unit_trees = STRtree([g.boundary for _, g in unit_polys]) if unit_polys else None
    unit_area_tree = STRtree([g for _, g in unit_polys]) if unit_polys else None
    sub_tree = STRtree([g.boundary for _, g in sub_polys]) if sub_polys else None
    unit_list = [u for u, _ in unit_polys]
    sub_list = [s for s, _ in sub_polys]

    ordered = outer + internal
    counters = {"outer": 0, "internal": 0}
    by_key = {}
    for number, rec in enumerate(ordered, start=1):
        counters[rec["boundary_class"]] += 1
        rec["point_number"] = number
        rec["point_label"] = ("O" if rec["boundary_class"] == "outer" else "I") + str(counters[rec["boundary_class"]])
        by_key[rec["key"]] = rec

    # which line(s) each point is on, and where in each: a junction is on every line that meets there
    for rec in ordered:
        rec["lines"] = {}
        rec["line_id"] = None
    result_lines: List[Dict[str, Any]] = []
    for ld in line_defs:
        for order, key in enumerate(ld["keys"], start=1):
            rec = by_key[key]
            rec["lines"][ld["id"]] = order
            if rec["line_id"] is None:
                rec["line_id"] = ld["id"]
        result_lines.append({
            "id": ld["id"], "kind": ld["kind"], "closed": ld["closed"],
            "labels": [by_key[k]["point_label"] for k in ld["keys"]],
        })

    for rec in ordered:
        pt = Point(rec["x"], rec["y"])
        touching = []
        if unit_trees is not None:
            touching = sorted(unit_trees.query(pt, predicate="dwithin", distance=TOL).tolist())
        touching_units = [unit_list[i] for i in touching]
        touching_units.sort(key=lambda u: u.number)

        related = list(touching_units)
        if not related and unit_area_tree is not None:  # inside a unit, on no unit's outline (a sub-area island)
            inside = sorted(unit_area_tree.query(pt, predicate="within").tolist())
            related = sorted((unit_list[i] for i in inside), key=lambda u: u.number)

        subs = []
        if sub_tree is not None:
            subs = sorted(sub_tree.query(pt, predicate="dwithin", distance=TOL).tolist())
        sub_hits = [sub_list[i] for i in subs]

        names = [u.name for u in related]
        rec["adjacent_units"] = names
        rec["block_name"] = ", ".join(u.name for u in touching_units) or None
        rec["block_number"] = touching_units[0].number if touching_units else None
        rec["sub_area_name"] = ", ".join(dict.fromkeys(s.name for s in sub_hits)) or None
        cats = [s.category for s in sub_hits if s.category]
        rec["sub_area_category"] = ", ".join(dict.fromkeys(cats)) or None
        rec["is_excluded"] = (True if any(s.is_excluded for s in sub_hits) else False) if sub_hits else None
        degree = len(names)
        rec["junction_degree"] = degree
        # outer: the boundary plus >=2 units meeting there; internal: three or more regions meeting
        rec["is_junction"] = degree >= 2 if rec["boundary_class"] == "outer" else degree >= 3
        rec["remarks"] = remark_text(rec["boundary_class"], names, degree, rec["sub_area_name"])

    for rec in ordered:
        nxt = by_key.get(rec["next"]) if rec["next"] else None
        if nxt is not None:
            rec["azimuth_to_next"] = calculate_azimuth(rec["x"], rec["y"], nxt["x"], nxt["y"])
            rec["distance_to_next"] = calculate_distance(rec["x"], rec["y"], nxt["x"], nxt["y"])
            rec["next_point_label"] = nxt["point_label"]
        else:
            rec["azimuth_to_next"] = rec["distance_to_next"] = rec["next_point_label"] = None

    return FieldbookSequence(ordered, perimeter, result_lines)


def remark_text(cls: str, names: List[str], degree: int, sub_area: Optional[str]) -> str:
    if cls == "outer":
        text = "outer: " + ", ".join(names) if names else "outer"
    elif degree >= 3:
        text = f"internal (junction of {degree}): " + ", ".join(names)
    elif names:
        text = "internal: " + ", ".join(names)
    else:
        text = "internal"
    if sub_area:
        text += f"; sub-area: {sub_area}"
    return text


# ---------------------------------------------------------------------------
# internal chains
# ---------------------------------------------------------------------------

def _internal_chains(unit_polys, sub_polys, forest_g, outer: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Unit and sub-area outlines with the forest's outer ring cut away, merged into chains between junctions.

    Each chain: ``coords`` (route order not yet decided), ``a`` / ``b`` the canonical end points (snapped onto an
    existing outer point when within ``SNAP``), ``closed`` and ``free_ring`` (a closed loop touching nothing).
    """
    lines = [g.boundary for _, g in unit_polys + sub_polys]
    if not lines:
        return []
    outline = shapely.unary_union(lines)                       # noded, shared edges dissolved to ONE copy
    ring_line = shapely.unary_union([p.boundary for p in _polys(forest_g)])
    cut = outline.difference(ring_line.buffer(TOL))
    pieces = [ln for ln in _lines_of(cut) if ln.length > 2 * TOL]
    if not pieces:
        return []
    merged = [ln for ln in _lines_of(linemerge(pieces)) if ln.length > 2 * TOL]

    outer_xy = np.array([(r["x"], r["y"]) for r in outer], dtype=float).reshape(-1, 2)
    canon: List[Tuple[float, float]] = []

    def canon_end(x: float, y: float) -> Tuple[float, float]:
        if outer_xy.size:
            d = np.hypot(outer_xy[:, 0] - x, outer_xy[:, 1] - y)
            j = int(d.argmin())
            if d[j] < SNAP:
                return (float(outer_xy[j, 0]), float(outer_xy[j, 1]))
        for cx, cy in canon:
            if math.hypot(cx - x, cy - y) < SNAP:
                return (cx, cy)
        canon.append((x, y))
        return (x, y)

    chains = []
    for ln in merged:
        coords = [(float(x), float(y)) for x, y in ln.coords]
        s, e = canon_end(*coords[0]), canon_end(*coords[-1])
        coords[0], coords[-1] = s, e
        chains.append({"coords": coords, "a": _key(*s), "b": _key(*e), "closed": _key(*s) == _key(*e)})

    # a closed loop that meets nothing else (a sub-area island) is walked from its own north-west corner
    incidence: Dict[Tuple[float, float], int] = {}
    for ch in chains:
        for k in (ch["a"], ch["b"]):
            incidence[k] = incidence.get(k, 0) + 1
    on_outer = {_key(r["x"], r["y"]) for r in outer}
    for ch in chains:
        ch["free_ring"] = bool(ch["closed"] and incidence.get(ch["a"], 0) <= 2 and ch["a"] not in on_outer)
    return chains
