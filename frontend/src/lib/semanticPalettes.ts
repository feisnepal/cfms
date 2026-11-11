/**
 * Semantic colour SSOT — frontend mirror of `backend/app/core/semantic_palettes.py`
 * (THEMATIC_MAP_VARIABLES_PLAN §3.3, Appendix C.2).
 *
 * The backend is authoritative. `backend/tests/test_semantic_palettes.py` parses
 * THIS file and fails the build if any hex value drifts from the Python. Keep the
 * two in lockstep; do not edit one without the other.
 *
 * Sequential ramps live in `./colorRamps.ts` (unchanged, also mirrored by the
 * backend as `RAMPS`). This module adds the semantic categorical / diverging /
 * bivariate schemes and the sequential name→ramp map.
 */
import { COLOR_RAMPS } from './colorRamps';

export const RAMPS = COLOR_RAMPS;

/** semantic sequential measure → ramp key ("<key>_r" reverses the ramp). */
export const SEQUENTIAL: Record<string, string> = {
  growing_stock: 'ylgn',
  carbon: 'viridis',
  increment: 'ylgnbu',
  basal_area: 'bupu',
  stems: 'ylorbr',
  density: 'ylorrd',
  access: 'greys_r',
};

export const NO_DATA_FILL = '#e0e0e0';
export const NO_DATA_HATCH = '..';

const DBH8 = ['#6a51a3', '#2b83ba', '#1a9850', '#a6d854', '#ffd92f', '#fc8d62', '#e41a1c', '#7f2704'];
const DBH6 = DBH8.slice(2);
const DBH6_KEYS = ['10_20', '20_30', '30_40', '40_50', '50_60', '60_plus'];
const DBH8_KEYS = ['0_4', '4_10', '10_20', '20_30', '30_40', '40_50', '50_60', '60_plus'];

const SPECIES_QUAL = [
  '#E69F00', '#56B4E9', '#009E73', '#F0E442', '#0072B2', '#D55E00',
  '#CC79A7', '#999999', '#882255', '#44AA99', '#DDCC77', '#117733',
];

const SUBAREA_CATEGORY: Record<string, string> = {
  protected: '#ef4444',
  plantation: '#10b981',
  'pro-poor': '#f59e0b',
  religious: '#8b5cf6',
  biodiversity: '#06b6d4',
  tourist: '#ec4899',
  office: '#6b7280',
  private_land: '#dc2626',
  agroforestry: '#84cc17',
  tree_strata: '#15803d',
  water_hole: '#0ea5e9',
  wildlife_corridor: '#a855f7',
  agriculture: '#eab308',
  settlement: '#f97316',
  fire_line: '#c62828',
  river_bank: '#1e40af',
};

export const CATEGORICAL: Record<string, Record<string, string>> = {
  condition: { Good: '#2e7d32', Moderate: '#f9a825', Weak: '#c62828' },
  condition_pair: {
    'Good|Good': '#1b7837', 'Good|Moderate': '#5aae61', 'Good|Weak': '#b7e4b0',
    'Moderate|Good': '#c77700', 'Moderate|Moderate': '#f5a623', 'Moderate|Weak': '#fbe08a',
    'Weak|Good': '#a50f15', 'Weak|Moderate': '#e5534b', 'Weak|Weak': '#f7b6b0',
  },
  growth_rate: { Fast: '#2e7d32', Moderate: '#f9a825', Slow: '#795548' },
  working_circle: { production: '#3182bd', protection: '#15803d' },
  dbh_classes_3: { regeneration: '#1b9e77', advance_growth: '#d95f02', mature_tree: '#7570b3' },
  dbh_classes: Object.fromEntries(DBH8_KEYS.map((k, i) => [k, DBH8[i]])),
  dbh_classes_10plus: Object.fromEntries(DBH6_KEYS.map((k, i) => [k, DBH6[i]])),
  subarea_category: { ...SUBAREA_CATEGORY },
  species_qual: Object.fromEntries(SPECIES_QUAL.map((c, i) => [String(i), c])),
  aspect: {
    N: '#4575b4', NE: '#74add1', E: '#abd9e9', SE: '#e0f3f8',
    S: '#fee090', SW: '#fdae61', W: '#f46d43', NW: '#d73027',
  },
  // S9 / P6z — mirrors app/core/semantic_palettes.py (reused ramp hexes).
  slope_class: {
    gentle: '#fdbe85', moderate: '#fd8d3c', steep: '#e6550d', very_steep: '#a63603',
  },
  // S9 / P6z — mirrors app/core/forest_types.py FRTC_FOREST_TYPES (26
  // generic/tenure classes). Same keys and hexes as the backend, and the same
  // vocabulary the tile renderer draws with, so an OP map and the map beside
  // it cannot disagree. Used to be a local 10-species list that could not
  // label 6 of the 12 codes rasters.forest_type actually carries.
  // S9 / P6z — mirrors app/core/forest_types.py FRTC_FOREST_TYPES.
  // **Regenerated from the authoritative FRTC 2015 legend** (owner-supplied
  // 2026-09-30, RS-0.2), which replaced a fabricated 26-name list in which
  // *every* name differed and several entries (Grassland, Wetland, Built-up,
  // Plantation, Religious Forest) were not forest types at all. Keyed by NAME
  // because the frontend has no code->name lookup of its own, so a backend
  // rename orphans these keys silently -- regenerate this block, never hand-edit
  // it. Note code 26 is **Unclassified** (not "Protected Forest"; the legend's
  // own name is "Non forest", but the owner directed 2026-10-01/RS-9.5 that
  // the UI say "Unclassified" since RS-4.1a found 26 is ~90% co-located with
  // closed-canopy tree cover), and it is 78% of the raster. Do not build UI
  // copy on these names; the Nepali names in the backend dict are provisional
  // (owner decision, 2026-09-30).
  forest_type: {
    'Shorea robusta Forest': '#228b22',
    'Tropical Mixed Broadleaved Forest': '#6b8e23',
    'Subtropical Mixed Broadleaved Forest': '#8fbc8f',
    'Shorea robusta - Mixed Broadleaved Forest': '#2e8b57',
    'Abies Mixed Forest': '#3cb371',
    'Upper Temperate Coniferous Forest': '#20b2aa',
    'Cool Temperate Mixed Broadleaved Forest': '#008b8b',
    'Castanopsis Lower Temperate Mixed Broadleaved Forest': '#5f9ea0',
    'Pinus roxburghii Forest': '#4682b4',
    'Alnus Forest': '#6495ed',
    'Schima Forest': '#87ceeb',
    'Pinus roxburghii - Mixed Broadleaved Forest': '#b0c4de',
    'Pinus wallichiana Forest': '#daa520',
    'Warm Temperate Mixed Broadleaved Forest': '#d2691e',
    'Upper Temperate Quercus Forest': '#00ced1',
    'Rhododendron arboreum Forest': '#1e90ff',
    'Temperate Rhododendron Mixed Broadleaved Forest': '#a9a9a9',
    'Dalbergia sissoo-Senegalia catechu Forest': '#f0f8ff',
    'Terminalia - Tropical Mixed Broadleaved Forest': '#f5deb3',
    'Temperate Mixed Broadleaved Forest': '#cd5c5c',
    'Tropical Deciduous Indigenous Riverine Forest': '#4169e1',
    'Tropical Riverine Forest': '#32cd32',
    'Lower Temperate Mixed robusta Forest': '#006400',
    'Pinus roxburghii - Shorea robusta Forest': '#556b2f',
    'Lower Temperate Pinus roxburghii - Quercus Forest': '#8b4513',
    'Unclassified': '#483d8b',
  },
  // S9 / P6z — rasters.nepal_forest_health, 1..5 (0 = NoData). Mirrors
  // app/core/forest_types.py FOREST_HEALTH_CLASSES.
  forest_health_class: {
    Stressed: '#dc143c',
    Poor: '#ff8c00',
    Moderate: '#ffd700',
    Healthy: '#90ee90',
    Excellent: '#228b22',
  },
  // S9 / P6z — rasters.nasa_forest_2020, 1..3 (0 = NoData). Mirrors
  // app/core/forest_types.py NASA_FOREST_QUALITY.
  nasa_quality: {
    'Primary Forest': '#00ff00',
    'Young Secondary Forest': '#ff0000',
    'Old Secondary Forest': '#6666ff',
  },
  // SFM P5 — the 14 अनुसूची-१ forest types (keys "1".."14"): 12 from the
  // qualitative species palette + 2 dark ramp stops.
  sfm_forest_type: Object.fromEntries(
    [...SPECIES_QUAL, '#08519c', '#a63603'].map((c, i) => [String(i + 1), c]),
  ),
  // SFM P5 — working-circle orientation (reuses working_circle + condition hexes).
  sfm_orientation: { Production: '#3182bd', Conservation: '#f9a825', Protection: '#15803d' },
};

export const CATEGORICAL_OTHER: Record<string, string> = {
  condition: '#bdbdbd',
  condition_pair: '#bdbdbd',
  growth_rate: '#bdbdbd',
  dbh_classes_3: '#bdbdbd',
  dbh_classes_10plus: '#bdbdbd',
  species_qual: '#bdbdbd',
  subarea_category: '#9e9e9e',
  slope_class: '#bdbdbd',
  forest_type: '#bdbdbd',
  sfm_forest_type: '#bdbdbd',
  sfm_orientation: '#bdbdbd',
};

export const DIVERGING: Record<string, string[]> = {
  deviation: ['#ca0020', '#f4a582', '#f7f7f7', '#92c5de', '#0571b0'],
  gain_loss: ['#c62828', '#ef9a9a', '#f5f5f5', '#a5d6a7', '#2e7d32'],
};

export const BIVARIATE: Record<string, string[]> = {
  bivariate_gp: [
    '#e8e8e8', '#ace4e4', '#5ac8c8',
    '#dfb0d6', '#a5add3', '#5698b9',
    '#be64ac', '#8c62aa', '#3b4994',
  ],
  bivariate_gg: [
    '#e8f4e8', '#b7dbb7', '#6ec06e',
    '#b9d9c8', '#8fbfb0', '#4f9d78',
    '#6db56d', '#4f9d78', '#1f6d4f',
  ],
};

// Colour for one categorical value; CATEGORICAL_OTHER (or null) if unmatched.
export function colorForCategory(palette: string, value: unknown, fallback = true): string | null {
  const scheme = CATEGORICAL[palette] ?? {};
  const key = value == null ? '' : String(value);
  if (key in scheme) return scheme[key];
  return fallback ? (CATEGORICAL_OTHER[palette] ?? null) : null;
}
