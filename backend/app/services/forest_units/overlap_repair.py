"""Resolve the overlaps between sibling units (owner decision 2026-10-19: the SMALLER neighbour keeps the contested ground).

Pure geometry, no database. Siblings = units with the same parent. The units are processed from the smallest up; each loses
whatever the smaller ones already hold, so the ground is never lost (the union of the siblings is unchanged) and nothing is
left twice. The difference is taken in the units' own coordinates, so the cut edge reuses the neighbour's vertices exactly and
no sliver gap is opened between them.

``scripts/repair_unit_overlaps.py`` is the command line (dry run by default); ``structure_write`` is where the changes are saved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

#: overlap smaller than this (square degrees) is not worth cutting - it is float noise from an earlier cut
_NOISE_DEG2 = 1e-14


@dataclass
class Unit:
    id: Any
    name: str
    geom: BaseGeometry
    area_ha: float          # geodesic, from the caller (this module has no CRS)


@dataclass
class Change:
    id: Any
    name: str
    geometry: BaseGeometry          # the new shape: a Polygon, or a MultiPolygon with no MORE parts than the unit already had
    lost_to: List[str]              # the smaller neighbours it gave ground to
    parts_dropped: int = 0          # extra fragments the cut left (a unit is one polygon): reported, never silently kept
    fragments: List[Polygon] = None  # type: ignore[assignment]  # those fragments themselves, for the caller to judge


def _polygonal(geom: BaseGeometry) -> List[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if hasattr(geom, "geoms"):
        out: List[Polygon] = []
        for g in geom.geoms:
            out.extend(_polygonal(g))
        return out
    return []


def resolve(siblings: Sequence[Unit]) -> List[Change]:
    """The changes that make ``siblings`` disjoint. Empty when they already are."""
    order = sorted(siblings, key=lambda u: (u.area_ha, u.name))
    changes: List[Change] = []
    for i, big in enumerate(order):
        geom = big.geom
        lost_to: List[str] = []
        for small in order[:i]:
            if not geom.intersects(small.geom):
                continue
            if geom.intersection(small.geom).area <= _NOISE_DEG2:
                continue
            geom = make_valid(geom.difference(small.geom))
            lost_to.append(small.name)
        if not lost_to:
            continue
        parts = sorted(_polygonal(geom), key=lambda p: -p.area)
        if not parts:
            continue  # nothing left of it: the caller reports it; a unit swallowed whole is not repaired automatically
        had = len(_polygonal(big.geom))
        keep, extra = parts[:max(had, 1)], parts[max(had, 1):]
        shape = keep[0] if len(keep) == 1 else MultiPolygon(keep)
        changes.append(Change(big.id, big.name, shape, lost_to, parts_dropped=len(extra), fragments=extra))
    return changes


def overlap_area(siblings: Sequence[Unit]) -> float:
    """Total overlap between siblings in the geometry's own units (square degrees): for a before/after comparison only."""
    total = 0.0
    for i, a in enumerate(siblings):
        for b in siblings[i + 1:]:
            if a.geom.intersects(b.geom):
                total += a.geom.intersection(b.geom).area
    return total
