"""
Field Inventory Service
Processes field inventory data with 4 stand types and calculates forest condition
"""

import os
import pandas as pd
import numpy as np
import math
from typing import Dict, List, Any, Optional, Tuple
from app.core.forest_condition import assess_conditions
from sqlalchemy.orm import Session
from sqlalchemy import text
from uuid import UUID
from datetime import datetime, timezone
import logging

from app.core.sub_area_kinds import PROTECTION_SUB_AREA_CATEGORIES
import time

from app.core.constants import (
    MAI_PCT_MATRIX,
    MAI_PCT_DEFAULT,
    REGEN_PLOT_AREA_SQM,
    SAPLING_PLOT_AREA_SQM,
    POLE_PLOT_AREA_SQM,
    TREE_PLOT_AREA_SQM,
    HEIGHT_FROM_DBH_FACTOR,
    CFT_PER_M3,
    M3_PER_CHATTA,
    DEFAULT_WOOD_DENSITY_T_M3,
    REGEN_GOOD_PER_HA,
    REGEN_MODERATE_PER_HA,
    SAPLING_GOOD_PER_HA,
    SAPLING_MODERATE_PER_HA,
    GS_GOOD_M3_PER_HA,
    GS_MODERATE_M3_PER_HA,
    SQM_PER_HA,
)

from ..models.field_inventory import (
    FieldInventoryCalculation,
    FieldInventorySamplePlot,
    FieldInventoryMeasurement,
    FieldInventoryBlockSummary,
)
from ..models.inventory import TreeSpeciesCoefficient
from ..core.dbh_classifier import DbhClassRegistry
from .forest_units import queries as forest_unit_queries
from .volume_calculator import calculate_tree_volumes as shared_calculate_volumes
from .carbon_calculator import calculate_all as calculate_carbon_all, IPCC_BEF, IPCC_RS

logger = logging.getLogger(__name__)


def protected_polygon_for_calc(db: Session, calculation_id: UUID):
    """Union of a forest's protected sub-area polygons (EPSG:4326).

    Returns a Shapely geometry, or ``None`` when the forest has no protection
    stratum (no protection sub-areas - ``PROTECTION_SUB_AREA_CATEGORIES``: the protected zones and the river bank - that are not
    excluded).
    Best-effort: a malformed sub-area geometry is skipped, never raised.

    Module-level so it can be tested without constructing the whole service
    (whose ``__init__`` loads species coefficients from the DB).
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from ..models.calculation import Calculation

    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    rd = (calc.result_data if calc else None) or {}
    sub_areas = rd.get("sub_areas", []) if isinstance(rd, dict) else []

    geoms = []
    for sa in sub_areas:
        if sa.get("category") not in PROTECTION_SUB_AREA_CATEGORIES or sa.get("isExcluded", False):
            continue
        raw = sa.get("geometry")
        if not isinstance(raw, dict):
            continue
        try:
            geom = shape(raw)
            if raw.get("type") == "GeometryCollection":
                polys = [
                    g
                    for g in getattr(geom, "geoms", [])
                    if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty
                ]
                geom = unary_union(polys) if polys else None
            if geom is not None and not geom.is_empty:
                geoms.append(geom)
        except Exception:  # noqa: BLE001 -- a bad sub-area must not break FI processing
            logger.warning(
                "[FI zone] skipping unparseable protected sub-area", exc_info=True
            )

    if not geoms:
        return None
    try:
        return unary_union(geoms)
    except (
        Exception
    ):  # noqa: BLE001 -- fall back to no stratum rather than fail processing
        logger.warning("[FI zone] protected-area union failed", exc_info=True)
        return None


def unit_working_circles(db: Session, calculation_id: UUID) -> Dict[str, str]:
    """{unit block_name/name: 'production'|'protection'} from the reconciled units.

    P0 (PROTECTION_WORKING_CIRCLE_PLAN.md) writes ``working_circle`` into the
    ``result_data`` unit dicts. A missing value reads as ``'production'``.
    """
    from ..models.calculation import Calculation

    out: Dict[str, str] = {}
    # The unit rows (leaf view - the units plots are keyed to) are authoritative.
    for row in forest_unit_queries.unit_rows(
        db, calculation_id, forest_unit_queries.View.LEAF
    ):
        wc = row.working_circle or "production"
        for key in (row.block_name, row.name):
            if key:
                out[str(key)] = wc
    if out:
        return out

    # No unit rows: an upload-mode forest keeps its units only in result_data.
    calc = db.query(Calculation).filter(Calculation.id == calculation_id).first()
    rd = (calc.result_data if calc else None) or {}
    if not isinstance(rd, dict):
        return {}
    for u in rd.get("compartments") or rd.get("blocks") or []:
        wc = u.get("working_circle") or "production"
        for key in (u.get("block_name"), u.get("name")):
            if key:
                out[str(key)] = wc
    return out


def assign_plot_zone_types(
    db: Session,
    field_inventory_id: UUID,
    field_inventory: "FieldInventoryCalculation",
) -> None:
    """Tag every sample plot ``productive`` / ``protected``.

    A plot in a **protection working-circle unit** is ``protected`` outright;
    otherwise it is point-in-polygon-tested against the protected sub-areas.
    No-op (plots keep ``zone_type = NULL``) when the forest has neither a
    protection unit nor a protected sub-area. Best-effort: never raises.
    """
    if not field_inventory or not field_inventory.calculation_id:
        return
    protected = protected_polygon_for_calc(db, field_inventory.calculation_id)
    unit_wc = unit_working_circles(db, field_inventory.calculation_id)
    has_protection_unit = any(v == "protection" for v in unit_wc.values())
    if protected is None and not has_protection_unit:
        return

    from geoalchemy2.shape import to_shape
    from shapely import wkt as shapely_wkt

    def _point(loc):
        # After a flush (but before a refresh) `location` is still the
        # 'SRID=4326;POINT(lon lat)' string we assigned; a re-read hands back a
        # geoalchemy element. Handle both.
        if loc is None:
            return None
        if isinstance(loc, str):
            return shapely_wkt.loads(loc.split(";", 1)[-1].strip())
        return to_shape(loc)

    plots = (
        db.query(FieldInventorySamplePlot)
        .filter(
            FieldInventorySamplePlot.field_inventory_calculation_id
            == field_inventory_id
        )
        .all()
    )

    in_protected = 0
    for plot in plots:
        # A plot inside a protection working-circle unit is protected regardless
        # of sub-area geometry.
        if unit_wc.get(str(plot.block_name)) == "protection":
            plot.zone_type = "protected"
            in_protected += 1
            continue
        try:
            point = _point(plot.location)
            plot.zone_type = (
                "protected"
                if protected is not None
                and point is not None
                and protected.intersects(point)
                else "productive"
            )
        except (  # noqa: BLE001 -- one bad plot geometry must not abort tagging
            Exception
        ):
            plot.zone_type = "productive"
        if plot.zone_type == "protected":
            in_protected += 1

    db.flush()
    logger.info(
        f"[FI zone] {in_protected}/{len(plots)} sample plots in the protection stratum"
    )


def assign_plot_blocks_by_location(
    db: Session,
    field_inventory_id: UUID,
    field_inventory: "FieldInventoryCalculation",
    *,
    snap_tolerance_deg: float = 0.0025,
) -> None:
    """Re-key every sample plot to the forest unit its GPS point falls inside,
    overriding the block label carried in the uploaded sheet.

    The upload's block column is routinely unreliable: it names compartments
    that were since deleted and re-divided, or holds junk (``'nan'`` from a
    blank cell, a settlement name). Every downstream join from field-inventory
    results to the *current* forest structure keys on
    ``field_inventory_sample_plots.block_name`` — the per-block summaries, the
    forest-condition / growing-stock maps, per-unit MAI & AAH — so a stale
    label silently drops that plot's block out of all of them.

    Units are the same set the maps and yield regulation use: the calculation's
    compartments when it has any, else its top-level blocks
    (``forest_blocks`` — the authoritative store, keyed by ``name``). A plot is
    assigned to the first unit that contains it; a plot just outside every unit
    (boundary-precision slivers) is snapped to the nearest unit within
    ``snap_tolerance_deg`` (~0.0025° ≈ 250 m at Nepal latitudes). A plot with
    no usable location, or one further out than that (a genuinely bad
    coordinate — e.g. swapped lat/lon), keeps its uploaded label.

    No-op when the calculation has no ``forest_blocks`` rows (an upload-only
    forest whose structure lives solely in ``result_data``). Best-effort: a
    bad unit geometry is skipped and nothing is raised.
    """
    if not field_inventory or not field_inventory.calculation_id:
        return

    from geoalchemy2.shape import to_shape
    from shapely import wkt as shapely_wkt

    try:
        # The leaf view (FS-1a.5): the units that are not divided further. A plot is keyed to the smallest unit
        # that holds it; the old "compartments at every depth, else top-level blocks" list let a divided
        # compartment C1 win over its own sub-compartments SC1/SC2, so no plot ever reached them.
        units = forest_unit_queries.unit_rows(
            db, field_inventory.calculation_id, forest_unit_queries.View.LEAF
        )
    except Exception:  # noqa: BLE001 -- no structure to snap to → keep uploaded labels
        logger.warning("[FI block] could not load forest_blocks", exc_info=True)
        return
    if not units:
        return

    def _unit_name(b) -> str:
        return (
            b.name
            or b.block_name
            or getattr(b, "compartment_code", None)
            or f"Block {getattr(b, 'index', '') or ''}".strip()
        )

    shapes: list[tuple[str, Any, Any]] = []
    for b in units:
        try:
            g = to_shape(b.geometry)
            if g is not None and not g.is_empty:
                shapes.append((_unit_name(b), g, b.id))
        except (
            Exception
        ):  # noqa: BLE001 -- one bad unit geometry must not abort the pass
            logger.warning(
                "[FI block] skipping unit with unparseable geometry", exc_info=True
            )
    if not shapes:
        return
    unit_id_by_name = {nm: uid for nm, _g, uid in shapes}

    def _point(loc):
        if loc is None:
            return None
        if isinstance(loc, str):
            return shapely_wkt.loads(loc.split(";", 1)[-1].strip())
        return to_shape(loc)

    plots = (
        db.query(FieldInventorySamplePlot)
        .filter(
            FieldInventorySamplePlot.field_inventory_calculation_id
            == field_inventory_id
        )
        .all()
    )

    # 1) Resolve each plot's destination unit (only plots that actually move),
    # and -- Forest Structure rule D10, FS-1d.4 -- every plot's `unit_id`
    # (the live FK link), independent of whether its name label changes.
    targets: dict = {}
    unit_id_targets: dict = {}
    snapped = unmatched = 0
    for plot in plots:
        try:
            pt = _point(plot.location)
        except (  # noqa: BLE001 -- one bad plot geometry must not abort the pass
            Exception
        ):
            pt = None
        if pt is None:
            unmatched += 1
            continue

        hit = next((nm for nm, g, _uid in shapes if g.contains(pt)), None)
        if hit is None:
            nm, dist = min(
                ((nm, g.distance(pt)) for nm, g, _uid in shapes),
                key=lambda t: t[1],
                default=(None, None),
            )
            if nm is not None and dist is not None and dist <= snap_tolerance_deg:
                hit, snapped = nm, snapped + 1
        if hit is None:
            unmatched += 1
            continue
        if str(plot.block_name) != hit:
            targets[plot] = hit
        hit_unit_id = unit_id_by_name.get(hit)
        if hit_unit_id is not None and plot.unit_id != hit_unit_id:
            unit_id_targets[plot] = hit_unit_id

    if unit_id_targets:
        for plot, uid in unit_id_targets.items():
            plot.unit_id = uid
        db.flush()
        logger.info(
            "[FI block] %d/%d sample plots' unit_id resolved by location",
            len(unit_id_targets),
            len(plots),
        )

    if not targets:
        logger.info(
            "[FI block] all %d sample plots already keyed to their containing unit",
            len(plots),
        )
        return

    # 2) The (fi, block_name, sample_plot_number) unique key means two plots the
    #    sheet filed under different blocks but the same number collide once
    #    merged into one unit. Keep the first, renumber the rest to a free slot
    #    in that unit (non-destructive — measurements are FK-linked by plot id).
    moving = list(targets)
    orig_num = {p: int(p.sample_plot_number) for p in plots}
    reserved: dict = {}
    for plot in plots:
        dest = targets.get(plot) or str(plot.block_name)
        reserved.setdefault(dest, set())
        if plot not in targets:  # a plot that stays put owns its number
            reserved[dest].add(orig_num[plot])
    final_num = {}
    renumbered = 0
    for plot in moving:
        dest = targets[plot]
        n = orig_num[plot]
        if n in reserved[dest]:
            n = (max(reserved[dest]) if reserved[dest] else 0) + 1
            renumbered += 1
        reserved[dest].add(n)
        final_num[plot] = n

    # 3) Two-phase write: park every moving plot at a guaranteed-free number
    #    first so no intermediate row state trips the unique key mid-flush.
    for i, plot in enumerate(moving):
        plot.sample_plot_number = 1_000_000 + i
    db.flush()
    for plot in moving:
        plot.block_name = targets[plot]
        plot.sample_plot_number = final_num[plot]
    db.flush()

    if renumbered:
        logger.warning(
            "[FI block] %d plot(s) shared a plot number with another plot in the "
            "same destination unit (dirty upload) and were renumbered",
            renumbered,
        )
    logger.info(
        "[FI block] %d/%d sample plots re-keyed to their containing unit "
        "(%d snapped to nearest within %.4f°, %d kept their uploaded label)",
        len(moving),
        len(plots),
        snapped,
        snap_tolerance_deg,
        unmatched,
    )


# SQL predicate: a plot feeds yield regulation unless it is in the protection
# stratum. NULL zone_type (no protected sub-areas, or a pre-072 plot) counts as
# productive. `{a}` is the table alias prefix ('' or 'p.' / 'sp.').
def productive_plots_sql(alias: str = "") -> str:
    return f"({alias}zone_type IS DISTINCT FROM 'protected')"


def is_productive_plot(plot) -> bool:
    """ORM-side counterpart of :func:`productive_plots_sql`."""
    return getattr(plot, "zone_type", None) != "protected"


def invalidate_render_caches(db: Session, calculation_id: UUID) -> None:
    """Drop caches that hold *rendered* output keyed only by geometry/spec.

    ``op_data_cache`` self-invalidates on any ``calculation_id`` model change,
    but the pre-rendered map PNGs under ``uploads/maps_cache/<calc_id>/`` are
    keyed by ``calc_id + spec_hash + dpi`` only — a field-inventory reprocess
    changes every thematic map's data without changing that key, so a stale
    "No data" / old-value image would keep being served. Best-effort.
    """
    try:
        from app.services.management_plan_docx.plan_map_service import clear_map_cache

        clear_map_cache(calculation_id=calculation_id)
    except Exception:  # noqa: BLE001 -- a cache-clear failure must not fail processing
        logger.warning(
            "[FI] could not clear rendered-map cache for calc %s",
            calculation_id,
            exc_info=True,
        )

    try:
        from app.services.operational_plan.soil_erosion import clear_cache as _se_clear

        _se_clear(calculation_id)
    except Exception:  # noqa: BLE001 -- a cache-clear failure must not fail processing
        logger.warning(
            "[FI] could not clear soil-erosion cache for calc %s",
            calculation_id,
            exc_info=True,
        )

    try:
        from app.services.operational_plan.landslide_susceptibility import (
            clear_cache as _hv_clear,
        )

        _hv_clear(calculation_id)
    except Exception:  # noqa: BLE001 -- a cache-clear failure must not fail processing
        logger.warning(
            "[FI] could not clear hazard-vuln cache for calc %s",
            calculation_id,
            exc_info=True,
        )

    try:
        from app.services.sustainable_fm.sfm_service import invalidate_sfm

        invalidate_sfm(calculation_id, db)
    except (
        Exception
    ):  # noqa: BLE001 -- an invalidation failure must not fail processing
        logger.warning(
            "[FI] could not invalidate SFM block for calc %s",
            calculation_id,
            exc_info=True,
        )


# Debug logging for volume calculation comparison
DEBUG_VOLUME_CALC = os.environ.get("DEBUG_VOLUME_CALC", "false").lower() == "true"


def _debug_log(msg: str):
    """Print debug message if DEBUG_VOLUME_CALC is enabled"""
    if DEBUG_VOLUME_CALC:
        logger.debug(f"[FIELD_INV_VOLUME] {msg}")


# business: CFMG §6.2 — field inventory measurement processing
class FieldInventoryService:
    """
    Service for processing field inventory data
    """

    def __init__(self, db: Session):
        """Initialize service with database session"""
        self.db = db
        # why: species coefficients cached per service instance to avoid repeated DB queries
        self.species_coefficients = self._load_species_coefficients()

    # Columns pulled from tree_species_coefficients. The `core` set is created by
    # migration 002 and always present; the `optional` set has drifted between
    # environments — `growth_rate` (a reporting column) exists in cf_db/prod but
    # is created by no migration, so a migrations-only database (CI, the test
    # harness) does not have it. A missing optional column must degrade to a
    # default, not crash the whole service on construction.
    _SPECIES_CORE_COLS = (
        "scientific_name",
        "local_name",
        "a",
        "b",
        "c",
        "a1",
        "b1",
        "s",
        "m",
        "bg",
    )
    _SPECIES_OPTIONAL_COLS = (
        "growth_rate",
        "wood_density_gm_cm3",
        "full_stem_merchantable",
    )

    def _load_species_coefficients(self) -> Dict[str, Dict]:
        """Load species coefficients keyed by scientific name (incl. wood density)."""
        present = {
            r[0]
            for r in self.db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = 'tree_species_coefficients'"
                )
            ).fetchall()
        }
        cols = [
            c
            for c in (*self._SPECIES_CORE_COLS, *self._SPECIES_OPTIONAL_COLS)
            if c in present
        ]
        if "growth_rate" not in present:
            logger.warning(
                "[FI] tree_species_coefficients.growth_rate is absent on this "
                "database — MAI growth rate defaults to 'Moderate' for every species"
            )

        # cols is an allowlist filtered by the DB catalogue — no user input.
        rows = (
            self.db.execute(
                text(  # noqa: S608 -- identifiers are a hardcoded allowlist, not user input
                    f"SELECT {', '.join(cols)} FROM public.tree_species_coefficients WHERE is_active = TRUE"
                )
            )
            .mappings()
            .all()
        )

        coefficients: Dict[str, Dict] = {}
        for row in rows:
            wd = row.get("wood_density_gm_cm3")
            fsm = row.get("full_stem_merchantable")
            coefficients[row["scientific_name"]] = {
                "local_name": row.get("local_name"),
                "a": row.get("a"),
                "b": row.get("b"),
                "c": row.get("c"),
                "a1": row.get("a1"),
                "b1": row.get("b1"),
                "s": row.get("s"),
                "m": row.get("m"),
                "bg": row.get("bg"),
                "growth_rate": row.get("growth_rate"),
                "wood_density": (
                    float(wd) if wd is not None else float(DEFAULT_WOOD_DENSITY_T_M3)
                ),
                "full_stem_merchantable": bool(fsm) if fsm is not None else False,
            }

        return coefficients

    # business: 7-step pipeline: plots -> measurements -> volumes -> per-ha -> condition -> MAI -> DBH class
    async def process_field_inventory(
        self, field_inventory_id: UUID, df: pd.DataFrame, column_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Process complete field inventory

        Args:
            field_inventory_id: UUID of field inventory calculation
            df: DataFrame with field inventory data
            column_mapping: Column mapping dict

        Returns:
            Processing summary dict
        """
        start_time = time.time()

        # Get field inventory calculation record
        field_inventory = (
            self.db.query(FieldInventoryCalculation)
            .filter(FieldInventoryCalculation.id == field_inventory_id)
            .first()
        )

        if not field_inventory:
            raise ValueError(f"Field inventory {field_inventory_id} not found")

        try:
            # Update status
            field_inventory.status = "processing"
            self.db.commit()
            logger.info(
                f"[FIELD_INVENTORY] Processing {field_inventory_id} with {len(df)} rows"
            )

            # 0. Clean up any raw rows stored during upload (cascade deletes measurements)
            existing_plots = (
                self.db.query(FieldInventorySamplePlot)
                .filter(
                    FieldInventorySamplePlot.field_inventory_calculation_id
                    == field_inventory_id
                )
                .all()
            )
            for sp in existing_plots:
                self.db.delete(sp)
            self.db.flush()
            logger.info(
                f"[FIELD_INVENTORY] Cleaned up {len(existing_plots)} pre-existing sample plots"
            )

            # 1. Parse CSV and create sample plots
            sample_plots = await self._create_sample_plots(
                field_inventory_id, df, column_mapping
            )
            logger.info(f"[FIELD_INVENTORY] Created {len(sample_plots)} sample plots")

            # 2. Create measurements for all stand types. Rows are matched to
            #    plots by the uploaded (block_name, plot_number) key, so this
            #    must run BEFORE 2b re-keys block_name.
            measurements_count = await self._create_measurements(
                sample_plots, df, column_mapping
            )
            logger.info(f"[FIELD_INVENTORY] Created {measurements_count} measurements")

            # 2b. Re-key each sample plot to the forest block / compartment its
            #     GPS point actually falls inside. The uploaded block column
            #     routinely names units that were since deleted and re-divided,
            #     or holds junk ('nan', a settlement name); every per-unit join
            #     downstream (block summaries, thematic maps, per-unit MAI & AAH)
            #     keys on block_name. No-op for an upload-only forest with no
            #     forest_blocks rows.
            assign_plot_blocks_by_location(self.db, field_inventory_id, field_inventory)

            # 2c. Stratify plots into productive / protection zones (no-op unless
            #     the forest has a protection working circle or protected
            #     sub-areas). Runs after 2b so protection-unit matching by name
            #     sees the corrected block_name. Growing stock, MAI and allowable
            #     cut read this so the protection stratum stays out of yield
            #     regulation.
            assign_plot_zone_types(self.db, field_inventory_id, field_inventory)

            # 3. Calculate volumes for pole and tree
            await self._calculate_volumes(field_inventory_id)
            logger.info(f"[FIELD_INVENTORY] Volumes calculated")

            # 4. Calculate per-hectare extrapolation by block
            block_summaries = await self._calculate_per_hectare(
                field_inventory_id, field_inventory
            )
            logger.info(
                f"[FIELD_INVENTORY] Per-hectare calculated for {len(block_summaries)} blocks"
            )

            # 5. Assess forest condition for each block
            await self._assess_forest_condition(block_summaries)
            logger.info(f"[FIELD_INVENTORY] Forest condition assessed")

            # 6. Calculate MAI for each block
            await self._calculate_mai(block_summaries, field_inventory_id)
            logger.info(f"[FIELD_INVENTORY] MAI calculated")

            # 6.5. Calculate DBH class breakdown
            await self._calculate_dbh_class_breakdown(
                field_inventory_id, field_inventory, block_summaries
            )
            logger.info(f"[FIELD_INVENTORY] DBH class breakdown calculated")

            # 7. Update summary statistics
            field_inventory.total_sample_plots = len(sample_plots)
            field_inventory.total_blocks = len(block_summaries)
            field_inventory.status = "completed"
            field_inventory.completed_at = datetime.now(timezone.utc)
            field_inventory.processing_time_seconds = int(time.time() - start_time)
            self.db.commit()

            # Pre-rendered thematic/analysis map PNGs are keyed by geometry+spec
            # only, so this reprocess would otherwise keep serving stale images
            # (e.g. an all-"No data" forest-condition map from before the plots
            # were re-keyed to their blocks).
            if field_inventory.calculation_id:
                invalidate_render_caches(self.db, field_inventory.calculation_id)
                self._list_species_in_biodiversity(field_inventory)

            logger.info(
                f"[FIELD_INVENTORY] Processing complete in {field_inventory.processing_time_seconds}s"
            )

            return {
                "success": True,
                "field_inventory_id": str(field_inventory_id),
                "total_sample_plots": len(sample_plots),
                "total_blocks": len(block_summaries),
                "measurements_count": measurements_count,
                "processing_time_seconds": field_inventory.processing_time_seconds,
            }

        except Exception as e:
            # Update status to failed
            field_inventory.status = "failed"
            field_inventory.error_message = str(e)
            self.db.commit()
            logger.error(f"[FIELD_INVENTORY] Processing failed: {str(e)}")
            raise

    def _list_species_in_biodiversity(self, field_inventory: FieldInventoryCalculation) -> None:
        """Automatically record the inventory's unique tree species in the forest's Biodiversity list (owner rule 2026-10-10).
        Never fails the processing: the Biodiversity tab runs the same sync when it opens, so a miss here is caught up there."""
        try:
            from app.services.biodiversity_inventory_import import sync_from_inventory

            sync_from_inventory(self.db, field_inventory.calculation_id, field_inventory.user_id)
        except Exception:  # noqa: BLE001 -- best effort, logged; the tab's own sync retries
            self.db.rollback()
            logger.exception("[FIELD_INVENTORY] Could not list the inventory species in Biodiversity")

    async def refresh_from_stored(self, field_inventory_id: UUID) -> Dict[str, Any]:
        """Re-run the analysis of an ALREADY PROCESSED inventory from the plots and measurements stored in the database.

        The upload file is not kept, but steps 2b-7 of ``process_field_inventory`` never needed it: they re-key every plot to the
        CURRENT units by its GPS point, then recompute volumes, per-hectare figures, condition, MAI and the DBH classes. This is
        what "Update attribute" runs after the units were divided or reshaped.

        The old block summaries are kept in memory while the new ones are built and restored if anything fails, so a failure
        leaves the previous results exactly as they were.
        """
        field_inventory = (
            self.db.query(FieldInventoryCalculation)
            .filter(FieldInventoryCalculation.id == field_inventory_id)
            .first()
        )
        if not field_inventory:
            raise ValueError(f"Field inventory {field_inventory_id} not found")
        if str(field_inventory.status).lower() not in ("completed", "complete"):
            raise ValueError("Only a processed field inventory can be refreshed")
        n_plots = (
            self.db.query(FieldInventorySamplePlot)
            .filter(FieldInventorySamplePlot.field_inventory_calculation_id == field_inventory_id)
            .count()
        )
        if n_plots == 0:
            raise ValueError("No stored sample plots to refresh from; upload the field inventory again")

        # The database allows ONE summary per (inventory, unit name), so the old rows must go before the new ones are built. They are
        # kept in memory first, and put back unchanged if anything fails, so a failed refresh never costs the previous results.
        cols = [c.key for c in FieldInventoryBlockSummary.__table__.columns]
        snapshot = [{c: getattr(row, c) for c in cols} for row in field_inventory.block_summaries]
        started = time.time()
        try:
            self.db.query(FieldInventoryBlockSummary).filter(
                FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
            ).delete(synchronize_session=False)
            self.db.commit()
            self.db.expire_all()
            field_inventory = (
                self.db.query(FieldInventoryCalculation).filter(FieldInventoryCalculation.id == field_inventory_id).first()
            )
            assign_plot_blocks_by_location(self.db, field_inventory_id, field_inventory)
            assign_plot_zone_types(self.db, field_inventory_id, field_inventory)
            await self._calculate_volumes(field_inventory_id)
            summaries = await self._calculate_per_hectare(field_inventory_id, field_inventory)
            await self._assess_forest_condition(summaries)
            await self._calculate_mai(summaries, field_inventory_id)
            await self._calculate_dbh_class_breakdown(field_inventory_id, field_inventory, summaries)
        except Exception:
            self.db.rollback()
            self.db.query(FieldInventoryBlockSummary).filter(
                FieldInventoryBlockSummary.field_inventory_calculation_id == field_inventory_id
            ).delete(synchronize_session=False)
            self.db.add_all([FieldInventoryBlockSummary(**row) for row in snapshot])
            self.db.commit()
            logger.exception("[FIELD_INVENTORY] Refresh from stored data failed; previous results restored")
            raise

        field_inventory = (
            self.db.query(FieldInventoryCalculation).filter(FieldInventoryCalculation.id == field_inventory_id).first()
        )
        field_inventory.total_blocks = len(summaries)
        field_inventory.completed_at = datetime.now(timezone.utc)
        field_inventory.processing_time_seconds = int(time.time() - started)
        self.db.commit()
        if field_inventory.calculation_id:
            invalidate_render_caches(self.db, field_inventory.calculation_id)
            self._list_species_in_biodiversity(field_inventory)
        return {"success": True, "total_sample_plots": n_plots, "total_blocks": len(summaries), "replaced": len(snapshot)}

    # NOTE: first GPS coordinate used as plot center when multiple rows per plot
    async def _create_sample_plots(
        self, field_inventory_id: UUID, df: pd.DataFrame, column_mapping: Dict[str, str]
    ) -> List[FieldInventorySamplePlot]:
        """Create sample plot records"""
        sample_plots_dict = {}

        block_col = column_mapping.get("block_name")
        plot_col = column_mapping.get("sample_plot_number")
        lon_col = column_mapping.get("longitude")
        lat_col = column_mapping.get("latitude")

        # Resource yield columns (optional — from uploaded CSV/Excel)
        fw_col = column_mapping.get("firewood_kg_per_100sqm_per_year")
        gr_col = column_mapping.get("grass_kg_per_100sqm_per_year")
        bd_col = column_mapping.get("bedding_material_kg_per_100sqm_per_year")

        for idx, row in df.iterrows():
            try:
                block_name = str(row[block_col])
                plot_number = int(
                    float(row[plot_col])
                )  # Convert to float first in case it's "1.0"
                lon = float(row[lon_col])
                lat = float(row[lat_col])
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(
                    f"[SAMPLE_PLOTS] Skipping row {idx}: Invalid data - {str(e)}"
                )
                continue

            # Create unique key
            key = (block_name, plot_number)

            # Extract resource yield values (only from first row of each plot)
            firewood_kg = None
            grass_kg = None
            bedding_kg = None
            if fw_col:
                try:
                    firewood_kg = float(row[fw_col])
                except (ValueError, TypeError, KeyError):
                    pass
            if gr_col:
                try:
                    grass_kg = float(row[gr_col])
                except (ValueError, TypeError, KeyError):
                    pass
            if bd_col:
                try:
                    bedding_kg = float(row[bd_col])
                except (ValueError, TypeError, KeyError):
                    pass

            # Create sample plot only once per unique (block, plot) combination
            # If multiple rows have different coordinates for same plot (common when GPS recorded per tree),
            # we use the FIRST coordinate encountered as the plot center
            if key not in sample_plots_dict:
                sample_plot = FieldInventorySamplePlot(
                    field_inventory_calculation_id=field_inventory_id,
                    block_name=block_name,
                    sample_plot_number=plot_number,
                    location=f"SRID=4326;POINT({lon} {lat})",
                    firewood_kg_per_100sqm_per_year=firewood_kg,
                    grass_kg_per_100sqm_per_year=grass_kg,
                    bedding_material_kg_per_100sqm_per_year=bedding_kg,
                )
                self.db.add(sample_plot)
                sample_plots_dict[key] = sample_plot

        self.db.flush()
        return list(sample_plots_dict.values())

    async def _create_measurements(
        self,
        sample_plots: List[FieldInventorySamplePlot],
        df: pd.DataFrame,
        column_mapping: Dict[str, str],
    ) -> int:
        """Create measurement records for all stand types"""
        measurements_count = 0

        # Create lookup dict for sample plots
        plot_lookup = {}
        for plot in sample_plots:
            key = (plot.block_name, plot.sample_plot_number)
            plot_lookup[key] = plot

        # Get column names
        block_col = column_mapping.get("block_name")
        plot_col = column_mapping.get("sample_plot_number")

        # Process each row
        for idx, row in df.iterrows():
            block_name = str(row[block_col])
            plot_number = int(row[plot_col])
            key = (block_name, plot_number)

            sample_plot = plot_lookup.get(key)
            if not sample_plot:
                continue

            # Create measurements for each stand type present
            # 1. Regeneration
            if self._has_stand_type_data(row, "regeneration", column_mapping):
                measurement = self._create_stand_measurement(
                    row, "Regeneration", sample_plot.id, column_mapping
                )
                if measurement:
                    self.db.add(measurement)
                    measurements_count += 1

            # 2. Sapling
            if self._has_stand_type_data(row, "sapling", column_mapping):
                measurement = self._create_stand_measurement(
                    row, "Sapling", sample_plot.id, column_mapping
                )
                if measurement:
                    self.db.add(measurement)
                    measurements_count += 1

            # 3. Pole
            if self._has_stand_type_data(row, "pole", column_mapping):
                measurement = self._create_stand_measurement(
                    row, "Pole", sample_plot.id, column_mapping
                )
                if measurement:
                    self.db.add(measurement)
                    measurements_count += 1

            # 4. Tree
            if self._has_stand_type_data(row, "tree", column_mapping):
                measurement = self._create_stand_measurement(
                    row, "Tree", sample_plot.id, column_mapping
                )
                if measurement:
                    self.db.add(measurement)
                    measurements_count += 1

        self.db.flush()
        return measurements_count

    def _has_stand_type_data(
        self, row: pd.Series, stand_type: str, column_mapping: Dict[str, str]
    ) -> bool:
        """Check if row has data for this stand type"""
        # Map stand type to column prefix
        if stand_type == "regeneration":
            prefix = "regen"
        elif stand_type == "sapling":
            prefix = "sapling"
        elif stand_type == "pole":
            prefix = "pole"
        elif stand_type == "tree":
            prefix = "tree"
        else:
            prefix = stand_type.lower()

        species_col = column_mapping.get(f"{prefix}_species_scientific")

        if not species_col or species_col not in row.index:
            return False

        # Check if species is present and not null
        species_value = row[species_col]
        return pd.notna(species_value) and str(species_value).strip() != ""

    def _create_stand_measurement(
        self,
        row: pd.Series,
        stand_type: str,
        sample_plot_id: UUID,
        column_mapping: Dict[str, str],
    ) -> Optional[FieldInventoryMeasurement]:
        """Create a measurement record for a specific stand type"""
        # Determine column prefix
        if stand_type == "Regeneration":
            prefix = "regen"
        elif stand_type == "Sapling":
            prefix = "sapling"
        elif stand_type == "Pole":
            prefix = "pole"
        elif stand_type == "Tree":
            prefix = "tree"
        else:
            return None

        # Get column names
        species_col = column_mapping.get(f"{prefix}_species_scientific")
        dbh_col = column_mapping.get(f"{prefix}_dbh_cm") or column_mapping.get(
            f"{prefix}_dbh"
        )
        height_col = column_mapping.get(f"{prefix}_height_m")
        class_col = column_mapping.get(f"{prefix}_class")
        count_col = column_mapping.get(f"{prefix}_count")
        sn_col = column_mapping.get(f"{prefix}_sn")

        if not species_col:
            return None

        # Get species
        species = str(row[species_col]).strip()
        if not species or species == "" or pd.isna(row[species_col]):
            return None

        # Get local name from species coefficients
        species_local = self.species_coefficients.get(species, {}).get("local_name")

        # Get DBH
        dbh_cm = None
        if dbh_col and dbh_col in row.index:
            dbh_value = row[dbh_col]
            if pd.notna(dbh_value):
                try:
                    dbh_cm = float(dbh_value)
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[MEASUREMENT] Cannot convert DBH to float: '{dbh_value}' (column: {dbh_col})"
                    )
                    return None  # Skip this measurement if DBH is invalid

        # Get height
        height_m = None
        height_estimated = False
        if height_col and height_col in row.index:
            height_value = row[height_col]
            if pd.notna(height_value):
                try:
                    height_m = float(height_value)
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[MEASUREMENT] Cannot convert height to float: '{height_value}' (column: {height_col}), will estimate if possible"
                    )
                    # Don't return None yet - height can be estimated for pole/tree
            elif dbh_cm and stand_type in ["Pole", "Tree"]:
                # Estimate height for pole/tree if missing
                height_m = dbh_cm * HEIGHT_FROM_DBH_FACTOR
                height_estimated = True

            # If height still not available but we have DBH, estimate it
            if not height_m and dbh_cm and stand_type in ["Pole", "Tree"]:
                height_m = dbh_cm * HEIGHT_FROM_DBH_FACTOR
                height_estimated = True

        # Get class
        tree_class = None
        if class_col and class_col in row.index:
            class_value = row[class_col]
            if pd.notna(class_value) and str(class_value).strip() != "":
                tc_raw = str(class_value).strip()
                try:
                    tc_num = str(int(float(tc_raw)))
                    tree_class = {"1": "a", "2": "b", "3": "c", "4": "d"}.get(
                        tc_num, tc_num
                    )
                except (ValueError, TypeError):
                    tc_lower = tc_raw.lower()
                    tree_class = {
                        "i": "a",
                        "ii": "b",
                        "iii": "c",
                        "iv": "d",
                        "a": "a",
                        "b": "b",
                        "c": "c",
                        "d": "d",
                    }.get(tc_lower, tc_lower)

        # Get count (for regeneration and sapling)
        count = 1
        if count_col and count_col in row.index:
            count_value = row[count_col]
            if pd.notna(count_value):
                try:
                    count = int(
                        float(count_value)
                    )  # Convert to float first to handle "1.0"
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[MEASUREMENT] Cannot convert count to int: '{count_value}' (column: {count_col}), using default 1"
                    )
                    count = 1

        # Get SN
        sn = None
        if sn_col and sn_col in row.index:
            sn_value = row[sn_col]
            if pd.notna(sn_value):
                try:
                    sn = int(float(sn_value))
                except (ValueError, TypeError) as e:
                    logger.warning(
                        f"[MEASUREMENT] Cannot convert SN to int: '{sn_value}' (column: {sn_col}), skipping"
                    )

        # Volumes are NEVER read from the uploaded CSV. Per SSOT rule (Decision #4),
        # every volume is always (re)computed by the shared volume_calculator so
        # the formula and coefficients stay the single source of truth across all tabs.

        # Classify DBH
        dbh_class = None
        if dbh_cm:
            dbh_class = DbhClassRegistry.classify_detailed(dbh_cm)

        # Calculate basal area (m²) from DBH (cm): BA = π × (DBH/200)²
        basal_area_m2 = None
        if dbh_cm:
            basal_area_m2 = round(math.pi * (dbh_cm / 200.0) ** 2, 6)

        measurement = FieldInventoryMeasurement(
            sample_plot_id=sample_plot_id,
            stand_type=stand_type,
            sn=sn,
            species_scientific=species,
            species_local=species_local,
            dbh_cm=dbh_cm,
            height_m=height_m,
            height_estimated=height_estimated,
            tree_class=tree_class,
            count=count,
            dbh_class=dbh_class,
            basal_area_m2=basal_area_m2,
        )

        return measurement

    def store_raw_measurements(
        self, field_inventory_id: UUID, df: pd.DataFrame, column_mapping: Dict[str, str]
    ):
        """Store raw measurement rows at upload time (no volume calculations).

        Creates sample plots and measurements with only the raw uploaded fields
        (species, DBH, height, class, count, yield data). Volume columns are left NULL
        — they will be filled during the processing step.

        This mirrors _create_sample_plots() + _create_measurements() but without
        _calculate_volumes(), so that {{table:fieldinventory}} works immediately
        after upload.
        """
        block_col = column_mapping.get("block_name")
        plot_col = column_mapping.get("sample_plot_number")
        lon_col = column_mapping.get("longitude")
        lat_col = column_mapping.get("latitude")
        fw_col = column_mapping.get("firewood_kg_per_100sqm_per_year")
        gr_col = column_mapping.get("grass_kg_per_100sqm_per_year")
        bd_col = column_mapping.get("bedding_material_kg_per_100sqm_per_year")

        # 1. Create sample plots (unique block+plot combos)
        sample_plots_dict = {}
        for idx, row in df.iterrows():
            try:
                block_name = str(row[block_col])
                plot_number = int(float(row[plot_col]))
                lon = float(row[lon_col])
                lat = float(row[lat_col])
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(
                    f"[RAW_STORE] Skipping row {idx}: Invalid plot data - {str(e)}"
                )
                continue

            key = (block_name, plot_number)
            if key in sample_plots_dict:
                continue

            firewood_kg = grass_kg = bedding_kg = None
            if fw_col:
                try:
                    firewood_kg = float(row[fw_col])
                except (ValueError, TypeError, KeyError):
                    pass
            if gr_col:
                try:
                    grass_kg = float(row[gr_col])
                except (ValueError, TypeError, KeyError):
                    pass
            if bd_col:
                try:
                    bedding_kg = float(row[bd_col])
                except (ValueError, TypeError, KeyError):
                    pass

            sample_plot = FieldInventorySamplePlot(
                field_inventory_calculation_id=field_inventory_id,
                block_name=block_name,
                sample_plot_number=plot_number,
                location=f"SRID=4326;POINT({lon} {lat})",
                firewood_kg_per_100sqm_per_year=firewood_kg,
                grass_kg_per_100sqm_per_year=grass_kg,
                bedding_material_kg_per_100sqm_per_year=bedding_kg,
            )
            self.db.add(sample_plot)
            sample_plots_dict[key] = sample_plot

        self.db.flush()

        # 2. Create measurement rows (raw fields only, no volume calculations)
        for idx, row in df.iterrows():
            try:
                block_name = str(row[block_col])
                plot_number = int(float(row[plot_col]))
            except (ValueError, TypeError, KeyError):
                continue

            sample_plot = sample_plots_dict.get((block_name, plot_number))
            if not sample_plot:
                continue

            for stand_type_info in [
                ("Regeneration", "regen"),
                ("Sapling", "sapling"),
                ("Pole", "pole"),
                ("Tree", "tree"),
            ]:
                stand_type, prefix = stand_type_info
                species_col = column_mapping.get(f"{prefix}_species_scientific")
                if not species_col or species_col not in row.index:
                    continue
                species_value = row[species_col]
                if pd.isna(species_value) or str(species_value).strip() == "":
                    continue

                species = str(species_value).strip()
                species_local = self.species_coefficients.get(species, {}).get(
                    "local_name"
                )

                dbh_col = column_mapping.get(f"{prefix}_dbh_cm") or column_mapping.get(
                    f"{prefix}_dbh"
                )
                dbh_cm = None
                if dbh_col and dbh_col in row.index and pd.notna(row[dbh_col]):
                    try:
                        dbh_cm = float(row[dbh_col])
                    except (ValueError, TypeError):
                        pass

                height_col = column_mapping.get(f"{prefix}_height_m")
                height_m = None
                height_estimated = False
                if height_col and height_col in row.index and pd.notna(row[height_col]):
                    try:
                        height_m = float(row[height_col])
                    except (ValueError, TypeError):
                        pass
                if not height_m and dbh_cm and stand_type in ("Pole", "Tree"):
                    height_m = dbh_cm * HEIGHT_FROM_DBH_FACTOR
                    height_estimated = True

                class_col = column_mapping.get(f"{prefix}_class")
                tree_class = None
                if class_col and class_col in row.index and pd.notna(row[class_col]):
                    tc_raw = str(row[class_col]).strip()
                    if tc_raw:
                        try:
                            tc_num = str(int(float(tc_raw)))
                            tree_class = {"1": "a", "2": "b", "3": "c", "4": "d"}.get(
                                tc_num, tc_num
                            )
                        except (ValueError, TypeError):
                            tc_lower = tc_raw.lower()
                            tree_class = {
                                "i": "a",
                                "ii": "b",
                                "iii": "c",
                                "iv": "d",
                                "a": "a",
                                "b": "b",
                                "c": "c",
                                "d": "d",
                            }.get(tc_lower, tc_lower)

                count_col = column_mapping.get(f"{prefix}_count")
                count = 1
                if count_col and count_col in row.index and pd.notna(row[count_col]):
                    try:
                        count = int(float(row[count_col]))
                    except (ValueError, TypeError):
                        pass

                sn_col = column_mapping.get(f"{prefix}_sn")
                sn = None
                if sn_col and sn_col in row.index and pd.notna(row[sn_col]):
                    try:
                        sn = int(float(row[sn_col]))
                    except (ValueError, TypeError):
                        pass

                dbh_class = (
                    DbhClassRegistry.classify_detailed(dbh_cm) if dbh_cm else None
                )
                basal_area_m2 = (
                    round(math.pi * (dbh_cm / 200.0) ** 2, 6) if dbh_cm else None
                )

                measurement = FieldInventoryMeasurement(
                    sample_plot_id=sample_plot.id,
                    stand_type=stand_type,
                    sn=sn,
                    species_scientific=species,
                    species_local=species_local,
                    dbh_cm=dbh_cm,
                    height_m=height_m,
                    height_estimated=height_estimated,
                    tree_class=tree_class,
                    count=count,
                    dbh_class=dbh_class,
                    basal_area_m2=basal_area_m2,
                )
                self.db.add(measurement)

        self.db.flush()

    # why: stem_volume/branch_volume from volume_calculator, raw values not quality-adjusted
    async def _calculate_volumes(self, field_inventory_id: UUID):
        """Calculate volumes for pole and tree measurements"""
        logger.info(
            "[VOLUME_CALCULATION] Starting volume calculations for pole and tree..."
        )

        # Get all pole and tree measurements
        measurements = (
            self.db.query(FieldInventoryMeasurement)
            .join(FieldInventorySamplePlot)
            .filter(
                FieldInventorySamplePlot.field_inventory_calculation_id
                == field_inventory_id,
                FieldInventoryMeasurement.stand_type.in_(["Pole", "Tree"]),
            )
            .all()
        )

        logger.info(
            f"[VOLUME_CALCULATION] Calculating volumes for {len(measurements)} pole/tree measurements"
        )

        for measurement in measurements:
            # Skip if no DBH
            if not measurement.dbh_cm or measurement.dbh_cm < 10:
                continue

            # Volumes are ALWAYS recomputed via the shared calculator (Decision #4):
            # CSV-provided volumes are ignored so the SSOT formula/coefficients apply.

            # Get species coefficients
            species = measurement.species_scientific
            if species not in self.species_coefficients:
                logger.warning(f"[VOLUME_CALCULATION] Species not found: {species}")
                continue

            coef = self.species_coefficients[species]

            # Get or estimate height
            height_m = measurement.height_m
            height_estimated = False
            if not height_m:
                height_m = measurement.dbh_cm * HEIGHT_FROM_DBH_FACTOR
                height_estimated = True

            # Normalize tree class to int (1-4) before calling the shared calculator
            dbh_cm = float(measurement.dbh_cm)
            tree_class_raw = measurement.tree_class or "b"
            try:
                tree_class = str(int(float(tree_class_raw)))
            except (ValueError, TypeError):
                tree_class = str(tree_class_raw).strip().lower()
            class_mapping = {
                "1": 1,
                "i": 1,
                "a": 1,
                "2": 2,
                "ii": 2,
                "b": 2,
                "3": 3,
                "iii": 3,
                "c": 3,
                "4": 4,
                "iv": 4,
                "d": 4,
            }
            normalized_class = class_mapping.get(tree_class, 2)

            _debug_log(
                f"INPUT: dbh={dbh_cm}, height={height_m}, height_estimated={height_estimated}, normalized_class={normalized_class}"
            )
            _debug_log(f"SPECIES: {species}")
            _debug_log(
                f"COEFFS: a={coef.get('a')}, b={coef.get('b')}, c={coef.get('c')}, a1={coef.get('a1')}, b1={coef.get('b1')}, s={coef.get('s')}, m={coef.get('m')}, bg={coef.get('bg')}, fsm={coef.get('full_stem_merchantable')}"
            )

            # Call the shared volume calculator (single source of truth)
            volumes = shared_calculate_volumes(dbh_cm, height_m, normalized_class, coef)

            _debug_log(
                f"NET: original_class={measurement.tree_class}, normalized_class={normalized_class}, net_vol={volumes['net_volume']}"
            )
            _debug_log(
                f"FINAL: stem={volumes['stem_volume']}, branch={volumes['branch_volume']}, tree={volumes['tree_volume']}, gross={volumes['gross_volume']}, net={volumes['net_volume']}, firewood={volumes['firewood_m3']}"
            )

            # Convert to cubic feet
            net_volume_cft = volumes["net_volume"] * CFT_PER_M3

            # 8. Firewood in chatta
            firewood_chatta = volumes["firewood_m3"] / M3_PER_CHATTA

            # Update measurement
            measurement.stem_volume = round(volumes["stem_volume"], 6)
            measurement.branch_volume = round(volumes["branch_volume"], 6)
            measurement.tree_volume = round(volumes["tree_volume"], 6)
            measurement.gross_volume = round(volumes["gross_volume"], 6)
            measurement.net_volume = round(volumes["net_volume"], 6)
            measurement.net_volume_cft = round(net_volume_cft, 6)
            measurement.firewood_m3 = round(volumes["firewood_m3"], 6)
            measurement.firewood_chatta = round(firewood_chatta, 6)

        self.db.commit()
        logger.info("[VOLUME_CALCULATION] Volume calculations complete")

    # business: per-ha = value / total_plots / plot_area * SQM_PER_HA
    # constraint: pole plot = 100m², tree plot = 500m²
    async def _calculate_per_hectare(
        self, field_inventory_id: UUID, field_inventory: FieldInventoryCalculation
    ) -> List[FieldInventoryBlockSummary]:
        """Calculate per-hectare extrapolation for each block"""
        logger.info("[PER_HECTARE] Calculating per-hectare extrapolation...")

        # Get all sample plots grouped by block
        query = text(
            """
            SELECT DISTINCT block_name
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :field_inventory_id
        """
        )
        blocks = self.db.execute(
            query, {"field_inventory_id": str(field_inventory_id)}
        ).fetchall()

        block_summaries = []

        for (block_name,) in blocks:
            # Get sample plots in this block
            block_plots = (
                self.db.query(FieldInventorySamplePlot)
                .filter(
                    FieldInventorySamplePlot.field_inventory_calculation_id
                    == field_inventory_id,
                    FieldInventorySamplePlot.block_name == block_name,
                )
                .all()
            )

            # Split into strata. The summary below (growing stock -> condition ->
            # MAI -> AAH) is built from PRODUCTIVE plots only; protection-stratum
            # plots yield a growing-stock-only figure reported on the side.
            plots = [p for p in block_plots if is_productive_plot(p)]
            protected_plots = [p for p in block_plots if not is_productive_plot(p)]

            total_sample_plots = len(plots)

            # Get all measurements for this block
            plot_ids = [plot.id for plot in plots]

            # Calculate averages per stand type
            regen_stats = self._calculate_stand_averages(
                "Regeneration", plot_ids, total_sample_plots
            )
            sapling_stats = self._calculate_stand_averages(
                "Sapling", plot_ids, total_sample_plots
            )
            pole_stats = self._calculate_stand_averages(
                "Pole", plot_ids, total_sample_plots
            )
            tree_stats = self._calculate_stand_averages(
                "Tree", plot_ids, total_sample_plots
            )

            # Extrapolate to per-hectare (1 ha = 10,000 sqm)
            regen_area = float(
                field_inventory.regeneration_area_sqm or REGEN_PLOT_AREA_SQM
            )
            sapling_area = float(
                field_inventory.sapling_area_sqm or SAPLING_PLOT_AREA_SQM
            )
            pole_area = float(field_inventory.pole_area_sqm or POLE_PLOT_AREA_SQM)
            tree_area = float(field_inventory.tree_area_sqm or TREE_PLOT_AREA_SQM)

            regen_per_ha = (
                int((regen_stats["count"] / regen_area) * SQM_PER_HA)
                if regen_stats["count"] > 0
                else 0
            )
            sapling_per_ha = (
                int((sapling_stats["count"] / sapling_area) * SQM_PER_HA)
                if sapling_stats["count"] > 0
                else 0
            )
            pole_per_ha = (
                int((pole_stats["count"] / pole_area) * SQM_PER_HA)
                if pole_stats["count"] > 0
                else 0
            )
            tree_per_ha = (
                int((tree_stats["count"] / tree_area) * SQM_PER_HA)
                if tree_stats["count"] > 0
                else 0
            )

            # Extrapolate volumes to per-hectare
            pole_timber_per_ha = (
                (pole_stats["net_volume"] / pole_area) * SQM_PER_HA
                if pole_stats["net_volume"] > 0
                else 0
            )
            pole_firewood_per_ha = (
                (pole_stats["firewood"] / pole_area) * SQM_PER_HA
                if pole_stats["firewood"] > 0
                else 0
            )
            tree_timber_per_ha = (
                (tree_stats["net_volume"] / tree_area) * SQM_PER_HA
                if tree_stats["net_volume"] > 0
                else 0
            )
            tree_firewood_per_ha = (
                (tree_stats["firewood"] / tree_area) * SQM_PER_HA
                if tree_stats["firewood"] > 0
                else 0
            )

            # Extrapolate basal area (m²/ha) - Pole and Tree only
            pole_basal_per_ha = (
                (pole_stats["basal_area"] / pole_area) * SQM_PER_HA
                if pole_stats["basal_area"] > 0
                else 0
            )
            tree_basal_per_ha = (
                (tree_stats["basal_area"] / tree_area) * SQM_PER_HA
                if tree_stats["basal_area"] > 0
                else 0
            )
            total_basal_area_m2_per_ha = pole_basal_per_ha + tree_basal_per_ha

            # Total growing stock (timber only, for DFO reporting) — PRODUCTIVE.
            total_growing_stock = pole_timber_per_ha + tree_timber_per_ha

            # Protection stratum: growing stock only (pole + tree net volume),
            # extrapolated the same way but kept OUT of condition / MAI / AAH.
            protected_plot_count = len(protected_plots)
            protected_growing_stock = None
            if protected_plot_count:
                p_ids = [p.id for p in protected_plots]
                p_pole = self._calculate_stand_averages(
                    "Pole", p_ids, protected_plot_count
                )
                p_tree = self._calculate_stand_averages(
                    "Tree", p_ids, protected_plot_count
                )
                protected_growing_stock = round(
                    (p_pole["net_volume"] / pole_area) * SQM_PER_HA
                    + (p_tree["net_volume"] / tree_area) * SQM_PER_HA,
                    6,
                )

            # Gross volume (merchantable stem) per-ha — for IPCC AGB calculation
            pole_gross_per_ha = (
                (pole_stats["gross_volume"] / pole_area) * SQM_PER_HA
                if pole_stats["gross_volume"] > 0
                else 0
            )
            tree_gross_per_ha = (
                (tree_stats["gross_volume"] / tree_area) * SQM_PER_HA
                if tree_stats["gross_volume"] > 0
                else 0
            )
            total_gross_per_ha = pole_gross_per_ha + tree_gross_per_ha

            # Calculate carbon metrics using IPCC Tier 2 methodology
            # AGB = VOB × WD × BEF where VOB = gross_volume (merchantable stem)
            carbon_metrics = self._calculate_carbon_metrics(
                plot_ids=plot_ids, total_gross_per_ha=total_gross_per_ha
            )

            # Calculate satellite-derived volume from AGB raster
            satellite_volume = None
            if field_inventory.calculation_id:
                satellite_volume = self._calculate_satellite_volume_for_block(
                    calculation_id=field_inventory.calculation_id, block_name=block_name
                )

            # --- NEW: Per-hectare resource yields (for Demand & Supply tab) ---
            # Average kg/100sqm/year values across all plots in block,
            # then multiply by 100 to get kg/ha/year
            fw_vals = [
                p.firewood_kg_per_100sqm_per_year
                for p in plots
                if p.firewood_kg_per_100sqm_per_year is not None
            ]
            gr_vals = [
                p.grass_kg_per_100sqm_per_year
                for p in plots
                if p.grass_kg_per_100sqm_per_year is not None
            ]
            bd_vals = [
                p.bedding_material_kg_per_100sqm_per_year
                for p in plots
                if p.bedding_material_kg_per_100sqm_per_year is not None
            ]

            n_fw = len(fw_vals)
            n_gr = len(gr_vals)
            n_bd = len(bd_vals)

            firewood_kg_per_ha = round(
                (sum(fw_vals) / n_fw * 100) if n_fw > 0 else 0, 6
            )
            grass_kg_per_ha = round((sum(gr_vals) / n_gr * 100) if n_gr > 0 else 0, 6)
            bedding_kg_per_ha = round((sum(bd_vals) / n_bd * 100) if n_bd > 0 else 0, 6)

            # Create block summary
            block_summary = FieldInventoryBlockSummary(
                field_inventory_calculation_id=field_inventory_id,
                block_name=block_name,
                total_sample_plots=total_sample_plots,
                regeneration_per_ha=regen_per_ha,
                sapling_per_ha=sapling_per_ha,
                pole_per_ha=pole_per_ha,
                tree_per_ha=tree_per_ha,
                pole_timber_m3_per_ha=round(pole_timber_per_ha, 6),
                pole_firewood_m3_per_ha=round(pole_firewood_per_ha, 6),
                tree_timber_m3_per_ha=round(tree_timber_per_ha, 6),
                tree_firewood_m3_per_ha=round(tree_firewood_per_ha, 6),
                total_growing_stock_m3_per_ha=round(total_growing_stock, 6),
                protected_growing_stock_m3_per_ha=protected_growing_stock,
                protected_sample_plots=protected_plot_count or None,
                basal_area_m2_per_ha=round(total_basal_area_m2_per_ha, 6),
                satellite_volume_m3_per_ha=satellite_volume,
                # Resource yields (kg/ha/year for Demand & Supply tab)
                firewood_kg_per_ha_per_year=firewood_kg_per_ha,
                grass_kg_per_ha_per_year=grass_kg_per_ha,
                bedding_material_kg_per_ha_per_year=bedding_kg_per_ha,
                # Carbon metrics
                weighted_wood_density=carbon_metrics["weighted_density"],
                agb_t_per_ha=carbon_metrics["agb_t_per_ha"],
                bgb_t_per_ha=carbon_metrics["bgb_t_per_ha"],
                total_biomass_t_per_ha=carbon_metrics["total_biomass_t_per_ha"],
                carbon_stock_tc_per_ha=carbon_metrics["carbon_stock_tc_per_ha"],
                co2_equivalent_tco2_per_ha=carbon_metrics["co2_equivalent_tco2_per_ha"],
            )

            self.db.add(block_summary)
            block_summaries.append(block_summary)

            logger.info(
                f"[PER_HECTARE] Block '{block_name}': Regen={regen_per_ha}/ha, Sapling={sapling_per_ha}/ha, Growing stock={total_growing_stock:.2f} m³/ha"
            )

        self.db.flush()
        logger.info(
            f"[PER_HECTARE] Per-hectare calculation complete for {len(block_summaries)} blocks"
        )
        return block_summaries

    def _calculate_stand_averages(
        self, stand_type: str, plot_ids: List[UUID], total_plots: int
    ) -> Dict[str, float]:
        """Calculate average counts and volumes per plot for a stand type"""
        measurements = (
            self.db.query(FieldInventoryMeasurement)
            .filter(
                FieldInventoryMeasurement.sample_plot_id.in_(plot_ids),
                FieldInventoryMeasurement.stand_type == stand_type,
            )
            .all()
        )

        if not measurements:
            return {
                "count": 0,
                "net_volume": 0,
                "firewood": 0,
                "basal_area": 0,
                "gross_volume": 0,
            }

        # Sum counts and volumes
        total_count = sum(m.count for m in measurements)
        total_net_volume = sum(float(m.net_volume or 0) for m in measurements)
        total_firewood = sum(float(m.firewood_m3 or 0) for m in measurements)
        total_basal_area = sum(
            float(m.basal_area_m2 or 0) * m.count for m in measurements
        )
        total_gross_volume = sum(float(m.gross_volume or 0) for m in measurements)

        # Calculate averages per plot
        avg_count = total_count / total_plots
        avg_net_volume = total_net_volume / total_plots
        avg_firewood = total_firewood / total_plots
        avg_basal_area = total_basal_area / total_plots
        avg_gross_volume = total_gross_volume / total_plots

        return {
            "count": avg_count,
            "net_volume": avg_net_volume,
            "firewood": avg_firewood,
            "basal_area": avg_basal_area,
            "gross_volume": avg_gross_volume,
        }

    def _calculate_carbon_metrics(
        self, plot_ids: List[UUID], total_gross_per_ha: float
    ) -> Dict[str, float]:
        """
        Calculate carbon metrics using IPCC Tier 2 methodology.

        Formulas (IPCC 2006 Guidelines, Vol 4, Ch 4):
          AGB = VOB × WD × BEF           [Eq 2.2.1]
          BGB = AGB × R/S                 [Eq 2.2.2]
          Total Biomass = AGB + BGB
          Carbon Stock = Total Biomass × CF     [Table 4.3]
          CO2e = Carbon Stock × 3.67

        Where:
          VOB = Gross merchantable stem volume (gross_volume in DB)
          WD  = Species wood density (g/cm³ = t/m³)
          BEF = 1.3   (Table 4.4 — tropical moist deciduous forest)
          R/S = 0.24  (Table 4.4 — tropical moist forest)
          CF  = 0.47  (Table 4.3 — tropical forest)

        Density is computed as per-tree sum:
          weighted_density = Σ(gross_volume × species_density) / Σ(gross_volume)

        Args:
            plot_ids: List of sample plot UUIDs
            total_gross_per_ha: Total gross merchantable volume (m³/ha)

        Returns:
            Dictionary with carbon metrics
        """
        if total_gross_per_ha <= 0:
            return {
                "weighted_density": 0.0,
                "agb_t_per_ha": 0.0,
                "bgb_t_per_ha": 0.0,
                "total_biomass_t_per_ha": 0.0,
                "carbon_stock_tc_per_ha": 0.0,
                "co2_equivalent_tco2_per_ha": 0.0,
            }

        # Get measurements for Pole and Tree only (they have volume data)
        measurements = (
            self.db.query(FieldInventoryMeasurement)
            .filter(
                FieldInventoryMeasurement.sample_plot_id.in_(plot_ids),
                FieldInventoryMeasurement.stand_type.in_(["Pole", "Tree"]),
                FieldInventoryMeasurement.gross_volume.isnot(None),
                FieldInventoryMeasurement.gross_volume > 0,
            )
            .all()
        )

        # Per-tree sum: Σ(gross_volume × species_density) and Σ(gross_volume)
        total_gross_volume = 0.0
        weighted_density_sum = 0.0

        for m in measurements:
            species_name = m.species_scientific
            gross_vol = float(m.gross_volume or 0)

            wood_density = float(DEFAULT_WOOD_DENSITY_T_M3)
            if species_name in self.species_coefficients:
                wood_density = self.species_coefficients[species_name].get(
                    "wood_density", float(DEFAULT_WOOD_DENSITY_T_M3)
                )

            total_gross_volume += gross_vol
            weighted_density_sum += gross_vol * wood_density

        # Calculate gross-volume-weighted average density (t/m³)
        if total_gross_volume > 0:
            weighted_density = weighted_density_sum / total_gross_volume
        else:
            weighted_density = DEFAULT_WOOD_DENSITY_T_M3

        # Calculate all carbon metrics using shared IPCC calculator
        carbon = calculate_carbon_all(total_gross_per_ha, weighted_density)

        logger.info(
            f"[CARBON] GrossVol={total_gross_per_ha:.2f} m³/ha, "
            f"Density={weighted_density:.3f} t/m³, "
            f"AGB={carbon['agb_t_per_ha']:.2f} t/ha, "
            f"CO2e={carbon['co2_equivalent_tco2_per_ha']:.2f} tCO2/ha"
        )

        return {"weighted_density": round(weighted_density, 3), **carbon}

    def _resolve_unit_geometry_wkt(
        self, calculation_id: UUID, block_name: str
    ) -> Optional[str]:
        """WKT for one field-inventory unit, or None if it has no geometry.

        `forest_blocks` is the authoritative source, and it is the right one for a
        reason that is easy to get wrong: it holds **both** streams. A forest on
        the blocks stream and a forest on the compartments stream both keep their
        units in this one table, told apart by its depth column and its
        parent-unit foreign key (see `forest_units.model` for the names). So
        resolving a name here works whichever stream the forest uses, with no
        branching and no chance of mixing them.

        The lookup this replaced read `calculations.result_data->'blocks'` and
        expected a `wkt` key on each entry. Two things were wrong with that:

          * For a forest on the **compartments** stream, `result_data->'blocks'`
            is an *empty list* -- the units live under `result_data->'compartments'`
            instead. So the lookup matched nothing and every block came back NULL.
          * Even where `result_data->'blocks'` is populated, the entries carry
            **GeoJSON** under a `geometry` key, not WKT under a `wkt` key, so
            `block_json.get("wkt")` would have been None anyway.

        Together those meant `satellite_volume_m3_per_ha` was NULL for every row
        in the table - 0 of 26 - while the AGB raster it needs was present and
        working (4,186 tiles). The column rendered as an empty column with no
        error anywhere, because a missing geometry was a logged warning, not a
        failure.
        """
        row = self.db.execute(
            text(
                "SELECT ST_AsText(geometry) FROM public.forest_blocks "
                "WHERE calculation_id = CAST(:c AS uuid) AND name = :n LIMIT 1"
            ),
            {"c": str(calculation_id), "n": block_name},
        ).first()

        if row and row[0]:
            return row[0]

        logger.warning(
            "[SATELLITE_VOLUME] No geometry for unit '%s' in calculation %s "
            "(looked in forest_blocks.name); satellite volume left empty",
            block_name,
            calculation_id,
        )
        return None

    def _calculate_satellite_volume_for_block(
        self, calculation_id: UUID, block_name: str
    ) -> Optional[float]:
        """
        Calculate satellite-derived volume (m³/ha) for a block using AGB 2022 Nepal raster

        Formula: Volume (m³/ha) = AGB (Mg/ha) × 0.67 (wood density conversion)

        Args:
            calculation_id: The calculation ID containing the block geometry
            block_name: Name of the unit to calculate volume for

        Returns:
            Volume in m³/ha, or None if the unit has no geometry or no raster
            coverage. None is a legitimate answer here -- a block outside the
            AGB raster's footprint genuinely has no satellite volume -- so the
            caller stores NULL rather than inventing a number.
        """
        try:
            block_wkt = self._resolve_unit_geometry_wkt(calculation_id, block_name)
            if not block_wkt:
                return None

            # Query AGB raster for this block geometry
            # NOTE: ST_Union all intersecting tiles before clipping (LIMIT 1 would miss data)
            agb_query = text(
                """
                SELECT
                    (stats).mean as agb_mean
                FROM (
                    SELECT ST_SummaryStats(
                        ST_Clip(ST_Union(rast), 1, ST_GeomFromText(:wkt, 4326)),
                        1,
                        true
                    ) as stats
                    FROM rasters.agb_2022_nepal
                    WHERE ST_Intersects(rast, ST_GeomFromText(:wkt, 4326))
                ) as subquery
            """
            )

            agb_result = self.db.execute(agb_query, {"wkt": block_wkt}).first()

            if agb_result and agb_result.agb_mean and agb_result.agb_mean > 0:
                # Convert AGB (Mg/ha) to Volume (m³/ha) using 0.67 conversion factor
                # This matches the conversion used in User Group Map analysis
                volume_m3_per_ha = float(agb_result.agb_mean) * 0.67
                logger.info(
                    f"[SATELLITE_VOLUME] Block '{block_name}': AGB={agb_result.agb_mean:.2f} Mg/ha, Volume={volume_m3_per_ha:.2f} m³/ha"
                )
                return round(volume_m3_per_ha, 6)
            else:
                logger.warning(
                    f"[SATELLITE_VOLUME] No AGB data found for block '{block_name}'"
                )
                return None

        except Exception as e:
            logger.error(
                f"[SATELLITE_VOLUME] Error calculating satellite volume for block '{block_name}': {e}"
            )
            return None

    # business: CFMG condition class per Nepal Forest Regulation 2075
    async def _assess_forest_condition(
        self, block_summaries: List[FieldInventoryBlockSummary]
    ):
        """
        Assess regeneration_condition and forest_condition for each block.

        == Algorithm Reference (Forest Regulation 2075/2079, Nepal) ==

        A) Regeneration Condition (पुनरोत्पादनको अवस्था)
           Based on per-hectare counts of regeneration (0-4 cm DBH) AND
           saplings (4-10 cm DBH). Both thresholds must be met (AND logic):

           राम्रो (Good):
             Regen per ha >= 5000 AND Sapling per ha >= 2000
           मध्यम (Moderate):
             Regen per ha >= 2000 AND Sapling per ha >= 800
           कमजोर (Weak):
             All other cases

        B) Forest Condition (वनको अवस्था)
           3×3 matrix combining Growing Stock (m³/ha) with Regeneration Condition:

                        Regen=राम्रो   Regen=मध्यम   Regen=कमजोर
                        (Good)       (Moderate)    (Weak)
           GS > 200     राम्रो       राम्रो        मध्यम
           GS 50-200    राम्रो       मध्यम        कमजोर
           GS < 50      मध्यम       कमजोर        कमजोर

        Input columns (per-ha, from _calculate_per_hectare):
          regeneration_per_ha    — count/ha of regeneration (0-4 cm DBH)
          sapling_per_ha         — count/ha of saplings (4-10 cm DBH)
          total_growing_stock_m3_per_ha — net timber volume (pole+tree), m³/ha

        These follow Nepal Forest Regulation 2079 assessment criteria.
        """
        logger.info("[FOREST_CONDITION] Assessing forest condition...")

        for block in block_summaries:
            # The rule lives in one pure function (core/forest_condition.py) so the roll-up for a divided parent unit applies
            # exactly the same one.
            regen_per_ha = block.regeneration_per_ha or 0
            sapling_per_ha = block.sapling_per_ha or 0
            growing_stock = float(block.total_growing_stock_m3_per_ha or 0)
            regen_condition, forest_condition = assess_conditions(regen_per_ha, sapling_per_ha, growing_stock)
            block.regeneration_condition = regen_condition
            block.forest_condition = forest_condition

            logger.info(
                f"[FOREST_CONDITION] Block '{block.block_name}': Regen={regen_condition}, Forest={forest_condition}, Growing stock={growing_stock:.2f} m³/ha"
            )

        self.db.commit()
        logger.info("[FOREST_CONDITION] Forest condition assessment complete")

    # business: MAI = weighted avg of species growth rates × volume proportion
    async def _calculate_mai(
        self,
        block_summaries: List[FieldInventoryBlockSummary],
        field_inventory_id: UUID,
    ):
        """
        Calculate Mean Annual Increment (MAI %) for each block.

        == Algorithm ==

        A) Determine dominant growth rate:
           Count the top 5 species by measurement frequency in the block.
           Each species' growth rate comes from tree_species_coefficients.
           The growth rate with the highest count wins.

        B) MAI % = f(growth_rate, forest_condition) — 3×3 matrix:

                        राम्रो (Good)   मध्यम (Moderate)   कमजोर (Weak)
           Fast            5.0%            4.0%             3.0%
           Moderate        4.0%            3.0%             2.0%
           Slow            3.0%            2.0%             1.0%

        This determines the annual volume increment percentage applied
        to growing stock for MAI and AAH calculations.
        """
        logger.info("[MAI] Calculating Mean Annual Increment...")

        for block in block_summaries:
            # Get dominant species growth rate in this block
            dominant_growth_rate = await self._get_dominant_growth_rate(
                field_inventory_id, block.block_name
            )

            block.dominant_growth_rate = dominant_growth_rate

            # Calculate MAI based on forest condition + growth rate
            forest_condition = block.forest_condition
            mai = MAI_PCT_MATRIX.get(
                (dominant_growth_rate, forest_condition), MAI_PCT_DEFAULT
            )
            block.mai_percent = round(mai, 2)

            logger.info(
                f"[MAI] Block '{block.block_name}': Growth rate={dominant_growth_rate}, MAI={mai}%"
            )

        self.db.commit()
        logger.info("[MAI] MAI calculation complete")

    def _classify_dbh(self, dbh: Optional[float], stand_type: str) -> str:
        """Classify a DBH measurement into a DBH class key."""
        if dbh is not None:
            dbh = float(dbh)
            cls_def = DbhClassRegistry.classify(dbh, "guideline_2061")
            cls = cls_def.key if cls_def else "60_plus"
        else:
            cls = {
                "Regeneration": "0_4",
                "Sapling": "4_10",
                "Pole": "10_20",
                "Tree": "30_40",
            }.get(stand_type, "0_4")

        if stand_type == "Pole" and cls not in ("10_20", "20_30"):
            cls = "20_30"
        elif stand_type == "Tree" and cls not in ("30_40", "40_50", "50_60", "60_plus"):
            cls = "30_40"
        elif stand_type == "Regeneration":
            cls = "0_4"
        elif stand_type == "Sapling":
            cls = "4_10"

        return cls

    # business: 8 DBH classes per CFMG guidelines for stand structure analysis
    async def _calculate_dbh_class_breakdown(
        self,
        field_inventory_id: UUID,
        field_inventory: FieldInventoryCalculation,
        block_summaries: List[FieldInventoryBlockSummary],
    ):
        """Calculate 8-class DBH breakdown per block (count, timber, firewood)

        Uses per-plot averaging (same method as _calculate_per_hectare/_calculate_stand_averages)
        to ensure DBH sub-class totals are consistent with block-wise per-hectare values.

        For each block:
          1. Get all sample plots (including empty ones)
          2. Group measurements by (stand_type, dbh_class) per plot
          3. Sum values per class across all plots
          4. Average across all plots
          5. Expand to per-hectare: (avg / plot_area_sqm) * SQM_PER_HA
        """
        _sys_2061 = DbhClassRegistry.get_system("guideline_2061")
        DBH_CLASSES = [(c.key, c.label_en, c.label_np) for c in _sys_2061]

        plot_areas = {
            "Regeneration": float(field_inventory.regeneration_area_sqm),
            "Sapling": float(field_inventory.sapling_area_sqm),
            "Pole": float(field_inventory.pole_area_sqm),
            "Tree": float(field_inventory.tree_area_sqm),
        }

        # Get all plot IDs grouped by block — PRODUCTIVE only, so the DBH-class
        # growing stock matches the productive block summary (increment 2).
        plots_query = text(
            f"""
            SELECT id, block_name
            FROM public.field_inventory_sample_plots
            WHERE field_inventory_calculation_id = :fid
              AND {productive_plots_sql()}
        """
        )  # noqa: S608 -- productive_plots_sql() is a fixed literal, no user input
        all_plots = self.db.execute(
            plots_query, {"fid": str(field_inventory_id)}
        ).fetchall()

        block_all_plots: Dict[str, List[UUID]] = {}
        for p in all_plots:
            blk = str(p.block_name).strip()
            if blk not in block_all_plots:
                block_all_plots[blk] = []
            block_all_plots[blk].append(p.id)

        # Get all measurements — PRODUCTIVE plots only (see above).
        meas_query = text(
            f"""
            SELECT sp.block_name, sp.id as plot_id, m.stand_type,
                   m.dbh_cm, m.count, m.net_volume, m.firewood_m3
            FROM public.field_inventory_measurements m
            JOIN public.field_inventory_sample_plots sp ON m.sample_plot_id = sp.id
            WHERE sp.field_inventory_calculation_id = :fid
              AND {productive_plots_sql('sp.')}
        """
        )  # noqa: S608 -- productive_plots_sql() is a fixed literal, no user input
        meas_rows = self.db.execute(
            meas_query, {"fid": str(field_inventory_id)}
        ).fetchall()

        # Group measurements by (block, stand_type, dbh_class) — sum across plots
        grouped: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
        for row in meas_rows:
            blk = str(row.block_name).strip()
            st = str(row.stand_type).strip()
            dbh_v = row.dbh_cm
            cnt = float(row.count or 0)
            net_vol = float(row.net_volume or 0)
            firewood = float(row.firewood_m3 or 0)

            cls = self._classify_dbh(dbh_v, st)

            if blk not in grouped:
                grouped[blk] = {}
            if st not in grouped[blk]:
                grouped[blk][st] = {}
            if cls not in grouped[blk][st]:
                grouped[blk][st][cls] = {"count": 0.0, "net": 0.0, "fw": 0.0}

            grouped[blk][st][cls]["count"] += cnt
            grouped[blk][st][cls]["net"] += net_vol
            grouped[blk][st][cls]["fw"] += firewood

        for block in block_summaries:
            blk = block.block_name.strip()
            plot_ids = block_all_plots.get(blk, [])
            total_plots = len(plot_ids)

            breakdown_init = {
                k: {"count": 0.0, "timber": 0.0, "firewood": 0.0}
                for k, en, np in DBH_CLASSES
            }

            if total_plots > 0 and blk in grouped:
                for st, classes in grouped[blk].items():
                    plot_area = plot_areas.get(st, 100)
                    for cls, vals in classes.items():
                        if cls not in breakdown_init:
                            continue
                        avg_cnt = vals["count"] / total_plots
                        avg_net = vals["net"] / total_plots
                        avg_fw = vals["fw"] / total_plots

                        per_ha_cnt = (avg_cnt / plot_area) * SQM_PER_HA
                        per_ha_net = (avg_net / plot_area) * SQM_PER_HA
                        per_ha_fw = (avg_fw / plot_area) * SQM_PER_HA

                        breakdown_init[cls]["count"] += per_ha_cnt
                        breakdown_init[cls]["timber"] += per_ha_net
                        breakdown_init[cls]["firewood"] += per_ha_fw

            breakdown = {}
            for key, en, np in DBH_CLASSES:
                vals = breakdown_init[key]
                breakdown[key] = {
                    "count_per_ha": round(vals["count"], 2),
                    "timber_m3_per_ha": round(vals["timber"], 2),
                    "firewood_m3_per_ha": round(vals["firewood"], 2),
                    "label_en": en,
                    "label_np": np,
                }

            block.dbh_class_breakdown = breakdown

        self.db.flush()
        logger.info(
            "[DBH_CLASS_BREAKDOWN] DBH class breakdown complete (per-plot averaging)"
        )

    async def _get_dominant_growth_rate(
        self, field_inventory_id: UUID, block_name: str
    ) -> str:
        """Get dominant growth rate for species in this block"""
        # Get all measurements in this block
        # Productive plots only — this feeds MAI, which feeds AAH.
        query = text(
            f"""
            SELECT m.species_scientific, COUNT(*) as count
            FROM public.field_inventory_measurements m
            JOIN public.field_inventory_sample_plots p ON m.sample_plot_id = p.id
            WHERE p.field_inventory_calculation_id = :field_inventory_id
              AND p.block_name = :block_name
              AND {productive_plots_sql('p.')}
              AND m.stand_type IN ('Pole', 'Tree')
            GROUP BY m.species_scientific
            ORDER BY count DESC
            LIMIT 5
        """
        )  # noqa: S608 -- productive_plots_sql() is a fixed literal, no user input

        result = self.db.execute(
            query,
            {"field_inventory_id": str(field_inventory_id), "block_name": block_name},
        ).fetchall()

        # Count growth rates
        growth_rate_counts = {"Fast": 0, "Moderate": 0, "Slow": 0}

        for species, count in result:
            coef = self.species_coefficients.get(species, {})
            growth_rate = coef.get("growth_rate", "Moderate")

            if growth_rate in growth_rate_counts:
                growth_rate_counts[growth_rate] += count

        # Find dominant
        dominant = max(growth_rate_counts, key=growth_rate_counts.get)
        return dominant
