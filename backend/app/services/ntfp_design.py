"""NTFP sampling design: the pure maths (NTFP inventory, phase 2). No database, no request: shapely only, in a metric CRS.

Guideline: गैरकाष्ठ वन पैदावारको स्रोत सर्वेक्षण मार्गदर्शन २०६९, section 3.3 (plot size 3.3.3, intensity 3.3.4, plot count and spacing 3.3.5-3.3.6,
transect lines 3.3.7) and the composite plot (section 3.3.2, Table 2 and its figure).

* ``plot_count``     n = (forest area x intensity %) / plot area, at least ``MIN_PLOTS_PER_STRATUM``, at most what fits.
* ``plot_spacing_m`` a = sqrt(A / (n + 1)): the distance between plots, and between the parallel transect lines.
* ``lay_out``        a lattice of plots on parallel transect lines, a random start, plots kept whole inside the area.
* ``composite``      species of different growth form share one plot position: the largest plot is the frame, each smaller size is a
                     sub-plot in a corner of it (the guideline's "composite plot").
* ``design``         the lot: per stratum, one master set of plot positions; each species samples an evenly spread subset of it
                     (as many plots as its own intensity asks for) and so only measures where it is wanted.

Nothing here knows what a species is: a :class:`SpeciesSpec` carries a key, a growth class, a plot area and an intensity. The profile
table (``ntfp_method_profile``) and the Table-4 intensities (``core/ntfp_methods``) feed it from outside.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

#: Fewer plots than this say nothing about a stratum. The guideline gives no floor; this is the working value (owner may change it).
MIN_PLOTS_PER_STRATUM = 3
#: The lattice is tightened to find enough plots, but never closer than a plot's side (plots would touch).
SPACING_SHRINK = 0.9
SHAPES = ("square", "circular")


@dataclass(frozen=True)
class SpeciesSpec:
    species_key: str
    plot_sqm: float
    intensity_pct: float
    growth_class: str = "herb"
    label: str = ""


@dataclass
class Plot:
    stratum: str
    number: int            # across the whole design, in stratum order then along the transects
    transect: int          # 1-based transect line within the stratum
    x: float               # metric CRS
    y: float
    species_keys: List[str] = field(default_factory=list)


@dataclass
class StratumResult:
    name: str
    area_ha: float
    plots_wanted: int      # what the most demanding species asks for
    plots_laid: int
    spacing_m: float       # the lattice spacing finally used
    transects: List[LineString] = field(default_factory=list)  # metric CRS
    warnings: List[str] = field(default_factory=list)


@dataclass
class DesignResult:
    strata: List[StratumResult]
    plots: List[Plot]
    species: List[dict]    # per species: plots by stratum, intensity achieved
    layout: dict           # the composite plot
    seed: int
    warnings: List[str] = field(default_factory=list)


# ── counts and distances ────────────────────────────────────────────────────────────────────────────────────────────────────────

def plot_count(area_sqm: float, plot_sqm: float, intensity_pct: float, min_plots: int = MIN_PLOTS_PER_STRATUM) -> int:
    """Plots to lay: area x intensity / plot area, rounded up, at least ``min_plots``, never more than fit in the area."""
    if area_sqm <= 0 or plot_sqm <= 0 or intensity_pct <= 0:
        return 0
    n = math.ceil(area_sqm * intensity_pct / 100.0 / plot_sqm)
    return int(max(1, min(max(n, min_plots), math.floor(area_sqm / plot_sqm))))


def plot_spacing_m(area_sqm: float, n: int) -> float:
    """Guideline 3.3.5: a² = A / (n + 1). 40 ha with 80 plots: 70.27 m."""
    return math.sqrt(area_sqm / (n + 1)) if n >= 0 and area_sqm > 0 else 0.0


def plot_side_m(plot_sqm: float) -> float:
    return math.sqrt(plot_sqm)


def intensity_achieved_pct(plots: int, plot_sqm: float, area_sqm: float) -> float:
    return plots * plot_sqm / area_sqm * 100.0 if area_sqm else 0.0


# ── the plot ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def plot_polygon(x: float, y: float, plot_sqm: float, shape: str = "square") -> BaseGeometry:
    """A plot centred on (x, y): a square of side sqrt(area), or a circle of the same area."""
    if shape == "circular":
        return Point(x, y).buffer(math.sqrt(plot_sqm / math.pi), 32)
    h = plot_side_m(plot_sqm) / 2.0
    return box(x - h, y - h, x + h, y + h)


def composite(specs: Sequence[SpeciesSpec]) -> dict:
    """The composite plot. The largest plot is the frame; every smaller size is one sub-plot in a corner of it (SW, SE, NE, NW in turn),
    shared by the species of that size. Offsets are metres from the plot centre to the sub-plot's centre."""
    sizes = sorted({round(s.plot_sqm, 4) for s in specs}, reverse=True)
    if not sizes:
        return {"frame_sqm": 0.0, "subplots": []}
    frame = sizes[0]
    half = plot_side_m(frame) / 2.0
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    subs = []
    for i, size in enumerate(sizes[1:]):
        h = plot_side_m(size) / 2.0
        cx, cy = corners[i % 4]
        subs.append({
            "plot_sqm": size,
            "offset_m": [round(cx * (half - h), 3), round(cy * (half - h), 3)],
            "species_keys": sorted(s.species_key for s in specs if round(s.plot_sqm, 4) == size),
        })
    return {"frame_sqm": frame, "frame_species_keys": sorted(s.species_key for s in specs if round(s.plot_sqm, 4) == frame), "subplots": subs}


# ── laying plots out in one stratum ─────────────────────────────────────────────────────────────────────────────────────────────

def _even_pick(items: list, n: int) -> list:
    """Exactly n items spread over the whole list (a fractional stride, never a slice that drops the tail)."""
    if n <= 0:
        return []
    if len(items) <= n:
        return list(items)
    step = len(items) / float(n)
    return [items[int(i * step)] for i in range(n)]


def _lattice(inner: BaseGeometry, spacing: float, rng: random.Random) -> List[Tuple[int, float, float]]:
    """(transect, x, y) of every lattice point inside ``inner``: transect lines run west to east, ``spacing`` apart, plots ``spacing`` apart
    along them; the start is random within one cell."""
    minx, miny, maxx, maxy = inner.bounds
    x0 = minx + rng.uniform(0.0, spacing)
    y0 = miny + rng.uniform(0.0, spacing)
    pts: List[Tuple[int, float, float]] = []
    row, y = 0, y0
    while y <= maxy:
        x, hit = x0, False
        while x <= maxx:
            if inner.contains(Point(x, y)):
                if not hit:
                    row += 1
                    hit = True
                pts.append((row, x, y))
            x += spacing
        y += spacing
    return pts


def lay_out(area_m: BaseGeometry, n: int, frame_sqm: float, rng: random.Random, shape: str = "square") -> Tuple[List[Tuple[int, float, float]], float, List[str]]:
    """Up to ``n`` plot positions on parallel transect lines inside ``area_m``, each plot whole inside the area.

    The spacing starts at the guideline's sqrt(A/(n+1)) and is tightened by 10 % until the lattice holds at least ``n`` positions, but
    never below the plot's side. More positions than needed are thinned evenly. Returns (positions, spacing used, warnings)."""
    warnings: List[str] = []
    if n <= 0 or area_m is None or area_m.is_empty:
        return [], 0.0, warnings
    half_extent = plot_side_m(frame_sqm) / 2.0 * (math.sqrt(2) if shape == "square" else 1.0)
    inner = area_m.buffer(-half_extent)
    if inner.is_empty:
        inner = area_m
        warnings.append("area_too_narrow_for_whole_plots")
    spacing = plot_spacing_m(area_m.area, n)
    floor = plot_side_m(frame_sqm)
    best: List[Tuple[int, float, float]] = []
    state = rng.getstate()
    while True:
        rng.setstate(state)  # the same random start for every spacing, so a tighter lattice is a refinement, not a reshuffle
        pts = _lattice(inner, max(spacing, floor), rng)
        if len(pts) > len(best):
            best = pts
        if len(pts) >= n or spacing <= floor:
            break
        spacing *= SPACING_SHRINK
    spacing = max(spacing, floor)
    if len(best) < n:
        warnings.append("fewer_plots_than_wanted")
    return _even_pick(best, n), spacing, warnings


def _transects(positions: Sequence[Tuple[int, float, float]]) -> List[LineString]:
    rows: Dict[int, List[Tuple[float, float]]] = {}
    for row, x, y in positions:
        rows.setdefault(row, []).append((x, y))
    return [LineString(sorted(pts)) for _, pts in sorted(rows.items()) if len(pts) >= 2]


# ── the whole design ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def design(strata: Dict[str, BaseGeometry], species: Sequence[SpeciesSpec], seed: Optional[int] = None, shape: str = "square",
           min_plots: int = MIN_PLOTS_PER_STRATUM) -> DesignResult:
    """The design for one forest. ``strata`` maps a name (a unit, or the forest as a whole) to its area in a metric CRS."""
    if shape not in SHAPES:
        raise ValueError(f"shape must be one of {SHAPES}, got {shape!r}")
    if not species:
        raise ValueError("choose at least one species")
    if len({s.species_key for s in species}) != len(species):
        raise ValueError("a species is listed twice")
    seed = random.SystemRandom().randrange(1, 2**31) if seed is None else int(seed)
    rng = random.Random(seed)
    frame = max(s.plot_sqm for s in species)
    layout = composite(species)
    plots: List[Plot] = []
    results: List[StratumResult] = []
    per_species: Dict[str, Dict[str, int]] = {s.species_key: {} for s in species}
    number = 0
    for name, geom in strata.items():
        area_sqm = float(geom.area) if geom is not None and not geom.is_empty else 0.0
        wanted = {s.species_key: plot_count(area_sqm, s.plot_sqm, s.intensity_pct, min_plots) for s in species}
        n = max(wanted.values()) if wanted else 0
        positions, spacing, warns = lay_out(geom, n, frame, rng, shape)
        res = StratumResult(name=name, area_ha=area_sqm / 10_000.0, plots_wanted=n, plots_laid=len(positions), spacing_m=spacing,
                            transects=_transects(positions), warnings=warns)
        results.append(res)
        laid: List[Plot] = []
        for row, x, y in positions:
            number += 1
            laid.append(Plot(stratum=name, number=number, transect=row, x=x, y=y))
        for s in species:
            for p in _even_pick(laid, min(wanted[s.species_key], len(laid))):
                p.species_keys.append(s.species_key)
            per_species[s.species_key][name] = len([p for p in laid if s.species_key in p.species_keys])
        plots.extend(laid)
    total_area = sum(r.area_ha for r in results) * 10_000.0
    summary = [{
        "species_key": s.species_key, "label": s.label, "growth_class": s.growth_class, "plot_sqm": s.plot_sqm,
        "intensity_pct": s.intensity_pct, "plots_by_stratum": per_species[s.species_key], "plots": sum(per_species[s.species_key].values()),
        "intensity_achieved_pct": round(intensity_achieved_pct(sum(per_species[s.species_key].values()), s.plot_sqm, total_area), 4),
    } for s in species]
    top = [w for r in results for w in r.warnings]
    return DesignResult(strata=results, plots=plots, species=summary, layout=layout, seed=seed, warnings=sorted(set(top)))
