"""Domain constants — single source of truth (SSOT).

Centralizes magic numbers that were previously hardcoded across many modules
(see SSOT_audit_Report.md / SSOT_detail_implementation_plan.md). Import these
instead of repeating literals.
"""

from decimal import Decimal
import math

# ---------------------------------------------------------------------------
# Area / plot geometry
# ---------------------------------------------------------------------------
SQM_PER_HA = 10000

# Canonical per-plot areas (m²) per Regulation 2079 / CLAUDE.md.
# NOTE: field_inventory rows also store pole_area_sqm/tree_area_sqm which may
# override these per calculation. Phase 2 makes all aggregation paths read the
# SAME source consistently (see SSOT plan Phase 2.2).
POLE_PLOT_AREA_SQM = 100.0
TREE_PLOT_AREA_SQM = 500.0
REGEN_PLOT_AREA_SQM = 10.0
SAPLING_PLOT_AREA_SQM = 25.0

# ---------------------------------------------------------------------------
# IPCC biomass constants (mirror carbon_calculator.py so callers stop hardcoding)
# Source of truth remains carbon_calculator.py; re-exported here for convenience.
# ---------------------------------------------------------------------------
IPCC_BEF = 1.3    # Biomass Expansion Factor (above/below ground)
IPCC_RS = 0.24    # Root:shoot ratio
IPCC_CF = 0.47    # Carbon fraction of biomass
IPCC_CO2R = 3.67  # CO2 : C ratio

# Net-volume retention by tree class (Regulation 2079 §5 net-timber factors).
# net = retention * gross; waste = (1 - retention). Distinct from AAH multiplier.
NET_VOLUME_RETENTION_CLASS1 = 0.80  # 20% waste
NET_VOLUME_RETENTION_CLASS2 = 0.60  # 40% waste
NET_VOLUME_RETENTION_CLASS3 = 0.30  # 70% waste
NET_VOLUME_RETENTION_CLASS4 = 0.0   # 100% firewood
NET_VOLUME_RETENTION = NET_VOLUME_RETENTION_CLASS2  # default (Class 2)

# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------
CFT_PER_M3 = 35.3147

# Regulation 2079: 1 bhari = 30 kg headload.
BHARI_KG = 30

# Firewood -> bhari wood density.
# Per-species density (t/m³, air-dry corrected) is used when a species has a
# density record; otherwise this Nepal-average constant (kg/m³) is the fallback.
# See core/units.py m3_to_bhari and SSOT plan Phase 3.1.
WOOD_DENSITY_KG_PER_M3 = 670

# Air-dry moisture correction applied ONLY to the per-species (t/m³) path,
# NOT to the kg/m³ fallback constant above.
AIR_DRY_CORRECTION = 1.15

# kg per tonne (for converting species density t/m³ -> kg/m³).
KG_PER_TONNE = 1000
MM_PER_INCH = 25.4

# ---------------------------------------------------------------------------
# MAI / AAH regulation percentages (Regulation 2079)
# Growing-stock MAI% by (growth_rate x forest_condition) — see MAI_PCT_MATRIX
# in this module. AAH% by forest condition.
# ---------------------------------------------------------------------------
AAH_MULTIPLIER = {"Good": 75.0, "Moderate": 60.0, "Weak": 40.0}

# 3x3 MAI% matrix: (growth_rate, forest_condition) -> percent.
# Default fallback when either key is missing.
MAI_PCT_DEFAULT = 2.0
MAI_PCT_MATRIX = {
    ("Fast", "Good"): 5.0,
    ("Fast", "Moderate"): 4.0,
    ("Fast", "Weak"): 3.0,
    ("Moderate", "Good"): 4.0,
    ("Moderate", "Moderate"): 3.0,
    ("Moderate", "Weak"): 2.0,
    ("Slow", "Good"): 3.0,
    ("Slow", "Moderate"): 2.0,
    ("Slow", "Weak"): 1.0,
}

# ---------------------------------------------------------------------------
# Volume & stacking
# ---------------------------------------------------------------------------
M3_PER_CHATTA: float = 9.486

DEFAULT_WOOD_DENSITY_T_M3: Decimal = Decimal('0.65')

# ---------------------------------------------------------------------------
# Geographic / UTM
# ---------------------------------------------------------------------------
METERS_PER_DEGREE_LAT: float = 111_320.0
METERS_PER_DEGREE_LON_NEPAL: float = 98_000.0
NEPAL_UTM_LON_DIVIDER: float = 84.0
UTM_SRID_WEST: int = 32_644
UTM_SRID_EAST: int = 32_645

# ---------------------------------------------------------------------------
# Import purpose values — single source of truth (frontend PURPOSES mirrors)
# ---------------------------------------------------------------------------
IMPORT_PURPOSE_INVENTORY = 'inventory'
IMPORT_PURPOSE_SAMPLE_PLOT = 'sample_plot'
IMPORT_PURPOSE_USER_GROUP_BOUNDARY = 'user_group_boundary'
IMPORT_PURPOSE_BOUNDARY = 'boundary'
IMPORT_PURPOSE_BLOCKS = 'blocks'
IMPORT_PURPOSE_COMPARTMENTS = 'compartments'
IMPORT_PURPOSE_SUB_COMPARTMENTS = 'sub_compartments'
IMPORT_PURPOSE_SUB_BLOCKS = 'sub_blocks'
IMPORT_PURPOSE_ROADS = 'roads'
IMPORT_PURPOSE_WATER = 'water'
IMPORT_PURPOSE_OTHER = 'other'
IMPORT_PURPOSE_SUB_AREAS = 'sub_areas'

IMPORT_PURPOSE_ALL = {
    IMPORT_PURPOSE_INVENTORY,
    IMPORT_PURPOSE_SAMPLE_PLOT,
    IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
    IMPORT_PURPOSE_BOUNDARY,
    IMPORT_PURPOSE_BLOCKS,
    IMPORT_PURPOSE_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_BLOCKS,
    IMPORT_PURPOSE_ROADS,
    IMPORT_PURPOSE_WATER,
    IMPORT_PURPOSE_OTHER,
    IMPORT_PURPOSE_SUB_AREAS,
}

# Purposes that accept ONLY point geometry (reject lines/polygons)
IMPORT_PURPOSE_STRICT_POINT = {IMPORT_PURPOSE_INVENTORY, IMPORT_PURPOSE_SAMPLE_PLOT}

# Purposes where geometries keep their original type
IMPORT_PURPOSE_POINT_PRESERVE = {IMPORT_PURPOSE_INVENTORY, IMPORT_PURPOSE_SAMPLE_PLOT, IMPORT_PURPOSE_WATER}
IMPORT_PURPOSE_LINE_PRESERVE = {IMPORT_PURPOSE_ROADS}

# Purposes where point data is auto-buffered into polygons
IMPORT_PURPOSE_POLYGON_AUTO_BUFFER = {
    IMPORT_PURPOSE_BLOCKS, IMPORT_PURPOSE_BOUNDARY, IMPORT_PURPOSE_USER_GROUP_BOUNDARY,
    IMPORT_PURPOSE_SUB_AREAS, IMPORT_PURPOSE_COMPARTMENTS, IMPORT_PURPOSE_SUB_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_BLOCKS,
}

# Import purposes whose prepared polygons REPLACE the existing builtin state on
# convert (the imported state becomes the truth; a later local split starts from
# the imported geometry).
IMPORT_PURPOSE_REPLACE = {
    IMPORT_PURPOSE_BLOCKS, IMPORT_PURPOSE_COMPARTMENTS, IMPORT_PURPOSE_SUB_COMPARTMENTS,
    IMPORT_PURPOSE_SUB_BLOCKS,
}

# Admin layers that must exist before sub-layers can be imported.
# U-6 (Task 6.2): the dependency rule is widened — importing sub_areas/sub-compartments
# is allowed when ≥1 of {boundary, block, compartment} is populated (not only blocks).
# IMPORT_PURPOSE_ADMIN remains the set of layers that may be imported FIRST.
IMPORT_PURPOSE_ADMIN = {IMPORT_PURPOSE_BLOCKS, IMPORT_PURPOSE_COMPARTMENTS}

# Any of these being non-empty satisfies the "first layer" dependency for sub-layers.
IMPORT_PURPOSE_DEPENDENCY_SATISFYING = {
    IMPORT_PURPOSE_BLOCKS, IMPORT_PURPOSE_COMPARTMENTS,
}

# Sub-areas import: snap-to-close tolerance for near-closed lines (metres)
SUB_AREA_SNAP_TOLERANCE_M: float = 20.0

# ---------------------------------------------------------------------------
# Feature geometry editing (Phase E-1 — geometry_edit_service / editing router)
# ---------------------------------------------------------------------------
# Minimum surviving piece area (m²) after a cut/divide — smaller pieces are
# dropped as slivers instead of polluting the layer (Shapely `split` can emit
# GeometryCollection artifacts). Approx-geodesic: ~0.01 ha.
MIN_SLIVER_AREA_M2: float = 100.0

# MMU auto-block sliver floor (m²). User-confirmed for community forests:
# 1 ha = 10000 m². During auto-block preview/commit, pieces smaller than this
# are dropped AND their area is absorbed into the largest touching neighbour so
# total coverage stays ≈ boundary area.
MMU_SLIVER_AREA_M2: float = 10000.0

# Hole-fill threshold (m²): interior rings (voids) smaller than this are filled.
# Defaults to MMU sliver floor (1 ha) so tiny artifact holes disappear but
# legitimate clearings/lakes above 1 ha are preserved.
MMU_HOLE_FILL_AREA_M2: float = MMU_SLIVER_AREA_M2

# Relative tolerance for equal-area division: every piece must be within ±5%
# of the target area or the division fails gracefully (D3).
DIVIDE_AREA_TOLERANCE_REL: float = 0.05

# Neighbour search radius for shared-edge integrity checks (R6).  Metres →
# degrees via the shared `_metres_to_degrees` conversion.  Features whose
# bounding box is within this distance of the edited feature are the candidate
# neighbour set (bbox pre-filter before the spatial grid build).
MAX_EDGE_TOLERANCE_M: float = 150.0

# Point-on-line tolerance for VERTEX CLASSIFICATION (vertex_edit / V-1).
# Distinct from MAX_EDGE_TOLERANCE_M above: that one is a neighbour SEARCH
# radius (a bbox pre-filter deciding which features are worth testing),
# whereas this answers "does this vertex actually lie ON that edge?".
# Reusing the 150 m search radius as the answer classified every vertex of a
# small forest as lying on the parent shell (an 11 ha forest spans ~340 m, so
# a 150 m band from the boundary swallows all of it), which locked every
# vertex and rendered no drag markers at all.  Sized for digitising / float
# noise instead; classification is stable anywhere in the 1-5 m range.
VERTEX_COINCIDENCE_TOLERANCE_M: float = 1.0

# "Did this vertex actually MOVE?" — the diff threshold for the server-side
# locked-vertex guard (VR-3).  A third, much tighter tolerance, and the three
# must never be conflated:
#   MAX_EDGE_TOLERANCE_M          150 m   which neighbours are worth testing
#   VERTEX_COINCIDENCE_TOLERANCE_M  1 m   does this vertex lie ON that edge
#   VERTEX_MOVE_EPSILON_M           1 mm  has this vertex changed position
# PostGIS → GeoJSON → Leaflet LatLng → JSON round-trips introduce micro-degree
# drift (~1e-8 deg), so an exact float comparison would raise VERTEX_LOCKED on
# vertices the user never touched.  1 mm sits far above that noise and far
# below any edit a human could intend.
VERTEX_MOVE_EPSILON_M: float = 0.001


# Over-coverage clamp tolerance (m²) for boundary≡blocks invariant.
# When merging/editing blocks, floating-point precision may cause the union
# area to exceed the boundary by a microscopic amount. If the excess is <= this
# value (0.1 ha = 1000 m²), we auto-clip to the boundary instead of rejecting.
OVER_COVERAGE_CLAMP_M2: float = 1000.0

# Performance budget (review-fix #9): vertex-drag validation
# (sanitize → clip → overlap → shared-edge) must complete in ≤200ms p95 for
# layers up to this many total vertices.
EDIT_VALIDATION_VERTEX_LIMIT: int = 10_000
EDIT_VALIDATION_P95_BUDGET_MS: int = 200

# Workspace import limits
WORKSPACE_IMPORT_MAX_FEATURES: int = 50
WORKSPACE_IMPORT_MAX_VERTICES: int = 5000
WORKSPACE_IMPORT_MAX_AREA_HA: float = 1000.0
WORKSPACE_IMPORT_10KM_BUFFER_M: int = 10_000

# Request-wide ingress cap (H2.15 / S2-56). `WORKSPACE_IMPORT_MAX_VERTICES` is
# the limit for a single geometry; this is the limit for everything one request
# carries. It has to be far looser, because legitimate bulk payloads exist: a
# digitize bulk-upsert may hold 50 features, and a sampling design posts one
# Point per plot. The largest boundary in the live database is 233 vertices, so
# the headroom here is three orders of magnitude — this bounds a hostile body,
# it does not shape a real one.
REQUEST_MAX_TOTAL_VERTICES: int = 250_000

# ---------------------------------------------------------------------------
# Plot geometry
# ---------------------------------------------------------------------------
PLOT_RADIUS_500SQM: float = math.sqrt(500.0 / math.pi)

# ---------------------------------------------------------------------------
# Forestry thresholds — regeneration / sapling / growing stock quality
# ---------------------------------------------------------------------------
REGEN_GOOD_PER_HA: int = 5_000
REGEN_MODERATE_PER_HA: int = 2_000
SAPLING_GOOD_PER_HA: int = 2_000
SAPLING_MODERATE_PER_HA: int = 800
GS_GOOD_M3_PER_HA: float = 200.0
GS_MODERATE_M3_PER_HA: float = 50.0

# ---------------------------------------------------------------------------
# Soil fertility scoring thresholds
# ---------------------------------------------------------------------------
SOIL_FERTILITY_SCORES = {
    'high': 25,
    'medium': 15,
    'low': 5,
}
SOIL_PH_OPTIMAL_MIN: float = 5.5
SOIL_PH_OPTIMAL_MAX: float = 7.0
SOIL_PH_TOLERANCE_MIN: float = 5.0
SOIL_PH_TOLERANCE_MAX: float = 7.5
SOIL_SOC_HIGH_PCT: float = 2.0
SOIL_SOC_MEDIUM_PCT: float = 1.0
SOIL_N_HIGH_PCT: float = 0.15
SOIL_N_MEDIUM_PCT: float = 0.10
SOIL_CEC_HIGH: float = 150.0
SOIL_CEC_MEDIUM: float = 80.0
SOIL_COMPACTION_OPTIMAL_MAX: float = 1.3
SOIL_COMPACTION_TOLERANCE_MAX: float = 1.6
SOIL_COMPACTION_POOR_MAX: float = 1.8
SOIL_FERTILITY_CLASS_THRESHOLDS = [80, 60, 40, 20]

# ---------------------------------------------------------------------------
# Forest health — NDVI
# ---------------------------------------------------------------------------
NDVI_STRESSED_MAX: float = 0.2
NDVI_POOR_MAX: float = 0.4
NDVI_MODERATE_MAX: float = 0.6
NDVI_HEALTHY_MAX: float = 0.8

# ---------------------------------------------------------------------------
# Slope classes — from rasters.slope_regulation. The ONE definition (owner, 2026-10-11): the अनुसूची-१ bands. The older
# <10/10-20/20-30/>30° and percent (CFMG) classes are gone; do not reintroduce them.
#   Code 1: 0-19°  (gentle)
#   Code 2: 19-31° (moderate)
#   Code 3: 31-45° (steep)
#   Code 4: >45°   (very_steep)
# ---------------------------------------------------------------------------
SLOPE_GENTLE_MAX_DEG: float = 19.0
SLOPE_MODERATE_MAX_DEG: float = 31.0
SLOPE_STEEP_MAX_DEG: float = 45.0

# Class code -> (EN label, NP label). Display labels for rasters.slope_regulation;
# the lowercase forms used as data keys live in
# operational_plan/raster_zonal.SLOPE_LABELS and are pinned to these by test.
SLOPE_CLASS_NAMES: dict[int, tuple[str, str]] = {
    1: ("Gentle", "मन्द"),
    2: ("Moderate", "मध्यम"),
    3: ("Steep", "भिरालो"),
    4: ("Very Steep", "अति भिरालो"),
}

# Class code -> inclusive degree band, derived from the thresholds above.
SLOPE_CLASS_BANDS: dict[int, str] = {
    1: f"0-{SLOPE_GENTLE_MAX_DEG:g}°",
    2: f"{SLOPE_GENTLE_MAX_DEG:g}-{SLOPE_MODERATE_MAX_DEG:g}°",
    3: f"{SLOPE_MODERATE_MAX_DEG:g}-{SLOPE_STEEP_MAX_DEG:g}°",
    4: f">{SLOPE_STEEP_MAX_DEG:g}°",
}

# ---------------------------------------------------------------------------
# Canopy height classes
# ---------------------------------------------------------------------------
CANOPY_NON_FOREST_MAX_M: float = 1.0
CANOPY_REGENERATION_MAX_M: float = 5.0
CANOPY_POLE_MAX_M: float = 15.0
CANOPY_HEIGHT_VALID_MAX_M: float = 50.0

# ---------------------------------------------------------------------------
# Tree class / volume quality boundaries
# ---------------------------------------------------------------------------
TREE_CLASS_4_DBH_MAX_CM: float = 15.0
TREE_CLASS_4_HEIGHT_MAX_M: float = 8.0
TREE_CLASS_4_FIREWOOD_PCT: float = 100.0
TREE_CLASS_3_DBH_MAX_CM: float = 25.0
TREE_CLASS_3_HEIGHT_MAX_M: float = 12.0
TREE_CLASS_3_FIREWOOD_PCT: float = 70.0
TREE_CLASS_2_DBH_MAX_CM: float = 40.0
TREE_CLASS_2_HEIGHT_MAX_M: float = 16.0
TREE_CLASS_2_FIREWOOD_PCT: float = 40.0
TREE_CLASS_1_FIREWOOD_PCT: float = 20.0

# ---------------------------------------------------------------------------
# Planning horizons
# ---------------------------------------------------------------------------
ROTATION_GOOD_YEARS: int = 5
ROTATION_MODERATE_YEARS: int = 7
ROTATION_WEAK_YEARS: int = 10
MIN_COUPE_AREA_HA: float = 2.0
MIN_COUPE_AREA_PCT: float = 0.15
DEFAULT_PLANNING_HORIZON_YEARS: int = 10

# ---------------------------------------------------------------------------
# Sampling design
# ---------------------------------------------------------------------------
SAMPLING_INTENSITY_PCT: float = 0.5
SAMPLING_MIN_SAMPLES_LARGE: int = 5
SAMPLING_MIN_SAMPLES_SMALL: int = 2
SAMPLING_BOUNDARY_BUFFER_M: float = 50.0
SAMPLING_MIN_BOUNDARY_DISTANCE_M: float = 20.0
SAMPLING_MAX_SLOPE_DEG: float = 45.0
SAMPLING_MAX_ATTEMPTS_MULTIPLIER: int = 100

# ---------------------------------------------------------------------------
# Strips along boundaries (fire line; the river bank follows) -- FIRELINE_RIVERBANK_PLAN.md
# Widths are per SIDE: a fire line is 1.5 m + 1.5 m = 3 m wide, centred on the line.
# ---------------------------------------------------------------------------
FIRE_LINE_SIDE_M: float = 1.5
# the river bank: 20 m + 20 m, centred on the river (owner, 2026-10-19). A PROTECTION area, not productive.
RIVER_BANK_SIDE_M: float = 20.0
# a stretch of centerline shorter than this is merged into its longer neighbour, or removed when it touches nothing
STRIP_MIN_LENGTH_M: float = 10.0
# Fire lines follow the units' shared edges. When the units overlap each other by more than this share of the forest the shared
# edges are not well defined (the field book shatters into hundreds of lines), so nothing is created and the forest is
# reported instead. 0.1 % is 255 m2 on a 255 ha forest.
STRIP_MAX_UNIT_OVERLAP_FRACTION: float = 0.001
# ... and when more than this share of the field-book legs cannot be told apart.
STRIP_MAX_UNRESOLVED_FRACTION: float = 0.05
# ... and when a pair of neighbouring units is cut into more than this many separate pieces ON AVERAGE. A clean forest has about 1
# (one shared edge, one piece); when the neighbours' edges do not line up (slivers a few centimetres wide between them) the field
# book's lines break again and again and the same edge comes out as 15-20 pieces. Measured: a clean 2x2 forest 1.0, बनस्पती 3.8,
# बनस्खन्डी 7.2.
STRIP_MAX_PIECES_PER_PAIR: float = 2.0
#: neighbouring unit edges closer than this are one edge when fire lines are derived (working copy only)
STRIP_SNAP_M: float = 0.2
# a strip (or what is left of one after it is trimmed against the ones placed before it) smaller than this is noise
STRIP_MIN_AREA_M2: float = 1.0

# ---------------------------------------------------------------------------
# Financial / economic rates (NPR)
# NOTE: Two distinct rate sets exist — stumpage (forest authority) vs
# OP-economic (operational plan). Named explicitly to avoid confusion.
# See domain decision before Phase 2 reconciliation.
# ---------------------------------------------------------------------------
STUMPAGE_TIMBER_NPR_PER_M3: Decimal = Decimal('5000')
STUMPAGE_FUELWOOD_NPR_PER_M3: Decimal = Decimal('500')
STUMPAGE_CARBON_NPR_PER_TCO2: Decimal = Decimal('1500')
OP_ECONOMIC_TIMBER_NPR_PER_M3: Decimal = Decimal('2500')
OP_ECONOMIC_FUELWOOD_NPR_PER_M3: Decimal = Decimal('1000')
OP_ECONOMIC_CARBON_NPR_PER_TCO2: Decimal = Decimal('3000')

# ---------------------------------------------------------------------------
# Private land defaults
# ---------------------------------------------------------------------------
PRIVATE_MAI_PCT: Decimal = Decimal('3.0')
PRIVATE_SHRUB_MAI_PCT: Decimal = Decimal('1.5')
PRIVATE_AAH_PCT: float = 60.0
PRIVATE_TIMBER_FRACTION: Decimal = Decimal('0.60')
PRIVATE_FIREWOOD_FRACTION: Decimal = Decimal('0.40')
PRIVATE_AVG_POLE_VOLUME_M3: float = 0.05
PRIVATE_CROPLAND_GRASS_YIELD_KG_HA_YR: int = 12_000
PRIVATE_GRASSLAND_BEDDING_YIELD_KG_HA_YR: int = 8_000
PRIVATE_LAND_GROWING_STOCK_M3_HA: float = 120.0
PRIVATE_SHRUBLAND_GROWING_STOCK_M3_HA: float = 20.0

# ---------------------------------------------------------------------------
# Carbon / biomass
# ---------------------------------------------------------------------------
IPCC_CF_CONSERVATIVE: Decimal = Decimal('0.5')
SATELLITE_AGB_TO_VOLUME_FACTOR: float = 0.67

# ---------------------------------------------------------------------------
# Height & volume fallback factors
# ---------------------------------------------------------------------------
HEIGHT_FROM_DBH_FACTOR: float = 0.8
BRANCH_VOLUME_RATIO: float = 0.2
GROSS_VOLUME_FACTOR: float = 0.85
HEIGHT_ADJUSTMENT_SLOPE: float = 0.02
HEIGHT_ADJUSTMENT_BASE: float = 1.0
HEIGHT_ADJUSTMENT_REF_HEIGHT_M: float = 15.0
HEIGHT_FACTOR_MIN: float = 0.8
HEIGHT_FACTOR_MAX: float = 1.3
COMMERCIAL_DBH_MIN_CM: float = 10.0
MIN_TREE_HEIGHT_M: float = 5.0
MAX_TREES_PER_HA: int = 500

# Household vulnerability places every household on a BUILDING FOOTPRINT from the user-group building analysis
# (owner, 2026-10-05). Crews rarely collect household latitude/longitude and the footprints are reliable, so the
# household latitude/longitude columns are deliberately NOT used by the analysis. They stay in the upload template
# for other purposes. Set True only to bring surveyed coordinates back into the vulnerability analysis.
HOUSEHOLD_SURVEY_COORDINATES_IN_VULNERABILITY = False

# Sustainable Forest Management: a block's forest type comes from its OWN sample plots. 5 or more plots in a
# block is enough for a firm type; 1-4 is "provisional"; none (on forest land) means the inventory is missing.
SFM_MIN_PLOTS_PER_BLOCK = 5

# User Group analysis (building / settlement clip) is refused for a group larger than this: the
# clip against the national building layer grows with area and would stall the request.
USER_GROUP_MAX_ANALYSIS_AREA_HA = 5000
