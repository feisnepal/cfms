import { useEffect, useCallback, useMemo, useRef } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useGeometryHistory } from './useGeometryHistory';
import type { GeometryOperation, FeatureDeleteOperation, FeaturePasteOperation } from '../lib/editOperations';
import type { GeoJSON } from 'geojson';
import {
  isVisibilityOperation,
  isLabelsOperation,
  isStyleOperation,
  isDeleteOperation,
  isDuplicateOperation,
  isRenameOperation,
  isLabelFieldOperation,
  isDigitizeAddFeatureOperation,
  isDigitizeDeleteFeatureOperation,
  isDigitizeDeleteFeatureByIdOperation,
  isFeatureDeleteOperation,
  isFeaturePasteOperation,
  isBatchOperation,
  isAttributeEditOperation,
  isSplitOperation,
  isMergeOperation,
  isVertexEditOperation,
} from '../lib/editOperations';
import { isBuiltinLayerId, getLayerConfig } from '../lib/layerRegistry';
import type { LayerTypeId } from '../lib/layerRegistry';
import { forestApi } from '../services/api';
import {
  deleteFeatureRow,
  restoreFeatureRow,
  type FeatureRowContext,
} from '../lib/featureRowOps';
import {
  undoCutServer,
  undoMergeServer,
  redoCutServer,
  redoMergeServer,
  applyVertexServer,
  importedFeaturesAfterSplitInverse,
  importedFeaturesAfterMergeInverse,
  importedFeaturesAfterSplitForward,
  importedFeaturesAfterMergeForward,
  importedFeaturesAfterVertexInverse,
  importedFeaturesAfterVertexForward,
} from '../lib/geometryUndo';
import {
  createSubAreaFromPaste,
  appendFeaturesToImportedLayer,
  fetchImportedFeatures,
  type SubAreaCreateBody,
} from '../lib/featurePasteApi';

const HISTORY_INSTANCE = 'context-menu';
const HISTORY_USER = 'user';

export function useContextMenuUndoRedo() {
  const store = useWorkspaceStore();
  const { state, pushOp, undo: historyUndo, redo: historyRedo } =
    useGeometryHistory(HISTORY_INSTANCE, HISTORY_USER, { maxSize: 200, autoSave: true });

  const bumpAfterGeometryOp = useCallback((): void => {
    store.bumpGeometryVersion();
  }, [store]);

  /** UE-3.2 — imported mirror for a geometry inverse/replay. */
  const mirrorImported = useCallback((layerId: number, next: GeoJSON.Feature[]): void => {
    store.setImportedLayerFeatures(layerId, next);
  }, [store]);

  const runInverse = useCallback((op: GeometryOperation): void => {
    const done = (err?: unknown) => {
      if (err) store.setError(String((op as any).layerType ?? 'geometry'), (err as Error)?.message || 'Undo failed');
      else bumpAfterGeometryOp();
    };
    if (isSplitOperation(op)) {
      undoCutServer(op)
        .then(() => {
          if (op.layerType === 'imported' && op.importLayerId != null) {
            const cur = store.importedLayerFeatures[op.importLayerId] ?? [];
            mirrorImported(op.importLayerId, importedFeaturesAfterSplitInverse(cur, op));
          }
          done();
        })
        .catch(done);
    } else if (isMergeOperation(op)) {
      undoMergeServer(op)
        .then(() => {
          if (op.layerType === 'imported' && op.importLayerId != null) {
            const cur = store.importedLayerFeatures[op.importLayerId] ?? [];
            mirrorImported(op.importLayerId, importedFeaturesAfterMergeInverse(cur, op));
          }
          done();
        })
        .catch(done);
    } else if (isVertexEditOperation(op)) {
      if (op.layerType === 'boundary') {
        restoreFeatureRow(
          { calcId: op.calcId!, layerType: 'boundary', featureId: 'boundary' },
          { geometry: op.previousGeometry },
        )
          .then(() => done())
          .catch(done);
      } else {
        applyVertexServer(op, 'undo')
          .then(() => {
            if (op.layerType === 'imported' && op.importLayerId != null) {
              const cur = store.importedLayerFeatures[op.importLayerId] ?? [];
              mirrorImported(op.importLayerId, importedFeaturesAfterVertexInverse(cur, op));
            }
            done();
          })
          .catch(done);
      }
    }
  }, [store, mirrorImported, bumpAfterGeometryOp]);

  const runForward = useCallback((op: GeometryOperation): void => {
    const done = (err?: unknown) => {
      if (err) store.setError(String((op as any).layerType ?? 'geometry'), (err as Error)?.message || 'Redo failed');
      else bumpAfterGeometryOp();
    };
    if (isSplitOperation(op)) {
      redoCutServer(op)
        .then((body) => {
          if (op.layerType === 'imported' && op.importLayerId != null) {
            const cur = store.importedLayerFeatures[op.importLayerId] ?? [];
            mirrorImported(op.importLayerId, importedFeaturesAfterSplitForward(cur, op));
          }
          done();
        })
        .catch(done);
    } else if (isMergeOperation(op)) {
      redoMergeServer(op)
        .then((merged) => {
          if (op.layerType === 'imported' && op.importLayerId != null) {
            const cur = store.importedLayerFeatures[op.importLayerId] ?? [];
            mirrorImported(op.importLayerId, importedFeaturesAfterMergeForward(cur, op, merged));
          }
          done();
        })
        .catch(done);
    } else if (isVertexEditOperation(op)) {
      if (op.layerType === 'boundary') {
        restoreFeatureRow(
          { calcId: op.calcId!, layerType: 'boundary', featureId: 'boundary' },
          { geometry: op.newGeometry },
        )
          .then(() => done())
          .catch(done);
      } else {
        applyVertexServer(op, 'redo')
          .then(() => {
            if (op.layerType === 'imported' && op.importLayerId != null) {
              const cur = store.importedLayerFeatures[op.importLayerId] ?? [];
              mirrorImported(op.importLayerId, importedFeaturesAfterVertexForward(cur, op));
            }
            done();
          })
          .catch(done);
      }
    }
  }, [store, mirrorImported, bumpAfterGeometryOp]);

  /** P3.5 — re-PATCH one of an attribute edit's two payloads (undo or redo).
   *  An imported-layer edit re-PATCHes the workspace import-feature endpoint and
   *  mirrors the change into `importedLayerFeatures`; a builtin edit goes through
   *  the layer's `dataSource.update`. */
  const applyAttributeEdit = useCallback((
    op: Extract<GeometryOperation, { kind: 'attribute_edit' }>,
    direction: 'undo' | 'redo',
  ): void => {
    const payload = direction === 'undo' ? op.previousPayload : op.newPayload;

    if (op.importLayerId != null && op.featureIndex != null) {
      const props = (payload as { properties?: Record<string, unknown> }).properties ?? {};
      forestApi.updateImportedFeature(op.calcId, op.importLayerId, op.featureIndex, props)
        .then((res) => {
          const cur = store.importedLayerFeatures[op.importLayerId!] ?? [];
          if (cur[op.featureIndex!]) {
            const next = [...cur];
            next[op.featureIndex!] = {
              ...next[op.featureIndex!],
              properties: { ...next[op.featureIndex!].properties, ...(res?.properties ?? props) },
            };
            store.setImportedLayerFeatures(op.importLayerId!, next);
          }
          store.bumpGeometryVersion();
        })
        .catch((err) => store.setError(op.layerId, (err as Error)?.message || `${direction} failed`));
      return;
    }

    const cfg = getLayerConfig(op.layerId as LayerTypeId);
    if (!cfg) return;
    cfg.dataSource.update(op.calcId, op.featureId, payload as Partial<GeoJSON.Feature>)
      .then(() => store.bumpGeometryVersion())
      .catch((err) => store.setError(op.layerId, (err as Error)?.message || `${direction} failed`));
  }, [store]);

  /** Refresh after an applied row-delete/restore stays exactly one row deep. */
  const refreshAfterRowOp = useCallback((op: Extract<GeometryOperation, { kind: 'feature_delete' }>): void => {
    if (String(op.layerType).startsWith('import_')) {
      // Imported/digitize features are stored in the store — optimistically
      // mirror the server so the map + table update without a full refetch.
      // (Featset handled in the operation handlers via setImportedLayerFeatures.)
      store.bumpGeometryVersion();
    } else {
      store.bumpGeometryVersion();
    }
  }, [store]);

  // Batch replay re-enters applyInverse / applyForward for each child; the refs
  // let the (earlier-declared) helpers below call them without a cycle.
  const inverseRef = useRef<(op: GeometryOperation) => void | Promise<void>>(() => {});
  const forwardRef = useRef<(op: GeometryOperation) => void | Promise<void>>(() => {});

  const rowCtxOf = (op: FeatureDeleteOperation): FeatureRowContext => ({
    calcId: op.calcId,
    layerType: op.layerType as FeatureRowContext['layerType'],
    featureId: op.featureId,
    importLayerId: op.importLayerId,
    featureIndex: op.featureIndex,
  });

  const reportUndoError = useCallback((layerType: string, err: unknown, fallback: string): void => {
    store.setError(layerType, (err as Error)?.message || fallback);
  }, [store]);

  /** E3 undo: put the deleted row back exactly where it was. */
  const restoreDeletedRow = useCallback(async (op: FeatureDeleteOperation): Promise<void> => {
    try {
      await restoreFeatureRow(rowCtxOf(op), op.snapshot);
      if (op.importLayerId != null && op.featureIndex != null) {
        const current = useWorkspaceStore.getState().importedLayerFeatures[op.importLayerId] || [];
        const next = [...current];
        next.splice(op.featureIndex, 0, featureFromSnapshot(op.snapshot));
        store.setImportedLayerFeatures(op.importLayerId, next);
      }
      refreshAfterRowOp(op);
    } catch (err) {
      reportUndoError(String(op.layerType), err, 'Undo restore failed');
    }
  }, [store, refreshAfterRowOp, reportUndoError]);

  /** E3 redo: delete the row again. */
  const redoDelete = useCallback(async (op: FeatureDeleteOperation): Promise<void> => {
    try {
      await deleteFeatureRow(rowCtxOf(op));
      if (op.importLayerId != null && op.featureIndex != null) {
        const current = useWorkspaceStore.getState().importedLayerFeatures[op.importLayerId] || [];
        const next = [...current];
        next.splice(op.featureIndex, 1);
        store.setImportedLayerFeatures(op.importLayerId, next);
      }
      refreshAfterRowOp(op);
    } catch (err) {
      reportUndoError(String(op.layerType), err, 'Redo delete failed');
    }
  }, [store, refreshAfterRowOp, reportUndoError]);

  /** Paste undo: remove exactly the rows that paste created. */
  const undoPaste = useCallback(async (op: FeaturePasteOperation): Promise<void> => {
    try {
      if (op.importLayerId != null) {
        // Created rows sit at the tail: [baseIndex, baseIndex + n). Delete from
        // the highest index down so each remaining index stays valid.
        const base = op.baseIndex ?? 0;
        for (let i = op.features.length - 1; i >= 0; i--) {
          await deleteFeatureRow({
            calcId: op.calcId,
            layerType: op.layerType as FeatureRowContext['layerType'],
            featureId: op.state.createdIds[i] ?? String(base + i),
            importLayerId: op.importLayerId,
            featureIndex: base + i,
          });
        }
        store.setImportedLayerFeatures(op.importLayerId, await fetchImportedFeatures(op.calcId, op.importLayerId));
      } else {
        for (const id of [...op.state.createdIds].reverse()) {
          await deleteFeatureRow({
            calcId: op.calcId,
            layerType: op.layerType as FeatureRowContext['layerType'],
            featureId: id,
          });
        }
        op.state.createdIds = [];
      }
      store.bumpGeometryVersion();
    } catch (err) {
      reportUndoError(op.layerType, err, 'Undo paste failed');
    }
  }, [store, reportUndoError]);

  /** Paste redo: create the same features again (the server mints new ids). */
  const redoPaste = useCallback(async (op: FeaturePasteOperation): Promise<void> => {
    try {
      if (op.importLayerId != null) {
        await appendFeaturesToImportedLayer(op.calcId, op.importLayerId, [...op.features], 'append');
        store.setImportedLayerFeatures(op.importLayerId, await fetchImportedFeatures(op.calcId, op.importLayerId));
      } else {
        const ids: string[] = [];
        for (const body of op.payloads ?? []) {
          const created = await createSubAreaFromPaste(op.calcId, body as unknown as SubAreaCreateBody);
          ids.push(created.id);
        }
        op.state.createdIds = ids;
      }
      store.bumpGeometryVersion();
    } catch (err) {
      reportUndoError(op.layerType, err, 'Redo paste failed');
    }
  }, [store, reportUndoError]);

  const applyInverse = useCallback((op: GeometryOperation): void | Promise<void> => {
    if (isSplitOperation(op) || isMergeOperation(op) || isVertexEditOperation(op)) {
      runInverse(op);
      return;
    }
    if (isAttributeEditOperation(op)) {
      applyAttributeEdit(op, 'undo');
      return;
    }
    if (isVisibilityOperation(op)) {
      if (op.layerType === 'builtin') {
        store.setLayerVisibility(op.layerId, op.previousVisible);
      } else {
        store.setImportedLayerVisibility(Number(op.layerId), op.previousVisible);
      }
    } else if (isLabelsOperation(op)) {
      store.setLayerLabelsVisible(op.layerId, op.previousVisible);
    } else if (isStyleOperation(op)) {
      const hasPrevKeys = Object.keys(op.previousStyle).length > 0;
      if (hasPrevKeys) {
        store.setCustomLayerStyle(op.layerId, op.previousStyle);
      } else {
        store.removeCustomLayerStyle(op.layerId);
      }
    } else if (isRenameOperation(op)) {
      store.renameImportedLayer(Number(op.featureId), op.previousName);
    } else if (isDuplicateOperation(op)) {
      store.removeImportedLayer(Number(op.newFeatureId));
    } else if (isDeleteOperation(op)) {
      const deleted = op.deletedFeature.properties as Record<string, unknown>;
      if (deleted?.id != null) {
        store.addImportedLayer(deleted as any);
      }
    } else if (isLabelFieldOperation(op)) {
      if (isBuiltinLayerId(op.layerId)) {
        store.setBuiltinLabelField(op.layerId, op.previousField);
      } else {
        store.setLabelField(Number(op.layerId), op.previousField);
      }
    } else if (isDigitizeAddFeatureOperation(op)) {
      const fid = featureIdOf(op.feature);
      if (fid) store.removeDigitizeFeature(op.layerId, fid);
    } else if (isDigitizeDeleteFeatureByIdOperation(op)) {
      store.enqueueDigitizeFeature(op.layerId, op.deletedFeature);
    } else if (isFeatureDeleteOperation(op)) {
      // E3 undo: restore the exact deleted row from its snapshot.
      return restoreDeletedRow(op);
    } else if (isFeaturePasteOperation(op)) {
      return undoPaste(op);
    } else if (isBatchOperation(op)) {
      // Children were recorded in execution order; undo walks them backwards,
      // one at a time - two concurrent server restores would race on the
      // index-based splice of an imported layer's feature list.
      return (async () => {
        for (const child of [...op.operations].reverse()) {
          await inverseRef.current(child);
        }
      })();
    }
  }, [store, refreshAfterRowOp, applyAttributeEdit, restoreDeletedRow, undoPaste]);

  inverseRef.current = applyInverse;

  const applyForward = useCallback((op: GeometryOperation): void | Promise<void> => {
    if (isSplitOperation(op) || isMergeOperation(op) || isVertexEditOperation(op)) {
      runForward(op);
      return;
    }
    if (isAttributeEditOperation(op)) {
      applyAttributeEdit(op, 'redo');
      return;
    }
    if (isVisibilityOperation(op)) {
      if (op.layerType === 'builtin') {
        store.setLayerVisibility(op.layerId, op.newVisible);
      } else {
        store.setImportedLayerVisibility(Number(op.layerId), op.newVisible);
      }
    } else if (isLabelsOperation(op)) {
      store.setLayerLabelsVisible(op.layerId, op.newVisible);
    } else if (isStyleOperation(op)) {
      store.setCustomLayerStyle(op.layerId, op.newStyle);
    } else if (isRenameOperation(op)) {
      store.renameImportedLayer(Number(op.featureId), op.newName);
    } else if (isDuplicateOperation(op)) {
      store.duplicateImportedLayer(Number(op.sourceFeatureId));
    } else if (isDeleteOperation(op)) {
      store.removeImportedLayer(Number(op.featureId));
    } else if (isLabelFieldOperation(op)) {
      if (isBuiltinLayerId(op.layerId)) {
        store.setBuiltinLabelField(op.layerId, op.newField);
      } else {
        store.setLabelField(Number(op.layerId), op.newField);
      }
    } else if (isDigitizeAddFeatureOperation(op)) {
      store.enqueueDigitizeFeature(op.layerId, op.feature);
    } else if (isDigitizeDeleteFeatureByIdOperation(op)) {
      store.removeDigitizeFeature(op.layerId, op.featureId);
    } else if (isFeatureDeleteOperation(op)) {
      // E3 redo: re-run the delete.
      return redoDelete(op);
    } else if (isFeaturePasteOperation(op)) {
      return redoPaste(op);
    } else if (isBatchOperation(op)) {
      return (async () => {
        for (const child of op.operations) {
          await forwardRef.current(child);
        }
      })();
    }
  }, [store, refreshAfterRowOp, applyAttributeEdit, redoDelete, redoPaste]);

  forwardRef.current = applyForward;

  const undo = useCallback((): void => {
    // GD 1.3.4: undo/redo disabled while the digitize draft buffer is flushing
    // (buffer is locked during flush; mutating it mid-flush would corrupt sync).
    if (useWorkspaceStore.getState().digitizeSyncState === 'syncing') return;
    const op = historyUndo();
    if (op) applyInverse(op);
  }, [historyUndo, applyInverse]);

  const redo = useCallback((): void => {
    if (useWorkspaceStore.getState().digitizeSyncState === 'syncing') return;
    const op = historyRedo();
    if (op) applyForward(op);
  }, [historyRedo, applyForward]);

  const pushAndExecute = useCallback((
    op: GeometryOperation,
    execute: () => void,
  ): void => {
    pushOp(op);
    execute();
  }, [pushOp]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) {
          redo();
        } else {
          undo();
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [undo, redo]);

  return useMemo(() => ({
    canUndo: state.canUndo,
    canRedo: state.canRedo,
    undo,
    redo,
    pushOp,
    pushAndExecute,
  }), [state.canUndo, state.canRedo, undo, redo, pushOp, pushAndExecute]);
}

function featureIdOf(feature: GeoJSON.Feature): string | undefined {
  const props = (feature.properties as Record<string, unknown>) || {};
  return (props.featureId as string)
    ?? (props.id as string)
    ?? (feature as { id?: unknown }).id as string | undefined;
}

/** Recover the GeoJSON feature stored inside an E3 op snapshot. */
function featureFromSnapshot(snapshot: Record<string, unknown>): GeoJSON.Feature {
  const raw = snapshot.feature;
  if (Array.isArray(raw) && raw.length) return raw[0] as GeoJSON.Feature;
  if (raw && typeof raw === 'object') return raw as GeoJSON.Feature;
  return snapshot as unknown as GeoJSON.Feature;
}
