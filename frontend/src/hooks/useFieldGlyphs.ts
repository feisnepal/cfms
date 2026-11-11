/** Per-unit field-inventory chart data (timber m³/ha by tree size class) from the server. The server also supplies the colours
 *  (the placeholder's defaults with the user's own laid over them), so this hook re-asks once those colours have settled. */
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';

export interface GlyphSegment {
  index: number;
  key: string;
  label_ne: string;
  label_en: string;
  value: number;
  color: string;
}

export interface GlyphUnit {
  name: string;
  anchor: [number, number]; // lon, lat
  total_m3_per_ha: number;
  /** the unit's total in the chart's own unit (m³/ha, stems/ha, t/ha …) */
  total?: number;
  ge40_pct: number | null;
  plots: number;
  segments: GlyphSegment[];
  /** triplebar only: growing stock, MAI and AAH, each split over the same classes */
  bars?: Array<{ key: 'gs' | 'mai' | 'aah'; total: number; segments: GlyphSegment[] }>;
  /** radar only: each axis scaled 0..1 over all units */
  radar?: number[];
  /** the compact label at low / high zoom, written by the server so every chart says the same thing everywhere */
  text_short?: string;
  text_long?: string;
}

export type GlyphShape = 'stackbar' | 'triplebar' | 'pie' | 'waffle' | 'sparkline' | 'ternary' | 'radar';

export interface GlyphLegendClass {
  index: number;
  key: string;
  /** what a saved colour is keyed by: the class position, or — for the species chart — the species key */
  override_key?: string;
  label_ne: string;
  label_en: string;
  color: string;
}

export type FieldGlyphs =
  | { state: 'not_computed' | 'no_data'; kind: string }
  | {
      state: 'ready';
      kind: string;
      shape?: GlyphShape;
      id?: string;
      token?: string;
      /** false for the radar and the sparkline: their colours are fixed in the print map too */
      editable?: boolean;
      custom_colours: boolean;
      max_total: number;
      /** triplebar only: the largest of each bar over all units (each bar is scaled to its own) */
      bar_max?: { gs: number; mai: number; aah: number };
      units: GlyphUnit[];
      legend: GlyphLegendClass[];
    };

export function useFieldGlyphs(
  calculationId: string | null | undefined,
  slug: string | null,
  geometryVersion = 0,
  colourVersion = '0',
) {
  return useQuery({
    queryKey: ['field-glyphs', calculationId, slug, geometryVersion, colourVersion],
    queryFn: async () => (await api.get<FieldGlyphs>(`/api/calculations/${calculationId}/field-glyphs/${slug}`)).data,
    enabled: !!calculationId && !!slug,
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  });
}
