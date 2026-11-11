/**
 * Thematic renderer specs (WORKSPACE_LAYER_STYLING_PLAN.md P4, decision D8).
 *
 * A layer can be drawn by a *categorized* (one colour per distinct value) or a
 * *graduated* (colour ramp over numeric breaks) renderer instead of its single
 * style. The spec lives in `calculation.result_data.layer_renderers[layerKey]`
 * so it travels with the forest and appears in exports; it is never in
 * localStorage. In the render chain (D1) it sits **above** the layer's custom
 * style and the palette, **below** the per-feature `style` override.
 */
import { sampleRamp, equalBreaks, quantileBreaks } from './colorRamps';
import { SLOPE_BAND_LABEL, ASPECT_LABEL, CANOPY_CLASS_LABEL } from './layerRegistry';

export interface CategoryClass {
  value: string;
  color: string;
  label?: string;
}

export interface CategorizedRenderer {
  mode: 'categorized';
  field: string;
  classes: CategoryClass[];
  /** colour for a value not matched by any class; omitted → such features keep
   *  their normal (non-thematic) style. */
  otherColor?: string;
}

export interface GraduatedRenderer {
  mode: 'graduated';
  field: string;
  method: 'equal' | 'quantile';
  /** `classes - 1` ascending break values. */
  breaks: number[];
  /** `breaks.length + 1` colours, low → high. */
  colors: string[];
  ramp: string;
}

export type RendererSpec = CategorizedRenderer | GraduatedRenderer;

/**
 * P4.5 — the one-click "Colour by condition" preset for `blocks` / `compartments`.
 * Keyed to the field-inventory `forest_condition` ('Good' | 'Moderate' | 'Weak')
 * with a fixed green / amber / red palette; anything else (incl. blocks with no
 * field inventory) reads grey.
 */
export const CONDITION_RENDERER: CategorizedRenderer = {
  mode: 'categorized',
  field: 'forest_condition',
  classes: [
    { value: 'Good', color: '#2e7d32', label: 'Good' },
    { value: 'Moderate', color: '#f9a825', label: 'Moderate' },
    { value: 'Weak', color: '#c62828', label: 'Weak' },
  ],
  otherColor: '#bdbdbd',
};

/**
 * One-click presets for the 3 Auto-Block source classification fields
 * (SLOPE_COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN follow-on). Values are
 * stored as integers (1-4 / 1-8) but `rendererColorFor` matches on the
 * string form, so every class `value` here is the stringified code; labels
 * are pulled from the SAME dicts the attribute table and map-label
 * formatter already use (layerRegistry.ts), so a band never reads
 * differently in two places. `otherColor` is grey for a block/compartment
 * this Auto-Block source never classified (a different source carved it,
 * or it predates Auto-Block).
 *
 * SLOPE — a standard hazard/traffic-light ramp (कार्यविधि §15.2 bands):
 * gentle -> green, steep -> red.
 */
export const SLOPE_BAND_RENDERER: CategorizedRenderer = {
  mode: 'categorized',
  field: 'dominant_slope_band',
  classes: [
    { value: '1', color: '#a5d6a7', label: SLOPE_BAND_LABEL[1] },
    { value: '2', color: '#fff59d', label: SLOPE_BAND_LABEL[2] },
    { value: '3', color: '#ffab91', label: SLOPE_BAND_LABEL[3] },
    { value: '4', color: '#e53935', label: SLOPE_BAND_LABEL[4] },
  ],
  otherColor: '#bdbdbd',
};

/**
 * ASPECT — a diverging "heat-load index" scale on the N-S axis (the
 * convention forestry/ecology GIS use for solar-exposure aspect maps, e.g.
 * USDA's Topographic Radiation Aspect Index): N is coolest/wettest (deep
 * blue), S is hottest/driest (deep red), and the scale is symmetric —
 * NE/NW share one "cool-transitional" colour and SE/SW share one
 * "warm-transitional" colour, because each pair receives essentially the
 * same solar load (morning vs afternoon sun, not a different amount of
 * it). E/W share a neutral pale yellow at the scale's midpoint. This reads
 * more clearly than a full 8-hue compass wheel, which would wrongly imply
 * E and W are opposite extremes the way N and S are.
 */
export const ASPECT_RENDERER: CategorizedRenderer = {
  mode: 'categorized',
  field: 'dominant_aspect',
  classes: [
    { value: '1', color: '#08519c', label: ASPECT_LABEL[1] }, // N
    { value: '2', color: '#6baed6', label: ASPECT_LABEL[2] }, // NE
    { value: '3', color: '#ffffbf', label: ASPECT_LABEL[3] }, // E
    { value: '4', color: '#fd8d3c', label: ASPECT_LABEL[4] }, // SE
    { value: '5', color: '#bd0026', label: ASPECT_LABEL[5] }, // S
    { value: '6', color: '#fd8d3c', label: ASPECT_LABEL[6] }, // SW
    { value: '7', color: '#ffffbf', label: ASPECT_LABEL[7] }, // W
    { value: '8', color: '#6baed6', label: ASPECT_LABEL[8] }, // NW
  ],
  otherColor: '#bdbdbd',
};

/**
 * CANOPY — a young -> mature growth gradient (the standard convention for
 * vegetation-maturity/density maps: pale = sparse/young, deep green =
 * dense/mature). Non-forest is a neutral grey-brown, not green, since it
 * is literally the absence of canopy.
 */
export const CANOPY_CLASS_RENDERER: CategorizedRenderer = {
  mode: 'categorized',
  field: 'dominant_canopy_class',
  classes: [
    { value: '1', color: '#bcaaa4', label: CANOPY_CLASS_LABEL[1] }, // non-forest
    { value: '2', color: '#c7e9c0', label: CANOPY_CLASS_LABEL[2] }, // regeneration
    { value: '3', color: '#74c476', label: CANOPY_CLASS_LABEL[3] }, // pole
    { value: '4', color: '#238b45', label: CANOPY_CLASS_LABEL[4] }, // tree
  ],
  otherColor: '#bdbdbd',
};

export function isCategorized(s: RendererSpec | null | undefined): s is CategorizedRenderer {
  return !!s && s.mode === 'categorized';
}
export function isGraduated(s: RendererSpec | null | undefined): s is GraduatedRenderer {
  return !!s && s.mode === 'graduated';
}

/** The colour a renderer assigns to one feature value, or null when the
 *  renderer does not cover it (caller then keeps the feature's normal style). */
export function rendererColorFor(spec: RendererSpec, value: unknown): string | null {
  if (spec.mode === 'categorized') {
    const key = value == null ? '' : String(value);
    const hit = spec.classes.find((c) => c.value === key);
    return hit ? hit.color : (spec.otherColor ?? null);
  }
  if (value == null || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  const { breaks, colors } = spec;
  if (colors.length === 0) return null;
  for (let i = 0; i < breaks.length; i++) {
    if (n <= breaks[i]) return colors[i] ?? colors[colors.length - 1];
  }
  return colors[colors.length - 1];
}

/** One legend row per class / bucket, low → high. */
export function rendererLegendRows(spec: RendererSpec): Array<{ color: string; label: string }> {
  if (spec.mode === 'categorized') {
    const rows = spec.classes.map((c) => ({ color: c.color, label: c.label || c.value || '—' }));
    if (spec.otherColor) rows.push({ color: spec.otherColor, label: 'Other' });
    return rows;
  }
  const { breaks, colors } = spec;
  return colors.map((color, i) => {
    const lo = i === 0 ? null : breaks[i - 1];
    const hi = i < breaks.length ? breaks[i] : null;
    const label = lo == null ? `≤ ${fmt(hi)}` : hi == null ? `> ${fmt(lo)}` : `${fmt(lo)} – ${fmt(hi)}`;
    return { color, label };
  });
}

function fmt(n: number | null): string {
  if (n == null) return '';
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

/** Build a categorized renderer from a layer's features: one class per distinct
 *  value of `field`, colours sampled from `ramp`. */
export function buildCategorizedRenderer(
  features: Array<{ properties?: Record<string, unknown> | null }>,
  field: string,
  ramp: string,
): CategorizedRenderer {
  const seen: string[] = [];
  for (const f of features) {
    const raw = f.properties?.[field];
    const key = raw == null ? '' : String(raw);
    if (!seen.includes(key)) seen.push(key);
  }
  seen.sort();
  const palette = sampleRamp(ramp, Math.max(1, seen.length));
  return {
    mode: 'categorized',
    field,
    classes: seen.map((value, i) => ({ value, color: palette[i] ?? palette[palette.length - 1], label: value || '—' })),
  };
}

/** Build a graduated renderer from a layer's numeric field. */
export function buildGraduatedRenderer(
  features: Array<{ properties?: Record<string, unknown> | null }>,
  field: string,
  classes: number,
  method: 'equal' | 'quantile',
  ramp: string,
): GraduatedRenderer {
  const values = features
    .map((f) => Number(f.properties?.[field]))
    .filter((n) => Number.isFinite(n));
  const breaks = method === 'equal' ? equalBreaks(values, classes) : quantileBreaks(values, classes);
  return {
    mode: 'graduated',
    field,
    method,
    breaks,
    colors: sampleRamp(ramp, breaks.length + 1),
    ramp,
  };
}
