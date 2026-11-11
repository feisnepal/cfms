import { useWorkspaceStore } from '../store/workspaceStore';

/**
 * U02 — thin selector re-export for the geometry version clock.
 *
 * Derived panes key their queries on `[calcId, geometryVersion, paneKey]` with
 * `staleTime:0, gcTime:30_000` so an edit→commit→bump triggers a refetch. The
 * dirty flag guards auto-refetch: refetch only after a commit bump, never per-keystroke.
 */
export function useGeometryVersion() {
  return useWorkspaceStore((s) => s.geometryVersion);
}

/** Version-aware query key helper for derived panes. */
export function geometryQueryKey(calcId: string | null, paneKey: string): (string | number | null)[] {
  return [calcId ?? 'no-calc', useWorkspaceStore.getState().geometryVersion, paneKey];
}

/** Reconcile helper exposed for callers that fetch geometry (queries, map loads). */
export function useReconcileVersion() {
  return useWorkspaceStore((s) => s.reconcileVersion);
}