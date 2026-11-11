import { useEffect, useCallback } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { MapCompositionService } from '../services/mapCompositionService';
import { useCalculationContext } from './useCalculationContext';

/**
 * Hook for managing map compositions tied to the current calculation.
 * Loads/saves from calculation.result_data via MapCompositionService.
 */
export function useMapCompositions() {
  const { calculationId } = useCalculationContext();
  const {
    mapCompositions,
    activeCompositionId,
    setMapCompositions,
    setActiveComposition,
  } = useWorkspaceStore();

  const service = calculationId ? new MapCompositionService(calculationId) : null;

  // Load compositions on mount or calculationId change
  useEffect(() => {
    if (!service) return;
    let cancelled = false;
    service.load().then(({ compositions, activeCompositionId }) => {
      if (!cancelled) {
        setMapCompositions(compositions);
        if (activeCompositionId) {
          setActiveComposition(activeCompositionId);
        }
      }
    });
    return () => { cancelled = true; };
  }, [service, setMapCompositions, setActiveComposition]);

  const createComposition = useCallback(
    async (partial?: Partial<import('../lib/mapComposition').MapComposition>) => {
      if (!service) return;
      return service.createComposition(partial);
    },
    [service]
  );

  const updateComposition = useCallback(
    async (id: string, updates: Partial<import('../lib/mapComposition').MapComposition>) => {
      if (!service) return;
      await service.updateComposition(id, updates);
      // Reload to sync store
      const { compositions, activeCompositionId } = await service.load();
      setMapCompositions(compositions);
      if (activeCompositionId) setActiveComposition(activeCompositionId);
    },
    [service, setMapCompositions, setActiveComposition]
  );

  const deleteComposition = useCallback(
    async (id: string) => {
      if (!service) return;
      await service.deleteComposition(id);
      const { compositions, activeCompositionId } = await service.load();
      setMapCompositions(compositions);
      if (activeCompositionId) setActiveComposition(activeCompositionId);
    },
    [service, setMapCompositions, setActiveComposition]
  );

  const setActive = useCallback(
    async (id: string) => {
      if (!service) return;
      await service.setActive(id);
      setActiveComposition(id);
    },
    [service, setActiveComposition]
  );

  return {
    mapCompositions,
    activeCompositionId,
    createComposition,
    updateComposition,
    deleteComposition,
    setActiveComposition: setActive,
  };
}