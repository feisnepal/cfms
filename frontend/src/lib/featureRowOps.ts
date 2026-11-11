/**
 * E3 — per-row delete/restore helpers for the attribute table.
 *
 * Every builtin layer + imported/digitize layer routes to the correct backend
 * endpoint here, so `MapWorkspace` wiring stays thin and testable. Builtin
 * geometry rows (boundary/blocks/compartments/sub_compartments/sub_areas) use
 * the single-authority editing router (§E1.2) for snapshots + restore (R5:
 * exactly one row, no cascade). Imported/digitize + activity features mutate
 * their feature arrays directly.
 */
import { PlanLinesChoiceError, planLinesDetail } from './planLinesChoice';
import type { GeoJSON } from 'geojson';

export type FeatureDeleteLayerType =
  | 'boundary'
  | 'blocks'
  | 'sub_blocks'
  | 'compartments'
  | 'sub_compartments'
  | 'sub_areas'
  | 'activity_features'
  | 'user_group'
  | `import_${string}`;

const API_PREFIX = '/api/v1';

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? '';
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

export interface DeleteGuardReason {
  type: 'sample_plots' | 'field_inventory' | 'tree_inventory' | 'child_compartments' | 'yearly_activities' | string;
  count: number;
}

export interface DeleteGuardResult {
  layer_type: string;
  feature_id: string;
  blocked: boolean;
  reasons: DeleteGuardReason[];
}

export interface FeatureSnapshotResult {
  layer_type: string;
  feature_id: string;
  snapshot: Record<string, unknown>;
}

/** Full row context needed to delete/restore one feature. */
export interface FeatureRowContext {
  calcId: string;
  layerType: FeatureDeleteLayerType;
  featureId: string;
  /** imported/digitize layer id (numeric WorkspaceLayer pk) */
  importLayerId?: number;
  /** feature index within that layer (for array-mutated layers) */
  featureIndex?: number;
  /** a sub-area with yearly-plan lines: what happens to them (asked of the user after the server answers 409) */
  planLines?: 'delete' | 'keep';
}

export async function fetchDeleteGuard(
  ctx: Pick<FeatureRowContext, 'calcId' | 'layerType' | 'featureId'>,
): Promise<DeleteGuardResult> {
  const url = `${baseUrl()}${API_PREFIX}/calculations/${ctx.calcId}/geometry/delete-guard`
    + `?layer_type=${encodeURIComponent(ctx.layerType)}`
    + `&feature_id=${encodeURIComponent(ctx.featureId)}`;
  const resp = await fetch(url, { headers: authHeaders(), cache: 'no-store' });
  if (!resp.ok) {
    throw new Error(`Delete guard failed (${resp.status})`);
  }
  return (await resp.json()) as DeleteGuardResult;
}

export async function snapshotFeature(
  ctx: FeatureRowContext,
): Promise<FeatureSnapshotResult> {
  const url = `${baseUrl()}${API_PREFIX}/calculations/${ctx.calcId}/geometry/feature`
    + `?layer_type=${encodeURIComponent(ctx.layerType)}`
    + `&feature_id=${encodeURIComponent(ctx.featureId)}`;
  const resp = await fetch(url, { headers: authHeaders(), cache: 'no-store' });
  if (!resp.ok) {
    throw new Error(`Feature snapshot failed (${resp.status})`);
  }
  return (await resp.json()) as FeatureSnapshotResult;
}

/** Execute the row delete. Returns the deleted row (for undo snapshot). */
export async function deleteFeatureRow(
  ctx: FeatureRowContext,
): Promise<unknown> {
  if (ctx.layerType.startsWith('import_')) {
    if (ctx.importLayerId == null || ctx.featureIndex == null) {
      throw new Error('Import layer delete requires importLayerId + featureIndex');
    }
    const url = `${baseUrl()}${API_PREFIX}/workspace/${ctx.calcId}/import-layers/${ctx.importLayerId}/features/${ctx.featureIndex}`;
    const resp = await fetch(url, { method: 'DELETE', headers: authHeaders(), cache: 'no-store' });
    if (!resp.ok) throw new Error(`Failed to delete layer feature (${resp.status})`);
    const body = (await resp.json()) as { deleted_feature?: unknown };
    return body.deleted_feature ?? { id: ctx.featureId };
  }

  // Builtin geometry layers → single-authority editing/legacy endpoints.
  if (ctx.layerType === 'boundary') {
    const resp = await fetch(`${baseUrl()}${API_PREFIX}/calculations/${ctx.calcId}/boundary`, {
      method: 'DELETE',
      headers: authHeaders(),
      cache: 'no-store',
    });
    if (!resp.ok && resp.status !== 204) throw new Error(`Delete boundary failed (${resp.status})`);
    return { id: 'boundary' };
  }

  if (ctx.layerType === 'blocks' || ctx.layerType === 'sub_blocks') {
    // sub_blocks are `ForestBlock` rows with `is_compartment=false`, same as
    // top-level blocks — the compartments delete endpoint below explicitly
    // refuses a non-compartment row (400), so a sub-block must route here.
    await deleteBuiltin(`/api/forests/calculations/${ctx.calcId}/blocks/${ctx.featureId}`);
  } else if (ctx.layerType === 'compartments' || ctx.layerType === 'sub_compartments') {
    // compartments.py:1141 — leaf-only (R5 guarded). Deletes get stage-checked first.
    await deleteBuiltin(`/api/compartments/${ctx.featureId}`);
  } else if (ctx.layerType === 'sub_areas') {
    await deleteBuiltin(
      `/api/forests/calculations/${ctx.calcId}/sub-areas/${ctx.featureId}${ctx.planLines ? `?plan_lines=${ctx.planLines}` : ''}`,
    );
  } else if (ctx.layerType === 'user_group') {
    // P7e: each polygon is its own row, so deleting a feature deletes exactly
    // that row. It used to hit the id-less route, which removed the WHOLE group -
    // correct only while one row held everything, and destructive the moment a
    // second polygon existed.
    await deleteBuiltin(
      `/api/calculations/${ctx.calcId}/user-group/${encodeURIComponent(ctx.featureId)}`,
    );
  } else if (ctx.layerType === 'activity_features') {
    await deleteBuiltin(`/api/yearly-activities/calculations/${ctx.calcId}/drawn-features/${ctx.featureId}`);
  }
  return { id: ctx.featureId };
}

async function deleteBuiltin(url: string): Promise<void> {
  const resp = await fetch(url, { method: 'DELETE', headers: authHeaders(), cache: 'no-store' });
  if (resp.status === 409) {
    const body = (await resp.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = planLinesDetail(body?.detail);
    if (detail) throw new PlanLinesChoiceError(detail);
  }
  if (!resp.ok && resp.status !== 204) {
    throw new Error(`Delete failed (${resp.status})`);
  }
}

/** Undo-restore the deleted row from its snapshot. */
export async function restoreFeatureRow(
  ctx: FeatureRowContext,
  snapshot: Record<string, unknown>,
): Promise<void> {
  if (ctx.layerType.startsWith('import_')) {
    if (ctx.importLayerId == null) throw new Error('Import restore requires importLayerId');
    const feature = (snapshot.feature ?? snapshot) as GeoJSON.Feature;
    const url = `${baseUrl()}${API_PREFIX}/workspace/${ctx.calcId}/import-layers/${ctx.importLayerId}/features/restore`;
    const resp = await fetch(url, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        feature,
        feature_id: ctx.featureId,
        feature_index: ctx.featureIndex ?? undefined,
      }),
      cache: 'no-store',
    });
    if (!resp.ok) throw new Error(`Restore failed (${resp.status})`);
    return;
  }

  if (ctx.layerType === 'activity_features') {
    const resp = await fetch(`/api/yearly-activities/calculations/${ctx.calcId}/drawn-features`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(snapshot.feature ?? {}),
    });
    if (!resp.ok) throw new Error(`Restore drawn feature failed (${resp.status})`);
    return;
  }

  const body = { layer_type: ctx.layerType, feature_id: ctx.featureId, snapshot };
  const resp = await fetch(`${baseUrl()}${API_PREFIX}/calculations/${ctx.calcId}/geometry/restore-feature`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  if (!resp.ok) {
    throw new Error(`Restore failed (${resp.status})`);
  }
}