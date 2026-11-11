"""Rebuild the field book's lines from its saved points.

A field book is points, but the owner's rule is about LINES: the outer points form a closed outline that draws as
a polygon; the internal points form open lines that are never closed and never joined to one another.
``Fieldbook.lines`` stores, for every point, each line it is on and its place in that line
(``{"O-1": 12, "I-2": 5}``) -- a junction sits on every line that meets there -- so every line can be rebuilt end
to end with its shared end points. Everything that draws or lists a line (the exports, the API, the map) goes
through here, so they all agree.

Line ids: ``O-n`` outer ring (closed) | ``I-n`` internal edge (open) | ``L-n`` a free-standing internal loop,
closed because it has no ends (a sub-area inside a unit).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.services.fieldbook import calculate_distance


def line_kind(line_id: str) -> str:
    return "outer" if line_id.startswith("O-") else "internal"


def line_is_closed(line_id: str) -> bool:
    """Outer rings close back on their first point; so does a free-standing loop. An internal edge never does."""
    return line_id.startswith(("O-", "L-"))


def _sort_key(line_id: str):
    prefix, _, n = line_id.partition("-")
    return ({"O": 0, "I": 1, "L": 2}.get(prefix, 3), int(n) if n.isdigit() else 0)


def lines_from_points(points: Iterable[Any]) -> List[Dict[str, Any]]:
    """Every line of the book: ``id``, ``kind``, ``closed``, ``labels``, ``coordinates`` ([lon, lat], first point
    repeated at the end of a closed line) and ``length_m``. Outer rings first, then internal edges, then loops."""
    members: Dict[str, List[tuple]] = {}
    for p in points:
        memberships = getattr(p, "lines", None)
        if not memberships:
            continue
        for line_id, order in memberships.items():
            members.setdefault(line_id, []).append((int(order), p))

    out: List[Dict[str, Any]] = []
    for line_id in sorted(members, key=_sort_key):
        ordered = [p for _, p in sorted(members[line_id], key=lambda m: m[0])]
        coords = [[float(p.longitude), float(p.latitude)] for p in ordered]
        closed = line_is_closed(line_id)
        if closed and len(coords) > 1:
            coords.append(list(coords[0]))
        length = sum(
            calculate_distance(a[0], a[1], b[0], b[1]) for a, b in zip(coords, coords[1:])
        )
        out.append({
            "id": line_id,
            "kind": line_kind(line_id),
            "closed": closed,
            "labels": [p.point_label for p in ordered],
            "coordinates": coords,
            "length_m": round(length, 2),
        })
    return out
