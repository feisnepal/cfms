"""
ForestBlock model - stores forest blocks within a calculation
"""
import logging
from typing import Any, Dict

from sqlalchemy import Index, Column, String, DateTime, Integer, ForeignKey, Float, Boolean, Numeric
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, validates
from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import to_shape, from_shape
from datetime import datetime
import uuid

from ..core.database import Base
from ..utils.single_part_geometry import ensure_single_polygon

logger = logging.getLogger(__name__)


class ForestBlock(Base):
    """
    ForestBlock model - stores individual forest blocks within a calculation.
    
    Each forest can have multiple blocks (e.g., North Block, South Block, etc.)
    Created from user-uploaded polygon files where each polygon becomes a block.
    Supports compartment splitting and sub-compartment hierarchy.
    """
    __tablename__ = "forest_blocks"
    __table_args__ = (
        Index('idx_forest_blocks_calc_compartment', 'calculation_id', 'is_compartment'),
        Index('idx_forest_blocks_calc_division', 'calculation_id', 'division_level'),
        Index('idx_forest_blocks_calc_id', 'calculation_id'),
        Index('idx_forest_blocks_calculation', 'calculation_id'),
        Index('idx_forest_blocks_calculation_id', 'calculation_id'),
        Index('idx_forest_blocks_compartment_code', 'compartment_code'),
        Index('idx_forest_blocks_is_compartment', 'is_compartment'),
        Index('idx_forest_blocks_parent', 'parent_block_id'),
        Index('idx_forest_blocks_parent_id', 'parent_block_id'),
        Index('ix_forest_blocks_working_circle', 'calculation_id', 'working_circle'),
        Index('idx_forest_blocks_raster_layer_id', 'raster_layer_id'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    calculation_id = Column(UUID(as_uuid=True), ForeignKey("calculations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    geometry = Column(Geometry(srid=4326), nullable=False)
    area_hectares = Column(Float, nullable=False)
    index = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    
    # Compartment fields
    is_compartment = Column(Boolean, nullable=False, default=False)
    parent_block_id = Column(UUID(as_uuid=True), ForeignKey("forest_blocks.id", ondelete="CASCADE"), nullable=True)
    compartment_code = Column(String(50), nullable=True)
    area_sqm = Column(Float, nullable=True)
    
    # NEW: Hierarchy fields for sub-compartment support
    # DEPTH model (Forest Structure, migration 094): 1 = any top-level unit
    # (block or compartment); 2+ = sub-unit. 0 was "block" before 094 and is
    # no longer a valid constructor value (the DB CHECK enforces >= 1).
    division_level = Column(Integer, nullable=False, default=1)  # depth: 1=top-level, 2+=sub-unit
    color = Column(String(7), nullable=True)  # Hex color like "#FF5733"
    is_locked = Column(Boolean, nullable=False, default=False)  # Lock from further division
    child_count = Column(Integer, nullable=False, default=0)  # Cached child count
    display_order = Column(Integer, nullable=False, default=0)  # Order in parent's list

    # Auto-block generation (MMU) fields
    block_name = Column(String(255), nullable=True)  # User-editable serial: "Block-1", "Block-2", ...
    natural_name = Column(String(255), nullable=True)  # Best-effort nearest river/ridge label

    # Management working circle. 'production' (operable — felling series + AAH) or
    # 'protection' (no felling; growing stock still reported, never fed to AAH).
    # A protection unit is carved out of the production fabric at auto-create
    # time and numbered in its own P-N series. NULL/missing reads as 'production'.
    # See PROTECTION_WORKING_CIRCLE_PLAN.md (migration 074).
    working_circle = Column(String(20), nullable=False, default='production', server_default='production')

    # Per-feature style override (WORKSPACE_LAYER_STYLING_PLAN.md P3, migration 075).
    # {"fill": "#hex", "fillOpacity": 0-1, "stroke": "#hex", "weight": n} — any
    # subset. NULL/missing means "use the palette / working-circle style"; a set
    # value beats the layer's custom style, which beats the palette.
    style = Column(JSONB, nullable=True)

    # Slope band (1-4, कार्यविधि §15.2) that dominated this block's final
    # committed geometry, when it was carved via the slope-class Auto-Block
    # source (migration 084). NULL for every other origin (MMU auto-block,
    # manual draw, import, divide/split) and for anything created before 084.
    dominant_slope_band = Column(Integer, nullable=True)

    # Same shape as dominant_slope_band, for the `aspect` (1-8 = N/NE/E/SE/
    # S/SW/W/NW, rasters.aspect) and `canopy` (1-4 = non-forest/regeneration/
    # pole/tree, canopy_height5m.tif) Auto-Block sources (migration 085). A
    # block carries at most one of the three dominant_* columns in practice.
    dominant_aspect = Column(Integer, nullable=True)
    dominant_canopy_class = Column(Integer, nullable=True)

    # Same shape as the 084/085 dominant_* columns, for the four new Auto-Block
    # sources introduced by the Raster Sources plan (migration 105). A block
    # carries at most one of these in practice (the source it was carved by):
    #   dominant_health_class    NDVI forest health, 1-5 = Stressed..Excellent
    #   dominant_nasa_quality    NASA 2020, 1-3 = Primary/Young/Old secondary
    #   dominant_landcover       ESA WorldCover, 10-100 land-cover code (forest
    #                            classes grouped under one geometry, D24)
    #   dominant_elevation_zone  DEM zone 1-3 (low/mid/high). RS-2.19/D51
    #                            superseded the original "mean +/- 1 SD" rule
    #                            with the 33rd/67th percentile of THIS
    #                            forest's own unit elevations -- quantile
    #                            thirds always split a forest into three
    #                            equally-populated groups, where +/- 1 SD
    #                            could leave a group empty on a forest with
    #                            little elevation spread. Set by
    #                            elevation_service.assign_relative_elevation_zones,
    #                            not by any one carve source -- a zone code is
    #                            only comparable inside the forest it was set
    #                            for, never across forests (D19).
    # All are NULL for every other origin and for anything created before 105.
    dominant_health_class = Column(Integer, nullable=True)
    dominant_nasa_quality = Column(Integer, nullable=True)
    dominant_landcover = Column(Integer, nullable=True)
    dominant_elevation_zone = Column(Integer, nullable=True)

    # FRTC forest type, 1-25 (migration 108, RS-9.5/P9). NULL for a piece
    # dominated by the anonymous code 26 ("Unclassified"), and for every
    # other origin.
    dominant_forest_type = Column(Integer, nullable=True)

    # DEM contour-carve band, 1-N (migration 108, RS-9.3/P9). Deliberately
    # SEPARATE from `dominant_elevation_zone` above -- that column is RS-2.19's
    # forest-relative percentile attribute, set for every unit regardless of
    # carve source; this one is the DEM source's own per-forest
    # equal-elevation-interval band, set only when a piece was actually
    # carved by the `dem` source. The two can disagree and that is fine --
    # they answer different questions.
    dominant_contour_band = Column(Integer, nullable=True)

    # The NASA dominant class **as the raster has it**, 0-3, including the
    # anonymous non-forest class 0 (migration 106). `dominant_nasa_quality`
    # above is bound 1-3 and is therefore NULL for every compartment the raster
    # called mostly non-forest -- which rendered as a blank cell identical to
    # "no raster coverage" (RS-2.14). This column keeps the fact, so the UI can
    # say "Non-forest (0)" and a blank can mean only one thing. A NULL here
    # means the class was never determined (no coverage, or the query failed).
    dominant_nasa_code = Column(Integer, nullable=True)

    # Real altitude of the unit, in metres (migration 105). The zone code above
    # is a relative band (mean +- 1 SD of *this* forest), so a compartment also
    # carries its absolute altitude for cross-forest comparison (D19). The DEM
    # Auto-Block source writes all three per piece during a carve; they are
    # read-only derived values, not user-editable classifications.
    elevation_min_m = Column(Numeric(7, 1), nullable=True)
    elevation_mean_m = Column(Numeric(7, 1), nullable=True)
    elevation_max_m = Column(Numeric(7, 1), nullable=True)

    # Management orientation (Production/Conservation/Protection, migration
    # 086) -- auto-suggested from SFM's own classification pipeline
    # (zone_classifier -> species_assemblage -> forest_type_classifier ->
    # orientation.propose) when a block is carved via the slope Auto-Block
    # source, and always user-editable afterward. Stores the same capitalized
    # strings `orientation.py` returns, so it compares directly against the
    # live "Suggested Orientation" read from calc.result_data['sfm'] with no
    # re-casing step. NULL for every other origin.
    management_orientation = Column(String(20), nullable=True)

    # Suggested orientation (migration 087) -- read-only mirror of the SFM
    # pipeline's current orientation proposal for this block. Populated at the
    # same time as management_orientation (slope Auto-Block commit) and kept
    # in sync via the SFM cache. Differs from management_orientation when the
    # user has manually overridden the suggestion. NULL for every other origin.
    suggested_orientation = Column(String(20), nullable=True)

    # Orientation justification in English / Nepali (migration 087) -- the
    # सि.नं. reference and rule chain that produced the suggested orientation
    # (from `orientation.propose`'s `justification`). Populated alongside
    # suggested_orientation. NULL for every other origin.
    orientation_justification_en = Column(String(500), nullable=True)
    orientation_justification_ne = Column(String(500), nullable=True)

    # Independent Auto-Block layer this row belongs to (migration 107,
    # RS-2.16, D51). NULL for every row created before this migration, and
    # for any write path this phase has not wired yet -- manual draw, import,
    # divide/cut/merge on legacy data. A non-NULL value alone does not make
    # this row "real structure"; `raster_layer.promoted_as` decides that
    # (RS-2.17). Filtering reads by promotion is RS-2.18 -- not yet wired, so
    # this column is schema-only until then.
    raster_layer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("raster_layers.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Union composite layer (migration 109, RS-10.1/P10). Not source-specific
    # -- any layer could in principle report these -- but only `union_zonal`/
    # `union_fusion` populate them at first. `sub_area_category` is the
    # `ForestSubArea.category` covering the LARGEST share of this piece's
    # area by vector overlap (not a raster vote -- ForestSubArea is already
    # exact geometry); NULL means no sub-area was ever drawn here, the normal
    # case for most of a forest, never an error. `sub_area_excluded` is true
    # when that majority-overlap sub-area is Private Land (`is_excluded`) --
    # tagged, not omitted, so a Union piece tells a planner *why* it has no
    # classification rather than silently not showing up (CLAUDE.md's
    # forest-delete doughnut-hole convention, applied here).
    sub_area_category = Column(String(50), nullable=True)
    sub_area_excluded = Column(Boolean, nullable=False, default=False, server_default="false")

    # Relationships
    parent_block = relationship("ForestBlock", remote_side=[id], foreign_keys=[parent_block_id])
    # FS-4a.9: `passive_deletes=True` -- without it, SQLAlchemy's own delete
    # handling loads every child of a row being deleted and issues
    # `UPDATE ... SET parent_block_id = NULL` on them BEFORE the parent's
    # DELETE reaches Postgres, so the DB's `ON DELETE CASCADE` on
    # `parent_block_id` (above) never actually has anything left to cascade --
    # a child silently survives as a nulled-parent orphan instead of being
    # removed with its parent (found while building
    # forest_units/operations/reparent.py, FS-4a.7). This tells the ORM to
    # step aside and trust the DB constraint: a plain `db.delete(row)` on a
    # row with real children now genuinely cascade-deletes them (recursively,
    # through however many sub-levels exist -- Postgres handles that, not
    # Python). Callers that want re-parenting instead of deletion (cut/merge,
    # FS-4a.7/4a.8) still redistribute children explicitly BEFORE deleting the
    # old row, unaffected by this -- it only changes what happens to children
    # nobody redistributed first.
    compartments = relationship(
        "ForestBlock",
        back_populates="parent_block",
        foreign_keys=[parent_block_id],
        passive_deletes=True,
    )

    @validates("geometry")
    def _validate_single_part_geometry(self, key, value):
        """One row = one selectable map feature (see single_part_geometry.py).

        Only a `WKBElement` (the shape `from_shape(shapely_geom, srid=...)`
        produces — the pattern nearly every write site in this codebase
        uses) is checked; a raw SQL/driver value (e.g. straight from an
        `ST_Dump` query, already guaranteed single-part by PostGIS) passes
        through untouched. A degenerate-sliver-only MultiPolygon is
        silently repaired to its one real polygon; a genuine multi-piece
        MultiPolygon raises immediately rather than persisting a corrupt
        row (see `MultiPartFeatureError`).
        """
        if not isinstance(value, WKBElement):
            return value
        try:
            geom = to_shape(value)
        except Exception:
            logger.warning(
                "single-part-geometry guard: WKB decode failed - passing "
                "the value through unchecked", exc_info=True,
            )
            return value
        fixed = ensure_single_polygon(geom)
        if fixed is geom:
            return value
        return from_shape(fixed, srid=value.srid or 4326)

    def __repr__(self):
        return f"<ForestBlock(id={self.id}, name={self.name}, level={self.division_level}, locked={self.is_locked})>"


# Columns that describe a unit's forest/management character rather than its
# geometry or its position in the naming/hierarchy scheme. Every operation
# that produces one or more new rows from an existing one -- cut, divide
# (both the replace-in-place and carve-fresh-children paths), merge, and the
# legacy compartment-split endpoints -- should carry these forward from the
# source row, so a Protection-oriented / custom-styled block stays that way
# no matter which tool reshaped it (owner request, 2026-09-15: "It should be
# identical it was created by any means").
#
# Deliberately excluded: geometry/area_hectares/area_sqm/index (recalculated
# per piece), name/block_name/compartment_code (regenerated/suffixed by each
# caller), parent_block_id/is_compartment/division_level (hierarchy, handled
# per call site), is_locked (a split's pieces always start unlocked, D-2026-
# 09-15), child_count/display_order (bookkeeping, reset per call site).
CHILD_INHERITED_COLUMNS = (
    "natural_name",
    "working_circle",
    "management_orientation",
    "suggested_orientation",
    "orientation_justification_en",
    "orientation_justification_ne",
    "style",
    "dominant_slope_band",
    "dominant_aspect",
    "dominant_canopy_class",
    "dominant_health_class",
    "dominant_nasa_quality",
    "dominant_nasa_code",
    "dominant_landcover",
    "dominant_elevation_zone",
    "dominant_forest_type",
    "dominant_contour_band",
    "elevation_min_m",
    "elevation_mean_m",
    "elevation_max_m",
    "color",
    "sub_area_category",
    "sub_area_excluded",
    # A unit that belongs to an Auto-Block layer (RS-2.16) hands that membership to every row an edit
    # makes from it -- divide, cut, merge, paste, reshape remainders. Without it the new rows carry no
    # layer and read as LEGACY structure: demoting the layer then leaves them visible as orphans
    # (children of a hidden parent), and the layer can no longer be promoted ("This forest already has
    # blocks/compartments created before layers existed"). Owner report 2026-10-03. NULL for a unit
    # that is not in a layer, so every other path behaves exactly as before.
    "raster_layer_id",
)


def child_inherit_kwargs(parent: "ForestBlock") -> Dict[str, Any]:
    """The subset of ``parent``'s columns a newly-created child/piece row
    should start with (see ``CHILD_INHERITED_COLUMNS``).

    Callers must capture this *before* deleting/expiring ``parent`` (e.g.
    cut/divide-in-place delete the source row before building its
    replacement pieces) -- the returned dict is a plain snapshot, safe to
    use after that.
    """
    return {col: getattr(parent, col) for col in CHILD_INHERITED_COLUMNS}