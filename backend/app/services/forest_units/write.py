"""The write funnel (plan §3.3, FS-1b.2): every structural mutation goes through this, so the derived
``result_data`` caches, the sub-area breakdown, the geometry clock, the render caches and the "re-run"
banner can never go stale relative to the ``forest_blocks`` rows a caller just changed.

Usage at a call site that already mutates ``forest_blocks`` and commits::

    from app.services.forest_units.write import structure_write

    with structure_write(db, calc, change="divide compartment C1"):
        ... insert / update / delete ForestBlock rows ...
    db.commit()

``structure_write`` does its housekeeping on the way OUT of the ``with`` block (queuing more ORM changes,
never committing) so it lands in the SAME transaction as the caller's own commit that follows. On an
exception inside the block, nothing here runs - the caller's own rollback undoes everything together.

What it does *not* do: audit logging. `editing._write_geometry` already logs geometry mutations through
`_audit_geometry_write`; a funnel that logged again would double every row `geometry_audits` holds. A
future writer that has NO audit call of its own is the one place to add a funnel-level entry (review V3).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.calculation import Calculation
from app.services.block_reconcile_service import (
    reconcile_blocks_from_db,
    reconcile_compartments_from_db,
)
from app.services.geometry_edit_service import bump_geometry_version

logger = logging.getLogger(__name__)

# The three areas a structural change can make stale for a forest's downstream data. Kept as a tuple, not an
# enum, because `on_structure_changed` writes it straight into JSONB.
STALE_DOMAINS = ("analysis", "sampling", "field_inventory")


def downstream_domains(db: Session, calc: Calculation) -> tuple:
    """Which of ``STALE_DOMAINS`` this forest ACTUALLY holds data for.

    The banner the owner sees is a "your numbers may be out of date" warning, so
    it is only true for a domain that has numbers in it. Marking all three
    unconditionally meant a forest with no analysis, no sampling design and no
    field inventory — which is what a forest looks like for the whole first
    session, before any of them is uploaded — still got told to "re-run them",
    and got told so on every single structural edit. That is the "why do I always
    see this ribbon" report.

    Each predicate answers "is there something here that a divide/merge/cut
    would invalidate", not "has this step been completed" — a sampling design
    row with zero generated points still has an area and an intensity that the
    structure change moves, and the field-inventory row is created at upload
    time, long before it is processed. Best-effort throughout: a table that does
    not exist in this build reports False for its domain rather than raising,
    because this runs inside a structural edit that has already succeeded.
    """
    present = set()

    # `analysis` lives in `calculations.result_data` itself — there is no
    # analysis table. A completed calculation is the signal that its zonal /
    # slope / canopy figures exist and are now out of date.
    try:
        status = getattr(calc, "status", None)
        if (
            status is not None
            and str(getattr(status, "value", status)).lower() == "completed"
        ):
            present.add("analysis")
    except Exception:  # noqa: BLE001 -- never fail a successful edit
        logger.warning("downstream_domains: analysis probe failed", exc_info=True)

    try:
        from app.models.sampling import SamplingDesign

        if (
            db.query(SamplingDesign.id)
            .filter(SamplingDesign.calculation_id == calc.id)
            .first()
            is not None
        ):
            present.add("sampling")
    except Exception:  # noqa: BLE001
        logger.warning("downstream_domains: sampling probe failed", exc_info=True)

    try:
        from app.models.field_inventory import FieldInventoryCalculation

        if (
            db.query(FieldInventoryCalculation.id)
            .filter(FieldInventoryCalculation.calculation_id == calc.id)
            .first()
            is not None
        ):
            present.add("field_inventory")
    except Exception:  # noqa: BLE001
        logger.warning(
            "downstream_domains: field_inventory probe failed", exc_info=True
        )

    return tuple(d for d in STALE_DOMAINS if d in present)


def recompute_sub_area_breakdown(db: Session, calc: Calculation) -> bool:
    """Recompute each top-level unit's excluded/effective area from its sub-areas (FS-1b.6, "N2").

    This is the ONE copy of a calculation that existed three times, verbatim, in `api/geometry.py` (sub-area
    add / patch / delete) before P1b: forest-level `excluded_area_hectares` / `effective_area_hectares`, and
    per-unit `excluded_area_hectares` / `effective_area_hectares` via `calculate_block_excluded_areas`
    (cross-unit sub-areas via `blockBreakdown`). Runs over whichever top-level array the forest actually uses
    (`blocks` or `compartments`) rather than assuming `blocks` — a compartment forest's sub-area edits used to
    silently update an array nobody read.

    Returns True if either array changed. No-op (returns False) when the forest has no sub-areas or no units.
    """
    from app.api.forests import (  # local: avoids a circular import at module load
        calculate_block_excluded_areas,
        calculate_total_excluded_area,
    )

    rd = calc.result_data or {}
    if not isinstance(rd, dict):
        return False
    if "sub_areas" not in rd:
        # No sub-areas key at all: this forest has never had one, nothing to recompute. An EMPTY
        # ``sub_areas`` list (all sub-areas just deleted) still runs, below, so every unit's
        # excluded/effective area resets to 0 rather than keeping a stale non-zero value.
        return False
    sub_areas = rd.get("sub_areas") or []

    changed = False
    for array_key in ("blocks", "compartments"):
        units: List[Dict[str, Any]] = rd.get(array_key) or []
        if not units:
            continue
        excluded_map = calculate_block_excluded_areas(units, sub_areas)
        for unit in units:
            unit_id = unit.get("block_id") or unit.get("id")
            excluded = round(excluded_map.get(unit_id, 0.0), 4)
            original = unit.get("area_hectares", 0) or 0
            effective = round(original - excluded, 4)
            if (
                unit.get("excluded_area_hectares") != excluded
                or unit.get("effective_area_hectares") != effective
            ):
                unit["excluded_area_hectares"] = excluded
                unit["effective_area_hectares"] = effective
                changed = True

    # Forest-level totals are recomputed unconditionally (not gated on a per-unit change above):
    # clearing every sub-area leaves both unit arrays empty (nothing for the loop above to touch), and the
    # stale forest-level total must still drop to 0 rather than being left at its last non-zero value.
    total_area = rd.get("area_hectares", 0) or 0
    excluded_total = round(calculate_total_excluded_area(sub_areas), 4)
    effective_total = round(total_area - excluded_total, 4)
    if (
        rd.get("excluded_area_hectares") != excluded_total
        or rd.get("effective_area_hectares") != effective_total
    ):
        changed = True

    if not changed:
        return False

    new_rd = dict(rd)
    new_rd["excluded_area_hectares"] = excluded_total
    new_rd["effective_area_hectares"] = effective_total
    calc.result_data = new_rd
    flag_modified(calc, "result_data")
    return True


def on_structure_changed(
    db: Session,
    calc: Calculation,
    change: Optional[str] = None,
    domains: Optional[tuple] = None,
) -> None:
    """The consequence hook (D11): mark downstream data stale (part 1) and re-sync every
    tree/plot's ``unit_id`` to the CURRENT unit geometry (part 2, FS-1d.5).

    Only the domains this forest actually holds data for are marked — see
    ``downstream_domains`` for why, and for the "always shows" bug that motivated
    it. When the forest holds nothing downstream, no flag is written at all (and
    an existing flag for an emptied domain is cleared), so the frontend's banner
    renders nothing instead of asking for a re-run that has nothing to re-run.

    Pass ``domains`` explicitly to override the probe (tests, and any caller that
    already knows better).

    Part 2 is best-effort past that point, like every other step in
    `structure_write` -- a re-assignment failure must never turn a successful
    structural edit into a 500.
    """
    if domains is None:
        domains = downstream_domains(db, calc)
    domains = tuple(d for d in STALE_DOMAINS if d in domains)

    if not domains:
        # Nothing to be stale. Drop the key rather than leaving a flag whose
        # domains are all false, so a consumer that only checks for the key's
        # presence sees nothing.
        if isinstance(calc.result_data, dict) and "structure_stale" in calc.result_data:
            rd = dict(calc.result_data)
            del rd["structure_stale"]
            calc.result_data = rd
            flag_modified(calc, "result_data")
    else:
        rd = dict(calc.result_data or {})
        if not isinstance(calc.result_data or {}, dict):
            rd = {}
        rd["structure_stale"] = {
            # Every domain is always present as a boolean, so a consumer can
            # read `stale['analysis']` without a `get()`; only the ones with
            # data behind them are True.
            **{d: d in domains for d in STALE_DOMAINS},
            "since": datetime.now(timezone.utc).isoformat(),
            "change": change,
        }
        calc.result_data = rd
        flag_modified(calc, "result_data")

    try:
        from .structure_impact import reassign_after_structure_change

        reassign_after_structure_change(db, calc)
    except Exception:  # noqa: BLE001 -- best-effort re-sync, never fail the edit
        logger.warning(
            "on_structure_changed: unit_id re-assignment failed for calc %s",
            getattr(calc, "id", None),
            exc_info=True,
        )


def clear_stale_domains(
    db: Session, calc: Calculation, domains: tuple = STALE_DOMAINS
) -> bool:
    """Clear the stale mark for the domains that have just been recomputed.

    This is the other half of ``on_structure_changed``. Without it the flag is
    write-only: it is set on the first structural edit and nothing ever unsets
    it, so a forest that HAD been re-analysed since its last divide kept telling
    the user to re-analyse — and did so for the rest of the calculation's life.
    Call this from the endpoint that actually recomputes a domain (re-analyse,
    sampling create, field-inventory process).

    Marks only the named domains false rather than deleting the key outright, so
    a divide that happened after the re-run still leaves the OTHER domains
    flagged. Returns True when something changed.
    """
    if not isinstance(calc.result_data, dict):
        return False
    stale = calc.result_data.get("structure_stale")
    if not isinstance(stale, dict):
        return False

    updated = dict(stale)
    for domain in domains:
        updated[domain] = False
    if not any(updated.get(d) for d in STALE_DOMAINS):
        # Nothing left flagged -- drop the key so the banner's presence check
        # (not its boolean check) is enough for consumers.
        rd = dict(calc.result_data)
        del rd["structure_stale"]
        calc.result_data = rd
    else:
        updated["since"] = datetime.now(timezone.utc).isoformat()
        rd = dict(calc.result_data)
        rd["structure_stale"] = updated
        calc.result_data = rd
    flag_modified(calc, "result_data")
    return True


def clear_stale_domains_for_calc(db: Session, calc_id: Any) -> bool:
    """``clear_stale_domains`` for a call site that has only a ``calculation_id``.

    The sampling engine and the field-inventory service both commit internally
    and never load the ``Calculation`` ORM object, so their endpoints clear the
    flag by id rather than by instance. Returns False (never raises) when the
    calculation is gone or the write fails -- a stale-mark cleanup must not turn
    a successful re-run into a 500.
    """
    try:
        calc = db.query(Calculation).filter(Calculation.id == calc_id).first()
        if calc is None:
            return False
        return clear_stale_domains(db, calc)
    except Exception:  # noqa: BLE001
        logger.warning(
            "clear_stale_domains_for_calc failed for calc %s", calc_id, exc_info=True
        )
        return False


def keep_code_in_step(row: Any, old_name: Optional[str], old_block_name: Optional[str]) -> bool:
    """After a polygon is renamed: carry its ``compartment_code`` along when the code was only a copy of the old name.

    Dividing a unit gives each piece an automatic code equal to its automatic name (``SC2-1``, ``SC2-2``). A rename changed the name
    and left that code behind, so the same polygon was "Encroached" on most screens and "SC2-2" in sampling, the inventory and the
    printed plan (all of which show ``compartment_code or name``). A code the user typed into the code field - one that is NOT the
    old name - is theirs and is never touched. Returns True when the code changed. Call after the new name is set.
    """
    code = getattr(row, "compartment_code", None)
    new = getattr(row, "name", None)
    if not code or not new or code == new or code not in {n for n in (old_name, old_block_name) if n}:
        return False
    row.compartment_code = new
    return True


def sync_child_counts(db: Session, calc_id: Any) -> int:
    """Set every unit's stored ``child_count`` to its real number of sub-units. Returns how many rows changed. Does not commit."""
    res = db.execute(
        text(
            """
            UPDATE forest_blocks b
               SET child_count = (SELECT count(*) FROM forest_blocks c WHERE c.parent_block_id = b.id)
             WHERE b.calculation_id = :cid
               AND b.child_count IS DISTINCT FROM (SELECT count(*) FROM forest_blocks c WHERE c.parent_block_id = b.id)
            """
        ),
        {"cid": str(calc_id)},
    )
    return res.rowcount or 0


@contextmanager
def structure_write(
    db: Session, calc: Calculation, *, change: Optional[str] = None
) -> Iterator[None]:
    """Wrap a block of code that mutates ``forest_blocks`` for one calculation.

    On a clean exit: rebuild the derived `result_data['blocks'/'compartments']` arrays, recompute the
    sub-area breakdown, bump the geometry-version clock, invalidate the render/SFM caches, and mark
    downstream data stale. Every step is best-effort past the reconcile step - a cache-invalidation failure
    must never turn a successful structural edit into a 500. Nothing here commits; the caller's own commit
    (right after the ``with`` block) persists it all as one transaction, same as before this funnel existed.

    One thing it DOES refuse: an edit that leaves the forest breaking a structure rule it did not break before
    (``invariants``: one branch per forest; children tile their parent). It raises ``StructureInvariantError`` (409)
    before anything is committed. A forest that was already broken is not locked out - only a new violation is refused.
    """
    from . import invariants

    before = None
    try:
        before = invariants.find_violations(db, calc.id)
    except Exception:  # noqa: BLE001 -- the guard must never be the reason an edit cannot start
        logger.warning("structure_write: invariant pre-check failed for calc %s", getattr(calc, "id", None), exc_info=True)

    yield

    # Several writers add a sub-unit without updating the parent's stored count. The count is a cache of a number the rows already
    # hold, so rebuild it here, before the checks: no writer can leave it stale, and a stale count is never what refuses an edit.
    try:
        db.flush()
        sync_child_counts(db, calc.id)
    except Exception:  # noqa: BLE001 -- a failed repair is logged; the invariant below still reports a count that stayed wrong
        logger.warning("structure_write: child_count repair failed for calc %s", getattr(calc, "id", None), exc_info=True)

    if before is not None:
        added = None
        try:
            db.flush()
            added = invariants.new_violations(before, invariants.find_violations(db, calc.id))
        except Exception:  # noqa: BLE001 -- a failing check is logged and skipped; only a real violation refuses
            logger.warning("structure_write: invariant check failed for calc %s", getattr(calc, "id", None), exc_info=True)
        if added:
            logger.warning("structure_write refused (calc %s, change=%r): %s", getattr(calc, "id", None), change, [v.code for v in added])
            raise invariants.StructureInvariantError(added)

    try:
        reconcile_blocks_from_db(db, calc)
        reconcile_compartments_from_db(db, calc)
        recompute_sub_area_breakdown(db, calc)
        bump_geometry_version(calc)
        on_structure_changed(db, calc, change=change)
    except (
        Exception
    ):  # noqa: BLE001 -- the mutation itself already succeeded; never lose it here
        logger.exception(
            "structure_write: derived-cache rebuild failed for calc %s (change=%r); "
            "the edit is already queued and will still be committed",
            getattr(calc, "id", None),
            change,
        )
        return

    try:
        from app.services.cache_invalidation import invalidate_calc_caches

        invalidate_calc_caches(str(calc.id))
    except (
        Exception
    ):  # noqa: BLE001 -- a cache-invalidation signal failing must not fail the write
        logger.warning(
            "structure_write: cache invalidation signal failed", exc_info=True
        )

    try:
        from app.services.sustainable_fm.sfm_service import invalidate_sfm

        invalidate_sfm(calc.id, db)
    except (
        Exception
    ):  # noqa: BLE001 -- SFM cache is rebuilt lazily; a failure here just delays that
        logger.warning("structure_write: SFM cache invalidation failed", exc_info=True)

    try:
        from app.services.field_inventory_service import invalidate_render_caches

        invalidate_render_caches(db, calc.id)
    except Exception:  # noqa: BLE001 -- rendered-map cache is rebuilt on next request
        logger.warning(
            "structure_write: render-cache invalidation failed", exc_info=True
        )


MANAGEMENT_ORIENTATIONS = ("Production", "Conservation", "Protection")


def set_management_orientation(calc: Calculation, block: Any, value: Optional[str]) -> None:
    """The one place a block's editable management orientation is written.

    Sets the ``forest_blocks`` column and re-syncs the legacy ``result_data`` unit snapshots, which shadow the table for
    some readers (the "result_data units stale trap"). Both ``update_block`` routes (``api/blocks.py`` and
    ``api/forests.py``) and the plan-decisions endpoint call this, so they cannot drift apart. The caller commits.
    """
    block.management_orientation = value
    bid = str(block.id)
    data = dict(calc.result_data or {})
    changed = False
    for coll in ("blocks", "compartments", "sub_compartments"):
        rows = data.get(coll)
        if not rows:
            continue
        fresh = []
        for row in rows:
            if isinstance(row, dict) and (row.get("block_id") == bid or row.get("id") == bid):
                row = {**row, "management_orientation": value}
                changed = True
            fresh.append(row)
        data[coll] = fresh
    if changed:
        calc.result_data = data  # a fresh dict, never an in-place edit (JSONB would not notice)
