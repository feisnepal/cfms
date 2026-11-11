/**
 * Feature clipboard — pure rules for the toolbar Copy / Paste.
 *
 * Copy takes features (with their attributes) out of one layer; Paste puts them
 * into another *at exactly the same coordinates*. What "not violating the
 * target's rules" means is decided here, in one place:
 *
 *   - sub-areas: polygons only, one name per sub-area, a valid category. The
 *     server additionally clips to the forest and subtracts existing sub-areas
 *     (first created keeps the ground) — that trimming is the "cut" behaviour,
 *     and it is the server's, so the client never second-guesses it.
 *   - free-form imported layers (`other`, `roads`, `water`): the geometry types
 *     the layer's purpose allows.
 *   - everything else (blocks / compartments / sub-compartments, which must tile
 *     the boundary; read-only layers; the boundary; the user-group extent;
 *     activity features, which belong to a proposed activity) is not a paste
 *     target, and says why.
 *
 * Nothing here touches the network or the store.
 */
import type { GeoJSON } from 'geojson';
import * as turf from '@turf/turf';
import { allowedGeometryTypes, type GeometryType } from './purposeGeometryRules';
import { SUB_AREA_CATEGORIES, getSubAreaCategory, isExcludedCategory } from './subAreaCategories';
import type { SubAreaCreateBody } from './featurePasteApi';

// ---------------------------------------------------------------------------
// Clipboard payload
// ---------------------------------------------------------------------------

/**
 * Properties that describe *the source row*, not the feature: identity, sync
 * bookkeeping, per-feature styling and derived measurements. They are dropped on
 * copy so the pasted feature gets fresh ones instead of impersonating the
 * original (a duplicate id would make a later edit hit the wrong row).
 */
const STRIPPED_KEYS = new Set([
  'id', 'featureId', 'colorIndex', '_vectorClock',
  'style', 'style_fill', 'style_opacity',
  'created_at', 'updated_at',
  'area_hectares', 'area_sqm', 'length_m',
  'block_id', 'blockId', 'blockName', 'blockBreakdown', 'parent_block_id',
]);

export function cleanProperties(props: GeoJSON.GeoJsonProperties): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(props ?? {})) {
    if (STRIPPED_KEYS.has(k) || k.startsWith('geo_')) continue;
    if (v === undefined) continue;
    out[k] = v;
  }
  return out;
}

const SINGLE_TYPES = new Set(['Point', 'LineString', 'Polygon']);

/** Multi* / GeometryCollection → one feature per single-part geometry. */
export function explodeFeature(feature: GeoJSON.Feature): GeoJSON.Feature[] {
  const g = feature.geometry;
  if (!g) return [];
  const make = (geometry: GeoJSON.Geometry): GeoJSON.Feature => ({
    type: 'Feature',
    geometry,
    properties: { ...(feature.properties ?? {}) },
  });
  switch (g.type) {
    case 'MultiPoint': return g.coordinates.map((c) => make({ type: 'Point', coordinates: c }));
    case 'MultiLineString': return g.coordinates.map((c) => make({ type: 'LineString', coordinates: c }));
    case 'MultiPolygon': return g.coordinates.map((c) => make({ type: 'Polygon', coordinates: c }));
    case 'GeometryCollection':
      return g.geometries.flatMap((sub) => explodeFeature(make(sub)));
    default:
      return SINGLE_TYPES.has(g.type) ? [make(g)] : [];
  }
}

/**
 * Snapshot features for the clipboard: deep-copied, attribute-cleaned,
 * single-part, and stripped of empty geometry. `dropped` counts the inputs that
 * had no usable geometry so the toast can say so.
 */
export function toClipboardFeatures(
  features: readonly GeoJSON.Feature[],
): { features: GeoJSON.Feature[]; dropped: number } {
  const out: GeoJSON.Feature[] = [];
  let dropped = 0;
  for (const f of features) {
    const parts = explodeFeature(JSON.parse(JSON.stringify(f)) as GeoJSON.Feature);
    if (parts.length === 0) { dropped += 1; continue; }
    for (const part of parts) {
      out.push({ ...part, properties: cleanProperties(part.properties) });
    }
  }
  return { features: out, dropped };
}

export function geometryKind(feature: GeoJSON.Feature): GeometryType | null {
  const t = feature.geometry?.type;
  return t === 'Point' || t === 'LineString' || t === 'Polygon' ? t : null;
}

// ---------------------------------------------------------------------------
// Target rules
// ---------------------------------------------------------------------------

export type PasteTarget =
  | { kind: 'builtin'; id: string }
  | { kind: 'imported'; id: number; purpose: string };

export type PasteIssueCode =
  | 'empty_clipboard'
  | 'no_target'
  | 'structure_locked'
  | 'layer_not_pastable'
  | 'purpose_not_pastable'
  | 'geometry_mismatch';

export interface PasteIssue {
  code: PasteIssueCode;
  params?: Record<string, string>;
}

/** Imported-layer purposes with no topology of their own. */
export const PASTABLE_IMPORT_PURPOSES: ReadonlySet<string> = new Set(['other', 'roads', 'water']);

/** Why a built-in layer cannot take a paste (i18n suffix), or null when it can. */
const BUILTIN_BLOCK_REASON: Record<string, PasteIssueCode> = {
  boundary: 'layer_not_pastable',
  blocks: 'layer_not_pastable',
  compartments: 'layer_not_pastable',
  sub_compartments: 'layer_not_pastable',
  user_group: 'layer_not_pastable',
  sample_plots: 'layer_not_pastable',
  stem_mapping: 'layer_not_pastable',
  fieldbook: 'layer_not_pastable',
  activity_features: 'layer_not_pastable',
};

function kindsOf(features: readonly GeoJSON.Feature[]): GeometryType[] {
  const seen = new Set<GeometryType>();
  for (const f of features) {
    const k = geometryKind(f);
    if (k) seen.add(k);
  }
  return [...seen];
}

/**
 * Can `features` be pasted into `target` right now? Returns the first reason it
 * cannot, or null. The reason's `code` maps to `editing.paste.reason.<code>`.
 */
export function pasteTargetIssue(
  target: PasteTarget | null,
  features: readonly GeoJSON.Feature[],
  opts: { structureLocked: boolean; layerLocked?: boolean },
): PasteIssue | null {
  if (features.length === 0) return { code: 'empty_clipboard' };
  if (!target) return { code: 'no_target' };
  if (opts.structureLocked || opts.layerLocked) return { code: 'structure_locked' };

  if (target.kind === 'builtin') {
    if (target.id === 'sub_areas') {
      const bad = kindsOf(features).filter((k) => k !== 'Polygon');
      return bad.length ? { code: 'geometry_mismatch', params: { have: bad.join('/'), need: 'Polygon' } } : null;
    }
    return { code: BUILTIN_BLOCK_REASON[target.id] ?? 'layer_not_pastable' };
  }

  if (!PASTABLE_IMPORT_PURPOSES.has(target.purpose)) return { code: 'purpose_not_pastable' };
  const allowed = allowedGeometryTypes(target.purpose);
  const bad = kindsOf(features).filter((k) => !allowed.includes(k));
  return bad.length
    ? { code: 'geometry_mismatch', params: { have: bad.join('/'), need: allowed.join('/') } }
    : null;
}

// ---------------------------------------------------------------------------
// Attribute preparation
// ---------------------------------------------------------------------------

/** `name`, else `name (copy)`, `name (copy 2)`, … — case-insensitive against `taken`. */
export function uniqueName(base: string, taken: ReadonlySet<string>): string {
  const clean = base.trim() || 'Feature';
  if (!taken.has(clean.toLowerCase())) return clean;
  let n = 1;
  for (;;) {
    const candidate = n === 1 ? `${clean} (copy)` : `${clean} (copy ${n})`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
    n += 1;
  }
}

/** The feature's own valid sub-area category, if it carries one. */
export function subAreaCategoryOf(props: Record<string, unknown> | null | undefined): string | null {
  const raw = props?.category;
  if (typeof raw !== 'string') return null;
  return SUB_AREA_CATEGORIES.some((c) => c.key === raw) ? raw : null;
}

/** Best human name a source feature carries, for naming its copy. */
export function sourceName(props: Record<string, unknown> | null | undefined, fallback: string): string {
  for (const key of ['name', 'block_name', 'compartment_code', 'label']) {
    const v = props?.[key];
    if (typeof v === 'string' && v.trim()) return v.trim();
  }
  return fallback;
}

/**
 * Sub-area create bodies for `features`. `categoryFor` resolves the category a
 * feature will get (its own, or the one the user picked for the ones without) —
 * a feature it returns null for is skipped, so the caller decides that up front.
 * Names are made unique against `takenNames`, including the ones in this batch.
 */
export function buildSubAreaBodies(
  features: readonly GeoJSON.Feature[],
  takenNames: ReadonlySet<string>,
  categoryFor: (feature: GeoJSON.Feature) => string | null,
  fallbackName: string,
): SubAreaCreateBody[] {
  const taken = new Set(takenNames);
  const bodies: SubAreaCreateBody[] = [];
  for (const f of features) {
    const category = categoryFor(f);
    if (!category || !f.geometry) continue;
    const props = (f.properties ?? {}) as Record<string, unknown>;
    const name = uniqueName(sourceName(props, getSubAreaCategory(category)?.label ?? fallbackName), taken);
    taken.add(name.toLowerCase());
    bodies.push({
      name,
      category,
      geometry: f.geometry,
      is_excluded: Boolean(props.is_excluded ?? props.isExcluded) || isExcludedCategory(category),
    });
  }
  return bodies;
}

let tempCounter = 0;

/** Features ready for an imported layer: fresh temp ids, source attributes kept. */
export function prepareImportedFeatures(features: readonly GeoJSON.Feature[]): GeoJSON.Feature[] {
  return features.map((f) => ({
    type: 'Feature',
    geometry: f.geometry,
    properties: {
      ...(f.properties ?? {}),
      featureId: `paste-${Date.now()}-${(tempCounter += 1)}-${Math.random().toString(36).slice(2, 7)}`,
    },
  }));
}

/** Area of a polygon feature in hectares (0 for non-polygons). */
export function areaHectares(feature: GeoJSON.Feature): number {
  const t = feature.geometry?.type;
  if (t !== 'Polygon' && t !== 'MultiPolygon') return 0;
  try { return turf.area(feature) / 10000; } catch { return 0; }
}

/**
 * True when the server kept materially less than was sent (>1 % lost). The
 * margin absorbs the small gap between the browser's spherical area and the
 * server's UTM area, so an untouched polygon is never reported as trimmed.
 */
export function wasTrimmed(sentHa: number, keptHa: number | undefined): boolean {
  if (keptHa == null || !(sentHa > 0)) return false;
  return keptHa < sentHa * 0.99;
}

/** Layer name for "Paste as new layer": `Source (copy)`, then `Source (copy) 2`, … */
export function newLayerName(sourceLabel: string, existingNames: readonly string[], suffix: string): string {
  const taken = new Set(existingNames.map((n) => n.toLowerCase()));
  const first = `${sourceLabel} ${suffix}`.trim();
  if (!taken.has(first.toLowerCase())) return first;
  for (let n = 2; ; n += 1) {
    const candidate = `${first} ${n}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
}
