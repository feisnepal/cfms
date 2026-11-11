/** The field inventory BY SUB-UNIT (one row per undivided unit, a roll-up for each divided parent, a forest total) and the problems
 *  between the stored inventory and the forest's current units. Stored data only; the server never computes anything here. */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

export interface ReportRow {
  name: string;
  kind: 'unit' | 'rollup' | 'total';
  depth: number;
  parent: string | null;
  area_ha: number;
  has_data: boolean;
  plots: number;
  regeneration_per_ha: number | null;
  sapling_per_ha: number | null;
  pole_per_ha: number | null;
  tree_per_ha: number | null;
  growing_stock_m3_per_ha: number | null;
  growing_stock_m3: number | null;
  basal_area_m2_per_ha: number | null;
  mai_m3_per_ha: number | null;
  mai_m3: number | null;
  aah_m3_per_ha: number | null;
  aah_m3: number | null;
  forest_condition: string | null;
  regeneration_condition: string | null;
  covered_pct: number;
}

export interface InventoryProblem {
  code: string;
  severity: 'error' | 'warning';
  unit: string;
  message: string;
  count: number;
}

export type InventoryReport =
  | { state: 'not_computed'; rows: []; total: null; leaf_count: 0; problems: InventoryProblem[]; has_errors: boolean }
  | { state: 'ready'; rows: ReportRow[]; total: ReportRow; leaf_count: number; problems: InventoryProblem[]; has_errors: boolean };

export function useFieldInventoryReport(calculationId: string | null | undefined, enabled: boolean, geometryVersion = 0) {
  return useQuery({
    queryKey: ['field-inventory-report', calculationId, geometryVersion],
    queryFn: async () => (await api.get<InventoryReport>(`/api/calculations/${calculationId}/field-inventory-report`)).data,
    enabled: !!calculationId && enabled,
    staleTime: 30 * 1000,
    refetchOnWindowFocus: false,
  });
}

/** Download the same report as an Excel workbook (the server names the file). */
export async function downloadInventoryReportXlsx(calculationId: string): Promise<void> {
  const res = await api.get(`/api/calculations/${calculationId}/field-inventory-report`, { params: { format: 'xlsx' }, responseType: 'blob' });
  const header = String(res.headers?.['content-disposition'] ?? '');
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(header);
  const plain = /filename="([^"]+)"/i.exec(header);
  const name = utf8 ? decodeURIComponent(utf8[1]) : plain ? plain[1] : 'FieldInventory_SubUnitReport.xlsx';
  const url = URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
