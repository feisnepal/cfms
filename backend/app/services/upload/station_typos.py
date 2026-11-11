"""A survey station with one mistyped digit (VALIDATION_TRACKER.md, C4).

Stations are walked in order, so every station is near the one before and the one after. A typo in one digit (the 15th of 50 stations, ``2`` typed as ``8``
in the 4th place) makes the point jump away and back: **both** neighbouring legs are far longer than the file's own typical leg, and the point adds a large
detour to the walk. This module finds such points and, because the cause is one digit, proposes the single-digit (or two-digit swap) value that puts the
point back where the walk says it belongs.

* the threshold comes from the file itself (a multiple of its median leg), never a fixed distance - forests run to 1000 ha;
* a station is flagged only when BOTH legs are long and it adds a large detour, so a legitimately long straight leg or a sharp corner is not;
* a typo smaller than a normal leg cannot be told from real variation - and is nearly harmless;
* nothing is changed here: the caller shows the proposals and the user decides.

Pure: no database access. Distances are metres (degrees are converted at the file's own latitude).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Callable, List, Optional, Sequence

_M_PER_DEG_LAT = 110_574.0
_M_PER_DEG_LON_EQ = 111_320.0

# Calibrated by simulation on the real boundaries in cf_db (6 forests, each cut to 8-100 stations; one digit corrupted at every position of 12 stations per ring):
#   * 0 false flags on 48 clean rings at every setting tried (legs x2..x4);
#   * at legs x3 / detour x4 a typo that moves the station more than 3 typical legs is found 98.3% of the time (100% for the integer and first decimal places,
#     ~96% for the second, lower for the third) and the true value is among the top 3 proposed repairs 97.0% of the time;
#   * a typo that moves the station by less than ~3 typical legs is not found (2 of 1734) - indistinguishable from real variation, and nearly harmless.
# The multiple of the median leg that BOTH legs must exceed ...
LEG_MULTIPLE = 3.0
# ... and the detour the station must add, in median legs (a spike, not just a long leg).
DETOUR_MULTIPLE = 4.0
MIN_STATIONS = 5  # fewer points than this gives no meaningful "typical leg"


def _dist(a: Sequence[float], b: Sequence[float], units: str, lat0: float) -> float:
    if units == "m":
        return math.hypot(a[0] - b[0], a[1] - b[1])
    dx = (a[0] - b[0]) * _M_PER_DEG_LON_EQ * math.cos(math.radians(lat0))
    dy = (a[1] - b[1]) * _M_PER_DEG_LAT
    return math.hypot(dx, dy)


@dataclass
class Suspect:
    index: int  # 0-based position in the file
    legs_m: tuple  # (leg before, leg after)
    detour_m: float  # how much longer the walk is because of this station
    typical_leg_m: float


@dataclass
class Repair:
    axis: str  # 'x' (longitude / easting) or 'y' (latitude / northing)
    kind: str  # 'digit' (one digit replaced) or 'swap' (two neighbouring digits exchanged)
    typed_from: str
    typed_to: str
    x: float
    y: float
    detour_after_m: float
    moved_m: float


def _legs(pts: Sequence[Sequence[float]], units: str, closed: bool) -> List[float]:
    n = len(pts)
    lat0 = sum(p[1] for p in pts) / n if units == "deg" else 0.0
    last = n if closed else n - 1
    return [_dist(pts[i], pts[(i + 1) % n], units, lat0) for i in range(last)]


def _drop_closing_duplicate(xs: Sequence[float], ys: Sequence[float]):
    """A ring whose last point repeats the first: judge it without the repeat."""
    if len(xs) > 2 and xs[0] == xs[-1] and ys[0] == ys[-1]:
        return list(xs[:-1]), list(ys[:-1])
    return list(xs), list(ys)


def find_suspects(xs: Sequence[float], ys: Sequence[float], *, units: str = "deg", closed: bool = True,
                  leg_multiple: float = LEG_MULTIPLE, detour_multiple: float = DETOUR_MULTIPLE) -> List[Suspect]:
    """Stations that look like a mistyped digit: both legs long, and a large detour. ``closed`` treats the file as a ring (a boundary)."""
    xs, ys = _drop_closing_duplicate(xs, ys)
    n = len(xs)
    if n < MIN_STATIONS:
        return []
    pts = list(zip(xs, ys))
    lat0 = sum(ys) / n if units == "deg" else 0.0
    legs = _legs(pts, units, closed)
    typical = median(l for l in legs if l > 0) if any(l > 0 for l in legs) else 0.0
    if typical <= 0:
        return []
    out: List[Suspect] = []
    rng = range(n) if closed else range(1, n - 1)
    for i in rng:
        prev, nxt = pts[(i - 1) % n], pts[(i + 1) % n]
        a, b = _dist(prev, pts[i], units, lat0), _dist(pts[i], nxt, units, lat0)
        chord = _dist(prev, nxt, units, lat0)
        detour = a + b - chord
        if min(a, b) > leg_multiple * typical and detour > detour_multiple * typical:
            out.append(Suspect(i, (a, b), detour, typical))
    return out


def _detour_at(pts: List[Sequence[float]], i: int, p: Sequence[float], units: str, lat0: float, closed: bool) -> float:
    n = len(pts)
    prev, nxt = pts[(i - 1) % n], pts[(i + 1) % n]
    return _dist(prev, p, units, lat0) + _dist(p, nxt, units, lat0) - _dist(prev, nxt, units, lat0)


def _variants(text: str):
    """Every one-digit replacement and every neighbouring-digit swap of a typed number, as (kind, new text)."""
    chars = list(text)
    for pos, ch in enumerate(chars):
        if ch.isdigit():
            for d in "0123456789":
                if d != ch:
                    yield "digit", "".join(chars[:pos] + [d] + chars[pos + 1:])
    for pos in range(len(chars) - 1):
        if chars[pos].isdigit() and chars[pos + 1].isdigit() and chars[pos] != chars[pos + 1]:
            swapped = chars[:]
            swapped[pos], swapped[pos + 1] = swapped[pos + 1], swapped[pos]
            yield "swap", "".join(swapped)


def propose_repairs(xs: Sequence[float], ys: Sequence[float], index: int, typed_x: str, typed_y: str, *, units: str = "deg", closed: bool = True,
                    top: int = 3, accept_detour_m: Optional[float] = None,
                    feature_distance_m: Optional[Callable[[float, float], Optional[float]]] = None) -> List[Repair]:
    """The one-digit changes that put station ``index`` back between its neighbours, best first.

    A candidate must make the station stop being a spike (``accept_detour_m``, default: the detour of a normal station for this file). They are ranked by
    the detour that remains; ``feature_distance_m(x, y)`` (metres to the nearest river / ridge / road / land-cover edge, when the caller can look it up)
    breaks ties in favour of a point that lies on something a boundary follows.
    """
    xs, ys = _drop_closing_duplicate(xs, ys)
    n = len(xs)
    pts = list(zip(xs, ys))
    lat0 = sum(ys) / n if units == "deg" else 0.0
    legs = _legs(pts, units, closed)
    typical = median(l for l in legs if l > 0) if any(l > 0 for l in legs) else 0.0
    limit = accept_detour_m if accept_detour_m is not None else DETOUR_MULTIPLE * typical
    here = pts[index]
    found: List[Repair] = []
    for axis, typed, other in (("x", typed_x, None), ("y", typed_y, None)):
        for kind, text in _variants(typed):
            try:
                value = float(text)
            except ValueError:
                continue
            p = (value, here[1]) if axis == "x" else (here[0], value)
            d = _detour_at(pts, index, p, units, lat0, closed)
            if d <= limit:
                found.append(Repair(axis, kind, typed, text, p[0], p[1], d, _dist(here, p, units, lat0)))

    def rank(r: Repair):
        feat = feature_distance_m(r.x, r.y) if feature_distance_m else None
        return (round(r.detour_after_m, 1), feat if feat is not None else float("inf"), r.kind != "digit", r.moved_m)

    found.sort(key=rank)
    seen, unique = set(), []
    for r in found:  # the same resulting point can arise from a swap and from a digit change
        k = (r.axis, r.typed_to)
        if k not in seen:
            seen.add(k)
            unique.append(r)
    return unique[:top]


def analyse_stations(xs: Sequence[float], ys: Sequence[float], typed_x: Sequence[Optional[str]], typed_y: Sequence[Optional[str]], *, units: str = "deg", closed: bool = True,
                     to_lonlat: Optional[Callable[[float, float], tuple]] = None) -> List[dict]:
    """The suspects of a station file as plain data for the screen: spreadsheet row, where the point is, how far off the walk it is, and the proposed repairs.

    ``typed_x`` / ``typed_y`` are the values as typed (``None`` when a cell is not a plain number, e.g. degrees-minutes-seconds: then no digit repair is offered).
    ``to_lonlat`` converts a point to longitude / latitude when the file is in metres, so the map can draw it.
    """
    def lonlat(x: float, y: float) -> dict:
        lng, lat = to_lonlat(x, y) if to_lonlat else (x, y)
        return {"lng": round(float(lng), 8), "lat": round(float(lat), 8)}

    out: List[dict] = []
    for sus in find_suspects(xs, ys, units=units, closed=closed):
        i = sus.index
        repairs: List[Repair] = []
        if typed_x[i] and typed_y[i]:
            repairs = propose_repairs(xs, ys, i, typed_x[i], typed_y[i], units=units, closed=closed)
        out.append({
            "row": i + 2, "index": i, "point": lonlat(xs[i], ys[i]),
            "detour_m": round(sus.detour_m, 1), "typical_leg_m": round(sus.typical_leg_m, 1), "legs_m": [round(v, 1) for v in sus.legs_m],
            "typed": {"x": typed_x[i], "y": typed_y[i]},
            "repairs": [{"axis": r.axis, "kind": r.kind, "typed_from": r.typed_from, "typed_to": r.typed_to, "point": lonlat(r.x, r.y),
                         "detour_after_m": round(r.detour_after_m, 1), "moved_m": round(r.moved_m, 1)} for r in repairs],
        })
    return out
