/**
 * A layer's symbology as the map draws it, for exports (KML styles, a GeoPackage's QGIS style).
 *
 * The map owns the rules that decide a feature's look (palette colour, the user's layer style, a thematic renderer, a per-feature override, the
 * layer opacity). Rather than copy those rules, the map registers its own style functions here and an export asks them: what is drawn is what is
 * written. The selection highlight is left out (`isProbing`), a highlighted feature must not be exported yellow.
 */
import { STYLE_PRESETS } from './layerStyles';

/** One feature's look, colours as '#rrggbb' and opacities 0..1. */
export interface FeatureSymbol {
  fill: string;
  fillOpacity: number;
  stroke: string;
  strokeOpacity: number;
  /** stroke width in pixels */
  weight: number;
  /** Leaflet dash pattern ("5, 5") or null for a solid line */
  dashArray: string | null;
  /** point radius in pixels */
  radius: number;
}

type PathStyle = Record<string, any>;
type StyleFn = (feature: GeoJSON.Feature) => PathStyle | undefined | null;

const resolvers = new Map<string, StyleFn>();
let probing = false;

/** True while an export asks the map for a style: the map must not apply the selection highlight. */
export const isProbing = (): boolean => probing;

export function registerStyleResolvers(next: Record<string, StyleFn>): void {
  resolvers.clear();
  for (const [key, fn] of Object.entries(next)) resolvers.set(key, fn);
}

const NAMED: Record<string, string> = {
  black: '#000000', white: '#ffffff', red: '#ff0000', green: '#008000', blue: '#0000ff', yellow: '#ffff00', orange: '#ffa500',
  purple: '#800080', brown: '#a52a2a', gray: '#808080', grey: '#808080', cyan: '#00ffff', magenta: '#ff00ff', pink: '#ffc0cb',
};

const two = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');

/** '#rgb' / '#rrggbb' / '#rrggbbaa' / rgb() / rgba() / a common colour name -> '#rrggbb' plus any alpha the text carried. */
export function parseColour(text: unknown, fallback = '#3388ff'): { hex: string; alpha: number } {
  const s = String(text ?? '').trim().toLowerCase();
  if (NAMED[s]) return { hex: NAMED[s], alpha: 1 };
  let m = /^#([0-9a-f]{3})$/.exec(s);
  if (m) return { hex: '#' + m[1].split('').map((c) => c + c).join(''), alpha: 1 };
  m = /^#([0-9a-f]{6})([0-9a-f]{2})?$/.exec(s);
  if (m) return { hex: '#' + m[1], alpha: m[2] ? parseInt(m[2], 16) / 255 : 1 };
  m = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+%?))?\s*\)$/.exec(s);
  if (m) {
    const a = m[4] == null ? 1 : m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]);
    return { hex: '#' + two(+m[1]) + two(+m[2]) + two(+m[3]), alpha: a };
  }
  return { hex: fallback, alpha: 1 };
}

const num = (v: unknown, d: number): number => (typeof v === 'number' && Number.isFinite(v) ? v : d);

/** Leaflet path options -> a symbol. Leaflet's own defaults fill the gaps (stroke #3388ff, weight 3, opacity 1, fill opacity 0.2). */
export function symbolFromPathStyle(style: PathStyle | undefined | null): FeatureSymbol {
  const st = style ?? {};
  const stroke = parseColour(st.color, '#3388ff');
  const fill = parseColour(st.fillColor ?? st.color, stroke.hex);
  const noStroke = st.stroke === false;
  const noFill = st.fill === false;
  return {
    fill: fill.hex,
    fillOpacity: noFill ? 0 : num(st.fillOpacity, 0.2) * fill.alpha,
    stroke: stroke.hex,
    strokeOpacity: noStroke ? 0 : num(st.opacity, 1) * stroke.alpha,
    weight: noStroke ? 0 : num(st.weight, 3),
    dashArray: st.dashArray ? String(st.dashArray) : null,
    radius: num(st.radius, 6),
  };
}

/** The look of `feature` on the map for `layerKey` ('blocks', 'activity_features', 'imported:12' ...). Falls back to the layer's preset. */
export function symbolFor(layerKey: string, feature: GeoJSON.Feature, presetKey?: string): FeatureSymbol {
  const fn = resolvers.get(layerKey);
  let style: PathStyle | undefined | null;
  if (fn) {
    probing = true;
    try {
      style = fn(feature);
    } catch (err) {
      console.warn('layer symbology: the map could not give a style for', layerKey, err);
    } finally {
      probing = false;
    }
  }
  if (!style && presetKey) style = (STYLE_PRESETS as Record<string, PathStyle>)[presetKey];
  return symbolFromPathStyle(style);
}
