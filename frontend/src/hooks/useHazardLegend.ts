/** The dynamic legend of a hazard analysis map: the classes this forest actually has, with area and share.
 *  Reads the backend's cached grid only; `state: 'not_computed'` when nothing is cached for the current parameters. */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

export interface HazardLegendClass {
  index: number;
  color: string;
  label_ne: string;
  label_en: string;
  from: number;
  to: number | null;
  area_ha: number;
  share_pct: number;
}

export type HazardLegend =
  | { state: 'not_computed'; key: string }
  | { state: 'no_data'; key: string }
  | { state: 'no_user_group'; key: string }
  | {
      state: 'ready';
      key: string;
      area?: 'forest' | 'user_group';
      custom_colours?: boolean;
      relative: boolean;
      params_hash: string;
      cell_m: number;
      total_ha: number;
      classes: HazardLegendClass[];
    };

export function useHazardLegend(
  calculationId: string | null | undefined,
  key: string | null,
  geometryVersion = 0,
  area: 'forest' | 'user_group' = 'forest',
  colourVersion = '0',
) {
  return useQuery({
    queryKey: ['hazard-legend', calculationId, key, geometryVersion, area, colourVersion],
    queryFn: async () =>
      (await api.get<HazardLegend>(`/api/calculations/${calculationId}/hazard-legend/${key}`, { params: { area } })).data,
    enabled: !!calculationId && !!key,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
