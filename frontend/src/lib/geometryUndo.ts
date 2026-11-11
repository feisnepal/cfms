/**
 * UE-3.2 — undo/redo across layers for the unified editing toolset.
 *
 * Each geometry mutation (cut-polygon / merge-features / edit-geometry) is
 * captured as an extended Split/Merge/VertexEdit operation carrying enough
 * server context to INVERSE it exactly:
 *
 *   cut    → delete the created pieces (pieceIds / boundaryPieceBlockIds /
 *            pieceFeatureIds) + restore the source row/feature
 *   merge  → delete the merged row + restore all sources
 *   vertex → re-POST edit-geometry with the previous (or new) geometry
 *
 * This file keeps the pure array math (imported-layer store mirror) separate
 * from the thin fetch helpers, so the mirror reducers are unit-testable.
 */
import type { GeoJSON } from 'geojson';
import {
  isSplitOperation,
  isMergeOperation,
  isVertexEditOperation,
  type SplitOperation,
  type MergeOperation,
  type VertexEditOperation,
} from './editOperations';
import { featureIdOf } from './geometryMerge';
import { deleteFeatureRow, restoreFeatureRow, type FeatureRowContext } from './featureRowOps';

type BuiltinLayerType = 'boundary' | 'blocks' | 'compartments' | 'sub_compartments' | 'sub_areas' | 'user_group';

function importedCtx(calcId: string, layerType: string, importLayerId: number, featureId: string, featureIndex?: number): FeatureRowContext {
  return {
    calcId,
    layerType: `import_${layerType}` as FeatureRowContext['layerType'],
    featureId,
    importLayerId,
    featureIndex,
  };
}

function builtinCtx(calcId: string, layerType: BuiltinLayerType, featureId: string): FeatureRowContext {
  return { calcId, layerType, featureId };
}

function apiBase(): string {
  return import.meta.env.VITE_API_URL ?? '';
}

/** Authenticated JSON headers (JWT-Bearer) for raw fetch calls.
 *  Also used by the workspace vertex-edit commit so drags persist. */
export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

// ─────────────────────────────────────────────────────────────────────────────
// pure imported-layer store-mirror reducers (unit-testable)
// ─────────────────────────────────────────────────────────────────────────────

/** UNDO cut on an imported layer: drop the pieces, splice the source back. */
export function importedFeaturesAfterSplitInverse(
  cur: GeoJSON.Feature[],
  op: SplitOperation,
): GeoJSON.Feature[] {
  const pieceIds = new Set(op.pieceFeatureIds ?? []);
  let next = cur.filter((f) => !pieceIds.has(featureIdOf(f)));
  if (op.sourceFeature && op.sourceFeatureIndex != null) {
    const insertAt = Math.min(op.sourceFeatureIndex, next.length);
    next = [...next.slice(0, insertAt), op.sourceFeature, ...next.slice(insertAt)];
  } else if (op.sourceFeature) {
    next = [...next, op.sourceFeature];
  }
  return next;
}

/** UNDO merge on an imported layer: drop the merged feature, resplice sources. */
export function importedFeaturesAfterMergeInverse(
  cur: GeoJSON.Feature[],
  op: MergeOperation,
): GeoJSON.Feature[] {
  const others = cur.filter((f) => featureIdOf(f) !== op.mergedFeatureId);
  if (!op.sourceFeatures?.length) return others;
  const indices = op.sourceIndices ?? [];
  // Sources were interleaved with the other features by original index; the
  // non-source features kept their relative order after the merge, so walking
  // the sources ASCENDING by index and inserting at that index reproduces the
  // exact pre-merge array (verified for merged-appended and interleaved cases).
  const placements = op.sourceFeatures
    .map((f, i) => ({ f, idx: indices[i] ?? i }))
    .sort((a, b) => a.idx - b.idx);
  let next = others;
  for (const { f, idx } of placements) {
    const at = Math.min(idx, next.length);
    next = [...next.slice(0, at), f, ...next.slice(at)];
  }
  return next;
}

/** REDO cut on an imported layer: drop source, append pieces from the op. */
export function importedFeaturesAfterSplitForward(
  cur: GeoJSON.Feature[],
  op: SplitOperation,
): GeoJSON.Feature[] {
  const pieces = op.pieces.map((p, i) => ({
    type: 'Feature' as const,
    geometry: p.geometry,
    properties: {
      ...p.properties,
      featureId: op.pieceFeatureIds?.[i] ?? `${op.sourceFeatureId}-piece-${i + 1}`,
    },
  }));
  return [...cur.filter((f) => featureIdOf(f) !== op.sourceFeatureId), ...pieces];
}

/** REDO merge on an imported layer: drop sources, append the merged feature. */
export function importedFeaturesAfterMergeForward(
  cur: GeoJSON.Feature[],
  op: MergeOperation,
  merged: GeoJSON.Feature,
): GeoJSON.Feature[] {
  return [...cur.filter((f) => !op.sourceFeatureIds.includes(featureIdOf(f))), merged];
}

/** UNDO vertex/move on an imported layer: replace geometry with previous. */
export function importedFeaturesAfterVertexInverse(
  cur: GeoJSON.Feature[],
  op: VertexEditOperation,
): GeoJSON.Feature[] {
  return cur.map((f) =>
    featureIdOf(f) === op.featureId ? { ...f, geometry: op.previousGeometry } : f,
  );
}

/** REDO vertex/move on an imported layer: replace geometry with new. */
export function importedFeaturesAfterVertexForward(
  cur: GeoJSON.Feature[],
  op: VertexEditOperation,
): GeoJSON.Feature[] {
  return cur.map((f) =>
    featureIdOf(f) === op.featureId ? { ...f, geometry: op.newGeometry } : f,
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// server actions (thinnest possible fetch wrappers)
// ─────────────────────────────────────────────────────────────────────────────

/** UNDO split — delete the created pieces + restore the source. */
export async function undoCutServer(op: SplitOperation): Promise<void> {
  if (!op.calcId) return;
  if (op.layerType === 'imported') {
    if (op.importLayerId == null) return;
    for (const pid of op.pieceFeatureIds ?? []) {
      const ctx = importedCtx(op.calcId, op.layerType, op.importLayerId, pid);
      await deleteFeatureRow(ctx);
    }
    if (op.sourceFeature && op.layerType === 'imported' && op.importLayerId != null) {
      await restoreFeatureRow(importedCtx(op.calcId, op.layerType, op.importLayerId, op.sourceFeatureId, op.sourceFeatureIndex), { feature: op.sourceFeature });
    }
    return;
  }
  if (op.layerType === 'boundary') {
    for (const bid of op.boundaryPieceBlockIds ?? []) {
      await deleteFeatureRow(builtinCtx(op.calcId, 'blocks', bid));
    }
    return;
  }
  if (op.layerType === 'user_group') {
    // P7e: a cut now CREATES rows - it deletes the source row and inserts one per
    // piece - so undo is the ordinary shape the generic path below already does:
    // delete the created rows, restore the source. The old branch assumed a cut
    // rewrote one row in place and created nothing, so the created rows would have
    // survived an undo and the layer would show the cut twice.
    const ugLt = op.layerType as BuiltinLayerType;
    for (const pid of op.pieceIds ?? []) {
      await deleteFeatureRow(builtinCtx(op.calcId, ugLt, pid));
    }
    if (op.sourceSnapshot) {
      await restoreFeatureRow(
        builtinCtx(op.calcId, ugLt, op.sourceFeatureId),
        op.sourceSnapshot,
      );
    }
    return;
  }
  const lt = op.layerType as BuiltinLayerType;
  for (const pid of op.pieceIds ?? []) {
    await deleteFeatureRow(builtinCtx(op.calcId, lt, pid));
  }
  if (op.sourceSnapshot && (lt === 'blocks' || lt === 'compartments' || lt === 'sub_compartments' || lt === 'sub_areas')) {
    await restoreFeatureRow(builtinCtx(op.calcId, lt, op.sourceFeatureId), op.sourceSnapshot);
  }
}

/** UNDO merge — delete the merged row + restore all sources. */
export async function undoMergeServer(op: MergeOperation): Promise<void> {
  if (!op.calcId) return;
  if (op.layerType === 'imported') {
    if (op.importLayerId == null) return;
    const mergedCtx = importedCtx(op.calcId, op.layerType, op.importLayerId, op.mergedFeatureId);
    await deleteFeatureRow(mergedCtx);
    const sources = op.sourceFeatures ?? [];
    for (let i = 0; i < sources.length; i++) {
      const src = sources[i];
      await restoreFeatureRow(
        importedCtx(op.calcId, op.layerType, op.importLayerId, op.sourceFeatureIds[i] ?? featureIdOf(src), op.sourceIndices?.[i]),
        { feature: src },
      );
    }
    return;
  }
  const lt = op.layerType as BuiltinLayerType;
  if (op.mergedRowId && lt !== 'boundary') {
    await deleteFeatureRow(builtinCtx(op.calcId, lt, op.mergedRowId));
  }
  for (let i = 0; i < op.sourceFeatureIds.length; i++) {
    const snap = op.sourceSnapshots?.[i];
    if (snap && (lt === 'blocks' || lt === 'compartments' || lt === 'sub_compartments' || lt === 'sub_areas')) {
      await restoreFeatureRow(builtinCtx(op.calcId, lt, op.sourceFeatureIds[i]), snap);
    }
  }
}

/** REDO split — replay the identical cut-polygon request. Returns the response. */
export async function redoCutServer(op: SplitOperation): Promise<{ pieces?: unknown; piece_feature_ids?: unknown }> {
  const resp = await fetch(
    `${apiBase()}/api/v1/calculations/${op.calcId}/geometry/cut-polygon`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        layer_type: op.layerType,
        layer_id: op.importLayerId,
        feature_id: op.sourceFeatureId,
        cut_line: op.cutGeometry,
      }),
    },
  );
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail = (body as any)?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Redo cut failed (${resp.status})`);
  }
  return resp.json();
}

/** REDO merge — replay the identical merge-features request. Returns merged. */
export async function redoMergeServer(op: MergeOperation): Promise<GeoJSON.Feature> {
  const resp = await fetch(
    `${apiBase()}/api/v1/calculations/${op.calcId}/geometry/merge-features`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        layer_type: op.layerType,
        layer_id: op.importLayerId,
        feature_ids: [...op.sourceFeatureIds],
      }),
    },
  );
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    const detail = (body as any)?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Redo merge failed (${resp.status})`);
  }
  const body = await resp.json();
  return (body.feature ?? body.merged ?? body) as GeoJSON.Feature;
}

/** UNDO or REDO a vertex/move edit — re-POST edit-geometry with the given geometry. */
export async function applyVertexServer(op: VertexEditOperation, direction: 'undo' | 'redo'): Promise<void> {
  if (!op.calcId) return;
  const geometry = direction === 'undo' ? op.previousGeometry : op.newGeometry;
  if (op.layerType === 'boundary') {
    // Boundary has no edit-geometry route — persist through PUT /boundary and
    // recompute the geodesic area so result_data stays accurate.
    const { area } = await import('@turf/turf');
    const resp = await fetch(
      `${apiBase()}/api/forests/calculations/${op.calcId}/boundary`,
      {
        method: 'PUT',
        headers: authHeaders(),
        body: JSON.stringify({
          geometry,
          area_hectares: (area(geometry) || 0) / 10000,
        }),
      },
    );
    if (!resp.ok) {
      const body = await resp.json().catch(() => null);
      const detail = (body as any)?.detail;
      throw new Error(typeof detail === 'string' ? detail : `Boundary ${direction} failed (${resp.status})`);
    }
    return;
  }
  const body: Record<string, unknown> = {
    layer_type: op.layerType,
    layer_id: op.importLayerId,
    feature_id: op.featureId,
    geometry,
  };
  // V-2 atomic shared-vertex move: undo/redo must replay the whole batch in
  // ONE request so no side is left in the moved state (single-feature undo of
  // a shared move would open a gap and be rejected by R6).
  if (op.sharedMovePartners?.length) {
    body.shared_moves = op.sharedMovePartners.map((p) => ({
      feature_id: p.featureId,
      geometry: direction === 'undo' ? p.previousGeometry : p.newGeometry,
    }));
  }
  const resp = await fetch(
    `${apiBase()}/api/v1/calculations/${op.calcId}/geometry/edit-geometry`,
    {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(body),
    },
  );
  if (!resp.ok) {
    const body2 = await resp.json().catch(() => null);
    const detail = (body2 as any)?.detail;
    const msg = typeof detail === 'string' ? detail : detail?.message ?? `Vertex ${direction} failed (${resp.status})`;
    throw new Error(msg);
  }
}

export function opNeedsServerSync(op: SplitOperation | MergeOperation | VertexEditOperation): boolean {
  return isSplitOperation(op) || isMergeOperation(op) || isVertexEditOperation(op);
}