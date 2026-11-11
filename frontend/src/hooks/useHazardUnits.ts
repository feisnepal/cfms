/** Keeps `store.hazardUnits` current: what each cached hazard map says about every block / compartment. Cache only on the
 *  server; refetches when the forest or its geometry changes. A failure just means no hazard labels / columns. */
import { useEffect } from 'react';
import api from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';
import { unitsByName, type HazardUnitsResponse } from '../lib/hazardFeatureProps';

export function useHazardUnits(calculationId: string | null | undefined, geometryVersion: number): void {
  const set = useWorkspaceStore((s) => s.setHazardUnits);
  useEffect(() => {
    if (!calculationId) {
      set({});
      return;
    }
    let live = true;
    api
      .get<HazardUnitsResponse>(`/api/calculations/${calculationId}/hazard-units`)
      .then((r) => live && set(unitsByName(r.data)))
      .catch(() => live && set({}));
    return () => {
      live = false;
    };
  }, [calculationId, geometryVersion, set]);
}
