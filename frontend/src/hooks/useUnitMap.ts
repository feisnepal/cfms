/**
 * Field-inventory data for the unit layers, mirrored into the workspace store (the map, the labels and the attribute table
 * all read it from there):
 *  - `useUnitMapSync`: the ACTIVE single-number map's per-unit colours + dynamic legend (re-asked once the user's colours have
 *    settled, because the server paints from what it has saved);
 *  - `useFieldInventoryUnits`: the raw per-unit numbers for the table columns.
 * Both are cache-only on the server; a failure just means no colouring / no columns.
 */
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';
import { fiSpecKey, isFiMap, type AnalysisMapId } from '../lib/analysisMaps';
import type { FieldInventoryUnits, UnitMapData } from '../lib/unitMapProps';

export function useUnitMapQuery(
  calculationId: string | null | undefined,
  id: AnalysisMapId | null | undefined,
  geometryVersion = 0,
  colourVersion = '0',
) {
  const spec = id && isFiMap(id) ? fiSpecKey(id) : null;
  return useQuery({
    queryKey: ['unit-map', calculationId, spec, geometryVersion, colourVersion],
    queryFn: async () => (await api.get<UnitMapData>(`/api/calculations/${calculationId}/unit-maps/${spec}`)).data,
    enabled: !!calculationId && !!spec,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

export function useUnitMapSync(
  calculationId: string | null | undefined,
  id: AnalysisMapId | null | undefined,
  geometryVersion: number,
  colourVersion: string,
): void {
  const setUnitMap = useWorkspaceStore((s) => s.setUnitMap);
  const { data } = useUnitMapQuery(calculationId, id, geometryVersion, colourVersion);
  const active = !!id && isFiMap(id);
  useEffect(() => {
    setUnitMap(active ? (data ?? null) : null);
  }, [active, data, setUnitMap]);
}

export function useFieldInventoryUnits(calculationId: string | null | undefined, geometryVersion: number): void {
  const set = useWorkspaceStore((s) => s.setFieldInventoryUnits);
  useEffect(() => {
    if (!calculationId) {
      set({});
      return;
    }
    let live = true;
    api
      .get<{ state: string; units: FieldInventoryUnits }>(`/api/calculations/${calculationId}/field-inventory-units`)
      .then((r) => live && set(r.data.units ?? {}))
      .catch(() => live && set({}));
    return () => {
      live = false;
    };
  }, [calculationId, geometryVersion, set]);
}

/** What "Run analysis" computed for every unit (any level), for the attribute-table columns. Stored data only. */
export function useUnitAnalysis(calculationId: string | null | undefined, geometryVersion: number): void {
  const set = useWorkspaceStore((s) => s.setUnitAnalysis);
  useEffect(() => {
    if (!calculationId) {
      set({});
      return;
    }
    let live = true;
    api
      .get<{ state: string; units: Record<string, Record<string, string | number | boolean>> }>(
        `/api/calculations/${calculationId}/unit-analysis`,
      )
      .then((r) => live && set(r.data.units ?? {}))
      .catch(() => live && set({}));
    return () => {
      live = false;
    };
  }, [calculationId, geometryVersion, set]);
}
