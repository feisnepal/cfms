import type { Feature, Geometry } from 'geojson';
import type L from 'leaflet';
import {
  classifyVertices,
  coordAtIndex,
  LAYER_TYPES,
  type ClassifiableLayerType,
  type ClassifyOptions,
} from './vertexClassifier';
import { polygonRings } from './sharedEdgeIndex';

/**
 * vertexEditMask — V-3 (D1) render-only-editable vertex markers.
 *
 * After Geoman enables editing on a layer it instantiates a marker for EVERY
 * vertex of every layer in the group, so today a user can grab a locked
 * (outer-shell) vertex.  Rule 1 says locked vertices are NEVER rendered
 * (prevention over rejection).  This module turns a V-1 classification into
 * an "editable [lng,lat]" set and applies it to Geoman's live marker objects:
 *
 *   - vertex markers whose coordinate is editable stay visible + draggable;
 *   - every other vertex marker (locked shell / unshared interior) is hidden
 *     (opacity 0, interactive false, dragging disabled, `.pm-locked` class);
 *   - middle (add-vertex) markers between two locked vertices are hidden too,
 *     so no shell vertex can be introduced by dragging a midpoint.
 *
 * Marker→index resolution is coordinate-based (never index-based) because
 * Geoman marks every Leaflet latlng — including the closing ring duplicate —
 * while the classifier's flat indices drop it.  Both sides land on the SAME
 * physical coordinates, so a coordinate match is the robust bridge.
 */

type FeatureLike = { id?: string | number; properties?: { id?: string | number } } | Feature;

/**
 * Coordinate-key precision, in decimal degrees.
 *
 * MUST stay at 6.  The two sides of the match are produced differently:
 *   - the editable set comes from `layer.toGeoJSON()`, and Leaflet's
 *     `formatNum(num, undefined)` ROUNDS TO 6 DECIMALS (`core/Util.js`);
 *   - the marker side comes from `marker.getLatLng()`, which is the
 *     full-precision float.
 * At 9 decimals the same physical vertex keys as `85.762339000,27.413729000`
 * on one side and `85.762339184,27.413729172` on the other, so the sets never
 * intersect and EVERY marker is masked — the "vertex tool renders no handles
 * at all" bug (measured live 2026-08-19: expected 85 editable, rendered 0).
 * Rounding both sides to Leaflet's own 6 dp makes them agree.
 *
 * 1e-6° ≈ 0.11 m, far below the 1.0 m classification tolerance, so two
 * vertices that collide at this precision are already the same point as far
 * as the rules are concerned.
 */
const KEY_ROUND = 6;

function keyOf(lng: number, lat: number): string {
  return lng.toFixed(KEY_ROUND) + ',' + lat.toFixed(KEY_ROUND);
}

export function featureIdOf(f: FeatureLike | null | undefined): string {
  const id = (f as any)?.id ?? (f as any)?.properties?.id;
  return String(id ?? '');
}

export function featureGeometryOf(
  features: Array<{ id?: string | number; geometry: Geometry | null } | Feature> | null | undefined,
  featureId: string | number,
): Geometry | null {
  for (const f of features ?? []) {
    if (featureIdOf(f as FeatureLike) === String(featureId)) {
      return (f as any)?.geometry as Geometry | null;
    }
  }
  return null;
}

/** Live geometry of a registry layer (post-Geoman edits), if readible.
 *  `toGeoJSON(false)` skips Leaflet's default 6-decimal rounding so this
 *  geometry stays in the same precision space as the API payload it is
 *  classified against (see `snapshotOf` in geometryEditLifecycle.ts). */
export function liveGeometryOf(layer: L.Layer): Geometry | null {
  try {
    const json = (layer as any)?.toGeoJSON?.(false);
    return json?.geometry ?? null;
  } catch {
    return null;
  }
}

/** Real Bloom registry: editable flat indices → editable [lng, lat] coords. */
export function editableCoordinates(
  geom: Geometry | null | undefined,
  opts: ClassifyOptions,
): Array<[number, number]> {
  if (!geom) return [];
  const { editable } = classifyVertices(geom, opts);
  const out: Array<[number, number]> = [];
  for (const index of editable) {
    const c = coordAtIndex(geom, index);
    if (c) out.push([c[0], c[1]]);
  }
  return out;
}

/**
 * Parent-shell geometry for a structural-layer feature (V-3 / plan §1.5).
 * The shell is the COARSER feature that spatially contains it:
 * blocks → the forest boundary; compartments → their parent block;
 * sub-compartments → their parent compartment.  Spatial containment is used
 * because the layer payloads carry the parent *name* but not the parent id.
 * Anchors tried in order: the first exterior-ring vertex, then the ring
 * centroid — a strict point-in-polygon hit selects the shell.
 */
export function shellGeometryFor(
  layerType: ClassifiableLayerType,
  featureId: string | number,
  features: Array<{ id?: string | number; geometry: Geometry | null } | Feature> | null | undefined,
  shells: Array<{ id?: string | number; geometry: Geometry | null } | Feature> | null | undefined,
): Geometry | null {
  if (layerType === LAYER_TYPES.boundary) return null;
  const child = findFeature(features, featureId);
  const geom = (child as any)?.geometry as Geometry | null;
  if (!geom) return null;
  const candidates = shells ?? [];
  if (candidates.length === 0) return null;

  // 1. The declared parent — the only answer that cannot be wrong.  The
  //    compartment tree knows it structurally and `layerRegistry` records it
  //    as `parent_block_id`.
  const parentId = (child as any)?.properties?.parent_block_id
    ?? (child as any)?.parent_block_id
    ?? (child as any)?.parent;
  if (parentId != null && String(parentId) !== '') {
    const declared = findFeature(candidates, String(parentId));
    const g = (declared as any)?.geometry as Geometry | null;
    if (g) return g;
  }

  // 2. Fallback for payloads with no parent id: containment, CENTROID FIRST.
  //    Ordering matters.  A child's first ring vertex usually lies ON the
  //    shared boundary between two parents, where an even-odd ray cast is a
  //    coin flip — the old anchor-outer/candidate-inner loop therefore
  //    returned a neighbouring block for compartment C2 of बृन्दाबन (verified
  //    2026-08-19) and locked the wrong vertices.  The centroid is interior
  //    and decides correctly; a vertex is only a last resort.
  const anchors = containmentAnchors(geom); // [firstVertex, centroid]
  const ordered = anchors.length > 1 ? [anchors[1], anchors[0]] : anchors;
  for (const anchor of ordered) {
    for (const shell of candidates) {
      const g = (shell as any)?.geometry as Geometry | null;
      if (g && pointInPolygon(anchor[0], anchor[1], g)) return g;
    }
  }
  // No containing shell (a shell layer with no structure) → nothing locked by shell.
  return null;
}

/** Locate a feature by id in a feature list (id or properties.id). */
function findFeature(
  features: Array<{ id?: string | number; geometry: Geometry | null } | Feature> | null | undefined,
  featureId: string | number,
): FeatureLike | null {
  for (const f of features ?? []) {
    if (featureIdOf(f as FeatureLike) === String(featureId)) return f as FeatureLike;
  }
  return null;
}

/** Exterior anchors of a polygon: first vertex, then the first-ring centroid. */
function containmentAnchors(geom: Geometry): Array<[number, number]> {
  const out: Array<[number, number]> = [];
  const rings = polygonRings(geom);
  const outer = rings.find((r) => r.length >= 3);
  if (!outer) return out;
  out.push([outer[0][0], outer[0][1]]);
  let sx = 0;
  let sy = 0;
  for (const p of outer) {
    sx += p[0];
    sy += p[1];
  }
  out.push([sx / outer.length, sy / outer.length]);
  return out;
}

/** First vertex [lng, lat] of a polygon feature (anchor for containment). */
export function firstRingVertex(geom: Geometry): [number, number] | null {
  const rings = polygonRings(geom);
  const first = rings.find((r) => r.length >= 3);
  if (!first) return null;
  const p = first[0];
  return [p[0], p[1]];
}

/** Even-odd ray cast: is (x=lng, y=lat) inside this closed ring? */
export function pointInRing(
  x: number,
  y: number,
  ring: readonly ReadonlyArray<number>[],
): boolean {
  let inside = false;
  const n = ring.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const intersects = yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

/** Is (x=lng, y=lat) inside the polygon (exterior true, holes excluded)? */
export function pointInPolygon(x: number, y: number, geom: Geometry): boolean {
  if (geom.type !== 'Polygon' && geom.type !== 'MultiPolygon') return false;
  const polys = geom.type === 'MultiPolygon'
    ? geom.coordinates
    : [geom.coordinates];
  for (const rings of polys) {
    const outer = rings[0];
    if (!outer || outer.length < 3) continue;
    if (!pointInRing(x, y, outer)) continue;
    let inHole = false;
    for (let i = 1; i < rings.length; i++) {
      if (rings[i].length >= 3 && pointInRing(x, y, rings[i])) {
        inHole = true;
        break;
      }
    }
    if (!inHole) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Geoman marker masking
// ---------------------------------------------------------------------------

/** Minimal structural shape of a Geoman vertex / middle marker. */
interface GeomanMarker {
  getLatLng(): L.LatLng;
  _icon?: HTMLElement | null;
  _middleMarkerNext?: GeomanMarker | null;
  rightM?: GeomanMarker | null;
  leftM?: GeomanMarker | null;
  options?: Record<string, unknown>;
  dragging?: { enable?(): void; disable?(): void; enabled?(): boolean };
  setOpacity?(opacity: number): unknown;
  [k: string]: unknown;
}

function isGeomanMarker(value: unknown): value is GeomanMarker {
  return !!value && typeof (value as any).getLatLng === 'function';
}

/** Collect every vertex marker (incl. closing-dup) from Geoman's nested arrays. */
export function collectVertexMarkers(root: unknown): GeomanMarker[] {
  const out: GeomanMarker[] = [];
  const walk = (node: unknown): void => {
    if (Array.isArray(node)) {
      for (const child of node) walk(child);
    } else if (isGeomanMarker(node)) {
      out.push(node);
    }
  };
  walk(root);
  return out;
}

/**
 * Hide/show Geoman's vertex + linked middle markers against an editable
 * [lng, lat] set.  Returns the hidden/shown vertex counts.  Middle markers
 * between two editable corner markers stay visible (V-4 allows shared-edge
 * adds); any edge touching a locked vertex loses its midpoint so no shell
 * vertex can be introduced.
 */
export function maskVertexMarkers(
  layer: L.Layer,
  editable: Array<[number, number]> | null | undefined,
  /**
   * VR-5 shared-edge midpoint rule.  Given a midpoint's [lng, lat], is a
   * vertex allowed to be inserted there?
   *
   * Without this a midpoint was shown only when BOTH its corners were
   * editable, which made an auto-divided layer completely uneditable: an
   * equal-area division cuts with STRAIGHT segments, so every compartment
   * vertex is a cut endpoint lying on the parent shell, every corner is
   * locked, and no midpoint ever appeared either (measured on बृन्दाबन —
   * `shell == vertexCount` for all 8 compartments).
   *
   * The interior of a shared edge is not on the shell, so subdividing it
   * moves no locked vertex; the inserted vertex is shared-and-not-shell,
   * i.e. immediately editable.  That makes the cut reshapeable without
   * weakening rule 4.
   */
  isMidpointInsertable?: ((lng: number, lat: number) => boolean) | null,
): { masked: number; shown: number } {
  const empty = { masked: 0, shown: 0 };
  const pm = (layer as any)?.pm;
  if (!pm) return empty;
  const markers = collectVertexMarkers(pm._markers);
  if (markers.length === 0) return empty;

  const editableSet = new Set<string>();
  for (const [lng, lat] of editable ?? []) editableSet.add(keyOf(lng, lat));

  const enabledMap = new Map<GeomanMarker, boolean>();
  for (const m of markers) {
    const ll = m.getLatLng();
    const enabled = editableSet.has(keyOf(ll.lng, ll.lat));
    enabledMap.set(m, enabled);
    setCornerMarkerVisible(m, enabled);
  }

  let masked = 0;
  let shown = 0;
  for (const m of markers) {
    const enabled = enabledMap.get(m) ?? false;
    if (enabled) shown += 1; else masked += 1;
    const mid = m._middleMarkerNext;
    if (mid) {
      const rightEnabled = enabledMap.get(mid.rightM as GeomanMarker) ?? false;
      let visible = enabled && rightEnabled;
      if (!visible && isMidpointInsertable) {
        try {
          const ll = mid.getLatLng();
          visible = isMidpointInsertable(ll.lng, ll.lat);
        } catch {
          /* marker not mounted — leave hidden */
        }
      }
      setMiddleMarkerVisible(mid, visible);
    }
  }
  return { masked, shown };
}

function setCornerMarkerVisible(marker: GeomanMarker, visible: boolean): void {
  // Mutate in place — do NOT replace the object.  Leaflet builds `options` as
  // `Object.create(ClassDefaults)` (L.Util.setOptions), so a spread copy keeps
  // only the OWN properties and silently drops every inherited default (icon,
  // pane, riseOffset, autoPanPadding, …).
  setInteractive(marker, visible);
  try {
    marker.setOpacity?.(visible ? 1 : 0);
  } catch {
    /* leaflet marker may not be mounted */
  }
  if (marker._icon) {
    marker._icon.classList.toggle('pm-locked', !visible);
  }
  if (visible) {
    if (marker.dragging && marker.dragging.enable && marker.dragging.enabled && !marker.dragging.enabled()) {
      marker.dragging.enable();
    }
  } else if (marker.dragging && marker.dragging.disable) {
    marker.dragging.disable();
  }
}

/** Set `options.interactive` without discarding Leaflet's prototype defaults. */
function setInteractive(marker: GeomanMarker, visible: boolean): void {
  if (!marker.options) marker.options = {};
  marker.options.interactive = visible;
}

function setMiddleMarkerVisible(marker: GeomanMarker, visible: boolean): void {
  setInteractive(marker, visible);
  try {
    marker.setOpacity?.(visible ? 1 : 0);
  } catch {
    /* not mounted */
  }
  if (marker._icon) {
    marker._icon.classList.toggle('pm-locked', !visible);
  }
}