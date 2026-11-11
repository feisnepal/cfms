import type L from 'leaflet';
import { SUB_AREA_CATEGORIES, ALL_SUB_AREA_CATEGORIES } from './subAreaCategories';

export interface LayerStyle {
  fillColor?: string;
  fillOpacity?: number;
  /** stroke opacity (Leaflet `opacity`) — set by the whole-layer alpha (P5.2). */
  opacity?: number;
  color?: string;
  weight?: number;
  haloColor?: string;
  haloWeight?: number;
  radius?: number;
  dashArray?: string;
}

// Permanent color palettes for each hierarchy level
// Designed for 5-10 features per level with maximum visual distinction
// All colors have transparency built-in for base map visibility

export const BLOCK_COLORS = [
  '#1E90FF',  // Dodger Blue
  '#00CED1',  // Dark Turquoise
  '#00BFFF',  // Deep Sky Blue
  '#4169E1',  // Royal Blue
  '#6495ED',  // Cornflower Blue
  '#4682B4',  // Steel Blue
  '#5F9EA0',  // Cadet Blue
  '#7B68EE',  // Medium Slate Blue
  '#6A5ACD',  // Slate Blue
  '#483D8B',  // Dark Slate Blue
];

// FS-4a.16: the block branch's sub-level palette — a teal/cyan family,
// distinct from BLOCK_COLORS' blues, mirroring how SUB_COMPARTMENT_COLORS
// (red/orange) differs from COMPARTMENT_COLORS (brown).
export const SUB_BLOCK_COLORS = [
  '#00897B',  // Teal
  '#00ACC1',  // Cyan
  '#26A69A',  // Teal (lighter)
  '#00BFA5',  // Teal Accent
  '#4DB6AC',  // Teal (muted)
  '#00838F',  // Cyan dark
  '#0097A7',  // Cyan (deep)
  '#006064',  // Cyan very dark
  '#1DE9B6',  // Teal Accent bright
  '#004D40',  // Teal very dark
];

export const COMPARTMENT_COLORS = [
  '#8B4513',  // Saddle Brown
  '#A0522D',  // Sienna
  '#CD853F',  // Peru
  '#D2691E',  // Chocolate
  '#DEB887',  // Burlywood
  '#BC8F8F',  // Rosy Brown
  '#8B7355',  // Beaver
  '#964B00',  // Brown
  '#8B6914',  // Dark Goldenrod variant
  '#A52A2A',  // Brown
];

export const SUB_COMPARTMENT_COLORS = [
  '#FF6347',  // Tomato
  '#FF4500',  // Orange Red
  '#FF8C00',  // Dark Orange
  '#FF7F50',  // Coral
  '#FF6B6B',  // Light Coral variant
  '#E34234',  // Red
  '#D84315',  // Deep Orange
  '#BF360C',  // Deep Orange dark
  '#C62828',  // Red dark
  '#E65100',  // Orange dark
];

// Protection Working Circle (PROTECTION_WORKING_CIRCLE_PLAN.md P5-display).
// A `working_circle === 'protection'` block / compartment / sub-compartment is
// felling-free — it must read differently from the production palette at a
// glance: a fixed conservation green with a dashed stroke, regardless of the
// unit's palette colorIndex.
export const PROTECTION_WC_COLOR = '#047857';       // emerald-700
export const PROTECTION_WC_STROKE = '#065F46';      // emerald-800

export const PROTECTION_WC_STYLE: LayerStyle = {
  fillColor: PROTECTION_WC_COLOR,
  fillOpacity: 0.35,
  color: PROTECTION_WC_STROKE,
  weight: 2,
  dashArray: '6, 4',
  haloColor: '#FFFFFF',
  haloWeight: 3,
};

// Overlay the protection treatment onto an already-computed unit style when the
// feature belongs to the protection working circle; otherwise pass the style
// through untouched (same reference, so callers can identity-compare).
export function applyWorkingCircleStyle(
  style: LayerStyle,
  workingCircle: string | null | undefined,
): LayerStyle {
  if (workingCircle !== 'protection') return style;
  return {
    ...style,
    fillColor: PROTECTION_WC_COLOR,
    color: PROTECTION_WC_STROKE,
    fillOpacity: Math.max(style.fillOpacity ?? 0, 0.35),
    dashArray: '6, 4',
  };
}

// ── Custom per-layer style resolution (WORKSPACE_LAYER_STYLING_PLAN.md P0) ──
//
// A user-chosen style for a layer, from the right-click "Style Layer" dialog,
// keyed per calculation for built-ins (`<calcId>::<layerId>`) and by DB id for
// imported layers (`imported-<id>` — unchanged). Before P0 this map was written
// but never read for built-in layers, and read at the wrong key for imported.
export type CustomLayerStyle = LayerStyle & { __flat?: boolean };

/** Key under which a layer's custom style is stored. Built-ins are scoped to
 *  the calculation so a colour set on "blocks" in one forest does not bleed
 *  into another. Imported layers keep their globally-unique `imported-<id>`. */
export function layerStyleKey(
  layerId: string,
  layerType: 'builtin' | 'imported' | 'raster',
  calculationId: string | null,
): string {
  return layerType === 'imported'
    ? (layerId.startsWith('imported-') ? layerId : `imported-${layerId}`)
    : `${calculationId ?? 'nc'}::${layerId}`;
}

/**
 * Fold a layer's custom style over its computed base style.
 *
 * Precedence is per-property, not whole-object: on a palette layer the palette
 * owns `fillColor` / `color` unless the user ticked "override palette" (`__flat`);
 * the custom style owns everything else. Returns `base` *by reference* when there
 * is nothing to apply, so the no-override path is provably unchanged.
 */
export function resolveLayerStyle(opts: {
  base: LayerStyle;
  custom?: CustomLayerStyle | null;
  usesPalette?: boolean;
  paletteColor?: string;
}): LayerStyle {
  const { base, custom, usesPalette, paletteColor } = opts;
  const hasCustom = !!custom && Object.keys(custom).some((k) => k !== '__flat' && (custom as Record<string, unknown>)[k] != null);

  if (!hasCustom) {
    return paletteColor ? { ...base, fillColor: paletteColor, color: paletteColor } : base;
  }

  const { __flat, ...rest } = custom as CustomLayerStyle;
  const clean: LayerStyle = {};
  for (const [k, v] of Object.entries(rest)) if (v != null) (clean as Record<string, unknown>)[k] = v;

  const merged: LayerStyle = { ...base, ...clean };
  if (paletteColor) {
    if (usesPalette && !__flat) {
      merged.fillColor = paletteColor;
      merged.color = paletteColor;
    } else if (!usesPalette) {
      if (clean.fillColor == null) merged.fillColor = paletteColor;
      if (clean.color == null) merged.color = paletteColor;
    }
  }
  return merged;
}

// A per-feature style override — the nullable `style` JSON carried on a block /
// compartment / sub-compartment / sub-area row (WORKSPACE_LAYER_STYLING_PLAN.md
// P3, migration 075). Any subset of the four keys.
export interface FeatureStyleOverride {
  fill?: string | null;
  fillOpacity?: number | null;
  stroke?: string | null;
  weight?: number | null;
}

/**
 * Fold a per-feature style override over an already layer-resolved style.
 *
 * Precedence (D1): selection ▸ per-feature style ▸ renderer (P4) ▸ custom layer
 * style ▸ palette / base. This is the per-feature tier — call it on the output
 * of `resolveLayerStyle` (and, for units, `applyWorkingCircleStyle`). Returns
 * `base` by reference when the override is empty, so the no-override path is
 * provably unchanged.
 */
export function resolveFeatureStyle(
  base: LayerStyle,
  override?: FeatureStyleOverride | null,
): LayerStyle {
  if (!override || typeof override !== 'object') return base;
  const has =
    override.fill != null ||
    override.stroke != null ||
    override.fillOpacity != null ||
    override.weight != null;
  if (!has) return base;
  const out: LayerStyle = { ...base };
  if (override.fill != null) out.fillColor = override.fill;
  if (override.stroke != null) out.color = override.stroke;
  if (override.fillOpacity != null) out.fillOpacity = override.fillOpacity;
  if (override.weight != null) out.weight = override.weight;
  return out;
}

/**
 * Fold a thematic renderer's colour over an already layer-resolved style
 * (WORKSPACE_LAYER_STYLING_PLAN.md P4.2). Sits above the custom layer style /
 * palette / working-circle treatment, below the per-feature `style` override.
 * `colour` is `rendererColorFor(spec, feature.properties[spec.field])` — `null`
 * when the renderer doesn't cover this feature, in which case `base` is returned
 * unchanged by reference.
 */
/** The outline of a unit coloured by an analysis map: dark and always drawn, so the edge of every unit - and the line between two
 *  neighbours of the same class - stays visible on top of the fill (a stroke in the fill's own colour made the boundary vanish). */
export const ANALYSIS_UNIT_OUTLINE = '#263238';

/** A unit coloured by an analysis map (SFM, field inventory): the class colour as the fill, a dark outline for the boundary. */
export function analysisUnitStyle(base: LayerStyle, colour: string | null | undefined): LayerStyle {
  if (!colour) return base;
  return { ...base, fillColor: colour, color: ANALYSIS_UNIT_OUTLINE, weight: Math.max(base.weight ?? 1, 1.6), opacity: 1 };
}

export function resolveRendererStyle(base: LayerStyle, colour: string | null | undefined): LayerStyle {
  if (!colour) return base;
  return { ...base, fillColor: colour, color: colour };
}

/**
 * Multiply a resolved style's stroke + fill opacity by a whole-layer alpha
 * (WORKSPACE_LAYER_STYLING_PLAN.md P5.2). `alpha` of 1 (or missing) returns the
 * style unchanged by reference.
 */
export function applyLayerAlpha(style: LayerStyle, alpha: number | undefined): LayerStyle {
  if (alpha == null || alpha >= 1) return style;
  const a = Math.max(0, alpha);
  return {
    ...style,
    opacity: style.opacity != null ? style.opacity * a : a,
    fillOpacity: (style.fillOpacity ?? 1) * a,
  };
}

/**
 * Build the `style` value for a PATCH from an attribute-table edit on the
 * per-feature colour / opacity columns (P3.4).
 *
 * Returns `undefined` when `colKey` is not a style column (the caller then
 * falls back to its normal field handling); `null` to clear the override; or
 * the merged `{fill, fillOpacity}` object otherwise. A merge that ends up empty
 * also collapses to `null`.
 */
export function buildStylePatch(
  existing: unknown,
  colKey: string,
  value: string,
): Record<string, unknown> | null | undefined {
  if (colKey !== 'style_fill' && colKey !== 'style_opacity' && colKey !== 'style_clear') {
    return undefined;
  }
  if (colKey === 'style_clear') return null;
  const base: Record<string, unknown> =
    existing && typeof existing === 'object' ? { ...(existing as Record<string, unknown>) } : {};
  if (colKey === 'style_fill') {
    if (value) base.fill = value;
    else delete base.fill;
  } else {
    const n = Number(value);
    if (value === '' || Number.isNaN(n)) delete base.fillOpacity;
    else base.fillOpacity = n;
  }
  return Object.keys(base).length > 0 ? base : null;
}

// The Auto-Block classification columns (dominant_slope_band/_aspect/
// _canopy_class) are backend Optional[int] fields, but an HTML <select>'s
// onChange value is always a string — "" for the blank/clear option, else
// the option's string value (e.g. "3"). User report, 2026-09-12: these are
// now editable, same as any other attribute; these are the integer-typed
// case among them, so it needs its own coercion the same way style does.
const INTEGER_ATTRIBUTE_KEYS = new Set([
  'dominant_slope_band', 'dominant_aspect', 'dominant_canopy_class',
  // Raster class columns (RS-5.4). Same reason: <select> yields a string, the
  // backend column is Optional[int], so clearing ("") would 422 uncoerced.
  'dominant_nasa_quality', 'dominant_landcover', 'dominant_health_class',
]);

/**
 * Coerce an attribute-table edit's raw string `value` to the type the PATCH
 * body actually needs: `null` for the blank/clear option, a `number` for one
 * of the 3 classification columns, or `value` unchanged for every other
 * (string) column.
 */
export function coerceAttributeValue(colKey: string, value: string): unknown {
  if (!INTEGER_ATTRIBUTE_KEYS.has(colKey)) return value;
  if (value === '') return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

// Named starting points offered from the layer ⋮ menu (P1.4). Colour keys are
// only honoured on palette layers when `__flat` is set — that is why each
// preset carries `__flat: true`.
export const NAMED_STYLE_PRESETS: Record<string, CustomLayerStyle> = {
  muted: { __flat: true, fillColor: '#9CA3AF', color: '#6B7280', weight: 1, fillOpacity: 0.15 },
  highContrast: { __flat: true, fillColor: '#F59E0B', color: '#111827', weight: 3, fillOpacity: 0.4 },
  printOutline: { __flat: true, fillColor: '#000000', color: '#000000', weight: 2, fillOpacity: 0 },
};

// In-memory "copy style / paste style" clipboard for the layer ⋮ menu (P1.4).
// Not the OS clipboard — session-scoped, lost on reload, which is the intent.
let _styleClipboard: CustomLayerStyle | null = null;
export const getStyleClipboard = (): CustomLayerStyle | null => _styleClipboard;
export const setStyleClipboard = (s: CustomLayerStyle | null): void => { _styleClipboard = s ? { ...s } : null; };

export function generateRedBluePalette(count: number): string[] {
  if (count <= 0) return [];
  if (count === 1) return ['#cc3344'];
  const colors: string[] = [];
  for (let i = 0; i < count; i++) {
    const t = i / (count - 1);
    const hue = Math.round(t * 220);
    colors.push(`hsl(${hue}, 75%, 55%)`);
  }
  return colors;
}

/** Deterministic string hash (FNV-1a, 32-bit) — same input always gives the
 *  same output, across sessions and reloads, with no shared state. */
function hashString(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * Owner report 2026-10-02: Block/Compartment/Sub-block/Sub-compartment
 * colours were assigned by each feature's POSITION in the fetched list
 * (`colorIndex: index`, `layerRegistry.ts`) — visually "categorical", but
 * every unit's colour silently shifts whenever one is added, deleted, or
 * the list is refetched in a different order, even though that unit
 * itself never changed. This derives the SAME red-blue hue range
 * (`generateRedBluePalette`'s own 0-220° spread) from the unit's own
 * stable identity (its id, never its display name — a name can be
 * reassigned by a merge/split/renumber elsewhere in this codebase, an id
 * never is) instead of its position, so a unit's colour only ever changes
 * if the unit itself does.
 */
export function stableUnitColor(id: string | null | undefined): string {
  if (!id) return 'hsl(0, 75%, 55%)';
  const hue = hashString(id) % 221; // 0-220°, same range generateRedBluePalette uses
  return `hsl(${hue}, 75%, 55%)`;
}

export const SUB_AREA_COLORS = [
  '#8B4513',  // Saddle Brown (Road/Path)
  '#4169E1',  // Royal Blue (Stream)
  '#00008B',  // Dark Blue (River)
  '#FF4500',  // Orange Red (Degraded)
  '#90EE90',  // Light Green (Plantation)
  '#808080',  // Gray (Settlement)
  '#FFD700',  // Gold (Agriculture)
  '#00CED1',  // Dark Turquoise (Water Body)
  '#555555',  // Dim Gray (Cliff)
  '#008080',  // Teal (Wetland)
  '#32CD32',  // Lime Green (Grassland)
  '#6B8E23',  // Olive Drab (Shrubland)
  '#800080',  // Purple (Conservation)
  '#D3D3D3',  // Light Gray (Other)
];

/** Field Book's colour (sky blue, Tailwind sky-400) — the one place it is defined. The map
 *  marker, the layer glyph and the style preset all read it. Sample Plots stay amber. */
export const FIELDBOOK_COLOR = '#38bdf8';
/** Legible text/ring colour on a sky-blue fill, and for the hollow "interpolated" ring. */
export const FIELDBOOK_TEXT_COLOR = '#0c4a6e';

export const STYLE_PRESETS = {
  forest_boundary: {
    fillColor: '#228B22',
    fillOpacity: 0.20,
    color: '#006400',
    weight: 2,
  } as LayerStyle,

  blocks: {
    fillOpacity: 0.15,
    color: '#1E90FF',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  // FS-4a.16: the block branch's sub-level layer — same family as `blocks`
  // (steel blue vs dodger blue), a touch more opaque, mirroring how
  // `sub_compartments` differs from `compartments`.
  sub_blocks: {
    fillOpacity: 0.22,
    color: '#4682B4',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  compartments: {
    fillOpacity: 0.25,
    color: '#8B4513',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_compartments: {
    fillOpacity: 0.30,
    color: '#FF6347',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_road: {
    fillColor: '#8B4513',
    fillOpacity: 0.40,
    color: '#5C2E00',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_stream: {
    fillColor: '#4169E1',
    fillOpacity: 0.40,
    color: '#1E3F8E',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_river: {
    fillColor: '#00008B',
    fillOpacity: 0.40,
    color: '#000066',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_degraded: {
    fillColor: '#FF4500',
    fillOpacity: 0.40,
    color: '#CC3700',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_plantation: {
    fillColor: '#90EE90',
    fillOpacity: 0.40,
    color: '#228B22',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_settlement: {
    fillColor: '#808080',
    fillOpacity: 0.40,
    color: '#555555',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_agriculture: {
    fillColor: '#FFD700',
    fillOpacity: 0.40,
    color: '#BBA600',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_water_body: {
    fillColor: '#00CED1',
    fillOpacity: 0.40,
    color: '#008B8B',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_cliff: {
    fillColor: '#555555',
    fillOpacity: 0.40,
    color: '#333333',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_wetland: {
    fillColor: '#008080',
    fillOpacity: 0.40,
    color: '#004D4D',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_grassland: {
    fillColor: '#32CD32',
    fillOpacity: 0.40,
    color: '#228B22',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_shrubland: {
    fillColor: '#6B8E23',
    fillOpacity: 0.40,
    color: '#556B2F',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_conservation: {
    fillColor: '#800080',
    fillOpacity: 0.40,
    color: '#4B004B',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  sub_area_other: {
    fillColor: '#D3D3D3',
    fillOpacity: 0.40,
    color: '#999999',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  activity_points: {
    fillColor: '#1E90FF',
    fillOpacity: 1.0,
    color: '#1E90FF',
    weight: 2,
    radius: 8,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  activity_point: {
    fillColor: '#1E90FF',
    fillOpacity: 1.0,
    color: '#1E90FF',
    weight: 2,
    radius: 8,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  activity_line: {
    fillOpacity: 0,
    color: '#32CD32',
    weight: 3,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  activity_polygon: {
    fillColor: '#FF8C00',
    fillOpacity: 0.40,
    color: '#FF6600',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  activity_lines: {
    fillOpacity: 0,
    color: '#32CD32',
    weight: 3,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  activity_polygons: {
    fillColor: '#FF8C00',
    fillOpacity: 0.40,
    color: '#FF6600',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  selection: {
    fillColor: '#FFD700',
    fillOpacity: 0.30,
    color: '#FFD700',
    weight: 4,
    dashArray: '6, 3',
  } as LayerStyle,

  sub_areas_default: {
    fillColor: '#90EE90',
    fillOpacity: 0.40,
    color: '#228B22',
    weight: 2,
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  activity_features_default: {
    fillColor: '#1E90FF',
    fillOpacity: 0.30,
    color: '#1E90FF',
    weight: 2,
    radius: 8,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  // Field Book workspace layer — sky blue, so it never reads as Sample Plots (amber):
  // both are numbered circle markers, and with the same colour a walked boundary point
  // and a sample plot are indistinguishable on the map and in the legend.
  fieldbook: {
    fillColor: FIELDBOOK_COLOR,
    fillOpacity: 0.85,
    color: FIELDBOOK_COLOR,
    weight: 2,
    radius: 7,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  // Phase G — Sample Plots workspace layer (amber = legacy numbered markers)
  sample_plots: {
    fillColor: '#fbbf24',
    fillOpacity: 0.85,
    color: '#fbbf24',
    weight: 2,
    radius: 7,
    haloColor: '#FFFFFF',
    haloWeight: 2,
  } as LayerStyle,

  // User Group Boundary workspace layer (indigo, dashed — the settlement
  // catchment; distinct from the forest-green boundary). USER_GROUP_BOUNDARY_PLAN.md D6.
  user_group: {
    fillColor: '#6366F1',
    fillOpacity: 0.12,
    color: '#4338CA',
    weight: 2,
    dashArray: '4, 4',
    haloColor: '#FFFFFF',
    haloWeight: 3,
  } as LayerStyle,

  // Stem Mapping workspace layer — one point per surveyed tree (read-only,
  // like Sample Plots). Violet, unused elsewhere in the palette, so a dense
  // cluster of tree points still reads distinctly against the forest-green
  // boundary/sub-areas and the blue blocks underneath it.
  stem_mapping: {
    fillColor: '#7C3AED',
    fillOpacity: 0.85,
    color: '#5B21B6',
    weight: 1,
    radius: 5,
    haloColor: '#FFFFFF',
    haloWeight: 1,
  } as LayerStyle,
} as const;

export type StylePresetKey = keyof typeof STYLE_PRESETS;

// Single source of sub-area styling keyed by official List A category (D1).
// Derived from subAreaCategories colors so map, table and legacy tabs agree.
export const SUB_AREA_STYLES: Record<string, LayerStyle> = (() => {
  const map: Record<string, LayerStyle> = {
    other: STYLE_PRESETS.sub_area_other,
  };
  for (const cat of ALL_SUB_AREA_CATEGORIES) {
    map[cat.key] = { fillColor: cat.color, fillOpacity: 0.40, color: cat.color, weight: 2, haloColor: '#FFFFFF', haloWeight: 3 };
  }
  return map;
})();

export type SubAreaCategoryInfo = { key: string; label: string; labelNp: string; styleKey: keyof typeof STYLE_PRESETS; contrastColor: string };

// List A (official 13-value) as the exposed category keys. List B (road/stream/…)
// is retired per D1.
export const SUB_AREA_CATEGORY_KEYS: SubAreaCategoryInfo[] = SUB_AREA_CATEGORIES.map((c) => ({
  key: c.key,
  label: c.label,
  labelNp: c.labelNp,
  styleKey: 'sub_area_other' as keyof typeof STYLE_PRESETS,
  contrastColor: '#FFFFFF',
}));

export function getCategoryLabel(key: string, lang: 'en' | 'np' = 'en'): string {
  const cat = ALL_SUB_AREA_CATEGORIES.find((c) => c.key === key);
  return cat ? (lang === 'np' ? cat.labelNp : cat.label) : key;
}

export function getContrastColor(key: string): string {
  const cat = ALL_SUB_AREA_CATEGORIES.find((c) => c.key === key);
  return cat?.color || '#000000';
}

export const ACTIVITY_STYLES: Record<string, LayerStyle> = {
  point: STYLE_PRESETS.activity_point,
  line: STYLE_PRESETS.activity_line,
  polygon: STYLE_PRESETS.activity_polygon,
};

export const ACTIVITY_FEATURE_STYLES: Record<string, LayerStyle> = {
  activity_point: STYLE_PRESETS.activity_point,
  activity_line: STYLE_PRESETS.activity_line,
  activity_polygon: STYLE_PRESETS.activity_polygon,
};

export function getLayerStyle(key: StylePresetKey): LayerStyle | undefined {
  return STYLE_PRESETS[key];
}

export function getStyleForSubAreaCategory(category: string): LayerStyle {
  return SUB_AREA_STYLES[category] || SUB_AREA_STYLES.other;
}

export function getStyleForActivityFeature(geomType: string): LayerStyle {
  if (geomType === 'Point') return STYLE_PRESETS.activity_point;
  if (geomType === 'LineString' || geomType === 'MultiLineString') return STYLE_PRESETS.activity_line;
  if (geomType === 'Polygon' || geomType === 'MultiPolygon') return STYLE_PRESETS.activity_polygon;
  return STYLE_PRESETS.activity_point;
}

export interface BoundaryStyleConfig {
  color: string;
  weight: number;
  dashArray: string | null;
  fillColor: string;
  fillOpacity: number;
  label: string;
  labelNp: string;
}

export const BOUNDARY_STATUS_STYLES: Record<string, BoundaryStyleConfig> = {
  draft:     { color: '#FFD700', weight: 2, dashArray: '8,6', fillColor: '#FFD700', fillOpacity: 0.25, label: 'Draft', labelNp: 'मस्यौदा' },
  validated: { color: '#228B22', weight: 2, dashArray: null, fillColor: '#228B22', fillOpacity: 0.20, label: 'Validated', labelNp: 'प्रमाणित' },
  approved:  { color: '#1E90FF', weight: 2.5, dashArray: null, fillColor: '#1E90FF', fillOpacity: 0.20, label: 'Approved', labelNp: 'स्वीकृत' },
  disputed:  { color: '#FF4444', weight: 2, dashArray: '4,4', fillColor: '#FF4444', fillOpacity: 0.20, label: 'Disputed', labelNp: 'विवादित' },
};

export const BOUNDARY_LEGEND = [
  { symbol: '─ ─', color: '#FFD700', label: 'मस्यौदा (Draft)' },
  { symbol: '───', color: '#228B22', label: 'प्रमाणित (Validated)' },
  { symbol: '───', color: '#1E90FF', label: 'स्वीकृत (Approved)' },
  { symbol: '···', color: '#FF4444', label: 'विवादित (Disputed)' },
];

export function getBoundaryStatusStyle(status: string): BoundaryStyleConfig {
  return BOUNDARY_STATUS_STYLES[status] || BOUNDARY_STATUS_STYLES.draft;
}

export const IMPORTED_LAYER_COLORS = [
  '#3388ff', '#e6194b', '#3cb44b', '#ffe119', '#f58231',
  '#911eb4', '#42d4f4', '#f032e6', '#bfef45', '#fabed4',
  '#469990', '#dcbeff', '#9a6324', '#fffac8', '#800000',
  '#aaffc3', '#808000', '#ffd8b1', '#000075', '#a9a9a9',
];

export function getImportedLayerColor(index: number): string {
  return IMPORTED_LAYER_COLORS[index % IMPORTED_LAYER_COLORS.length];
}

export function createHaloStyles(style: LayerStyle, useHalo: boolean = true): [L.PathOptions, L.PathOptions] {
  if (!useHalo || !style.haloColor || !style.haloWeight) {
    return [{}, style as L.PathOptions];
  }

  const haloStyle: L.PathOptions = {
    color: style.haloColor,
    weight: (style.weight || 2) + (style.haloWeight || 3),
    opacity: 0.6,
    fillOpacity: 0,
  };

  if (style.radius) {
    return [
      { ...haloStyle, radius: (style.radius || 8) + 2 } as any,
      style as L.PathOptions,
    ];
  }

  return [haloStyle, style as L.PathOptions];
}

// Owner report 2026-10-02: "Make all layer labeled based on their existing
// field names." Built-in layers already had a sensible hardcoded default
// label (boundary->name, blocks->name, etc., MapCanvas.tsx's own
// `getLabelText`) and Auto-Block raster sources already had
// `defaultLabelField` (autoBlockLayerStyles.ts). Imported layers were the
// one gap: with no field explicitly picked yet, the stored `labelField`
// stayed null and NOTHING rendered — not a wrong default, no default at
// all. This picks the first real, likely-meaningful field from the
// layer's OWN existing properties (never a field that doesn't exist on
// it), the same "pick something sensible you already have" principle the
// built-in defaults use. Shared between MapCanvas.tsx (what actually
// renders) and LayerPanel.tsx (the label-field picker's own display of
// "currently selected"), so the two can never disagree about what the
// default is.
const IMPORTED_LABEL_HIDDEN_FIELDS = new Set(['id', 'featureId', 'colorIndex', 'style', 'geometry', 'part_index', 'part_count']);
const IMPORTED_LABEL_PRIORITY = ['name', 'label', 'title', 'block_name', 'feature_name'];

export function defaultImportedLabelField(features: GeoJSON.Feature[]): string | null {
  if (!features.length) return null;
  const keys = Object.keys(features[0].properties ?? {}).filter(
    (k) => !IMPORTED_LABEL_HIDDEN_FIELDS.has(k) && !k.startsWith('_'),
  );
  if (!keys.length) return null;
  const byLower = new Map(keys.map((k) => [k.toLowerCase(), k] as const));
  for (const candidate of IMPORTED_LABEL_PRIORITY) {
    const match = byLower.get(candidate);
    if (match) return match;
  }
  // No name-like field at all -- fall back to whatever real field exists
  // first, rather than showing no label at all for a layer that does have
  // SOME data to show.
  return keys[0];
}
