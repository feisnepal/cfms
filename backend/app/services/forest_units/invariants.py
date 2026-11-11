"""The structure invariants of a forest's units, checked at runtime.

Owner rules (2026-10-03 / 2026-10-07):

  * **One branch per forest.** A forest has blocks OR compartments, never both. A second, older set of units left beside
    the new ones (परिक्षण वन kept Block-1..8 next to its compartments) shadows the real ones, answers "which units
    does this forest have" differently in different places, and carries no analysis data.
  * **Children tile their parent.** The sub-units of a unit lie inside it, do not overlap, and together cover it. So the
    undivided (leaf) units tile the forest, and the sub-unit total never exceeds the parent total.

``find_violations`` reads only ``forest_blocks`` (no side effects) and measures with PostGIS on the geography, so the areas
are true hectares. ``structure_write`` calls it before and after every structure edit and refuses an edit that adds a
violation that was not already there: a forest that was broken before is not locked out of every later edit, but an edit
cannot make it worse. ``scripts/report_unit_structure.py`` runs it over every forest.

The geometry checks allow a small tolerance (``REL_TOL`` of the parent's area, never less than ``ABS_TOL_HA``): units are
cut and clipped in lon/lat and stored areas are rounded, so slivers of that size are noise, not a gap.

OVERLAP is held to a much tighter tolerance than a gap (``OVERLAP_REL_TOL`` / ``OVERLAP_ABS_TOL_HA``, owner 2026-10-19: "overlap should
not happen"). A gap is a sliver that a clip leaves; an overlap is ground two units both claim, which every area figure then counts
twice. बनस्खन्डी's units overlapped by 0.27 ha (11 pairs) and passed the old 0.5 %-of-the-parent tolerance (1.1 ha) without a word.
Overlap is also checked between the TOP-LEVEL units of a branch (they have no parent, so the parent query never saw them), and an
edit that makes an existing overlap WORSE is refused even though the overlap was already there (``new_violations``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, List, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

REL_TOL = 0.005  # of the parent's area
ABS_TOL_HA = 0.02
# overlap: 0.005 % of the parent (0.011 ha = 110 m2 on 221 ha), never less than 0.001 ha (10 m2): a clip leaves a few m2 of rounding,
# never hundreds
OVERLAP_REL_TOL = 0.00005
OVERLAP_ABS_TOL_HA = 0.001
# an existing overlap that grows by more than this (ha) counts as a new violation
OVERLAP_WORSE_BY_HA = 0.001
TOP_LEVEL = "(top level)"

MIXED_BRANCHES = "MIXED_BRANCHES"
CHILD_OUTSIDE_PARENT = "CHILD_OUTSIDE_PARENT"
CHILDREN_OVERLAP = "CHILDREN_OVERLAP"
CHILDREN_DO_NOT_COVER_PARENT = "CHILDREN_DO_NOT_COVER_PARENT"
CHILD_COUNT_STALE = "CHILD_COUNT_STALE"
CODES = (MIXED_BRANCHES, CHILD_OUTSIDE_PARENT, CHILDREN_OVERLAP, CHILDREN_DO_NOT_COVER_PARENT, CHILD_COUNT_STALE)


@dataclass(frozen=True)
class Violation:
    code: str
    #: the unit the finding is about ("" for a forest-wide one)
    unit: str
    message: str
    #: hectares (or a count for MIXED_BRANCHES) — for the report; not part of the identity
    value: float = field(default=0.0, compare=False)

    @property
    def key(self) -> Tuple[str, str]:
        return (self.code, self.unit)


class StructureInvariantError(AppException):
    """An edit would leave the forest's units breaking a structure rule. Nothing has been committed."""

    def __init__(self, violations: Iterable[Violation]):
        vs = list(violations)
        super().__init__(
            error_code="structure_invariant_violated",
            message="This change would leave the forest's units inconsistent: "
            + "; ".join(v.message for v in vs[:3])
            + (f" (+{len(vs) - 3} more)" if len(vs) > 3 else ""),
            http_status=409,
            details=[{"code": v.code, "unit": v.unit, "message": v.message} for v in vs],
        )
        self.violations = vs


_MIXED_SQL = text(
    """
    SELECT count(*) FILTER (WHERE is_compartment) AS comps,
           count(*) FILTER (WHERE NOT is_compartment) AS blocks
    FROM forest_blocks WHERE calculation_id = :cid
    """
)

# the stored child_count must equal the real number of children: "undivided" readers trust it (DBG's B1 said 0 with 2 children,
# so it counted as an undivided unit and its area was counted twice)
_COUNT_SQL = text(
    """
    SELECT b.block_name AS name, b.child_count AS stored,
           (SELECT count(*) FROM forest_blocks c WHERE c.parent_block_id = b.id) AS actual
    FROM forest_blocks b
    WHERE b.calculation_id = :cid
      AND b.child_count IS DISTINCT FROM (SELECT count(*) FROM forest_blocks c WHERE c.parent_block_id = b.id)
    ORDER BY b.block_name
    """
)

# one row per parent that has children; every area in hectares on the geography
_PARENTS_SQL = text(
    """
    WITH kids AS (
        SELECT p.id AS pid, p.block_name AS pname, p.geometry AS pgeom,
               ST_Union(c.geometry) AS u, SUM(ST_Area(c.geometry::geography)) AS sum_children
        FROM forest_blocks p
        JOIN forest_blocks c ON c.parent_block_id = p.id
        WHERE p.calculation_id = :cid
        GROUP BY p.id, p.block_name, p.geometry
    )
    SELECT pname,
           ST_Area(pgeom::geography) / 10000.0 AS parent_ha,
           ST_Area(ST_Difference(u, pgeom)::geography) / 10000.0 AS outside_ha,
           ST_Area(ST_Difference(pgeom, u)::geography) / 10000.0 AS uncovered_ha,
           GREATEST(sum_children - ST_Area(u::geography), 0) / 10000.0 AS overlap_ha
    FROM kids
    ORDER BY pname
    """
)


def _tol(parent_ha: float) -> float:
    return max(ABS_TOL_HA, REL_TOL * float(parent_ha or 0.0))


def _overlap_tol(parent_ha: float) -> float:
    return max(OVERLAP_ABS_TOL_HA, OVERLAP_REL_TOL * float(parent_ha or 0.0))


# the top-level units of each branch (no parent). Auto-Block trial layers (raster_layer_id) are alternatives to each other and are
# meant to overlap, so they are not siblings.
_ROOTS_SQL = text(
    """
    SELECT is_compartment AS comp,
           count(*) AS n,
           COALESCE(SUM(ST_Area(geometry::geography)), 0) AS sum_a,
           ST_Area(ST_Union(geometry)::geography) AS union_a
    FROM forest_blocks
    WHERE calculation_id = :cid AND parent_block_id IS NULL AND raster_layer_id IS NULL AND geometry IS NOT NULL
    GROUP BY is_compartment
    """
)


def find_violations(db: Session, calc_id: Any) -> List[Violation]:
    """Every structure rule the forest breaks right now. Read-only."""
    out: List[Violation] = []
    cid = str(calc_id)

    row = db.execute(_MIXED_SQL, {"cid": cid}).one()
    if row.comps and row.blocks:
        out.append(
            Violation(
                MIXED_BRANCHES,
                "",
                f"the forest has both blocks ({row.blocks}) and compartments ({row.comps}); it may have only one",
                float(min(row.comps, row.blocks)),
            )
        )

    for r in db.execute(_COUNT_SQL, {"cid": cid}):
        out.append(
            Violation(
                CHILD_COUNT_STALE,
                r.name or "",
                f"{r.name} records {r.stored} sub-unit(s) but has {r.actual}",
                float(r.actual),
            )
        )

    for r in db.execute(_PARENTS_SQL, {"cid": cid}):
        tol = _tol(r.parent_ha)
        name = r.pname or ""
        if (r.outside_ha or 0) > tol:
            out.append(Violation(CHILD_OUTSIDE_PARENT, name, f"sub-units of {name} reach {r.outside_ha:.2f} ha outside it", float(r.outside_ha)))
        if (r.overlap_ha or 0) > _overlap_tol(r.parent_ha):
            out.append(Violation(CHILDREN_OVERLAP, name, f"sub-units of {name} overlap each other by {r.overlap_ha:.3f} ha", float(r.overlap_ha)))
        if (r.uncovered_ha or 0) > tol:
            out.append(Violation(CHILDREN_DO_NOT_COVER_PARENT, name, f"sub-units of {name} leave {r.uncovered_ha:.2f} ha of it uncovered", float(r.uncovered_ha)))

    for r in db.execute(_ROOTS_SQL, {"cid": cid}):
        if (r.n or 0) < 2:
            continue
        overlap_ha = max((r.sum_a or 0) - (r.union_a or 0), 0) / 10000.0
        if overlap_ha > _overlap_tol((r.union_a or 0) / 10000.0):
            what = "compartments" if r.comp else "blocks"
            out.append(Violation(CHILDREN_OVERLAP, TOP_LEVEL, f"the top-level {what} overlap each other by {overlap_ha:.3f} ha", float(overlap_ha)))
    return out


def keys(violations: Iterable[Violation]) -> Set[Tuple[str, str]]:
    return {v.key for v in violations}


def new_violations(before: Iterable[Violation], after: Iterable[Violation]) -> List[Violation]:
    """The violations in ``after`` that were not already in ``before`` (same rule, same unit) - plus an OVERLAP that already existed
    and has grown by more than ``OVERLAP_WORSE_BY_HA``: an edit may not make an overlap worse, though it is not locked out of
    the forest for having one."""
    was = {v.key: v for v in before}
    out: List[Violation] = []
    for v in after:
        old = was.get(v.key)
        if old is None or (v.code == CHILDREN_OVERLAP and v.value > old.value + OVERLAP_WORSE_BY_HA):
            out.append(v)
    return out
