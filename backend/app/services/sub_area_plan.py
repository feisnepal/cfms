"""Sub-areas and the yearly activities plan are one thing (owner rule 2026-10-08).

A sub-area (an entry of ``calculations.result_data['sub_areas']``) must be tied to the plan, except private land. It is
*planned* when at least one REAL plan line points at it, either

* a per-sub-area line (``proposed_yearly_activities.sub_area_id``), or
* a forest line assigned to it (``activity_spatial_assignments`` of type ``sub_area``).

A line the user has not given numbers to does not count: ``reviewed_at`` is the system's "the numbers are the user's" mark
(set when numbers are typed, when the wizard supplies them, or on Confirm), and the legacy starting values (quantity 1,
Rs 5,000 in every year) are a placeholder besides. Otherwise "add activity" and typing nothing would satisfy the rule.

Both stored links need a block (a database CHECK), so a sub-area that lies in no unit cannot be planned: it is reported
as ``no_unit`` (fix the geometry), never as "needs a plan".

Pure reads plus ``create_plan_lines``; the routes and the issue gate call these.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.sub_area_kinds import STRIP_CATEGORIES
from ..models.calculation import Calculation
from ..models.yearly_activities import PotentialActivity, ProposedYearlyActivity
from . import yearly_plan_service as plan
from .forest_units.hierarchy import leaf_unit_by_overlap, leaf_unit_ids
from .yearly_plan_rules import planned_years

logger = logging.getLogger(__name__)

#: Categories that need no plan. Private land is not the forest's to plan; a strip (fire line) is planned through its own
#: yearly activity, created from the strip. ``office`` is NOT exempt.
SUB_AREA_PLAN_EXEMPT_CATEGORIES = frozenset({"private_land"}) | frozenset(STRIP_CATEGORIES)

#: Starting suggestions: sub-area category -> ``potential_activities.map_kind`` values. Suggestions only - the user may
#: pick any activity. Matched on ``map_kind``, never on names.
SUB_AREA_ACTIVITY_SUGGESTIONS: Dict[str, tuple] = {
    "plantation": ("plantation",),
    "agroforestry": ("agroforestry_area",),
    "biodiversity": ("biodiversity_block",),
    "tourist": ("ecotourism_site",),
    "pro-poor": ("propoor_plot",),
    "religious": ("religious_cultural",),
    "water_hole": ("water_hole", "water_source_protection"),
    "protected": ("grazing_closure", "anr_area", "signboard"),
    "tree_strata": ("silviculture_area",),
    "wildlife_corridor": ("biodiversity_block", "fire_line"),
    "office": ("community_infrastructure",),
    "fire_line": ("fire_line",),
}

# states
EXEMPT = "exempt"
PLANNED = "planned"
NEEDS_PLAN = "needs_plan"
NO_UNIT = "no_unit"
NO_ID = "no_id"


def is_exempt(sub_area: Dict[str, Any]) -> bool:
    return bool(
        sub_area.get("is_excluded")
        or sub_area.get("isExcluded")
        or (sub_area.get("category") in SUB_AREA_PLAN_EXEMPT_CATEGORIES)
    )


def _is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------------------- the unit of a sub-area
def resolve_sub_area_unit(
    db: Session, calculation_id: UUID, sub_area: Dict[str, Any], leaves: Optional[set] = None
) -> Optional[str]:
    """The leaf unit a sub-area belongs to: the one it says (if it still exists), else the one it overlaps most."""
    leaves = leaf_unit_ids(db, calculation_id) if leaves is None else leaves
    stored = str(sub_area.get("blockId") or sub_area.get("block_id") or "")
    if stored in leaves:
        return stored
    if not sub_area.get("geometry"):
        return None
    try:
        with db.begin_nested():
            hit = leaf_unit_by_overlap(db, calculation_id, json.dumps(sub_area["geometry"]))
    except Exception:  # noqa: BLE001 -- one unreadable sub-area geometry must not hide the others
        logger.debug("resolve_sub_area_unit: sub-area %s unreadable", sub_area.get("id"), exc_info=True)
        return None
    return hit or None


# ------------------------------------------------------------------------------- what is planned
def _real_lines_by_sub_area(db: Session, calculation_id: UUID) -> Dict[str, List[str]]:
    """``{sub_area_id: [line ids]}`` of the REAL (not placeholder, planned in some year) lines tied to each sub-area."""
    lines = (
        db.query(ProposedYearlyActivity)
        .filter(ProposedYearlyActivity.calculation_id == calculation_id)
        .all()
    )
    if not lines:
        return {}
    rows = plan.year_rows_for(db, [ln.id for ln in lines])
    real: Dict[Any, ProposedYearlyActivity] = {}
    for ln in lines:
        by_year = rows.get(ln.id, {})
        if ln.reviewed_at is None or plan.placeholder_fields(ln, by_year):
            continue
        if not planned_years(ln.default_quantity, ln.default_yearly_budget, by_year):
            continue
        real[ln.id] = ln

    out: Dict[str, List[str]] = {}
    for ln in real.values():
        if ln.sub_area_id is not None:
            out.setdefault(str(ln.sub_area_id), []).append(str(ln.id))
    assigned = db.execute(
        text(
            "SELECT a.sub_area_id::text, a.proposed_activity_id FROM activity_spatial_assignments a "
            "JOIN proposed_yearly_activities p ON p.id = a.proposed_activity_id "
            "WHERE p.calculation_id = :c AND a.assignment_type = 'sub_area' AND a.sub_area_id IS NOT NULL"
        ),
        {"c": str(calculation_id)},
    ).fetchall()
    for sub_area_id, line_id in assigned:
        if line_id in real:
            out.setdefault(sub_area_id, []).append(str(line_id))
    return {k: sorted(set(v)) for k, v in out.items()}


def sub_area_plan_status(db: Session, calculation: Calculation) -> List[Dict[str, Any]]:
    """One entry per sub-area: its state (exempt / planned / needs_plan / no_unit / no_id) and the real lines tied to it."""
    sub_areas = (calculation.result_data or {}).get("sub_areas", []) or []
    if not sub_areas:
        return []
    leaves = leaf_unit_ids(db, calculation.id)
    real = _real_lines_by_sub_area(db, calculation.id)
    out: List[Dict[str, Any]] = []
    for sa in sub_areas:
        sa_id = str(sa.get("id") or "")
        entry: Dict[str, Any] = {
            "id": sa_id,
            "name": sa.get("name") or "",
            "category": sa.get("category") or "",
            "area_ha": sa.get("area_hectares"),
            "unit_id": None,
            "line_ids": [],
        }
        if is_exempt(sa):
            entry["state"] = EXEMPT
        elif not _is_uuid(sa_id):
            entry["state"] = NO_ID
        else:
            entry["unit_id"] = resolve_sub_area_unit(db, calculation.id, sa, leaves)
            entry["line_ids"] = real.get(sa_id, [])
            if entry["line_ids"]:
                entry["state"] = PLANNED
            elif entry["unit_id"] is None:
                entry["state"] = NO_UNIT
            else:
                entry["state"] = NEEDS_PLAN
        out.append(entry)
    return out


def sub_areas_needing_plan(status: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Those that stop the issue step: every non-exempt sub-area without a real plan line (including ones that cannot be
    planned yet because they lie in no unit or have no id - they must be fixed first)."""
    return [s for s in status if s["state"] in (NEEDS_PLAN, NO_UNIT, NO_ID)]


def assert_sub_areas_planned(db: Session, calculation: Calculation) -> None:
    """The issue gate: refuse (409, bilingual, naming the sub-areas) while any non-exempt sub-area has no plan."""
    from ..core.exceptions import i18n_error

    missing = sub_areas_needing_plan(sub_area_plan_status(db, calculation))
    if missing:
        names = ", ".join((m["name"] or m["id"] or "?") for m in missing[:10])
        if len(missing) > 10:
            names += ", ..."
        raise i18n_error(409, "yearly_plan.sub_areas_need_plan", count=len(missing), names=names)


# ------------------------------------------------------------------------------- when a sub-area goes away
def linked_lines(db: Session, calculation_id: UUID, sub_area_ids: Iterable[str]) -> List[Dict[str, Any]]:
    """Every plan line tied to these sub-areas, real or not: ``[{line_id, activity, sub_area_id, via}]``. ``via`` is ``line``
    (the line IS the sub-area's) or ``assignment`` (a forest line assigned to it)."""
    ids = [str(i) for i in sub_area_ids if _is_uuid(i)]
    if not ids:
        return []
    rows = db.execute(
        text(
            "SELECT p.id::text, COALESCE(m.activities, ''), p.sub_area_id::text, 'line' "
            "FROM proposed_yearly_activities p LEFT JOIN potential_activities m ON m.id = p.potential_activity_id "
            "WHERE p.calculation_id = :c AND p.sub_area_id = ANY(CAST(:ids AS uuid[])) "
            "UNION ALL "
            "SELECT p.id::text, COALESCE(m.activities, ''), a.sub_area_id::text, 'assignment' "
            "FROM activity_spatial_assignments a JOIN proposed_yearly_activities p ON p.id = a.proposed_activity_id "
            "LEFT JOIN potential_activities m ON m.id = p.potential_activity_id "
            "WHERE p.calculation_id = :c AND a.assignment_type = 'sub_area' AND a.sub_area_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"c": str(calculation_id), "ids": ids},
    ).fetchall()
    return [{"line_id": r[0], "activity": r[1], "sub_area_id": r[2], "via": r[3]} for r in rows]


def assert_choice_made(db: Session, calculation_id: UUID, sub_area_ids: Iterable[str], choice: Optional[str]) -> None:
    """A sub-area with plan lines is never removed silently: without ``choice`` (``delete`` or ``keep``) answer 409 with the lines."""
    from ..core.exceptions import i18n_error

    lines = linked_lines(db, calculation_id, sub_area_ids)
    if not lines:
        return
    if choice not in ("delete", "keep"):
        names = ", ".join(sorted({ln["activity"] or "?" for ln in lines})[:8])
        exc = i18n_error(409, "yearly_plan.sub_area_has_plan_lines", count=len(lines), names=names)
        exc.detail["lines"] = lines
        raise exc


def release_sub_areas(db: Session, calculation_id: UUID, sub_area_ids: Iterable[str], choice: str) -> Dict[str, int]:
    """Untie the plan from sub-areas that are going away. ``delete``: the sub-areas' own lines are deleted. ``keep``: they become
    forest-level lines (or are dropped when the forest already has that activity, which already covers it). Assignments of a
    forest line to a removed sub-area are always removed. The caller commits."""
    from .optimistic_lock import check_and_bump

    ids = [str(i) for i in sub_area_ids if _is_uuid(i)]
    out = {"deleted": 0, "kept": 0, "unassigned": 0}
    if not ids:
        return out
    out["unassigned"] = db.execute(
        text(
            "DELETE FROM activity_spatial_assignments a USING proposed_yearly_activities p "
            "WHERE p.id = a.proposed_activity_id AND p.calculation_id = :c AND a.assignment_type = 'sub_area' "
            "AND a.sub_area_id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"c": str(calculation_id), "ids": ids},
    ).rowcount
    lines = (
        db.query(ProposedYearlyActivity)
        .filter(
            ProposedYearlyActivity.calculation_id == calculation_id,
            ProposedYearlyActivity.sub_area_id.in_([UUID(i) for i in ids]),
        )
        .all()
    )
    for ln in lines:
        forest_level = plan._find_line(db, calculation_id, ln.potential_activity_id)
        if choice == "keep" and forest_level is None:
            check_and_bump(db, "yearly_plan", ln.id, None)
            ln.sub_area_id = None
            ln.block_id = None
            db.flush()
            out["kept"] += 1
        else:
            db.delete(ln)
            out["deleted"] += 1
    db.flush()
    return out


def orphaned_sub_area_links(db: Session) -> List[Dict[str, Any]]:
    """Plan lines and assignments, in ANY forest, that point at a sub-area which no longer exists (read-only).
    ``[{calculation_id, line_id, sub_area_id, via}]``; the delete, promote and boundary-drop flows are meant to leave none."""
    rows = db.execute(
        text(
            """
            WITH live AS (
                SELECT c.id AS calc_id, sa->>'id' AS sub_area_id
                FROM calculations c, jsonb_array_elements(COALESCE(c.result_data->'sub_areas', '[]'::jsonb)) sa
            )
            SELECT p.calculation_id::text, p.id::text, p.sub_area_id::text, 'line'
            FROM proposed_yearly_activities p
            WHERE p.sub_area_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM live l WHERE l.calc_id = p.calculation_id AND l.sub_area_id = p.sub_area_id::text)
            UNION ALL
            SELECT p.calculation_id::text, p.id::text, a.sub_area_id::text, 'assignment'
            FROM activity_spatial_assignments a JOIN proposed_yearly_activities p ON p.id = a.proposed_activity_id
            WHERE a.assignment_type = 'sub_area' AND a.sub_area_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM live l WHERE l.calc_id = p.calculation_id AND l.sub_area_id = a.sub_area_id::text)
            """
        )
    ).fetchall()
    return [{"calculation_id": r[0], "line_id": r[1], "sub_area_id": r[2], "via": r[3]} for r in rows]


# ------------------------------------------------------------------------------- suggestions and creation
def suggested_activities(db: Session, category: str) -> List[Dict[str, Any]]:
    """The master activities suggested for a sub-area category (may be empty)."""
    kinds = SUB_AREA_ACTIVITY_SUGGESTIONS.get(category or "", ())
    if not kinds:
        return []
    rows = (
        db.query(PotentialActivity)
        .filter(PotentialActivity.map_kind.in_(kinds))
        .order_by(PotentialActivity.id)
        .all()
    )
    return [
        {"id": r.id, "activity": r.activities, "program": r.progarms, "unit": r.unit, "map_kind": r.map_kind}
        for r in rows
    ]


def create_plan_lines(
    db: Session, calculation: Calculation, sub_area_id: str, potential_activity_ids: Iterable[int]
) -> List[Dict[str, Any]]:
    """Give a sub-area plan lines for the chosen activities. A hectare activity starts at the sub-area's area (a real number,
    so the line is a plan); any other unit starts without the user's numbers and does not count as a plan until they are
    typed. The caller commits."""
    sub_area = next(
        (s for s in (calculation.result_data or {}).get("sub_areas", []) or [] if str(s.get("id")) == str(sub_area_id)),
        None,
    )
    if sub_area is None:
        raise LookupError("sub_area_not_found")
    unit_id = resolve_sub_area_unit(db, calculation.id, sub_area)
    if unit_id is None:
        raise ValueError("sub_area_no_unit")
    area = sub_area.get("area_hectares")
    made: List[Dict[str, Any]] = []
    for pid in dict.fromkeys(potential_activity_ids):
        master = db.get(PotentialActivity, pid)
        if master is None:
            raise LookupError("activity_not_found")
        in_ha = (master.unit or "").strip() in plan._UNIT_HA and area
        # a strip also knows its length: a kilometre activity starts at it, so the plan line and the map agree (FL-6)
        length_m = sub_area.get("length_m")
        in_km = (master.unit or "").strip() in plan._UNIT_KM and length_m
        if in_ha:
            numbers = plan.PlanNumbers(quantity=Decimal(str(round(float(area), 4))))
        elif in_km:
            numbers = plan.PlanNumbers(quantity=Decimal(str(round(float(length_m) / 1000.0, 4))))
        else:
            numbers = None
        line, created, _rows = plan.get_or_create_line(
            db,
            calculation.id,
            pid,
            numbers=numbers,
            block_id=UUID(unit_id),
            sub_area_id=UUID(str(sub_area_id)),
        )
        made.append({"line_id": str(line.id), "potential_activity_id": pid, "created": created})
    return made
