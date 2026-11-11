/**
 * What the active single-number field-inventory map (and the raw field-inventory numbers) put on a unit feature's own
 * properties, next to the `sfm_*` / `hz_*` ones — so the colouring, the compact label and the attribute-table columns read one
 * place.
 *
 *  - `um_color` / `um_text` / `um_value`: from `GET /calculations/{id}/unit-maps/{spec}` — the colour is the PRINT renderer's own
 *    answer for that unit (with the user's colours laid over it), the text is the server-formatted value with its unit.
 *  - `fi_*`: from `GET /calculations/{id}/field-inventory-units` — raw numbers for the table.
 * A unit with no field-inventory summary simply carries none of them.
 */
import type { Feature } from 'geojson';

export interface UnitMapLegendRow {
  key: string;
  color: string;
  label: string;
  label_ne: string;
  label_en: string;
  count: number;
  /** the area the class covers, in hectares */
  area_ha?: number;
  editable: boolean;
}

export type UnitMapData =
  | { state: 'not_computed' | 'no_data' }
  | {
      state: 'ready';
      token: string;
      custom_colours: boolean;
      units: Record<string, { color: string; value: number | string | null; text: string | null; area_ha?: number; reason?: string; reason_ne?: string }>;
      legend: UnitMapLegendRow[];
    };

export type FieldInventoryUnits = Record<string, Record<string, number | string>>;

export const FI_PROP_KEYS = [
  'fi_stock', 'fi_basal_area', 'fi_aah', 'fi_mai', 'fi_mai_pct', 'fi_carbon', 'fi_biomass', 'fi_co2',
  'fi_regeneration', 'fi_sapling', 'fi_pole', 'fi_tree', 'fi_plots', 'fi_condition', 'fi_regen_condition',
] as const;

/** Same array back (by reference) when there is nothing to merge, so memoised consumers do not re-run. */
export function mergeUnitProps(
  features: Feature[] | null,
  unitMap: UnitMapData | null | undefined,
  fi: FieldInventoryUnits | undefined,
): Feature[] | null {
  const map = unitMap && unitMap.state === 'ready' ? unitMap.units : null;
  const hasFi = !!fi && Object.keys(fi).length > 0;
  if (!features || (!map && !hasFi)) return features;
  return features.map((f) => {
    const name = String(f.properties?.name ?? '');
    const m = map?.[name];
    const row = fi?.[name];
    if (!m && !row) return f;
    return {
      ...f,
      properties: {
        ...f.properties,
        ...(row ?? {}),
        ...(m ? { um_color: m.color, um_text: m.text, um_value: m.value, ...(m.reason ? { um_reason: m.reason, um_reason_ne: m.reason_ne } : {}) } : {}),
      },
    };
  });
}

/** Lay the per-unit `an_*` analysis values (keyed by unit id) onto the unit features. Same array back when there are none. */
export function mergeAnalysisProps(
  features: Feature[] | null,
  analysis: Record<string, Record<string, string | number | boolean>> | undefined,
): Feature[] | null {
  if (!features || !analysis || Object.keys(analysis).length === 0) return features;
  return features.map((f) => {
    const row = analysis[String(f.properties?.id ?? '')];
    return row ? { ...f, properties: { ...f.properties, ...row } } : f;
  });
}
