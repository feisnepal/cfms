"""Strip geometry: the pure maths behind the fire line (and, later, the river bank) -- FIRELINE_RIVERBANK_PLAN.md, FL-3.

No database, no request: shapely and pyproj only. Everything works in a metric CRS (the UTM zone of the forest, from
``core/geo.calculate_utm_epsg``); WGS84 comes in and goes out through :class:`Metric`. The widths are PER SIDE.

* :func:`strip_polygon` -- a centerline with a width for every segment -> the strip polygon.
* :func:`clip_to_area` / :func:`forest_area` -- clip to the forest area (boundary minus private land).
* :func:`trim_same_kind` -- pieces of one kind are trimmed against the earlier ones, so their areas add up (no double count).
* :func:`explode` -- single-part polygons (one sub-area entry = one polygon).
* :func:`build_pieces` -- the field book's stretches -> the fire-line centerlines: joined where one pair continues end to end,
  a stretch shorter than the minimum merged into the longer neighbour on the same field-book line or removed.
* :func:`natural_key`, :func:`piece_names` -- names (``SC1-SC2``, ``SC1-SC2 (2)``, ``SC1-बाहिरी सिमाना``).
* :func:`area_ha`, :func:`length_m`, :func:`combined_area_ha`, :func:`overlap_ha` -- the figures.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple, Union

from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, transform, unary_union

from app.core.constants import STRIP_MIN_LENGTH_M
from app.core.geo import calculate_utm_epsg

#: how the outer boundary reads in a name (owner, 2026-10-19)
OUTER_LABEL = "बाहिरी सिमाना"

#: an endpoint closer than this (metres) is the same node
NODE_TOL_M = 0.01
#: a clipped/trimmed polygon smaller than this (square metres) is noise, not a strip
MIN_AREA_SQM = 0.01

Widths = Union[float, Sequence[float]]


# ---------------------------------------------------------------------------
# metric CRS
# ---------------------------------------------------------------------------
class Metric:
    """WGS84 <-> the forest's UTM zone. Build one per forest and reuse it."""

    def __init__(self, epsg: int):
        self.epsg = epsg
        self._fwd = Transformer.from_crs(4326, epsg, always_xy=True)
        self._back = Transformer.from_crs(epsg, 4326, always_xy=True)

    @classmethod
    def for_geometry(cls, geom_wgs: BaseGeometry) -> "Metric":
        c = geom_wgs.centroid
        return cls(calculate_utm_epsg(c.x, c.y))

    def to_m(self, geom_wgs: BaseGeometry) -> BaseGeometry:
        return transform(self._fwd.transform, geom_wgs)

    def to_wgs(self, geom_m: BaseGeometry) -> BaseGeometry:
        return transform(self._back.transform, geom_m)


# ---------------------------------------------------------------------------
# figures (metric geometries in, metric units out)
# ---------------------------------------------------------------------------
def area_ha(geom_m: Optional[BaseGeometry]) -> float:
    return 0.0 if geom_m is None or geom_m.is_empty else geom_m.area / 10_000.0


def length_m(line_m: Optional[BaseGeometry]) -> float:
    return 0.0 if line_m is None or line_m.is_empty else float(line_m.length)


def combined_area_ha(*groups: Iterable[BaseGeometry]) -> float:
    """Area of the union of every geometry in every group - where two kinds overlap, the overlap counts once."""
    geoms = [g for group in groups for g in group if g is not None and not g.is_empty]
    return area_ha(unary_union(geoms)) if geoms else 0.0


def overlap_ha(a: Optional[BaseGeometry], b: Optional[BaseGeometry]) -> float:
    """Area two geometries share (the 'river bank inside plantation = x ha' column)."""
    if a is None or b is None or a.is_empty or b.is_empty:
        return 0.0
    return area_ha(a.intersection(b))


# ---------------------------------------------------------------------------
# the strip itself
# ---------------------------------------------------------------------------
def _segment_widths(n_segments: int, side_m: Widths) -> List[float]:
    if isinstance(side_m, (int, float)):
        return [float(side_m)] * n_segments
    widths = [float(w) for w in side_m]
    if len(widths) != n_segments:
        raise ValueError(f"{n_segments} segments need {n_segments} widths, got {len(widths)}")
    return widths


def strip_polygon(line_m: LineString, side_m: Widths) -> BaseGeometry:
    """The strip around a centerline: ``side_m`` metres EACH side, one width per segment or one for all.

    Every segment is buffered with flat ends; where two segments meet a disc of the narrower width fills the gap on the
    outside of the bend, so a bend never bulges past the wider segment. A closed ring is treated as a loop.
    """
    coords = list(line_m.coords)
    if len(coords) < 2:
        raise ValueError("a centerline needs at least two points")
    closed = coords[0] == coords[-1] and len(coords) > 2
    n = len(coords) - 1
    widths = _segment_widths(n, side_m)
    if any(w <= 0 for w in widths):
        raise ValueError("a strip width must be positive")

    parts: List[BaseGeometry] = [
        LineString([coords[i], coords[i + 1]]).buffer(widths[i], cap_style="flat") for i in range(n)
    ]
    joints = range(n) if closed else range(1, n)
    for i in joints:
        w = min(widths[i - 1], widths[i])  # i-1 wraps to the last segment for a ring
        parts.append(Point(coords[i]).buffer(w))
    return unary_union(parts)


def forest_area(boundary_m: BaseGeometry, private_land_m: Iterable[BaseGeometry] = ()) -> BaseGeometry:
    """The forest area a strip is clipped to: the boundary minus every private-land polygon."""
    private = [g for g in private_land_m if g is not None and not g.is_empty]
    return boundary_m.difference(unary_union(private)) if private else boundary_m


def clip_to_area(strip_m: BaseGeometry, area_m: BaseGeometry) -> Optional[BaseGeometry]:
    """The part of a strip inside the forest area, or None when nothing is left."""
    clipped = strip_m.intersection(area_m)
    polys = _polygons(clipped)
    return unary_union(polys) if polys else None


def _polygons(geom: Optional[BaseGeometry]) -> List[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area >= MIN_AREA_SQM else []
    if isinstance(geom, MultiPolygon) or hasattr(geom, "geoms"):
        out: List[Polygon] = []
        for g in geom.geoms:
            out.extend(_polygons(g))
        return out
    return []


def explode(geom: Optional[BaseGeometry]) -> List[Polygon]:
    """Single-part polygons, largest first (one sub-area entry = one polygon)."""
    return sorted(_polygons(geom), key=lambda p: -p.area)


def trim_same_kind(polygons: Sequence[Optional[BaseGeometry]]) -> List[Optional[BaseGeometry]]:
    """Each polygon minus the union of the EARLIER ones, in the order given: their areas then add up to the area of their union.

    A polygon with nothing left becomes None, so the result lines up with the input.
    """
    out: List[Optional[BaseGeometry]] = []
    taken: Optional[BaseGeometry] = None
    for poly in polygons:
        if poly is None or poly.is_empty:
            out.append(None)
            continue
        rest = poly if taken is None else poly.difference(taken)
        polys = _polygons(rest)
        out.append(unary_union(polys) if polys else None)
        taken = poly if taken is None else unary_union([taken, poly])
    return out


# ---------------------------------------------------------------------------
# centerlines: from the field book's stretches to fire-line pieces
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Stretch:
    """A run of one field-book line that separates the same two things.

    ``pair`` -- the unit names it separates (``("SC1", "SC2")``) or one unit and the outside (``("SC1", OUTER_LABEL)``).
    ``coords`` -- metric (x, y) points in walking order. ``line`` / ``order`` -- the field-book line it came from (``I-57``)
    and its place on that line, which decides who a tiny stretch may merge into.
    """

    pair: Tuple[str, ...]
    coords: Tuple[Tuple[float, float], ...]
    line: str
    order: int
    #: the sub-area whose outline this is when it lies INSIDE one unit (``SC1 (Plantation 1)``); "" for a unit edge
    tag: str = ""

    @property
    def length(self) -> float:
        return LineString(self.coords).length


@dataclass
class Piece:
    """A fire-line centerline: one pair, possibly built from several stretches."""

    pair: Tuple[str, ...]
    line: LineString
    lines: FrozenSet[str] = field(default_factory=frozenset)
    first: Tuple[str, int] = ("", 0)  # earliest (line, order) it contains: a stable order for naming
    tag: str = ""

    @property
    def length(self) -> float:
        return float(self.line.length)


def _node(p: Tuple[float, float]) -> Tuple[int, int]:
    return (round(p[0] / NODE_TOL_M), round(p[1] / NODE_TOL_M))


def _ends(line: LineString) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    c = list(line.coords)
    return _node(c[0]), _node(c[-1])


def _join(a: Piece, b: Piece) -> Optional[Piece]:
    """Join two pieces of the same pair that meet end to end (either way round)."""
    if a.pair != b.pair or a.tag != b.tag:
        return None
    a_s, a_e = _ends(a.line)
    b_s, b_e = _ends(b.line)
    if a_e == b_s:
        coords = list(a.line.coords) + list(b.line.coords)[1:]
    elif a_e == b_e:
        coords = list(a.line.coords) + list(reversed(list(b.line.coords)))[1:]
    elif a_s == b_e:
        coords = list(b.line.coords) + list(a.line.coords)[1:]
    elif a_s == b_s:
        coords = list(reversed(list(b.line.coords))) + list(a.line.coords)[1:]
    else:
        return None
    return Piece(a.pair, LineString(coords), a.lines | b.lines, min(a.first, b.first), a.tag)


PARALLEL_TOL_M = 1.0   # two pieces this close along their whole length are one border drawn twice


def _drop_parallel(pieces: List[Piece]) -> List[Piece]:
    """One border, one piece. Real units draw a shared edge twice (each unit has its own vertices a few centimetres apart), so the
    field book lists two chains between the same two junctions; every node then looks like a branch (degree 4) and the pieces are
    never joined. Of two pieces of one pair with the same end nodes and a Hausdorff distance within ``PARALLEL_TOL_M``, the one with
    more vertices is kept and takes the other's field-book lines."""
    kept: List[Piece] = []
    for p in pieces:
        ends = frozenset(_ends(p.line))
        twin = next((i for i, k in enumerate(kept)
                     if k.pair == p.pair and k.tag == p.tag and frozenset(_ends(k.line)) == ends
                     and k.line.hausdorff_distance(p.line) <= PARALLEL_TOL_M), None)
        if twin is None:
            kept.append(p)
            continue
        k = kept[twin]
        best = p if len(p.line.coords) > len(k.line.coords) else k
        kept[twin] = Piece(best.pair, best.line, k.lines | p.lines, min(k.first, p.first), best.tag)
    return kept


def _join_all(pieces: List[Piece]) -> List[Piece]:
    """Join same-pair pieces end to end until no two can be joined.

    A node where three or more pieces of the pair meet is left alone (it is a real branch, not a continuation).
    """
    pieces = list(pieces)
    changed = True
    while changed:
        changed = False
        degree: Dict[Tuple[Tuple[str, ...], str, Tuple[int, int]], int] = {}
        for p in pieces:
            for n in set(_ends(p.line)):
                degree[(p.pair, p.tag, n)] = degree.get((p.pair, p.tag, n), 0) + 1
        for i in range(len(pieces)):
            for j in range(i + 1, len(pieces)):
                a, b = pieces[i], pieces[j]
                if a.pair != b.pair or a.tag != b.tag:
                    continue
                shared = set(_ends(a.line)) & set(_ends(b.line))
                if not shared or any(degree[(a.pair, a.tag, n)] > 2 for n in shared):
                    continue
                joined = _join(a, b)
                if joined is None:
                    continue
                pieces[i] = joined
                del pieces[j]
                changed = True
                break
            if changed:
                break
    return pieces


def _absorb(tiny: Piece, into: Piece) -> Piece:
    """``tiny`` merged into its neighbour: the neighbour's pair, the two lines joined at the shared end."""
    probe = _join(Piece(into.pair, tiny.line, tiny.lines, tiny.first, into.tag), into)
    if probe is not None:
        return Piece(into.pair, probe.line, into.lines | tiny.lines, min(into.first, tiny.first), into.tag)
    # the ends do not meet exactly (a tiny stretch at a gap): keep the neighbour as it is, the tiny one is dropped
    return into


def build_pieces(stretches: Sequence[Stretch], min_length_m: float = STRIP_MIN_LENGTH_M) -> List[Piece]:
    """Field-book stretches -> fire-line centerlines.

    1. Stretches of one pair that meet end to end are joined (the field book breaks one shared edge at every junction).
    2. A piece shorter than ``min_length_m`` is merged into the LONGER of the pieces it touches that share a field-book line
       with it (the result keeps that neighbour's pair), or removed when it has none. Never merged into a piece of a line
       it does not belong to.
    3. Merging can make two pieces of one pair adjacent, so 1 and 2 repeat until nothing changes.

    The result is in a stable order (by the field-book line and place of its first stretch).
    """
    pieces = [
        Piece(s.pair, LineString(s.coords), frozenset({s.line}), (s.line, s.order), s.tag)
        for s in stretches
        if len(s.coords) >= 2 and LineString(s.coords).length > 0
    ]
    pieces = _drop_parallel(pieces)
    while True:  # every pass either stops or removes one piece, so this ends
        pieces = _join_all(pieces)
        tiny = [p for p in pieces if p.length < min_length_m]
        if not tiny:
            break
        victim = min(tiny, key=lambda p: (p.length, p.first))
        mine = set(_ends(victim.line))
        pieces = [p for p in pieces if p is not victim]
        neighbours = [
            (i, p) for i, p in enumerate(pieces)
            if (p.lines & victim.lines) and (set(_ends(p.line)) & mine)
        ]
        if neighbours:
            i, best = sorted(neighbours, key=lambda ip: (-ip[1].length, ip[1].first))[0]
            pieces[i] = _absorb(victim, best)
    return sorted(pieces, key=lambda p: p.first)


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------
def natural_key(name: str) -> Tuple[Any, ...]:
    """'SC2' < 'SC10': text and numbers compared as text and numbers."""
    return tuple(int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name) if t != "")


def pair_label(pair: Sequence[str]) -> str:
    """'SC1-SC2' in natural order; the outside always goes last: 'SC1-बाहिरी सिमाना'."""
    names = sorted((n for n in pair if n != OUTER_LABEL), key=natural_key)
    if OUTER_LABEL in pair:
        names.append(OUTER_LABEL)
    return "-".join(names)


def piece_names(pieces: Sequence[Piece]) -> List[str]:
    """One name per piece, in the order given. A second separate piece of one pair is 'SC1-SC2 (2)', the third '(3)'.

    A piece along a sub-area outline inside one unit carries the sub-area as its tag: 'SC1 (Plantation 1)'.
    """
    seen: Dict[str, int] = {}
    out: List[str] = []
    for p in pieces:
        base = pair_label(p.pair) + (f" ({p.tag})" if p.tag else "")
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return out
