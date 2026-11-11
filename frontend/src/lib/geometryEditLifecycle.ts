import L from 'leaflet';
import type { Feature, Geometry } from 'geojson';
import { SharedEdgeIndex, SNAP_TOLERANCE_M } from './sharedEdgeIndex';
import { type SharedMoveResult, type SharedVertexChange } from './vertexSharedMove';
import { maskVertexMarkers } from './vertexEditMask';

/**
 * Production Geoman edit lifecycle (E2.2a/E2.2b).
 *
 * Replaces the E-0 spike harness with the full pipeline:
 *
 *   | Action         | Capture                          | Validate                       | Save                     |
 *   |----------------|----------------------------------|--------------------------------|--------------------------|
 *   | Vertex drag    | pm:markerdragstart (snapshot)    | pm:markerdragend (topology)    | pm:markerdragend (commit)|
 *   | Add vertex     | pm:vertexadded                   | immediate                      | immediate                |
 *   | Delete vertex  | pm:vertexremoved                 | immediate                      | immediate                |
 *
 * `pm:edit` fires continuously during a drag and NEVER triggers a POST
 * (that event name is the Geoman continuous-update signal).  A gesture's
 * *first* save fires on `pm:markerdragend`; a local topology rejection
 * (SharedEdgeIndex R6 mirror) or a server 409 TOPOLOGY_REJECTED reverts the
 * layer to its snapshot and surfaces a toast — never leaves the layer
 * mid-drag and never double-POSTs.
 *
 * The plan's literal `pm:editstart`/`pm:editend` events do not exist in
 * @geoman-io/leaflet-geoman-free 2.19; `pm:markerdragstart/end` are the
 * equivalent gesture boundaries (verified in the installed build).
 */

export interface GeomanEditOptions {
  /** POST the edited feature.  Return `ok:false` + `code` when rejected.
   *  V-2: `sharedMoves` (optional) is the propagation payload; the edited
   *  feature + every partner must be committed together.
   *  Selectionless V-3: `featureId` is the id of the ACTUALLY dragged feature
   *  (the layer whose marker the user released) — NOT the armed "primary". */
  commit: (
    feature: Feature,
    snapshot: Feature,
    sharedMove: SharedMoveResult | null | undefined,
    featureId: string,
  ) => Promise<CommitOutcome>;
  /** Local R6 pre-check mirror (null → skip). */
  topology?: SharedEdgeIndex | null;
  /** V-2 atomic shared-vertex move: compute the shared partners for the
   *  dragged coincident vertex.  When a non-null result comes back, the local
   *  pre-check runs against the PROPAGATED neighbour set (see computeSharedMoves)
   *  and the commit receives the shared_moves payload.  Only coincident-shared
   *  vertices propagate; mid-edge moves return null (R6 alone verifies them).
   *  `featureId` is the dragged feature's id. */
  sharedMove?: (feature: Feature, snapshot: Feature, featureId: string) => SharedMoveResult | null;
  /** V-4 (D4) shared-edge add/delete: compute the both-sides propagation for a
   *  vertex ADD or DELETE.  A vertex inserted on a shared edge is inserted on
   *  every same-level feature that owns that segment; a shared vertex deleted
   *  is deleted from every feature that owns it — so the two sides never stop
   *  sharing the vertex.  `blocked` refuses the gesture (the change would
   *  collapse a partner ring).  `featureId` is the edited feature's id. */
  sharedVertexChange?: (
    feature: Feature,
    snapshot: Feature,
    featureId: string,
  ) => SharedVertexChange | null;
  /** Called when a rejection is surfaced to the user (toast). */
  onReject: (code: string, message: string) => void;
  /** Called after a successful commit (refresh geometry version). */
  onCommitted?: () => void;
  /** Called with the snapshot right after it is captured (undo entry). */
  onSnapshot?: (snapshot: Feature) => void;
  /** V-3 (D1) render-only-editable markers: return the editable [lng, lat]
   *  coordinate set CURRENT for `layer` (a classification of its live
   *  geometry).  `null` → leave all Geoman markers visible (no mask).  Locked
   *  vertices + their midpoints get no marker, so a forbidden grab cannot even
   *  be attempted.  Re-applied after every marker re-creation (arm, rejection
   *  restore, vertex add/remove). */
  mask?: (layer: L.Layer, featureId: string) => Array<[number, number]> | null;
  /** VR-5 shared-edge midpoint rule: may a vertex be inserted at this
   *  midpoint?  Lets the interior of a shared edge be subdivided even when
   *  both its endpoints are locked shell vertices — see `maskVertexMarkers`. */
  midpointInsertable?: (layer: L.Layer, featureId: string, lng: number, lat: number) => boolean;
}

export interface CommitOutcome {
  ok: boolean;
  status?: number;
  code?: string;
  message?: string;
}

const TOPOLOGY_REJECTED = 'TOPOLOGY_REJECTED';
const STRUCTURE_LOCKED = 'structure_locked';
const MAP_LIFECYCLE = 'map_lifecycle';
const VERTEX_CHANGE_BLOCKED = 'VERTEX_CHANGE_BLOCKED';

/** Geoman options for the VERTEX tool.
 *
 *  `draggable: false` is deliberate: Geoman's real option name is `draggable`
 *  (not `drag`) and it defaults to TRUE, so the vertex tool used to allow a
 *  whole-feature body drag as well.  That drag fires `pm:dragstart/pm:dragend`
 *  — events the vertex lifecycle does not listen for — so the shape moved on
 *  screen and was never committed (another "moved but not saved"), and it blurred
 *  the vertex tool into the move tool.  Vertex = vertices only; whole-feature
 *  movement belongs to the move tool (`enableMoveGesture`). */
const VERTEX_EDIT_PM_OPTIONS = {
  draggable: false,
  snap: true,
  allowSelfIntersection: false,
} as const;

/** Convert a GeoJSON geometry to the latlng structure a Leaflet path expects. */
export function geometryToLatLngs(
  geometry: Geometry | null | undefined,
): L.LatLng[] | L.LatLng[][] | L.LatLng[][][] {
  if (!geometry) return [];
  switch (geometry.type) {
    case 'Polygon':
      return (geometry.coordinates as number[][][]).map((ring) =>
        ring.map(([lng, lat]) => L.latLng(lat, lng)));
    case 'MultiPolygon':
      return (geometry.coordinates as number[][][][]).map((poly) =>
        poly.map((ring) => ring.map(([lng, lat]) => L.latLng(lat, lng))));
    case 'LineString':
      return (geometry.coordinates as number[][]).map(([lng, lat]) => L.latLng(lat, lng));
    case 'MultiLineString':
      return (geometry.coordinates as number[][][]).map((line) =>
        line.map(([lng, lat]) => L.latLng(lat, lng)));
    case 'Point':
      return [L.latLng(geometry.coordinates[1], geometry.coordinates[0])];
    default:
      return [];
  }
}

/** Restore a registry layer to a snapshot Feature (lat/lng coords back). */
export function restoreLayerFromSnapshot(layer: L.Layer, snapshot: Feature): void {
  const path = layer as any;
  if (typeof path.setLatLngs === 'function') {
    try {
      path.setLatLngs(geometryToLatLngs(snapshot.geometry));
      return;
    } catch {
      /* fall through to setLatLng */
    }
  }
  if (typeof path.setLatLng === 'function' && snapshot.geometry?.type === 'Point') {
    const [lng, lat] = snapshot.geometry.coordinates;
    path.setLatLng(L.latLng(lat, lng));
  }
}

/**
 * Capture a layer's geometry LOSSLESSLY.
 *
 * `toGeoJSON()` with no argument rounds every coordinate to 6 decimals
 * (Leaflet's `formatNum` default) — ~0.11 m at these latitudes.  Passing
 * `false` skips that processing entirely; Leaflet documents the value for
 * precisely this purpose ("can be useful to avoid round-off errors").
 *
 * The rounding was not cosmetic.  The edited geometry was quantised while its
 * neighbours came from the API at full precision, so an exactly-shared edge
 * turned into two edges up to ~5 cm apart that genuinely zig-zag across each
 * other.  R6's proper-crossing test then found real crossings and refused
 * every shared-vertex drag with "overlaps an adjacent feature" (live report
 * 2026-08-19).  It also meant each accepted edit wrote a 6 dp-quantised
 * polygon back to the database, degrading the geometry a little every time.
 */
function snapshotOf(layer: L.Layer): Feature | null {
  try {
    const f = (layer as any).toGeoJSON?.(false) as Feature;
    return f?.geometry ? f : null;
  } catch {
    return null;
  }
}

/**
 * Enable production vertex editing on a registry-resolved layer.
 * Returns a cleanup function.
 *
 * Selectionless V-3: `registry` must expose `forEach` and cover the ACTIVE
 * layer's features (MapWorkspace builds a layer-scoped view of the global
 * registry — never arm the global registry or Geoman springs markers on every
 * builtin/imported layer at once).  Every armed feature gets markers + mask;
 * dragging a marker commits THAT feature's geometry (the layer whose marker
 * was released), and shared coincident vertices propagate atomically across
 * same-level neighbours.  No manual feature selection is required.
 */
export function enableGeometryEdit(
  map: L.Map | null,
  registry: { get(fid: string): L.Layer | undefined; forEach?(cb: (id: string, layer: L.Layer) => void): void },
  featureId: string,
  opts: GeomanEditOptions,
): () => void {
  const noop = () => {};
  if (!map || !featureId) return noop;
  const layer = registry.get(featureId);
  if (!layer) return noop;

  // Enable editing on ALL registered layers in the active layer group simultaneously
  // so shared boundary vertices can be seen and adjusted across adjacent features.
  const allLayers: Array<{ id: string; layer: L.Layer }> = [];
  if (typeof registry.forEach === 'function') {
    registry.forEach((id, l) => {
      allLayers.push({ id, layer: l });
      const pm = (l as any).pm;
      if (pm) {
        if (pm.enabled()) pm.disable();
        pm.enable(VERTEX_EDIT_PM_OPTIONS);
      }
    });
  } else {
    const pmLayer: any = layer as any;
    if (pmLayer.pm) pmLayer.pm.disable();
    pmLayer.pm.enable(VERTEX_EDIT_PM_OPTIONS);
    allLayers.push({ id: featureId, layer });
  }

  // V-3 (D1): after Geoman instantiates every vertex marker, hide the locked
  // ones (and their midpoints) for every armed layer, per its own editable set.
  const applyMask = (entry: { id: string; layer: L.Layer }): void => {
    if (!opts.mask) return;
    try {
      const editable = opts.mask(entry.layer, entry.id);
      if (editable) {
        maskVertexMarkers(
          entry.layer,
          editable,
          opts.midpointInsertable
            ? (lng, lat) => opts.midpointInsertable!(entry.layer, entry.id, lng, lat)
            : null,
        );
      }
    } catch (err) {
      console.warn('[GeometryEdit] vertex mask failed:', err);
    }
  };
  for (const entry of allLayers) applyMask(entry);

  // Arm-time baseline snapshot per layer: every gesture — vertex add, vertex
  // delete, or drag — has a revert target keyed to the layer it happened on.
  // Add/remove have no `pm:markerdragstart`, so without this a rejected
  // add/delete could not be reverted (the symptom: "added vertex can not be
  // saved"), and a drag on a NON-primary armed layer must revert ITS geometry.
  const baseline = new Map<string, Feature | null>();
  for (const entry of allLayers) {
    const snap = snapshotOf(entry.layer);
    baseline.set(entry.id, snap);
    if (snap) opts.onSnapshot?.(snap);
  }

  interface StrokeState {
    entryId: string | null;
    snapshot: Feature | null;
    inFlight: boolean;
    committedThisStroke: boolean;
    rejected: boolean;
    // V-2: the shared-move payload for the CURRENT gesture (computed once on
    // drag-release from snapshot→post-drag geometry; cleared after commit).
    pendingSharedMove: SharedMoveResult | null;
  }

  const stroke: StrokeState = { entryId: null, snapshot: null, inFlight: false, committedThisStroke: false, rejected: false, pendingSharedMove: null };
  let gestureActive = false;

  const armStrokeFor = (entry: { id: string; layer: L.Layer }): void => {
    if (stroke.entryId === entry.id && stroke.snapshot) return;
    stroke.entryId = entry.id;
    stroke.snapshot = snapshotOf(entry.layer) ?? baseline.get(entry.id) ?? null;
    if (stroke.snapshot) opts.onSnapshot?.(stroke.snapshot);
  };

  const reject = (entry: { id: string; layer: L.Layer }, code: string, message: string) => {
    stroke.rejected = true;
    stroke.pendingSharedMove = null;
    const snapshot = stroke.entryId === entry.id ? stroke.snapshot : baseline.get(entry.id);
    if (snapshot) {
      try {
        for (const { layer: l } of allLayers) {
          const pm = (l as any).pm;
          if (pm?.enabled()) pm.disable();
        }
        restoreLayerFromSnapshot(entry.layer, snapshot);
        for (const e of allLayers) {
          const pm = (e.layer as any).pm;
          if (pm) {
            pm.enable(VERTEX_EDIT_PM_OPTIONS);
          }
        }
        // Geoman just re-created every marker → re-apply the locked-mask.
        for (const e of allLayers) applyMask(e);
      } catch (err) {
        console.error('[GeometryEdit] snapshot restore failed:', err);
      }
    }
    opts.onReject(code, message);
  };

  const save = async (entry: { id: string; layer: L.Layer }) => {
    if (stroke.inFlight || stroke.committedThisStroke || stroke.rejected) return;
    const feature = snapshotOf(entry.layer);
    if (!feature?.geometry) return;
    stroke.committedThisStroke = true;
    stroke.inFlight = true;
    try {
      // V-2/V-4: the partners were computed by handleDragEnd (drag) or
      // handleVertexChange (add/delete) — both use the same batch payload.
      const outcome = await opts.commit(
        feature,
        (stroke.entryId === entry.id ? stroke.snapshot : baseline.get(entry.id)) as Feature,
        stroke.pendingSharedMove,
        entry.id,
      );
      if (outcome.ok) {
        stroke.pendingSharedMove = null;
        stroke.snapshot = feature;
        stroke.committedThisStroke = false;
        // VR-7 mitigation for D-5.  Geoman re-runs `_initMarkers()` on several
        // internal paths and the markers come back UNMASKED; the mask was only
        // re-applied on arm, on rejection-restore, and on vertex add/remove.
        // A committed drag left a window in which a locked vertex could be
        // grabbed.  The window is small (the effect re-arms once the layer data
        // refetches) and the VR-3 server guard would refuse the write anyway —
        // but closing it costs one line, so there is no reason to leave it.
        for (const e of allLayers) applyMask(e);
        opts.onCommitted?.();
       } else if (outcome.code === TOPOLOGY_REJECTED) {
        // Keep the pre-gesture (arm-time) snapshot as the revert target — do NOT
        // overwrite it with the rejected post-edit geometry (doing so would
        // "accept" a rejected add/remove by restoring the edited shape).
        reject(entry, TOPOLOGY_REJECTED, outcome.message || 'Edit rejected: overlaps or creates a gap.');
      } else if (outcome.code === STRUCTURE_LOCKED) {
        reject(entry, STRUCTURE_LOCKED, outcome.message || 'Forest structure is locked.');
      } else if (outcome.code === MAP_LIFECYCLE) {
        reject(entry, MAP_LIFECYCLE, outcome.message || 'Calculation is not editable right now.');
      } else {
        reject(entry, outcome.code || 'SAVE_FAILED', outcome.message || 'Save failed — please retry.');
      }
    } catch (err: any) {
      stroke.rejected = true;
      opts.onReject('NETWORK', err?.message || 'Network error — edit not saved.');
    } finally {
      stroke.inFlight = false;
    }
  };

  // Continuous pm:edit — never POST, just keep the gesture flagged so we know
  // the stroke is still being worked on.
  const handleEdit = () => { gestureActive = true; };

  // Gesture start — capture snapshot BEFORE the first vertex moves.
  const handleDragStart = (entry: { id: string; layer: L.Layer }) => {
    armStrokeFor(entry);
    gestureActive = true;
  };

  // Drag release — local R6 pre-check, then commit (one POST per release).
  // `entry` is bound per layer, so a drag on ANY armed feature commits that
  // feature (selectionless: the dragged marker IS the intent).
  const handleDragEnd = (entry: { id: string; layer: L.Layer }) => {
    gestureActive = false;
    stroke.committedThisStroke = false;
    armStrokeFor(entry);
    const feature = snapshotOf(entry.layer);
    if (!feature?.geometry) return;

    // V-2: compute the shared-vertex propagation FIRST.  When a coincident
    // shared vertex moved, the local pre-check must run against the
    // PROPAGATED neighbour set (neighbours that will move with us) — otherwise
    // it would self-reject the very drag R6 is supposed to accept.
    let checkIndex = opts.topology ?? null;
    let checkSnapshot = stroke.snapshot?.geometry ?? null;
    stroke.pendingSharedMove = null;
    if (opts.sharedMove) {
      const result = opts.sharedMove(feature, stroke.snapshot as Feature, entry.id);
      if (result) {
        stroke.pendingSharedMove = result;
        checkIndex = new SharedEdgeIndex(result.propagatedFeatures);
        checkSnapshot = stroke.snapshot?.geometry ?? null;
      }
    }

    if (checkIndex) {
      const verdict = checkIndex.validate(feature.geometry, {
        excludeId: entry.id,
        snapshot: checkSnapshot,
      });
      if (!verdict.ok) {
        stroke.pendingSharedMove = null;
        reject(entry, verdict.witness === 'OVERLAP' ? TOPOLOGY_REJECTED : 'TOPOLOGY_GAP',
          verdict.message || 'Edit rejected by topology check.');
        return;
      }
    }
    void save(entry);
  };

  // Immediate save on vertex add/remove (per design table).  Geoman just
  // created/removed a marker → re-apply the locked-mask on that layer so a
  // newly added shell vertex is hidden immediately.
  const handleVertexChange = (entry: { id: string; layer: L.Layer }) => {
    gestureActive = true;
    stroke.committedThisStroke = false;
    stroke.pendingSharedMove = null;
    // Revert target for add/remove = the arm-time baseline (no drag-start).
    stroke.entryId = entry.id;
    stroke.snapshot = baseline.get(entry.id) ?? snapshotOf(entry.layer) ?? null;
    applyMask(entry);

    // V-4 (D4): an add/delete on a SHARED edge must be applied to both sides in
    // the same transaction, otherwise the sides stop sharing that vertex and
    // the next drag tears the edge open.  Same batch payload as V-2.
    const feature = snapshotOf(entry.layer);
    let checkIndex = opts.topology ?? null;
    if (feature?.geometry && opts.sharedVertexChange && stroke.snapshot) {
      const change = opts.sharedVertexChange(feature, stroke.snapshot as Feature, entry.id);
      if (change?.blocked) {
        reject(entry, VERTEX_CHANGE_BLOCKED,
          change.kind === 'remove'
            ? 'Cannot delete this shared vertex — the neighbouring unit would collapse.'
            : 'Cannot add a vertex here — the neighbouring unit would collapse.');
        return;
      }
      if (change?.propagation) {
        stroke.pendingSharedMove = change.propagation;
        checkIndex = new SharedEdgeIndex(change.propagation.propagatedFeatures);
      }
    }

    // Topology pre-check on the propagated set (an add/delete that opens a gap
    // against a neighbour is refused locally instead of round-tripping).
    if (feature?.geometry && checkIndex) {
      const verdict = checkIndex.validate(feature.geometry, {
        excludeId: entry.id,
        snapshot: stroke.snapshot?.geometry ?? null,
      });
      if (!verdict.ok) {
        stroke.pendingSharedMove = null;
        reject(entry, verdict.witness === 'OVERLAP' ? TOPOLOGY_REJECTED : 'TOPOLOGY_GAP',
          verdict.message || 'Edit rejected by topology check.');
        return;
      }
    }
    void save(entry);
  };

  // Attach pm:markerdragend and vertex events to ALL layers so that moving vertices
  // on any active layer triggers validation and saves.  Per-layer closures keep
  // the exact `off` reference for cleanup AND remember which feature a gesture
  // belongs to (selectionless arming — the dragged layer is the source of truth).
  const handlers = new Map<L.Layer, { dragStart: () => void; dragEnd: () => void; vertexAdded: () => void; vertexRemoved: () => void }>();
  for (const entry of allLayers) {
    const dragStart = () => handleDragStart(entry);
    const dragEnd = () => handleDragEnd(entry);
    const vertexAdded = () => handleVertexChange(entry);
    const vertexRemoved = () => handleVertexChange(entry);
    entry.layer.on('pm:markerdragstart', dragStart);
    entry.layer.on('pm:markerdragend', dragEnd);
    entry.layer.on('pm:vertexadded', vertexAdded);
    entry.layer.on('pm:vertexremoved', vertexRemoved);
    handlers.set(entry.layer, { dragStart, dragEnd, vertexAdded, vertexRemoved });
  }

  map.on('pm:edit', handleEdit);

  return () => {
    map.off('pm:edit', handleEdit);
    for (const entry of allLayers) {
      const h = handlers.get(entry.layer);
      if (h) {
        entry.layer.off('pm:markerdragstart', h.dragStart);
        entry.layer.off('pm:markerdragend', h.dragEnd);
        entry.layer.off('pm:vertexadded', h.vertexAdded);
        entry.layer.off('pm:vertexremoved', h.vertexRemoved);
      }
      try {
        const pm = (entry.layer as any).pm;
        if (pm?.enabled()) pm.disable();
      } catch {
        /* leaflet layer may already be destroyed */
      }
    }
  };
}

/** Snapshot capture for a plain registry layer (exported for tests). */
export function captureSnapshot(layer: L.Layer): Feature | null {
  return snapshotOf(layer);
}

export interface MoveGestureOptions {
  /** POST the moved feature.  Return `ok:false` + `code` when rejected. */
  commit: (feature: Feature, snapshot: Feature) => Promise<CommitOutcome>;
  /** Local R6 pre-check mirror (null → skip). */
  topology?: SharedEdgeIndex | null;
  /** Called when a rejection is surfaced to the user (toast). */
  onReject: (code: string, message: string) => void;
  /** Called after a successful commit (refresh geometry version). */
  onCommitted?: () => void;
  /** Called with the snapshot right after it is captured (undo entry). */
  onSnapshot?: (snapshot: Feature) => void;
}

/**
 * UE-2.1 — whole-feature MOVE gesture (Geoman body drag).
 *
 * Enables drag ONLY (no vertex markers) on the one registry-resolved layer;
 * snapshot at arm/dragstart time, commit ONCE on `pm:dragend` via the same
 * commit contract as `enableGeometryEdit`.  A rejected drag reverts the layer
 * to its snapshot and surfaces a toast.
 */
export function enableMoveGesture(
  map: L.Map | null,
  registry: { get(fid: string): L.Layer | undefined },
  featureId: string,
  opts: MoveGestureOptions,
): () => void {
  const noop = () => {};
  const mark = (s: string) => {
    if (typeof document !== 'undefined' && document.documentElement) {
      document.documentElement.dataset.moveGesture = s;
    }
  };
  if (!map || !featureId) return noop;
  const layer = registry.get(featureId);
  if (!layer) { mark('no-layer'); return noop; }

  const pmLayer: any = layer as any;
  if (!pmLayer?.pm) { mark('no-pm'); return noop; }

  // MOVE is a WHOLE-FEATURE gesture — it must NOT turn into vertex editing.
  // `pm.enable({draggable:true})` is Geoman's *edit* mode: it renders a marker
  // on every vertex (plus middle markers), so the move tool looked like the
  // vertex tool AND exposed locked outer-shell vertices that the V-3 mask only
  // hides on the vertex path.  `enableLayerDrag()` is the drag-only API: body
  // drag, zero vertex markers.  (Fallback kept for older Geoman builds.)
  const armDrag = () => {
    if (typeof pmLayer.pm.enableLayerDrag === 'function') {
      if (pmLayer.pm.enabled?.()) pmLayer.pm.disable();
      pmLayer.pm.enableLayerDrag();
      mark('pm-enabled:layerdrag');
      return;
    }
    if (pmLayer.pm.enabled()) pmLayer.pm.disable();
    pmLayer.pm.enable({ draggable: true, snap: true });
    mark('pm-enabled:drag=' + !!pmLayer.pm.options?.draggable);
  };
  const disarmDrag = () => {
    if (typeof pmLayer.pm.disableLayerDrag === 'function') {
      pmLayer.pm.disableLayerDrag();
      return;
    }
    if (pmLayer.pm?.enabled()) pmLayer.pm.disable();
  };
  armDrag();

  let snapshot: Feature | null = null;
  const armSnapshot = () => {
    if (!snapshot) {
      snapshot = snapshotOf(layer);
      if (snapshot) opts.onSnapshot?.(snapshot);
    }
  };
  armSnapshot();

  let inFlight = false;
  let committedThisStroke = false;
  let rejected = false;

  const reject = (code: string, message: string) => {
    rejected = true;
    try {
      disarmDrag();
      if (snapshot) restoreLayerFromSnapshot(layer, snapshot);
      armDrag();
    } catch (err) {
      console.error('[Move] snapshot restore failed:', err);
    }
    opts.onReject(code, message);
  };

  const save = async () => {
    if (inFlight || committedThisStroke || rejected) return;
    const feature = snapshotOf(layer);
    if (!feature?.geometry) return;
    committedThisStroke = true;
    inFlight = true;
    try {
      const outcome = await opts.commit(feature, snapshot as Feature);
      if (outcome.ok) {
        snapshot = feature;
        committedThisStroke = false;
        opts.onCommitted?.();
      } else if (outcome.code === TOPOLOGY_REJECTED) {
        reject(TOPOLOGY_REJECTED, outcome.message || 'Move rejected: overlaps or creates a gap.');
      } else if (outcome.code === STRUCTURE_LOCKED) {
        reject(STRUCTURE_LOCKED, outcome.message || 'Forest structure is locked.');
      } else if (outcome.code === MAP_LIFECYCLE) {
        reject(MAP_LIFECYCLE, outcome.message || 'Calculation is not editable right now.');
      } else {
        reject(outcome.code || 'SAVE_FAILED', outcome.message || 'Save failed — please retry.');
      }
    } catch (err: any) {
      rejected = true;
      opts.onReject('NETWORK', err?.message || 'Network error — move not saved.');
    } finally {
      inFlight = false;
    }
  };

  const handleDragStart = () => { mark('dragstart'); armSnapshot(); };
  const handleDragEnd = () => {
    committedThisStroke = false;
    const feature = snapshotOf(layer);
    mark('dragend:geom=' + !!feature?.geometry);
    if (!feature?.geometry) return;
    if (opts.topology) {
      const verdict = opts.topology.validate(feature.geometry, {
        excludeId: featureId,
        snapshot: snapshot?.geometry ?? null,
      });
      if (!verdict.ok) {
        reject(verdict.witness === 'OVERLAP' ? TOPOLOGY_REJECTED : 'TOPOLOGY_GAP',
          verdict.message || 'Move rejected by topology check.');
        return;
      }
    }
    void save();
  };

  pmLayer.on('pm:dragstart', handleDragStart);
  pmLayer.on('pm:dragend', handleDragEnd);

  return () => {
    pmLayer.off('pm:dragstart', handleDragStart);
    pmLayer.off('pm:dragend', handleDragEnd);
    try {
      disarmDrag();
    } catch {
      /* leaflet layer may already be destroyed */
    }
  };
}

/** Per-gesture re-arm (exported for tests). */
export const SNAP_TOLERANCE = SNAP_TOLERANCE_M;

export { TOPOLOGY_REJECTED };
