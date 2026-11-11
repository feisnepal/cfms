"""P8 tier 1 - review unit sizes *before* sampling, and propose merging slivers.

Why this exists
---------------
A field-inventory summary is only created for a unit that received a sample point
(``field_inventory_service.py:1347`` builds the list from
``SELECT DISTINCT block_name FROM field_inventory_sample_plots``). A unit that gets
zero points therefore vanishes from the summary with no message, and the user sees
21 blocks where there are 24. This module is the *prevention* half: it says so
before anything is generated, while fixing a sliver still costs nothing.

Three bands, not one threshold (SUSTAINABLE_FM_P8_PLAN.md 5.2)
-------------------------------------------------------------
===========================  ==========  =========================================
band                         here        action
===========================  ==========  =========================================
``sub_mmu``   < 1 ha        3 units     merge offer, or the 8.1 floor exemption
``review``    1 ha - 5%     16 units    **flag only - never an automatic merge**
``ok``        >= 5%         5 units     nothing
===========================  ==========  =========================================

The split matters because the two thresholds are different in kind. The MMU is
**absolute** and decides the action: 5% of a forest does not scale (18.3 ha here, but
183 ha on a 3,660 ha forest), and a management unit's minimum should not move with
forest size. The 5% screen is **relative** and only decides who gets looked at - it
catches exactly the mid-sized units a 1 ha MMU is blind to.

This module is **read-only**. It never mutates a unit, never merges, and never
touches a design. Applying a merge is the caller's job, through the existing
``merge_features`` path (``editing.py:1858``) so that ``structure_write`` does the
invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence

from app.core.constants import MMU_SLIVER_AREA_M2, SQM_PER_HA

# The field rule of thumb (a thumb rule, not a law), so it is a default the caller
# may override per calculation rather than a constant like the MMU above.
DEFAULT_REVIEW_PCT = 5.0

# Sub-millimetre: enough to forgive the hairline gaps that digitising leaves behind
# without letting a genuinely separate unit count as a neighbour.
DEFAULT_TOUCH_TOLERANCE_M = 0.01


class Band(str, Enum):
    """Where a unit falls. Only ``SUB_MMU`` may ever authorise a merge."""

    SUB_MMU = "sub_mmu"
    REVIEW = "review"
    OK = "ok"


@dataclass(frozen=True)
class Candidate:
    """One unit's review outcome. ``neighbour`` is the *proposal*, never an action."""

    block_name: str
    area_ha: float
    band: Band
    action: str  # "merge_offer" | "flag_only" | "none"
    neighbour: Optional[str] = None
    neighbour_area_ha: Optional[float] = None
    unmergeable: bool = False
    reason: str = ""

    @property
    def is_offer(self) -> bool:
        return self.action == "merge_offer"


def mmu_hectares() -> float:
    return MMU_SLIVER_AREA_M2 / SQM_PER_HA


def classify_band(
    area_ha: float,
    boundary_ha: float,
    *,
    mmu_ha: Optional[float] = None,
    review_pct: float = DEFAULT_REVIEW_PCT,
) -> Band:
    """Which band ``area_ha`` falls in.

    A non-positive area is ``SUB_MMU``: a unit with no measurable area is exactly the
    kind of degenerate geometry this exists to surface, and rounding it up to ``OK``
    would hide it.
    """
    mmu = mmu_ha if mmu_ha is not None else mmu_hectares()
    if area_ha <= 0:
        return Band.SUB_MMU
    if area_ha < mmu:
        return Band.SUB_MMU
    if boundary_ha <= 0:
        # The relative screen cannot be evaluated without a boundary area. Anything
        # above the MMU then stays REVIEW rather than falling through to OK - an
        # unknown boundary must never hand out a clean bill of health.
        return Band.REVIEW
    if area_ha < (boundary_ha * review_pct) / 100.0:
        return Band.REVIEW
    return Band.OK


def pick_largest_touching(
    block_name: str,
    areas: Dict[str, float],
    touching: Iterable[str],
) -> Optional[str]:
    """The largest neighbour that touches ``block_name``.

    Touching is a hard requirement before size is considered (P8 6): pure *nearest*
    can select another sliver, and merging sliver-into-sliver is no improvement. The
    tie-break is largest-by-area, which is the wording the MMU constant already uses
    ("absorbed into the largest touching neighbour"), so this aligns the code to the
    policy rather than changing policy.
    """
    best: Optional[str] = None
    best_area = -1.0
    for name in touching:
        if name == block_name:
            continue
        if name not in areas:
            # Touching but unmeasured: it cannot be ranked, and proposing a merge
            # into a unit of unknown area would make the preview's resulting-area
            # figure a guess. Skipped rather than ranked as 0.
            continue
        area = float(areas.get(name) or 0.0)
        # Strictly greater, so an equal-area tie resolves to a stable first-wins
        # rather than depending on dict ordering.
        if area > best_area:
            best, best_area = name, area
    return best


def describe(
    candidate: Candidate,
    *,
    mmu_ha: float,
    plot_area_sqm: float,
    min_plots: int,
) -> str:
    """A sentence carrying the *why* in numbers, so the note is credible on its own."""
    if candidate.band is Band.SUB_MMU:
        if candidate.unmergeable:
            return (
                f"{candidate.block_name}: {candidate.area_ha:.4f} ha, below the "
                f"{mmu_ha:g} ha MMU, and no unit touches it - cannot be merged."
            )
        return (
            f"{candidate.block_name}: {candidate.area_ha:.4f} ha, below the {mmu_ha:g} ha "
            f"MMU. Merging into {candidate.neighbour} "
            f"({(candidate.neighbour_area_ha or 0.0):.2f} ha) is the option; leaving it "
            f"means {min_plots} x {plot_area_sqm:g} m2 plots cannot be placed in it."
        )
    if candidate.band is Band.REVIEW:
        return (
            f"{candidate.block_name}: {candidate.area_ha:.2f} ha, under the review "
            f"threshold - flagged for a look, no merge proposed."
        )
    return f"{candidate.block_name}: {candidate.area_ha:.2f} ha - no action."


def build_candidate(
    block_name: str,
    area_ha: float,
    band: Band,
    *,
    areas: Optional[Dict[str, float]] = None,
    touching: Optional[Sequence[str]] = None,
) -> Candidate:
    """Turn a band into a candidate, resolving the merge proposal where one is due.

    Adjacency is the caller's to supply, and **its absence is not treated as
    success**: when ``touching`` is ``None`` (never computed) the unit is reported
    ``unmergeable`` rather than as a clean offer, so a caller that forgets the
    spatial query cannot manufacture a proposal it never verified.
    """
    if band is not Band.SUB_MMU:
        return Candidate(
            block_name=block_name,
            area_ha=area_ha,
            band=band,
            action="flag_only" if band is Band.REVIEW else "none",
        )
    neighbour = None
    neighbour_area = None
    unmergeable = touching is None
    if not unmergeable and areas is not None:
        neighbour = pick_largest_touching(block_name, areas, touching or ())
        if neighbour is None:
            unmergeable = True
        else:
            neighbour_area = float(areas.get(neighbour) or 0.0)
    return Candidate(
        block_name=block_name,
        area_ha=area_ha,
        band=band,
        action="merge_offer",
        neighbour=neighbour,
        neighbour_area_ha=neighbour_area,
        unmergeable=unmergeable,
    )


def review_units(
    areas: Dict[str, float],
    *,
    boundary_ha: float,
    touching: Optional[Dict[str, Sequence[str]]] = None,
    mmu_ha: Optional[float] = None,
    review_pct: float = DEFAULT_REVIEW_PCT,
) -> List[Candidate]:
    """Classify every named unit. Pure - ``touching`` is supplied by the caller.

    ``touching`` maps a unit name to the names that touch it. When it is ``None`` a
    sub-MMU unit is reported as ``unmergeable`` rather than silently un-actioned, so
    a caller that forgets to supply adjacency cannot fake a clean bill of health.
    """
    out: List[Candidate] = []
    for name in sorted(areas):
        area = float(areas.get(name) or 0.0)
        band = classify_band(area, boundary_ha, mmu_ha=mmu_ha, review_pct=review_pct)
        out.append(
            build_candidate(
                name,
                area,
                band,
                areas=areas,
                touching=(touching or {}).get(name, ()),
            )
        )
    return out


def summarise(candidates: Sequence[Candidate]) -> Dict[str, object]:
    """Counts a UI can render, including the exemption count the design must show."""
    return {
        "total": len(candidates),
        "sub_mmu": sum(1 for c in candidates if c.band is Band.SUB_MMU),
        "review": sum(1 for c in candidates if c.band is Band.REVIEW),
        "ok": sum(1 for c in candidates if c.band is Band.OK),
        "merge_offers": sum(1 for c in candidates if c.is_offer and not c.unmergeable),
        "unmergeable": sum(1 for c in candidates if c.unmergeable),
    }
