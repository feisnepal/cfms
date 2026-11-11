"""The yearly activity plan: one place for the rules both screens share.

The map workspace and the legacy page write the same three tables (plan line, year rows, drawn
features). This module holds the logic so the routes stay thin and the legacy endpoints and the new
facade cannot drift apart (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.1):

* get-or-create the plan line for an activity, race-safe (partial unique indexes, migration 091);
* the **first-value rule** (§4.7, D15) and the **reviewed rule** — what a user's first typed number
  does to the other years, and when the "placeholder" flag clears;
* measured quantity from drawn geometry, and location *derived* from geometry (nothing is stored);
* the per-line read model both screens and the health check use.

Pure rules live in ``yearly_plan_rules``; this module talks to the database.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models.calculation import Calculation
from ..models.yearly_activities import (
    ActivityDrawnFeature,
    ActivityYearDetail,
    PotentialActivity,
    ProposedYearlyActivity,
)
from .optimistic_lock import check_and_bump
from .yearly_plan_rules import (
    PLAN_YEARS,
    effective_budget,
    effective_quantity,
    is_planned,
    planned_years,
    total_budget,
)

logger = logging.getLogger(__name__)

# What the legacy "add activity" wrote for every line (createProposedActivity(…, 1, 5000)): a
# placeholder, not a plan. A line still carrying these in every year and never reviewed is flagged.
STARTING_QUANTITY = Decimal(1)
STARTING_BUDGET = Decimal(5000)

_UNIT_HA = {"हेक्टर", "ha", "hectare", "hectares"}
_UNIT_KM = {"कि.मि.", "km", "kilometer", "kilometre"}
_UNIT_COUNT = {"वटा", "स्थान", "each", "place", "places", "number"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any, default: Decimal = Decimal(0)) -> Decimal:
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


# --------------------------------------------------------------------------- reading
def year_rows_for(
    db: Session, line_ids: Iterable[UUID]
) -> Dict[UUID, Dict[int, ActivityYearDetail]]:
    """``{line_id: {year: row}}`` for the given plan lines."""
    ids = list(line_ids)
    out: Dict[UUID, Dict[int, ActivityYearDetail]] = {}
    if not ids:
        return out
    for row in db.query(ActivityYearDetail).filter(
        ActivityYearDetail.proposed_activity_id.in_(ids)
    ):
        out.setdefault(row.proposed_activity_id, {})[row.year_number] = row
    return out


def starting_value_fields(line: ProposedYearlyActivity, rows: Dict[int, Any]) -> set:
    """Fields (``"quantity"`` / ``"budget"``) that are still at their starting value in EVERY year."""
    fields = set()
    if all(
        effective_quantity(rows.get(y), line.default_quantity) == STARTING_QUANTITY
        for y in PLAN_YEARS
    ):
        fields.add("quantity")
    if all(
        effective_budget(rows.get(y), line.default_yearly_budget) == STARTING_BUDGET
        for y in PLAN_YEARS
    ):
        fields.add("budget")
    return fields


def placeholder_fields(line: ProposedYearlyActivity, rows: Dict[int, Any]) -> set:
    """What is still a placeholder on this line: empty once the line is reviewed."""
    if line.reviewed_at is not None:
        return set()
    return starting_value_fields(line, rows)


# ------------------------------------------------------------------------ measurements
def quantity_from_geometry(
    db: Session, line_id: UUID, unit: Optional[str]
) -> Optional[Decimal]:
    """The quantity the drawn features imply for this unit, or None when the unit cannot be measured.

    hectare -> polygon area, km -> line length, each / place -> number of features. Anything else
    (as needed, bundles, kilograms, cubic feet …) has to be asked of the user.
    """
    unit = (unit or "").strip()
    base = "FROM activity_drawn_features WHERE proposed_activity_id = :id AND deleted_at IS NULL"
    if unit in _UNIT_HA:
        sql = f"SELECT COALESCE(SUM(ST_Area(geometry::geography)), 0) / 10000.0 {base} AND feature_type = 'polygon'"
    elif unit in _UNIT_KM:
        sql = f"SELECT COALESCE(SUM(ST_Length(geometry::geography)), 0) / 1000.0 {base} AND feature_type = 'line'"
    elif unit in _UNIT_COUNT:
        sql = f"SELECT COUNT(*) {base}"
    else:
        return None
    value = db.execute(
        text(sql), {"id": str(line_id)}
    ).scalar()  # noqa: S608 -- static fragments
    return None if value is None else round(_dec(value), 2)


def derive_location(
    db: Session, calculation: Calculation, wkt: str
) -> Dict[str, List[str]]:
    """Blocks and sub-areas a geometry falls in — derived on read, never stored (plan §5.1, D13)."""
    blocks = [
        r[0]
        for r in db.execute(
            text(
                "SELECT COALESCE(block_name, name) FROM forest_blocks "
                "WHERE calculation_id = :c AND ST_Intersects(geometry, ST_GeomFromText(:w, 4326)) "
                "ORDER BY 1"
            ),
            {"c": str(calculation.id), "w": wkt},
        )
    ]
    sub_areas: List[str] = []
    try:
        from shapely import wkt as shapely_wkt
        from shapely.geometry import shape

        target = shapely_wkt.loads(wkt)
        for sa in (calculation.result_data or {}).get("sub_areas", []) or []:
            gj = sa.get("geometry")
            if not gj:
                continue
            try:
                if shape(gj).intersects(target):
                    sub_areas.append(sa.get("name") or "")
            except (
                Exception
            ):  # noqa: BLE001 -- one unreadable sub-area must not hide the others
                logger.debug(
                    "derive_location: unreadable sub-area geometry %s", sa.get("id")
                )
    except (
        Exception
    ):  # noqa: BLE001 -- location is a convenience read; never fail the caller
        logger.debug("derive_location: shapely unavailable or bad wkt", exc_info=True)
    return {"blocks": blocks, "sub_areas": [s for s in sub_areas if s]}


# ---------------------------------------------------------------------- get-or-create
@dataclass
class PlanNumbers:
    """What the user entered for a new plan line (the wizard's numbers step)."""

    quantity: Optional[Decimal] = None
    budget: Optional[Decimal] = None


def _master_default_budget(master: Optional[PotentialActivity]) -> Decimal:
    raw = getattr(master, "yearly_budget", None)
    if raw in (None, ""):
        return Decimal(0)
    value = _dec(str(raw).replace(",", ""), Decimal(0))
    return value if value > 0 else Decimal(0)


def get_or_create_line(
    db: Session,
    calculation_id: UUID,
    potential_activity_id: int,
    *,
    numbers: Optional[PlanNumbers] = None,
    years: Optional[List[int]] = None,
    block_id: Optional[UUID] = None,
    sub_area_id: Optional[UUID] = None,
) -> Tuple[ProposedYearlyActivity, bool, List[int]]:
    """The plan line for an activity, created if missing: the forest-level line, or - when ``block_id`` and
    ``sub_area_id`` are given - the line of that one sub-area (its own numbers).

    Returns ``(line, created, created_year_rows)``. Safe under concurrency: the partial unique
    index makes a second insert fail, and the loser re-reads the winner's row. A line the caller
    created *with the user's numbers* (the wizard) is created reviewed; a raw draw creates it
    unreviewed, with the quantity 1 and the budget from the master list (else 0), and the health
    check then says what is missing. A new line gets all ten year rows: the chosen years at the
    line's values, the others an explicit 0 / 0 (plan §5.4).
    """
    existing = _find_line(db, calculation_id, potential_activity_id, block_id, sub_area_id)
    if existing is not None:
        return existing, False, []

    master = db.get(PotentialActivity, potential_activity_id)
    quantity = (
        numbers.quantity
        if numbers and numbers.quantity is not None and numbers.quantity > 0
        else Decimal(1)
    )
    if numbers and numbers.budget is not None:
        budget = numbers.budget
    else:
        budget = _master_default_budget(master)
    line = ProposedYearlyActivity(
        calculation_id=calculation_id,
        potential_activity_id=potential_activity_id,
        default_quantity=quantity,
        default_yearly_budget=budget,
        status="proposed",
        reviewed_at=_now() if numbers is not None else None,
        block_id=block_id,
        sub_area_id=sub_area_id,
    )
    try:
        with db.begin_nested():
            db.add(line)
            db.flush()
    except IntegrityError:
        # another request created it first: use theirs
        again = _find_line(db, calculation_id, potential_activity_id, block_id, sub_area_id)
        if (
            again is None
        ):  # pragma: no cover -- an IntegrityError that is not the duplicate index
            raise
        return again, False, []

    chosen = sorted({y for y in (years or [1]) if y in PLAN_YEARS}) or [1]
    created: List[int] = []
    for year in PLAN_YEARS:
        on = year in chosen
        db.add(
            ActivityYearDetail(
                proposed_activity_id=line.id,
                year_number=year,
                quantity=quantity if on else 0,
                yearly_budget=budget if on else 0,
            )
        )
        created.append(year)
    db.flush()
    return line, True, created


def _find_line(
    db: Session,
    calculation_id: UUID,
    potential_activity_id: int,
    block_id: Optional[UUID] = None,
    sub_area_id: Optional[UUID] = None,
):
    """The forest-level line (no block, no sub-area), or the line of one sub-area in one block."""
    q = db.query(ProposedYearlyActivity).filter(
        ProposedYearlyActivity.calculation_id == calculation_id,
        ProposedYearlyActivity.potential_activity_id == potential_activity_id,
    )
    if sub_area_id is not None:
        q = q.filter(
            ProposedYearlyActivity.block_id == block_id,
            ProposedYearlyActivity.sub_area_id == sub_area_id,
        )
    else:
        q = q.filter(
            ProposedYearlyActivity.block_id.is_(None),
            ProposedYearlyActivity.sub_area_id.is_(None),
        )
    return q.first()


def _forest_level_line(db: Session, calculation_id: UUID, potential_activity_id: int):
    return _find_line(db, calculation_id, potential_activity_id)


def plan_years_too(
    db: Session, line: ProposedYearlyActivity, years: Iterable[int]
) -> List[int]:
    """ "Plan this year too": give each unplanned year the line's default values. Returns the years set."""
    rows = year_rows_for(db, [line.id]).get(line.id, {})
    done: List[int] = []
    for year in sorted(set(years)):
        if year not in PLAN_YEARS:
            continue
        row = rows.get(year)
        if is_planned(
            effective_quantity(row, line.default_quantity),
            effective_budget(row, line.default_yearly_budget),
        ):
            continue
        if row is None:
            row = ActivityYearDetail(proposed_activity_id=line.id, year_number=year)
            db.add(row)
        row.quantity = line.default_quantity
        row.yearly_budget = line.default_yearly_budget
        done.append(year)
    if done:
        db.flush()
    return done


# ------------------------------------------------------------------------ editing a line
@dataclass
class YearEdit:
    year: int
    quantity: Optional[Decimal] = None
    budget: Optional[Decimal] = None
    set_quantity: bool = False
    set_budget: bool = False


@dataclass
class LineEdit:
    default_quantity: Optional[Decimal] = None
    default_yearly_budget: Optional[Decimal] = None
    years: List[YearEdit] = field(default_factory=list)
    notes: Optional[str] = None
    status: Optional[str] = None
    set_notes: bool = False
    unreview: bool = False


def apply_line_edit(
    db: Session,
    line: ProposedYearlyActivity,
    edit: LineEdit,
    expected_version: Optional[int],
) -> List[int]:
    """Edit a plan line's numbers in one transaction; returns the years filled by the first-value rule.

    Takes the line's version first (409 when stale). Then applies the edit and:

    * **first-value rule** (D15): on a line the user has not reviewed, the amount typed for ONE year
      (or the default) is also used for every *other* year that still holds the starting value for
      that field. A year the user has changed, and any 0, is never overwritten; a line with real
      numbers is never touched;
    * **reviewed rule**: ``reviewed_at`` is set only when, after the edit, neither quantity nor
      budget is still at its starting value in every year — otherwise the untouched field keeps being
      flagged. (Confirm sets it regardless.)
    """
    check_and_bump(db, "yearly_plan", line.id, expected_version)

    rows = year_rows_for(db, [line.id]).get(line.id, {})
    was_unreviewed = line.reviewed_at is None
    old_default_q, old_default_b = line.default_quantity, line.default_yearly_budget

    touched: Dict[str, Dict[int, Decimal]] = {"quantity": {}, "budget": {}}
    for item in edit.years:
        if item.year not in PLAN_YEARS:
            raise ValueError(f"year {item.year} is outside 1-10")
        row = rows.get(item.year)
        if row is None:
            row = ActivityYearDetail(
                proposed_activity_id=line.id, year_number=item.year
            )
            db.add(row)
            rows[item.year] = row
        if item.set_quantity:
            row.quantity = item.quantity
            touched["quantity"][item.year] = _dec(item.quantity)
        if item.set_budget:
            row.yearly_budget = item.budget
            touched["budget"][item.year] = _dec(item.budget)

    filled: set = set()
    filled_fields: set = set()
    if was_unreviewed:
        for fld, default_new, old_default, start in (
            ("quantity", edit.default_quantity, old_default_q, STARTING_QUANTITY),
            ("budget", edit.default_yearly_budget, old_default_b, STARTING_BUDGET),
        ):
            years_typed = touched[fld]
            entered: Optional[Decimal] = None
            if len(years_typed) == 1:
                entered = next(iter(years_typed.values()))
            elif not years_typed and default_new is not None:
                entered = _dec(default_new)
            if entered is None or entered == start:
                continue
            for year in PLAN_YEARS:
                if year in years_typed:
                    continue
                row = rows.get(year)
                eff = (
                    effective_quantity(row, old_default)
                    if fld == "quantity"
                    else effective_budget(row, old_default)
                )
                if eff != start:
                    continue  # the user changed this year (a 0 included): never overwrite
                if row is None:
                    row = ActivityYearDetail(
                        proposed_activity_id=line.id, year_number=year
                    )
                    db.add(row)
                    rows[year] = row
                if fld == "quantity":
                    row.quantity = entered
                else:
                    row.yearly_budget = entered
                filled.add(year)
                filled_fields.add(fld)

    if edit.default_quantity is not None:
        line.default_quantity = edit.default_quantity
    if edit.default_yearly_budget is not None:
        line.default_yearly_budget = edit.default_yearly_budget
    # a first value that filled the rest also becomes the line's default (quantity stays > 0)
    if (
        "quantity" in filled_fields
        and len(touched["quantity"]) == 1
        and edit.default_quantity is None
    ):
        typed = next(iter(touched["quantity"].values()))
        if typed > 0 and old_default_q == STARTING_QUANTITY:
            line.default_quantity = typed
    if (
        "budget" in filled_fields
        and len(touched["budget"]) == 1
        and edit.default_yearly_budget is None
    ):
        if old_default_b == STARTING_BUDGET:
            line.default_yearly_budget = next(iter(touched["budget"].values()))
    if edit.set_notes:
        line.notes = edit.notes
    if edit.status is not None:
        line.status = edit.status

    db.flush()
    if edit.unreview:
        line.reviewed_at = None  # an Undo of an edit that had made the line reviewed
    if line.reviewed_at is None and not starting_value_fields(line, rows):
        line.reviewed_at = _now()
    db.flush()
    return sorted(filled)


def confirm_line(
    db: Session, line: ProposedYearlyActivity, expected_version: Optional[int] = None
) -> None:
    """ "These numbers are right": mark the line reviewed without changing them."""
    check_and_bump(db, "yearly_plan", line.id, expected_version)
    line.reviewed_at = _now()
    db.flush()


# ------------------------------------------------------------------------- read model
def location_mode(
    master: Optional[PotentialActivity],
    line: ProposedYearlyActivity,
    feature_count: int,
    assigned: Optional[Dict[str, Any]] = None,
) -> str:
    """not_applicable | places | whole_forest | units | needs_location (plan §4.4b). Never hides existing data.

    ``units``: no place is drawn, but blocks / sub-areas were chosen for the activity (the yearly-activities pages).
    ``assigned`` is what :func:`derive_line_assignments` returned for this line.
    """
    if feature_count > 0:
        return "places"
    if not (master is not None and master.requires_map):
        return "not_applicable"
    if line.assign_to_all_blocks or (assigned and assigned.get("all")):
        return "whole_forest"
    if assigned and assigned.get("units"):
        return "units"
    return "needs_location"


def _measured(
    db: Session, line_id: UUID, master: Optional[PotentialActivity]
) -> Optional[float]:
    """The quantity the line's drawn places measure, or None when the unit cannot be measured or nothing counts
    (an area unit with only points drawn measures 0: that is "nothing measured", not "the quantity is 0").
    """
    try:
        with db.begin_nested():
            value = quantity_from_geometry(db, line_id, getattr(master, "unit", None))
    except Exception:  # noqa: BLE001 -- a hint next to the numbers; never fail the plan
        logger.debug("measured quantity failed for %s", line_id, exc_info=True)
        return None
    return float(value) if value is not None and value > 0 else None


def derive_line_assignments(
    db: Session, calculation: Calculation, line_ids: Iterable[UUID]
) -> Dict[UUID, Dict[str, Any]]:
    """Where each line applies by ASSIGNMENT — the whole forest, or the blocks / sub-areas chosen for it.

    Read from ``activity_spatial_assignments`` (the yearly-activities pages write them). Best-effort like every
    location read: a failure gives an empty answer, never an error.
    """
    ids = [str(i) for i in line_ids]
    if not ids:
        return {}
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    "SELECT a.proposed_activity_id, a.assignment_type, a.sub_area_id::text, "
                    "       COALESCE(b.block_name, b.name) "
                    "FROM activity_spatial_assignments a "
                    "LEFT JOIN forest_blocks b ON b.id = a.block_id "
                    "WHERE a.proposed_activity_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": ids},
            ).fetchall()
    except (
        Exception
    ):  # noqa: BLE001 -- a location is a convenience read; never fail the plan
        logger.debug("derive_line_assignments failed", exc_info=True)
        return {}
    sub_area_names = {
        str(sa.get("id")): sa.get("name")
        for sa in ((calculation.result_data or {}).get("sub_areas", []) or [])
        if sa.get("id") and sa.get("name")
    }
    out: Dict[UUID, Dict[str, Any]] = {}
    for line_id, kind, sub_area_id, block_name in rows:
        entry = out.setdefault(line_id, {"all": False, "units": []})
        if kind == "all_blocks":
            entry["all"] = True
        elif kind == "sub_area":
            name = sub_area_names.get(sub_area_id) or block_name
            if name:
                entry["units"].append(name)
        elif block_name:
            entry["units"].append(block_name)
    for entry in out.values():
        entry["units"] = sorted(set(entry["units"]), key=_natural_key)
    return out


# The sub-area category a drawn activity of each kind belongs in (owner, 2026-10-14; ACTIVITY_KIND_CATEGORY_TABLE_DRAFT.md).
# Kinds with no entry (nursery, road, coupe ...) link to a sub-area by position only. A match only decides which sub-area is
# named first when several overlap; it never hides one.
KIND_SUB_AREA_CATEGORY: Dict[str, str] = {
    "plantation": "plantation",
    "agroforestry_area": "agroforestry",
    "biodiversity_block": "biodiversity",
    "propoor_plot": "pro-poor",
    "encroachment": "encroached",
    "ecotourism_site": "tourist",
    "religious_cultural": "religious",
    "water_hole": "water_hole",
}


def derive_line_sub_areas(
    db: Session,
    calculation: Calculation,
    lines: Iterable[Tuple[UUID, Optional[str]]],
) -> Dict[UUID, List[Dict[str, Any]]]:
    """The sub-areas each plan line's drawn places fall in: ``[{id, name, category, matches}]`` per line.

    ``lines`` is ``(line id, the activity's map_kind)``. Derived on read from the geometry and never stored, so a sub-area that is
    edited, moved or deleted can never leave a stale link behind (owner, 2026-10-15). ``matches`` is true when the sub-area's
    category is the one this kind of activity belongs in; those come first. Best-effort like every location read.
    """
    kinds = {str(i): k for i, k in lines}
    if not kinds:
        return {}
    sub_areas = [
        sa for sa in ((calculation.result_data or {}).get("sub_areas", []) or []) if sa.get("id") and sa.get("geometry")
    ]
    if not sub_areas:
        return {}
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    "SELECT proposed_activity_id, ST_AsText(geometry) FROM activity_drawn_features "
                    "WHERE proposed_activity_id = ANY(CAST(:ids AS uuid[])) AND deleted_at IS NULL"
                ),
                {"ids": list(kinds)},
            ).fetchall()
    except Exception:  # noqa: BLE001 -- a location is a convenience read; never fail the plan
        logger.debug("derive_line_sub_areas failed", exc_info=True)
        return {}
    try:
        from shapely import wkt as shapely_wkt
        from shapely.geometry import shape
    except Exception:  # noqa: BLE001
        return {}
    shapes: List[Tuple[Dict[str, Any], Any]] = []
    for sa in sub_areas:
        try:
            shapes.append((sa, shape(sa["geometry"])))
        except Exception:  # noqa: BLE001 -- one unreadable sub-area must not hide the others
            logger.debug("derive_line_sub_areas: unreadable sub-area %s", sa.get("id"))
    found: Dict[UUID, Dict[str, Dict[str, Any]]] = {}
    for line_id, wkt in rows:
        try:
            target = shapely_wkt.loads(wkt)
        except Exception:  # noqa: BLE001
            continue
        wanted = KIND_SUB_AREA_CATEGORY.get(kinds.get(str(line_id)) or "")
        for sa, geom in shapes:
            if geom.intersects(target):
                category = sa.get("category") or ""
                found.setdefault(line_id, {})[str(sa["id"])] = {
                    "id": str(sa["id"]),
                    "name": sa.get("name") or "",
                    "category": category,
                    "matches": bool(wanted and category == wanted),
                }
    return {
        line_id: sorted(by_id.values(), key=lambda e: (not e["matches"], _natural_key(e["name"])))
        for line_id, by_id in found.items()
    }


def _natural_key(name: str) -> Tuple[Any, ...]:
    """ "C-2" before "C-10": digits compare as numbers."""
    import re

    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", name or "")
    )


def derive_line_units(
    db: Session, calculation_id: UUID, line_ids: Iterable[UUID]
) -> Dict[UUID, List[str]]:
    """The forest units (blocks / compartments) in which each plan line's live places fall.

    Derived on read and never stored (plan §5.1, D13). Only the LEAF units are named — a block that has been
    divided into compartments is not listed beside them. Best-effort: a location is a convenience next to the
    numbers, so a failure here gives an empty answer, never an error (the read runs in a SAVEPOINT).
    """
    ids = [str(i) for i in line_ids]
    if not ids:
        return {}
    try:
        with db.begin_nested():
            rows = db.execute(
                text(
                    "SELECT f.proposed_activity_id, COALESCE(b.block_name, b.name) "
                    "FROM activity_drawn_features f "
                    "JOIN forest_blocks b ON b.calculation_id = :c "
                    "  AND ST_Intersects(b.geometry, ST_SetSRID(f.geometry, 4326)) "
                    "WHERE f.proposed_activity_id = ANY(CAST(:ids AS uuid[])) "
                    "  AND f.deleted_at IS NULL "
                    "  AND NOT EXISTS (SELECT 1 FROM forest_blocks k WHERE k.parent_block_id = b.id) "
                    "GROUP BY 1, 2"
                ),
                {"c": str(calculation_id), "ids": ids},
            ).fetchall()
    except (
        Exception
    ):  # noqa: BLE001 -- a location is a convenience read; never fail the plan
        logger.debug("derive_line_units failed", exc_info=True)
        return {}
    out: Dict[UUID, List[str]] = {}
    for line_id, unit in rows:
        if unit:
            out.setdefault(line_id, []).append(unit)
    return {k: sorted(v, key=_natural_key) for k, v in out.items()}


def forest_units_with_subareas(
    db: Session, calculation: Calculation
) -> List[Dict[str, Any]]:
    """The units an activity can be assigned to — the forest's LEAF blocks / compartments, each with its sub-areas.

    Read from ``forest_blocks`` (the single source of truth for units), not from the legacy ``result_data`` arrays.
    A sub-area that does not say which unit it is in is matched to the unit it overlaps most; one that overlaps
    none is left out (an assignment needs a unit). Shape: ``[{block_id, block_name, sub_areas: [{id, name,
    category}]}]``.
    """
    rows = db.execute(
        text(
            "SELECT b.id::text, COALESCE(b.block_name, b.name) FROM forest_blocks b "
            "WHERE b.calculation_id = :c "
            "AND NOT EXISTS (SELECT 1 FROM forest_blocks k WHERE k.parent_block_id = b.id)"
        ),
        {"c": str(calculation.id)},
    ).fetchall()
    units = sorted(
        ({"block_id": r[0], "block_name": r[1] or "", "sub_areas": []} for r in rows),
        key=lambda u: _natural_key(u["block_name"]),
    )
    by_id = {u["block_id"]: u for u in units}
    for sa in (calculation.result_data or {}).get("sub_areas", []) or []:
        sa_id, name = str(sa.get("id") or ""), sa.get("name") or ""
        if len(sa_id) != 36:
            continue
        unit_id = str(sa.get("blockId") or sa.get("block_id") or "")
        if unit_id not in by_id and sa.get("geometry"):
            try:
                with db.begin_nested():
                    hit = db.execute(
                        text(
                            "SELECT b.id::text FROM forest_blocks b "
                            "WHERE b.calculation_id = :c "
                            "AND NOT EXISTS (SELECT 1 FROM forest_blocks k WHERE k.parent_block_id = b.id) "
                            "AND ST_Intersects(b.geometry, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) "
                            "ORDER BY ST_Area(ST_Intersection(b.geometry, "
                            "ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326))) DESC LIMIT 1"
                        ),
                        {"c": str(calculation.id), "g": json.dumps(sa["geometry"])},
                    ).scalar()
                unit_id = hit or ""
            except (
                Exception
            ):  # noqa: BLE001 -- one unreadable sub-area geometry must not hide the others
                logger.debug(
                    "forest_units_with_subareas: sub-area %s skipped",
                    sa_id,
                    exc_info=True,
                )
                unit_id = ""
        if unit_id in by_id:
            by_id[unit_id]["sub_areas"].append(
                {"id": sa_id, "name": name, "category": sa.get("category") or ""}
            )
    return units


def feature_counts(db: Session, line_ids: Iterable[UUID]) -> Dict[UUID, int]:
    ids = list(line_ids)
    if not ids:
        return {}
    rows = (
        db.query(ActivityDrawnFeature.proposed_activity_id, text("count(*)"))
        .filter(
            ActivityDrawnFeature.proposed_activity_id.in_(ids),
            ActivityDrawnFeature.deleted_at.is_(None),
        )
        .group_by(ActivityDrawnFeature.proposed_activity_id)
        .all()
    )
    return {r[0]: int(r[1]) for r in rows}


def plan_view(db: Session, calculation: Calculation) -> List[Dict[str, Any]]:
    """Every plan line of the forest as the screens and the health check read it."""
    lines = (
        db.query(ProposedYearlyActivity)
        .filter(ProposedYearlyActivity.calculation_id == calculation.id)
        .order_by(ProposedYearlyActivity.created_at, ProposedYearlyActivity.id)
        .all()
    )
    masters = {
        m.id: m
        for m in db.query(PotentialActivity).filter(
            PotentialActivity.id.in_({ln.potential_activity_id for ln in lines} or {-1})
        )
    }
    rows = year_rows_for(db, [ln.id for ln in lines])
    counts = feature_counts(db, [ln.id for ln in lines])
    units = derive_line_units(
        db, calculation.id, [ln.id for ln in lines if counts.get(ln.id, 0) > 0]
    )
    assigned = derive_line_assignments(db, calculation, [ln.id for ln in lines])
    sub_area_links = derive_line_sub_areas(
        db,
        calculation,
        [(ln.id, getattr(masters.get(ln.potential_activity_id), "map_kind", None)) for ln in lines if counts.get(ln.id, 0) > 0],
    )
    out: List[Dict[str, Any]] = []
    for ln in lines:
        master = masters.get(ln.potential_activity_id)
        by_year = rows.get(ln.id, {})
        matrix = []
        for year in PLAN_YEARS:
            row = by_year.get(year)
            qty = effective_quantity(row, ln.default_quantity)
            bud = effective_budget(row, ln.default_yearly_budget)
            matrix.append(
                {
                    "year": year,
                    "quantity": float(qty),
                    "budget": float(bud),
                    "planned": is_planned(qty, bud),
                    "has_row": row is not None,
                }
            )
        out.append(
            {
                "id": str(ln.id),
                "potential_activity_id": ln.potential_activity_id,
                "activity": getattr(master, "activities", None),
                "program": getattr(master, "progarms", None),
                "unit": getattr(master, "unit", None),
                "requires_map": bool(getattr(master, "requires_map", False)),
                "default_quantity": float(ln.default_quantity),
                "default_yearly_budget": float(ln.default_yearly_budget),
                "years": matrix,
                "planned_years": planned_years(
                    ln.default_quantity, ln.default_yearly_budget, by_year
                ),
                "total_budget": float(total_budget(ln.default_yearly_budget, by_year)),
                "version": ln.version,
                "reviewed_at": ln.reviewed_at.isoformat() if ln.reviewed_at else None,
                "placeholder_fields": sorted(placeholder_fields(ln, by_year)),
                "feature_count": counts.get(ln.id, 0),
                # what the drawn places measure for this unit (ha / km / count), so the table can offer to adopt it
                "measured_quantity": (
                    _measured(db, ln.id, master) if counts.get(ln.id, 0) > 0 else None
                ),
                # where the places fall (derived from the geometry); else the blocks / sub-areas chosen for the line
                # the sub-areas the places fall in (id, name, category, matches the kind's category), best match first
                "sub_areas": sub_area_links.get(ln.id, []),
                "location_units": units.get(ln.id)
                or (assigned.get(ln.id, {}).get("units") or []),
                "location_mode": location_mode(
                    master, ln, counts.get(ln.id, 0), assigned.get(ln.id)
                ),
                "assign_to_all_blocks": bool(ln.assign_to_all_blocks),
                "status": ln.status,
                "notes": ln.notes,
            }
        )
    return out
