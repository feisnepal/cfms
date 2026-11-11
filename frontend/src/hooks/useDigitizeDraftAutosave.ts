/**
 * useDigitizeDraftAutosave — auto-saves the workspace digitize draft buffer to
 * localStorage and restores it on remount (Phase 5, Gap #1).
 *
 * Reality-aligned: the draft lives in `workspaceStore.digitizeDraftFeatures`
 * and is flushed to the backend by `useDraftSync`. This hook is a safety-net
 * snapshot on top of that — it persists the buffer locally every 30s and
 * restores it if a remount happens before a flush. It also listens for the
 * `draft:restore` event and flushes on `beforeunload`.
 */
import { useEffect } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import {
  loadDraftSnapshot,
  saveDraftSnapshot,
  clearDraftSnapshot,
} from '../lib/draftAutosave';

export const DRAFT_AUTOSAVE_INTERVAL_MS = 30_000;

export function useDigitizeDraftAutosave(calculationId?: string) {
  useEffect(() => {
    if (!calculationId) return;

    const restoreSnapshot = () => {
      const snapshot = loadDraftSnapshot(calculationId);
      if (!snapshot) return;
      const { setDigitizeDraftFeatures } = useWorkspaceStore.getState();
      Object.entries(snapshot.features || {}).forEach(([layerId, features]) => {
        setDigitizeDraftFeatures(Number(layerId), features);
      });
    };

    // Restore any fresh locally-saved draft on mount.
    restoreSnapshot();

    // Persist the live buffer every 30s while the component is mounted.
    const interval = window.setInterval(() => {
      const draft = useWorkspaceStore.getState().digitizeDraftFeatures;
      if (draft && Object.keys(draft).length > 0) {
        saveDraftSnapshot(calculationId, draft);
      }
    }, DRAFT_AUTOSAVE_INTERVAL_MS);

    // Listen for an explicit restore request (e.g. from a controller switching
    // tabs and wanting local edits restored into the live map).
    const onRestore = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { calculationId?: string; draft?: Record<number, GeoJSON.Feature[]> }
        | undefined;
      if (!detail || detail.calculationId !== calculationId) return;
      if (detail.draft) {
        const { setDigitizeDraftFeatures } = useWorkspaceStore.getState();
        Object.entries(detail.draft).forEach(([layerId, features]) => {
          setDigitizeDraftFeatures(Number(layerId), features);
        });
      } else {
        restoreSnapshot();
      }
    };
    window.addEventListener('draft:restore', onRestore as EventListener);

    // Flush once on unload so the latest buffer survives a quick close.
    const onUnload = () => {
      const draft = useWorkspaceStore.getState().digitizeDraftFeatures;
      if (draft && Object.keys(draft).length > 0) {
        saveDraftSnapshot(calculationId, draft);
      }
    };
    window.addEventListener('beforeunload', onUnload);

    return () => {
      window.clearInterval(interval);
      window.removeEventListener('draft:restore', onRestore as EventListener);
      window.removeEventListener('beforeunload', onUnload);
    };
  }, [calculationId]);
}

/** Manually drop the local draft snapshot for a calculation. */
export function discardLocalDraft(calculationId: string) {
  clearDraftSnapshot(calculationId);
}