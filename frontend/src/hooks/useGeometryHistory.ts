import { useRef, useState, useCallback, useEffect } from 'react';
import type { GeometryOperation } from '../lib/editOperations';
import { GeometryHistoryManager, createHistoryManager } from '../lib/historyManager';

export interface UseGeometryHistoryState {
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  readonly undoDepth: number;
  readonly redoDepth: number;
  readonly lastSaved: number;
}

export function useGeometryHistory(
  instanceId: string,
  userId: string,
  options?: { maxSize?: number; autoSave?: boolean },
) {
  const historyRef = useRef<GeometryHistoryManager | null>(null);

  const [state, setState] = useState<UseGeometryHistoryState>({
    canUndo: false,
    canRedo: false,
    undoDepth: 0,
    redoDepth: 0,
    lastSaved: Date.now(),
  });

  useEffect(() => {
    const manager = createHistoryManager(instanceId, userId, {
      maxSize: options?.maxSize,
      autoSave: options?.autoSave,
    });
    historyRef.current = manager;

    setState({
      canUndo: manager.canUndo,
      canRedo: manager.canRedo,
      undoDepth: manager.undoDepth,
      redoDepth: manager.redoDepth,
      lastSaved: manager.lastSaved,
    });

    const handleBeforeUnload = () => {
      manager.flush();
    };
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      manager.dispose();
      historyRef.current = null;
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [instanceId, userId, options?.maxSize, options?.autoSave]);

  const syncState = useCallback(() => {
    const mgr = historyRef.current;
    if (!mgr) return;
    setState({
      canUndo: mgr.canUndo,
      canRedo: mgr.canRedo,
      undoDepth: mgr.undoDepth,
      redoDepth: mgr.redoDepth,
      lastSaved: mgr.lastSaved,
    });
  }, []);

  const pushOp = useCallback(
    (operation: GeometryOperation): GeometryOperation => {
      const mgr = historyRef.current;
      if (!mgr) throw new Error('History manager not initialized');
      const result = mgr.push(operation);
      syncState();
      return result;
    },
    [syncState],
  );

  const undo = useCallback((): GeometryOperation | null => {
    const mgr = historyRef.current;
    if (!mgr) return null;
    const result = mgr.undo();
    if (result) syncState();
    return result;
  }, [syncState]);

  const redo = useCallback((): GeometryOperation | null => {
    const mgr = historyRef.current;
    if (!mgr) return null;
    const result = mgr.redo();
    if (result) syncState();
    return result;
  }, [syncState]);

  const clear = useCallback((): void => {
    const mgr = historyRef.current;
    if (!mgr) return;
    mgr.clear();
    syncState();
  }, [syncState]);

  const save = useCallback((): boolean => {
    const mgr = historyRef.current;
    if (!mgr) return false;
    const result = mgr.save();
    if (result) syncState();
    return result;
  }, [syncState]);

  return {
    history: historyRef,
    state,
    pushOp,
    undo,
    redo,
    clear,
    save,
  } as const;
}
