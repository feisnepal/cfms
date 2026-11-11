/**
 * Default per-source styling for Auto-Block layers (RS-2.16/2.20, owner
 * directive 2026-10-01) — the 9 carve sources (`mmu`, `slope`, `aspect`,
 * `canopy`, `nasa_quality`, `forest_health`, `landcover`, `dem`,
 * `forest_type`) each get a distinct, meaningful DEFAULT colour so they read
 * as themselves on the map rather than all sharing one flat purple. These
 * are defaults only — a user's own style override (the existing per-layer
 * style system) always wins; nothing here is enforced.
 *
 * Deliberately a SEPARATE module from `semanticPalettes.ts`, not an edit to
 * it: that file's `CATEGORICAL` export is parity-tested against
 * `backend/app/core/semantic_palettes.py` (a thematic-MAP-IMAGE palette
 * SSOT, a different subsystem to the live Leaflet vector layers this
 * styles) — forking a second set of hex values for the same semantic classes
 * risks exactly the "two sources of truth drift apart" failure this
 * codebase has hit before. Where a category here matches an existing SSOT
 * entry (aspect, forest_health, nasa_quality, forest_type), this module
 * reads it directly rather than re-declaring the hexes. `landcover` has no
 * existing CATEGORICAL entry (only a tile-legend array), so it is declared
 * fresh here from the SAME official ESA hex values `rasterLegends.ts`
 * already serves.
 */
import type { PathOptions } from 'leaflet';
import { CATEGORICAL } from './semanticPalettes';

export type AutoBlockSourceKey =
  | 'mmu' | 'slope' | 'aspect' | 'canopy' | 'nasa_quality'
  | 'forest_health' | 'landcover' | 'dem' | 'forest_type'
  // RS-10.2/10.5 (P10): Union, Mode B (zonal/default). Like mmu, no single
  // classification column — `layer_features` returns all 9 at once — so it
  // gets `null` in SOURCE_LABEL_KEY below.
  | 'union_zonal'
  // RS-10.3/10.5-fusion (P10): Union, Mode A (fusion/opt-in). Same
  // all-attributes-at-once shape as union_zonal.
  //
  // Owner directive 2026-10-02: the two Union modes share ONE default
  // style, not two distinct ones — "user will get the same sense from
  // those layers" (they're the same kind of thing, Union, just two
  // computation methods; visual consistency matters more than telling
  // them apart by colour). Both key off `dominant_slope_band` — the one
  // attribute every Union piece is guaranteed to carry (slope is the
  // fusion gate, and the zonal base always votes it) — with the exact
  // 4-class categorical scheme the owner specified: green <19°, yellow
  // 19-31°, orange 31-45°, red >45° (कार्यविधि §15.2's own bands), a flat
  // CATEGORICAL lookup, not the 2-colour continuous ramp the plain `slope`
  // source itself uses below.
  | 'union_fusion';

/** The feature property key `layer_features` (backend) writes the
 *  human-readable classification under, per source — `null` for `mmu`,
 *  which carves no classification (and for `union_zonal`, which carves 9).
 *  Mirrors `_source_attribute` in `auto_block_service.py` exactly; keep the
 *  two in step. */
export const SOURCE_LABEL_KEY: Record<AutoBlockSourceKey, string | null> = {
  mmu: null,
  slope: 'Slope Band',
  aspect: 'Aspect',
  canopy: 'Canopy Class',
  nasa_quality: 'NASA Forest Quality',
  forest_health: 'Forest Health',
  landcover: 'Land Cover',
  dem: 'Elevation Band',
  forest_type: 'Forest Type',
  union_zonal: null,
  union_fusion: null,
};

/** The property to show as the map LABEL by default for each source — the
 *  classification itself where one exists (seeing "Steep" on the map is
 *  more useful than seeing "slope-3"), falling back to the best available
 *  name for `mmu`, which has none. */
export function defaultLabelField(source: string): string {
  const key = SOURCE_LABEL_KEY[source as AutoBlockSourceKey];
  return key ?? 'Natural Name';
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function rgbToHex(r: number, g: number, b: number): string {
  const c = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}
/** Linear two-stop hex interpolation, `t` in [0, 1]. */
function rampAt(from: string, to: string, t: number): string {
  const [r1, g1, b1] = hexToRgb(from);
  const [r2, g2, b2] = hexToRgb(to);
  const clamped = Math.max(0, Math.min(1, t));
  return rgbToHex(r1 + (r2 - r1) * clamped, g1 + (g2 - g1) * clamped, b1 + (b2 - b1) * clamped);
}
function darken(hex: string, amount = 0.35): string {
  const [r, g, b] = hexToRgb(hex);
  return rgbToHex(r * (1 - amount), g * (1 - amount), b * (1 - amount));
}

/** ESA WorldCover official hexes (owner's "Standard USGS/CORINE" row) —
 *  same values `rasterLegends.ts`'s `landcover` tile legend already serves,
 *  and the same values `app/core/forest_types.py::ESA_WORLD_COVER` emits as
 *  `_source_attribute`'s human labels, keyed here by that exact label text
 *  so a feature's "Land Cover" property resolves directly. */
const LANDCOVER_COLORS: Record<string, string> = {
  'Tree cover': '#006400',
  'Shrubland': '#FFBB22',
  'Grassland': '#FFFF4C',
  'Cropland': '#F096FF',
  'Built-up': '#FA0000',
  'Bare / sparse vegetation': '#B4B4B4',
  'Snow and ice': '#F0F0F0',
  'Permanent water bodies': '#0064C8',
  'Herbaceous wetland': '#0096A0',
  'Mangroves': '#00CF75',
  'Moss and lichen': '#FAE6A0',
};

/** Each ramp source's known ordinal ceiling, for positioning a code within
 *  its ramp. `dem`'s band count is per-forest (`elevation_bands`, 1-5) and
 *  not carried in a per-feature property — 5 is this default's working
 *  assumption (the suggested range's upper bound), not a hard limit; a
 *  forest with fewer bands just won't reach the ramp's far end. */
const RAMP_MAX: Record<string, number> = {
  slope: 4, nasa_quality: 3, forest_health: 5, dem: 5,
};

interface RampSpec { from: string; to: string; fillOpacity: number; strokeFn: (fill: string) => string; weight: number; }
const RAMPS: Partial<Record<AutoBlockSourceKey, RampSpec>> = {
  // Standard topographic convention: gentle=cool yellow, steep/hazardous=deep red.
  slope: { from: '#FFFF00', to: '#D32F2F', fillOpacity: 0.45, strokeFn: () => '#8B0000', weight: 1.5 },
  // Warm gold->ochre, distinct from the raw green canopy layer.
  nasa_quality: { from: '#FFD54F', to: '#B71C1C', fillOpacity: 0.45, strokeFn: () => '#6D4C00', weight: 1.5 },
  // Stressed magenta (code 1) -> healthy green (code 5, Excellent); magenta
  // reads immediately against canopy green. Ramp direction follows the
  // CODE order (1=Stressed..5=Excellent), not reading order of the
  // "Healthy -> Stressed" column header, which names the concepts, not a
  // code-ascending direction.
  forest_health: { from: '#E91E63', to: '#1B5E20', fillOpacity: 0.5, strokeFn: (fill) => darken(fill), weight: 1.5 },
  // Hypsometric tint (purple->orange) — distinct from satellite greens/browns.
  dem: { from: '#4A148C', to: '#FF6F00', fillOpacity: 0.38, strokeFn: () => 'transparent', weight: 0 },
};

interface FlatSpec { color: string; fillOpacity: number; stroke: string; weight: number; dashArray?: string; }
const FLATS: Partial<Record<AutoBlockSourceKey, FlatSpec>> = {
  // Neon cyan boundary: reads against both green canopy and dark water, and
  // the near-hollow fill keeps the underlying terrain visible — MMU carves
  // river/ridge BOUNDARIES, not a classification, so a flat outline is the
  // honest representation, not a filled class.
  mmu: { color: '#00FFFF', fillOpacity: 0.08, stroke: '#00FFFF', weight: 2.5 },
  // Bright emerald, distinguishable from both forest imagery green and dark
  // background trees; canopy classes are read from the attribute table, not
  // colour-coded, since the structural classes (non-forest/regen/pole/tree)
  // read better as one recognizable "canopy" colour than four closely-related greens.
  canopy: { color: '#00FF66', fillOpacity: 0.45, stroke: '#006622', weight: 1.5 },
  // union_zonal/union_fusion are NOT here (owner directive 2026-10-02,
  // superseding RS-10.5's original flat-plum design) — both now key off
  // `dominant_slope_band` via `unionSlopeStyle`, handled as its own branch
  // in `classificationStyle` below, before this table is ever consulted.
};

const CATEGORICAL_OPTS: Partial<Record<AutoBlockSourceKey, { fillOpacity: number; stroke: string; weight: number; strokeFromFill?: boolean }>> = {
  aspect: { fillOpacity: 0.4, stroke: '#333333', weight: 1 },
  landcover: { fillOpacity: 0.4, stroke: '#222222', weight: 1 },
  forest_type: { fillOpacity: 0.45, stroke: '#000000', weight: 1, strokeFromFill: true },
};

const DEFAULT_FALLBACK: PathOptions = { color: '#8B5CF6', weight: 2, fillOpacity: 0.15 };

/** Owner directive 2026-10-02: both Union sources default to this exact
 *  4-class categorical scheme, keyed on `dominant_slope_band` (1-4,
 *  कार्यविधि §15.2) — green/yellow/orange/red, a flat lookup rather than
 *  the plain `slope` source's 2-colour continuous ramp. A code outside
 *  1-4 (no slope coverage at all for that piece) falls back to neutral
 *  grey, same convention every other categorical source here uses. */
export const SLOPE_BAND_COLORS: Record<number, string> = {
  1: '#2E7D32', // green  — gentle,      < 19°
  2: '#F9A825', // yellow — moderate,  19-31°
  3: '#EF6C00', // orange — steep,     31-45°
  4: '#C62828', // red    — very steep, > 45°
};
const UNION_STYLE_OPTS = { fillOpacity: 0.4, weight: 1.5 };

function unionSlopeStyle(code: number | null | undefined): PathOptions {
  const fill = (code != null && SLOPE_BAND_COLORS[code]) || '#9CA3AF';
  return { color: darken(fill), fillColor: fill, weight: UNION_STYLE_OPTS.weight, fillOpacity: UNION_STYLE_OPTS.fillOpacity };
}

/**
 * The default style for ONE classification, independent of how it was
 * obtained — a `GeoJSON.Feature`'s properties (the committed layer,
 * `autoBlockFeatureStyle` below) or a raw `(code, label)` pair a caller
 * already has on hand (the Auto-Block Designer's live MERGE PREVIEW,
 * before anything is committed — owner report 2026-10-02: "these should
 * also reflect in preview... make it easy for the user to perceive").
 * Exported so the preview never has to fabricate a fake `GeoJSON.Feature`
 * just to reuse this logic.
 */
export function classificationStyle(
  source: string,
  code: number | null | undefined,
  humanLabel: string | null | undefined,
): PathOptions {
  if (source === 'union_zonal' || source === 'union_fusion') {
    return unionSlopeStyle(code);
  }
  const flat = FLATS[source as AutoBlockSourceKey];
  if (flat) {
    return { color: flat.stroke, fillColor: flat.color, weight: flat.weight, fillOpacity: flat.fillOpacity };
  }
  const ramp = RAMPS[source as AutoBlockSourceKey];
  if (ramp) {
    const max = RAMP_MAX[source] ?? 5;
    const t = code != null && Number.isFinite(code) && max > 1 ? (code - 1) / (max - 1) : 0.5;
    const fill = rampAt(ramp.from, ramp.to, t);
    return { color: ramp.strokeFn(fill), fillColor: fill, weight: ramp.weight, fillOpacity: ramp.fillOpacity };
  }
  const catOpts = CATEGORICAL_OPTS[source as AutoBlockSourceKey];
  if (catOpts) {
    const table = source === 'landcover' ? LANDCOVER_COLORS : (CATEGORICAL[source] ?? {});
    const fill = table[humanLabel ?? ''] ?? '#9CA3AF';
    const stroke = catOpts.strokeFromFill ? darken(fill) : catOpts.stroke;
    return { color: stroke, fillColor: fill, weight: catOpts.weight, fillOpacity: catOpts.fillOpacity };
  }
  return DEFAULT_FALLBACK;
}

/**
 * The default Leaflet style for one Auto-Block layer feature, given its
 * source and the GeoJSON feature `layer_features` produced. Promoted
 * layers render with the dashed-vs-solid distinction the panel already
 * uses elsewhere (trial = dashed, lighter; promoted = solid, fuller) — pass
 * `promoted` through from the layer's own `promoted_as`.
 */
export function autoBlockFeatureStyle(
  source: string,
  feature: GeoJSON.Feature | undefined,
  promoted: boolean,
): PathOptions {
  const props = (feature?.properties ?? {}) as Record<string, unknown>;
  const base = ((): PathOptions => {
    if (source === 'union_zonal' || source === 'union_fusion') {
      // Both Union sources key off the slope band specifically, never the
      // generic `SOURCE_LABEL_KEY`-driven `_<Label>_code` lookup every
      // other source uses (theirs is `null` — a Union feature carries 9
      // classifications, not one).
      const code = Number(props['_Slope Band_code']);
      return classificationStyle(source, Number.isFinite(code) ? code : null, null);
    }
    const labelKey = SOURCE_LABEL_KEY[source as AutoBlockSourceKey];
    const code = labelKey ? Number(props[`_${labelKey}_code`]) : NaN;
    const human = labelKey ? String(props[labelKey] ?? '') : null;
    return classificationStyle(source, Number.isFinite(code) ? code : null, human);
  })();
  // Trial-vs-promoted distinction, layered on top of the source's own
  // palette (matches the existing raster-layer map convention: dashed +
  // dimmer while unpromoted, solid + fuller once it's the real structure).
  return promoted
    ? base
    : { ...base, dashArray: '4 3', fillOpacity: (base.fillOpacity ?? 0.3) * 0.7 };
}
