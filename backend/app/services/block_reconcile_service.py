"""block_reconcile_service -- make result_data.blocks a derived view of forest_blocks.

`forest_blocks` is the single source of truth for block geometry/identity.
`result_data.blocks` is a legacy/analysis JSONB snapshot that the workspace rarely
updates (auto-block, split, divide, draw etc. write `forest_blocks` only). This
service reconciles the snapshot FROM the DB so the legacy page, the analysis
engine and reports all see the same blocks as the workspace.

BA-1..BA-4 of `map_design_ui_impl/block_assignment_from_map_workspace.md`.
"""

from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..models.calculation import Calculation
from ..models.forest_block import ForestBlock
from .forest_units import queries as forest_unit_queries

logger = logging.getLogger(__name__)

# JSONB-only per-block keys produced by analysis / diagnostics that are NOT part
# of the identity/geometry snapshot. Reconciliation preserves these by id.
# Not an exhaustive allowlist -- see reconcile: we copy any key the fresh block
# does not already set (identity keys are always overwritten; everything else is
# preserved from the stale JSONB entry when the ids match).
_IDENTITY_KEYS = frozenset(
    {
        "block_index",
        "block_id",
        "id",
        "name",
        "block_name",
        "natural_name",
        "area_hectares",
        "geometry",
        "working_circle",
        "style",
    }
)


def _to_geojson(db: Session, geometry) -> Optional[Dict[str, Any]]:
    """Return a stored geometry as a GeoJSON dict, or None if unreadable.

    Mirrors `editing._to_geojson` semantics: never raises; the caller must be
    able to continue with a None geometry.
    """
    if geometry is None:
        return None
    try:
        from geoalchemy2.shape import to_shape
        from shapely.geometry import mapping

        # Normalize to pure-JSON form (lists, not tuples) so the in-memory
        # value equals what a JSONB store/re-read round-trip yields. Without
        # this, a second reconcile would keep seeing a "change" because tuples
        # != the lists the DB returns -> never idempotent.
        return _json_normalize(mapping(to_shape(geometry)))
    except Exception:  # noqa: BLE001 -- a bad geometry must not fail reconciliation
        logger.exception("reconcile: stored block geometry unreadable - returning None")
        return None


def _json_normalize(value: Any) -> Any:
    """Round-trip through JSON to match what the JSONB column will store/return.

    Converts tuples to lists, drops non-JSON types, so in-memory rebuilt
    blocks compare equal to a re-read from the database.
    """
    try:
        return json.loads(json.dumps(value))
    except Exception:  # noqa: BLE001 -- unsupported types just fall back raw
        return value


def _jsonb_block_identity(block: Dict[str, Any]) -> Optional[str]:
    """Return the best stable id of a JSONB block entry for matching to DB rows."""
    for key in ("block_id", "id"):
        val = block.get(key)
        if val:
            return str(val)
    return None


def _find_old_block(
    old_blocks: Sequence[Dict[str, Any]], row: ForestBlock
) -> Optional[Dict[str, Any]]:
    """Find the stale JSONB entry matching a DB row, by id then by name."""
    for old in old_blocks:
        oid = _jsonb_block_identity(old)
        if oid and (oid == str(row.id) or oid == str(getattr(row, "block_id", None))):
            return old
    row_id = str(row.id)
    for old in old_blocks:
        if _jsonb_block_identity(old) == row_id:
            return old
    # Name fallback: compare block_name/name interchangeably (JSONB snapshots may
    # store either key, and DB rows may have block_name unset while name is set).
    row_names = {
        n for n in (getattr(row, "block_name", None), getattr(row, "name", None)) if n
    }
    for old in old_blocks:
        old_names = {n for n in (old.get("block_name"), old.get("name")) if n}
        if old_names & row_names:
            return old
    return None


def reconcile_blocks_from_db(db: Session, calc: Calculation) -> bool:
    """Reconcile ``calc.result_data['blocks']`` from ``forest_blocks``.

    Returns True if the JSONB ``blocks`` array (or ``total_blocks``) CHANGED.

    - Rebuilds the array from the leaf BLOCKS of the forest (``forest_units``:
      blocks not divided further) ordered by ``index``.
    - Preserves JSONB-only per-block keys already present (per-block analysis
      output, excluded/effective areas, species...) by matching on block id and
      falling back to name/block_name.
    - If there are NO ``forest_blocks`` rows for the calc, leaves the JSONB
      untouched (legacy upload-mode snapshot) and returns False.
    - Never deletes analysis output; only merges/reorders.

    Does NOT commit -- the caller decides when to commit.
    """
    if calc is None:
        return False

    # The LEAF blocks (FS-1a.3): blocks not divided further - a block divided into sub-blocks is replaced by its
    # pieces. (Compartments are reconciled separately, into ``compartments``.)
    rows = forest_unit_queries.unit_rows(
        db,
        calc.id,
        forest_unit_queries.View.LEAF,
        branch=forest_unit_queries.Branch.BLOCK,
    )
    if not rows:
        return False

    rd = calc.result_data or {}
    # result_data may be non-dict (defensive); treat as empty dict.
    if not isinstance(rd, dict):
        rd = {}

    old_blocks = rd.get("blocks", [])
    if not isinstance(old_blocks, list):
        old_blocks = []

    rebuilt: List[Dict[str, Any]] = []
    for row in rows:
        fresh: Dict[str, Any] = {
            "block_index": row.index,
            "block_id": str(row.id),
            "id": str(row.id),
            "name": row.name,
            "block_name": row.block_name or row.name,
            "natural_name": getattr(row, "natural_name", None),
            "working_circle": getattr(row, "working_circle", None) or "production",
            "style": getattr(row, "style", None),
            "area_hectares": round(row.area_hectares or 0.0, 4),
            "geometry": _to_geojson(db, row.geometry),
        }
        # Preserve any JSONB-only keys from the stale snapshot, but never let a
        # stale value overwrite fresh identity/geometry/area.
        old = _find_old_block(old_blocks, row)
        if old and isinstance(old, dict):
            for key, value in old.items():
                if key in _IDENTITY_KEYS:
                    continue
                if key not in fresh:
                    fresh[key] = copy.deepcopy(value)
        rebuilt.append(fresh)

    new_rd = dict(rd)
    new_blocks = rebuilt
    new_total = len(rebuilt)

    old_total = rd.get("total_blocks")
    changed = (
        new_blocks != rd.get("blocks")
        or old_total != new_total
        or new_rd.get("total_blocks") != new_total
    )
    if not changed:
        return False

    new_rd["blocks"] = new_blocks
    new_rd["total_blocks"] = new_total
    calc.result_data = new_rd
    flag_modified(calc, "result_data")
    db.add(calc)
    return True


def _clear_stale_compartments(db: Session, calc: Calculation) -> bool:
    """No ``is_compartment`` rows in ``forest_blocks`` for this calc.

    For a **workspace-managed** forest — one that has ``forest_blocks`` rows, or
    whose structure the user explicitly cleared (``blocks_cleared_by_user``) — a
    lingering ``result_data['compartments']`` array is a since-deleted division
    that ``PolygonSource.for_result_data`` would still pick, making analysis run
    per-(deleted-)compartment instead of per current block. Empty it and drop
    ``polygon_type`` back to ``'block'``.

    A pure **upload-mode** calc (no ``forest_blocks`` rows at all — its
    structure lives only in the JSONB snapshot) is left untouched.

    Returns True if anything changed. Does NOT commit.
    """
    rd = calc.result_data
    if not isinstance(rd, dict):
        return False
    stale = rd.get("compartments") or []
    if not stale and rd.get("polygon_type") != "compartment":
        return False

    has_block_rows = (
        db.query(ForestBlock.id).filter(ForestBlock.calculation_id == calc.id).first()
        is not None
    )
    workspace_managed = has_block_rows or bool(
        getattr(calc, "blocks_cleared_by_user", False)
    )
    if not workspace_managed:
        return False

    new_rd = dict(rd)
    new_rd["compartments"] = []
    new_rd["total_compartments"] = 0
    if new_rd.get("polygon_type") == "compartment":
        new_rd["polygon_type"] = "block"
    calc.result_data = new_rd
    flag_modified(calc, "result_data")
    db.add(calc)
    logger.info(
        "reconcile: cleared %d stale result_data['compartments'] for calc %s "
        "(no compartment rows; forest is workspace-managed)",
        len(stale),
        calc.id,
    )
    return True


def reconcile_compartments_from_db(db: Session, calc: Calculation) -> bool:
    """Reconcile ``calc.result_data['compartments']`` from ``forest_blocks``.

    The mirror of :func:`reconcile_blocks_from_db` for the compartment dimension.
    Dividing a block into compartments in the workspace writes ``forest_blocks``
    rows (``is_compartment=True``, the compartment branch at any depth) and flips
    ``result_data['polygon_type']`` to ``'compartment'`` — but nothing populates
    the JSONB ``compartments`` array. ``analyze_forest_boundary`` selects its
    unit purely from that array (``PolygonSource.for_result_data``), so without
    this the analysis keeps running per BLOCK even though compartments exist.

    - Rebuilds ``result_data['compartments']`` from the LEAF view of the forest
      (``forest_units``): every unit that is not divided further - an undivided
      compartment beside a divided one, sub-compartments, and (in a legacy
      mixed forest) a plain block beside compartments - ordered by ``index``.
    - Preserves per-unit analysis output already present (matched by id then
      name), same as the block reconcile.
    - If there are NO compartment rows: a workspace-managed forest's stale
      ``compartments`` snapshot is cleared (a since-deleted division must not
      keep steering analysis per-compartment — see
      :func:`_clear_stale_compartments`); a pure upload-mode snapshot with no
      ``forest_blocks`` rows is left untouched.
    - Does NOT commit; the caller decides.

    Returns True if ``compartments`` / ``total_compartments`` CHANGED.
    """
    if calc is None:
        return False

    comp_rows = (
        db.query(ForestBlock)
        .filter(
            ForestBlock.calculation_id == calc.id,
            ForestBlock.is_compartment.is_(True),
        )
        .all()
    )
    if not comp_rows:
        return _clear_stale_compartments(db, calc)

    # The analysis set is the LEAF view: every unit that is not divided further (FS-1a.3). It used to be "the
    # deepest level only", which dropped an undivided compartment whenever a sibling had been divided (C1 divided
    # into SC1/SC2, C2 not -> only SC1/SC2 were analysed) and dropped a plain block beside compartments in a
    # legacy mixed forest.
    rows = forest_unit_queries.unit_rows(db, calc.id, forest_unit_queries.View.LEAF)
    if not rows:
        return False

    rd = calc.result_data or {}
    if not isinstance(rd, dict):
        rd = {}

    old_comps = rd.get("compartments", [])
    if not isinstance(old_comps, list):
        old_comps = []

    rebuilt: List[Dict[str, Any]] = []
    for row in rows:
        fresh: Dict[str, Any] = {
            "block_index": row.index,
            "block_id": str(row.id),
            "id": str(row.id),
            "name": row.name,
            "block_name": row.block_name or row.name,
            "compartment_code": getattr(row, "compartment_code", None),
            "natural_name": getattr(row, "natural_name", None),
            "working_circle": getattr(row, "working_circle", None) or "production",
            "style": getattr(row, "style", None),
            "division_level": row.division_level,
            "parent_block_id": (
                str(row.parent_block_id) if row.parent_block_id else None
            ),
            "area_hectares": round(row.area_hectares or 0.0, 4),
            "geometry": _to_geojson(db, row.geometry),
        }
        old = _find_old_block(old_comps, row)
        if old and isinstance(old, dict):
            for key, value in old.items():
                if key in _IDENTITY_KEYS:
                    continue
                if key not in fresh:
                    fresh[key] = copy.deepcopy(value)
        rebuilt.append(fresh)

    new_total = len(rebuilt)
    changed = (
        rebuilt != rd.get("compartments")
        or rd.get("total_compartments") != new_total
        or rd.get("polygon_type") != "compartment"
    )
    if not changed:
        return False

    new_rd = dict(rd)
    new_rd["compartments"] = rebuilt
    new_rd["total_compartments"] = new_total
    new_rd["polygon_type"] = "compartment"
    calc.result_data = new_rd
    flag_modified(calc, "result_data")
    db.add(calc)
    return True


def reconcile_after_block_write(db: Session, calc: Calculation) -> None:
    """Reconcile after any ``forest_blocks`` mutation and commit once.

    Best-effort: never raises -- reconciliation must never fail the user's edit.
    Use at call sites that have no explicit commit before returning; prefer the
    non-committing ``reconcile_blocks_from_db`` inside an existing transaction
    otherwise.
    """
    try:
        if reconcile_blocks_from_db(db, calc):
            db.commit()
    except Exception:  # noqa: BLE001 -- reconciliation must never break the write
        logger.exception(
            "reconcile_after_block_write failed for calc %s; edit already "
            "persisted, reconciliation left for next read/analysis",
            getattr(calc, "id", None),
        )
