/**
 * Hand-rolled colour ramps for thematic (graduated / categorized) symbology.
 * WORKSPACE_LAYER_STYLING_PLAN.md P4.2 — `d3-scale-chromatic` is far too heavy
 * for six gradients, so each ramp is a short list of stops and `sampleRamp`
 * linearly interpolates in RGB.
 */

export const COLOR_RAMPS: Record<string, string[]> = {
  blues:    ['#eff3ff', '#bdd7e7', '#6baed6', '#3182bd', '#08519c'],
  greens:   ['#edf8e9', '#bae4b3', '#74c476', '#31a354', '#006d2c'],
  reds:     ['#fee5d9', '#fcae91', '#fb6a4a', '#de2d26', '#a50f15'],
  oranges:  ['#feedde', '#fdbe85', '#fd8d3c', '#e6550d', '#a63603'],
  purples:  ['#f2f0f7', '#cbc9e2', '#9e9ac8', '#756bb1', '#54278f'],
  greys:    ['#f7f7f7', '#cccccc', '#969696', '#636363', '#252525'],
  spectral: ['#d7191c', '#fdae61', '#ffffbf', '#abdda4', '#2b83ba'],
  viridis:  ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  ylgn:     ['#ffffcc', '#c2e699', '#78c679', '#31a354', '#006837'],
  ylgnbu:   ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
  bupu:     ['#edf8fb', '#b3cde3', '#8c96c6', '#8856a7', '#810f7c'],
  ylorbr:   ['#ffffd4', '#fed98e', '#fe9929', '#d95f0e', '#993404'],
  ylorrd:   ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'],
};

export const RAMP_NAMES = Object.keys(COLOR_RAMPS);

const clamp255 = (n: number) => Math.max(0, Math.min(255, Math.round(n)));

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function rgbToHex(r: number, g: number, b: number): string {
  return `#${[r, g, b].map((n) => clamp255(n).toString(16).padStart(2, '0')).join('')}`;
}

/** `n` evenly-spaced colours sampled across a ramp (interpolated in RGB). */
export function sampleRamp(name: string, n: number): string[] {
  const stops = COLOR_RAMPS[name] ?? COLOR_RAMPS.blues;
  if (n <= 0) return [];
  if (n === 1) return [stops[Math.floor((stops.length - 1) / 2)]];
  const out: string[] = [];
  for (let i = 0; i < n; i++) {
    const t = (i / (n - 1)) * (stops.length - 1);
    const lo = Math.floor(t);
    const hi = Math.min(stops.length - 1, lo + 1);
    const f = t - lo;
    const [r1, g1, b1] = hexToRgb(stops[lo]);
    const [r2, g2, b2] = hexToRgb(stops[hi]);
    out.push(rgbToHex(r1 + (r2 - r1) * f, g1 + (g2 - g1) * f, b1 + (b2 - b1) * f));
  }
  return out;
}

/** `classes - 1` equal-interval break values over [min, max]. */
export function equalBreaks(values: number[], classes: number): number[] {
  const nums = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (nums.length === 0 || classes < 2) return [];
  const min = nums[0];
  const max = nums[nums.length - 1];
  const step = (max - min) / classes;
  return Array.from({ length: classes - 1 }, (_, i) => round4(min + step * (i + 1)));
}

/** `classes - 1` quantile break values (each class holds ~the same count). */
export function quantileBreaks(values: number[], classes: number): number[] {
  const nums = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (nums.length === 0 || classes < 2) return [];
  const breaks: number[] = [];
  for (let i = 1; i < classes; i++) {
    const pos = (nums.length - 1) * (i / classes);
    const lo = Math.floor(pos);
    const hi = Math.min(nums.length - 1, lo + 1);
    breaks.push(round4(nums[lo] + (nums[hi] - nums[lo]) * (pos - lo)));
  }
  return breaks;
}

function round4(n: number): number {
  return Math.round(n * 1e4) / 1e4;
}
