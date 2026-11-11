/** Household-vulnerability / priority-settlement dots for the active analysis map (GeoJSON points from the backend).
 *  Only fetched while that map is on; the server answers `not_computed` unless the hazard grids are already cached. */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

export type HouseholdKind = 'households' | 'settlements';

export interface HouseholdPoint {
  type: 'Feature';
  geometry: { type: 'Point'; coordinates: [number, number] };
  properties: { score: number; priority?: boolean; name?: string | null; n?: number; n_priority?: number };
}

export type HouseholdDots =
  | { state: 'not_computed' | 'no_user_group' | 'no_data'; kind: HouseholdKind }
  | {
      state: 'ready';
      kind: HouseholdKind;
      area: 'forest' | 'user_group';
      basis: string | null;
      count: number;
      n_priority: number;
      min: number;
      max: number;
      features: HouseholdPoint[];
    };

export function useHazardHouseholds(
  calculationId: string | null | undefined,
  kind: HouseholdKind | null,
  area: 'forest' | 'user_group',
  geometryVersion = 0,
) {
  return useQuery({
    queryKey: ['hazard-households', calculationId, kind, area, geometryVersion],
    queryFn: async () =>
      (await api.get<HouseholdDots>(`/api/calculations/${calculationId}/hazard-households/${kind}`, { params: { area } })).data,
    enabled: !!calculationId && !!kind,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
