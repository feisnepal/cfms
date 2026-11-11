"""
Apportion N equal-area compartments across the islands of a multi-part
(MultiPolygon) forest boundary.

A compartment never spans two detached parcels, so each island must receive a
**whole** number of pieces, and at least one (a parcel cannot be "half a
compartment"). "Equal area" is therefore equal *in aggregate* — exact only
when the island areas are multiples of the target piece size.

The allocation is the Hamilton / largest-remainder method with a floor of one
per island:

  1. target = Σ area / n_effective
  2. quota_i = area_i / target          (Σ quota == n_effective)
  3. count_i = max(1, floor(quota_i))
  4. hand out / claw back the difference so Σ count == n_effective, using the
     fractional remainders (largest first when adding, most-over-quota first
     when removing), never dropping an island below 1.

`n_effective` is `max(n, len(areas))` — you cannot have fewer compartments
than parcels.

This module is pure (no DB, no shapely) so it is unit-testable on its own and
can be mirrored 1:1 on the frontend (`lib/islandApportionment.ts`).

See MULTI_ISLAND_DIVIDE_PLAN.md (P0).
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, TypedDict

#: An island whose average piece is smaller than this fraction of the target is
#: flagged `undersized` — the parcel is too small to reach the target size.
#: Advisory only; it never blocks the divide.
UNDERSIZED_REL = 0.5


class IslandAllocation(TypedDict):
    counts: List[int]  # pieces per island, same order as `areas`; sums to n_effective
    n_effective: int  # n, raised to len(areas) when n < len(areas)
    target_area: float  # Σ area / n_effective — the ideal equal piece size
    undersized: List[
        int
    ]  # indices of islands whose avg piece < UNDERSIZED_REL * target


def allocate_island_counts(areas: Sequence[float], n: int) -> IslandAllocation:
    """Apportion `n` equal-area compartments across islands of the given `areas`.

    Raises ValueError on an empty island list, a non-positive area, or n < 1.
    """
    areas = [float(a) for a in areas]
    if not areas:
        raise ValueError("no islands to divide")
    if any(a <= 0 for a in areas):
        raise ValueError("island areas must be positive")
    n = int(n)
    if n < 1:
        raise ValueError("n must be at least 1")

    k = len(areas)
    n_eff = max(n, k)  # cannot have fewer compartments than parcels
    total = math.fsum(areas)
    target = total / n_eff
    quota = [a / target for a in areas]  # Σ quota == n_eff

    counts = [max(1, math.floor(q)) for q in quota]
    diff = n_eff - sum(counts)

    if diff > 0:
        # hand out the spare pieces to the largest fractional remainders
        # (tie → larger island → lower index, for determinism)
        order = sorted(
            range(k),
            key=lambda i: (quota[i] - math.floor(quota[i]), areas[i], -i),
            reverse=True,
        )
        for i in order[:diff]:
            counts[i] += 1
    elif diff < 0:
        # the floor-of-one over-allocated small parcels — claw back from the
        # islands furthest above their fair quota, never below 1
        take = -diff
        while take > 0:
            cands = [i for i in range(k) if counts[i] > 1]
            if not cands:  # every island already at 1 — unreachable given n_eff >= k
                break
            i = max(cands, key=lambda i: (counts[i] - quota[i], counts[i], -i))
            counts[i] -= 1
            take -= 1

    undersized = [
        i for i in range(k) if (areas[i] / counts[i]) < UNDERSIZED_REL * target
    ]

    return {
        "counts": counts,
        "n_effective": n_eff,
        "target_area": target,
        "undersized": undersized,
    }


def summarise_islands(
    areas: Sequence[float], counts: Sequence[int], target: float
) -> List[Dict]:
    """Per-island rows for the preview table (P2). Pure helper."""
    return [
        {
            "index": i,
            "area_ha": round(float(areas[i]), 4),
            "suggested_count": int(counts[i]),
            "avg_piece_ha": round(float(areas[i]) / counts[i], 4) if counts[i] else 0.0,
            "undersized": (
                bool((float(areas[i]) / counts[i]) < UNDERSIZED_REL * target)
                if counts[i]
                else False
            ),
        }
        for i in range(len(areas))
    ]
