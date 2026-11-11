"""Consequence hook, part 2 (D11, FS-1d.5): after a structural edit, re-sync every
tree's and sample plot's ``unit_id`` to the forest's CURRENT unit geometry.

``on_structure_changed`` (``write.py``) always marks downstream data stale (part 1); this
module is what actually keeps the live FK link (D10, migration 095) correct once units
exist. Without it, a boundary/unit reshape (or a divide/merge/delete) would leave every
tree and plot pointing at whatever unit last contained its point -- possibly wrong, and
possibly a unit that no longer exists in that shape.

Branch-generic (I10): every query below joins on geometry and orders by
``forest_units.sql.deepest_first`` -- it never tests ``is_compartment`` or a literal
depth, so it is correct unchanged whichever stream the forest uses, and once
sub-blocks exist alongside sub-compartments.

Best-effort, like every other step in ``structure_write``: a failure here must never
turn a successful structural edit into a 500 -- it is logged and swallowed by the
caller (``on_structure_changed``), and the next edit (or an explicit re-run) retries it.

Each pass runs inside its own SAVEPOINT (``db.begin_nested()``), the same convention
used everywhere else in this codebase for a best-effort query against a possibly-missing
table (see ``auto_block_service._nearest_natural_names``): this function runs INSIDE the
caller's still-open, uncommitted transaction (``structure_write`` never commits -- the
caller does, once, after every funnel step has queued its own changes). A bare
``except: ...`` with no rollback would leave Postgres's "current transaction is aborted"
state active for every statement after it in that same transaction -- including the
caller's own commit. A bare ``db.rollback()`` would be worse: it would discard the
caller's real, already-successful geometry edit along with this best-effort step's own
failure. A SAVEPOINT rollback undoes only this one query.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.calculation import Calculation
from app.models.sampling import SamplingDesign

from . import sql as unit_sql
from .write import STALE_DOMAINS

logger = logging.getLogger(__name__)


def reassign_after_structure_change(db: Session, calc: Calculation) -> Dict[str, int]:
    """Re-run point-in-polygon assignment for every tree/plot of ``calc`` against its
    CURRENT units. Two-pass per table: clear this forest's ``unit_id`` values, then
    refill from a fresh spatial join -- so a tree/plot whose old unit shrank away from
    its point is not left holding a stale reference, and one whose new unit now covers
    it is picked up, without a separate "does my current unit still contain me" check.

    Returns a stats dict (``trees_reassigned`` / ``plots_reassigned``), for logging by
    the caller; never raises.
    """
    calc_id = str(calc.id)
    stats = {"trees_reassigned": 0, "plots_reassigned": 0}

    try:
        with db.begin_nested():
            db.execute(
                text(
                    """
                UPDATE public.inventory_trees t
                SET unit_id = NULL
                FROM public.inventory_calculations ic
                WHERE ic.id = t.inventory_calculation_id
                  AND ic.calculation_id = :calc_id
                  AND t.unit_id IS NOT NULL
            """
                ),
                {"calc_id": calc_id},
            )
            result = db.execute(
                text(
                    f"""
                WITH candidates AS (
                    SELECT DISTINCT ON (it.id)
                        it.id AS tree_id, fb.id AS unit_id
                    FROM public.inventory_trees it
                    JOIN public.inventory_calculations ic ON ic.id = it.inventory_calculation_id
                    JOIN public.forest_blocks fb
                        ON fb.calculation_id = ic.calculation_id
                       AND ST_Intersects(it.location::geometry, fb.geometry)
                    WHERE ic.calculation_id = :calc_id
                    ORDER BY it.id, {unit_sql.deepest_first("fb")}, fb.id
                )
                UPDATE public.inventory_trees t
                SET unit_id = candidates.unit_id
                FROM candidates
                WHERE t.id = candidates.tree_id
            """
                ),
                {"calc_id": calc_id},
            )
            stats["trees_reassigned"] = result.rowcount
    except Exception:  # noqa: BLE001 -- best-effort re-sync, never fail the edit
        logger.warning(
            "structure_impact: tree re-assignment failed for calc %s",
            calc_id,
            exc_info=True,
        )

    try:
        with db.begin_nested():
            db.execute(
                text(
                    """
                UPDATE public.field_inventory_sample_plots p
                SET unit_id = NULL
                FROM public.field_inventory_calculations fic
                WHERE fic.id = p.field_inventory_calculation_id
                  AND fic.calculation_id = :calc_id
                  AND p.unit_id IS NOT NULL
            """
                ),
                {"calc_id": calc_id},
            )
            result = db.execute(
                text(
                    f"""
                WITH candidates AS (
                    SELECT DISTINCT ON (p.id)
                        p.id AS plot_id, fb.id AS unit_id
                    FROM public.field_inventory_sample_plots p
                    JOIN public.field_inventory_calculations fic ON fic.id = p.field_inventory_calculation_id
                    JOIN public.forest_blocks fb
                        ON fb.calculation_id = fic.calculation_id
                       AND ST_Intersects(p.location::geometry, fb.geometry)
                    WHERE fic.calculation_id = :calc_id
                    ORDER BY p.id, {unit_sql.deepest_first("fb")}, fb.id
                )
                UPDATE public.field_inventory_sample_plots p
                SET unit_id = candidates.unit_id
                FROM candidates
                WHERE p.id = candidates.plot_id
            """
                ),
                {"calc_id": calc_id},
            )
            stats["plots_reassigned"] = result.rowcount
    except Exception:  # noqa: BLE001 -- best-effort re-sync, never fail the edit
        logger.warning(
            "structure_impact: plot re-assignment failed for calc %s",
            calc_id,
            exc_info=True,
        )

    return stats


def _classify_at_risk(
    db: Session,
    calc_id: str,
    *,
    table: str,
    calc_join_table: str,
    calc_join_col: str,
    point_col: str,
    feature_ids: Sequence[str],
    new_geom_json: Optional[str],
) -> Dict[str, Any]:
    """One table's share of :func:`preview_structure_change` -- read-only,
    no writes at all (unlike :func:`reassign_after_structure_change`, this
    never runs inside a SAVEPOINT because it issues no statement that could
    poison the caller's transaction; a plain query failure is caught and
    reported as zero impact rather than raised, matching this module's
    best-effort convention).

    Every row currently pointing at one of ``feature_ids`` is "at risk".
    Each is then classified:
      - ``stays``: `new_geom_json` is given and the row's point still falls
        inside it (a reshape that keeps covering the same ground).
      - ``moves``: some OTHER unit (not in ``feature_ids``) already covers
        the point -- the deepest (innermost) match, same tie-break as the
        real re-sync.
      - ``unassigned``: neither -- nothing would contain the point at all.
    """
    empty = {"at_risk": 0, "stays": 0, "moves": 0, "unassigned": 0}
    if not feature_ids:
        return empty
    try:
        at_risk_rows = db.execute(
            text(
                f"""
                SELECT r.id AS row_id, ST_AsText(r.{point_col}) AS pt
                FROM public.{table} r
                JOIN public.{calc_join_table} j ON j.id = r.{calc_join_col}
                WHERE j.calculation_id = :calc_id
                  AND r.unit_id = ANY(CAST(:feature_ids AS uuid[]))
            """
            ),
            {"calc_id": calc_id, "feature_ids": list(feature_ids)},
        ).fetchall()
    except Exception:  # noqa: BLE001 -- a preview must never 500; report zero impact
        logger.warning(
            "structure_impact preview: at-risk query failed for %s", table, exc_info=True
        )
        return empty

    if not at_risk_rows:
        return empty

    at_risk_ids = [r.row_id for r in at_risk_rows]
    stays_ids: set = set()
    if new_geom_json:
        try:
            stays_rows = db.execute(
                text(
                    f"""
                    SELECT r.id AS row_id
                    FROM public.{table} r
                    WHERE r.id = ANY(:ids)
                      AND ST_Intersects(
                          r.{point_col}::geometry,
                          ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326)
                      )
                """
                ),
                {"ids": at_risk_ids, "geom_json": new_geom_json},
            ).fetchall()
            stays_ids = {r.row_id for r in stays_rows}
        except Exception:  # noqa: BLE001 -- a bad proposed geometry degrades to "not staying"
            logger.warning(
                "structure_impact preview: new_geometry containment check failed for %s",
                table, exc_info=True,
            )

    remaining_ids = [i for i in at_risk_ids if i not in stays_ids]
    moves_ids: set = set()
    if remaining_ids:
        try:
            candidates = db.execute(
                text(
                    f"""
                    WITH ranked AS (
                        SELECT DISTINCT ON (r.id)
                            r.id AS row_id, fb.id AS candidate_unit
                        FROM public.{table} r
                        JOIN public.forest_blocks fb
                            ON fb.calculation_id = :calc_id
                           AND fb.id != ALL(CAST(:feature_ids AS uuid[]))
                           AND ST_Intersects(r.{point_col}::geometry, fb.geometry)
                        WHERE r.id = ANY(:ids)
                        ORDER BY r.id, {unit_sql.deepest_first("fb")}, fb.id
                    )
                    SELECT row_id FROM ranked
                """
                ),
                {"calc_id": calc_id, "feature_ids": list(feature_ids), "ids": remaining_ids},
            ).fetchall()
            moves_ids = {r.row_id for r in candidates}
        except Exception:  # noqa: BLE001 -- degrade to "unassigned" rather than 500
            logger.warning(
                "structure_impact preview: other-unit candidate query failed for %s",
                table, exc_info=True,
            )

    unassigned = len(remaining_ids) - len(moves_ids)
    return {
        "at_risk": len(at_risk_ids),
        "stays": len(stays_ids),
        "moves": len(moves_ids),
        "unassigned": unassigned,
    }


def preview_structure_change(
    db: Session,
    calc: Calculation,
    *,
    feature_ids: Sequence[str],
    new_geometry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Read-only dry-run (FS-4a.15) of what a structural change to
    ``feature_ids`` (the unit(s) being reshaped/cut/merged/deleted) would do
    downstream. **Never writes anything** -- unlike
    :func:`reassign_after_structure_change`, this is called BEFORE the
    caller has decided to commit to the edit at all, so a frontend can show
    "N trees / M plots would move, K would become unassigned" before the
    user confirms.

    ``new_geometry`` (a GeoJSON geometry dict), when given, describes ONE
    proposed replacement shape for the affected unit(s) -- the reshape
    case. Omitted (``None``) means the affected units are simply going away
    entirely (delete/merge/cut consuming them) with nothing to test
    containment against, so every at-risk row is either picked up by some
    OTHER existing unit or becomes unassigned.

    Also reports whether any sampling design exists for this forest (any
    structural change invalidates a design's unit boundaries) and the
    stale domains a real commit would mark (mirrors ``write.STALE_DOMAINS``
    — informational only, this function marks nothing).
    """
    calc_id = str(calc.id)
    new_geom_json = json.dumps(new_geometry) if new_geometry else None

    trees = _classify_at_risk(
        db, calc_id,
        table="inventory_trees", calc_join_table="inventory_calculations",
        calc_join_col="inventory_calculation_id", point_col="location",
        feature_ids=feature_ids, new_geom_json=new_geom_json,
    )
    plots = _classify_at_risk(
        db, calc_id,
        table="field_inventory_sample_plots", calc_join_table="field_inventory_calculations",
        calc_join_col="field_inventory_calculation_id", point_col="location",
        feature_ids=feature_ids, new_geom_json=new_geom_json,
    )

    try:
        sampling_designs_affected = (
            db.query(SamplingDesign)
            .filter(SamplingDesign.calculation_id == calc.id)
            .count()
        )
    except Exception:  # noqa: BLE001 -- a preview must never 500
        logger.warning(
            "structure_impact preview: sampling design count failed for calc %s",
            calc_id, exc_info=True,
        )
        sampling_designs_affected = 0

    return {
        "affected_unit_ids": list(feature_ids),
        "trees": trees,
        "plots": plots,
        "sampling_designs_affected": sampling_designs_affected,
        "stale_domains": list(STALE_DOMAINS),
    }
