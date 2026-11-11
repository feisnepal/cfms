/**
 * Everything the workspace knows about ONE unit, gathered in sections for the unit card shown when a unit is clicked:
 * Sustainable FM, Hazard & erosion and Field inventory. Reads the merged feature properties (`sfm_*`, `hz_*`, `fi_*`, `area_hectares`),
 * so it needs no request and can never disagree with the labels, the colours or the table.
 *
 * A section appears only when the unit has data for it — a unit with no field inventory shows no Field inventory section, and
 * says nothing about it rather than printing blanks.
 */
import { SFM_NO_TYPE } from './sfmFeatureProps';

type Tr = (key: string, opts?: Record<string, unknown>) => string;

export interface FactRow {
  label: string;
  value: string;
}
export interface FactSection {
  id: 'unit' | 'sfm' | 'hazard' | 'inventory';
  title: string;
  rows: FactRow[];
}

const num = (v: unknown): number | null => (v == null || v === '' ? null : Number.isFinite(Number(v)) ? Number(v) : null);
const fmt = (v: number, d = 1): string => v.toLocaleString(undefined, { maximumFractionDigits: d });

export function unitFacts(p: Record<string, unknown>, lang: string, t: Tr): FactSection[] {
  const ne = String(lang || '').startsWith('ne');
  const L = (key: string, def: string, o: Record<string, unknown> = {}) => t(`unitFacts.${key}`, { defaultValue: def, ...o });
  const out: FactSection[] = [];

  const area = num(p.area_hectares);
  if (area != null) out.push({ id: 'unit', title: L('unit', 'Unit'), rows: [{ label: L('area', 'Area'), value: `${fmt(area, 2)} ha` }] });

  if (p.sfm_type != null) {
    const rows: FactRow[] = [];
    if (p.sfm_type === SFM_NO_TYPE) rows.push({ label: L('type', 'Forest type'), value: t(p.sfm_state === 'non_forest' ? 'sfm.state.nonForest' : 'sfm.state.noPlots') });
    else rows.push({ label: L('type', 'Forest type'), value: t('sfm.ref.typeDash', { n: p.sfm_type }) });
    if (p.sfm_orientation && p.sfm_orientation !== SFM_NO_TYPE) rows.push({ label: L('orientation', 'Orientation'), value: String(p.sfm_orientation) });
    if (num(p.sfm_gs) != null) rows.push({ label: L('stock40', 'Stock ≥40 cm'), value: `${fmt(num(p.sfm_gs)!, 0)} m³/ha` });
    if (p.sfm_slope_band) rows.push({ label: L('slope', 'Slope band'), value: String(p.sfm_slope_band) });
    if (num(p.sfm_plot_count) != null) rows.push({ label: L('plots', 'Sample plots'), value: String(num(p.sfm_plot_count)) });
    if (p.sfm_state === 'provisional') rows.push({ label: L('status', 'Status'), value: L('provisional', 'Provisional (few plots)') });
    out.push({ id: 'sfm', title: L('sfm', 'Sustainable forest management'), rows });
  }

  const hz: FactRow[] = [];
  if (num(p.hz_soil_mean) != null) {
    hz.push({ label: L('soilMean', 'Soil loss (mean)'), value: `${fmt(num(p.hz_soil_mean)!)} t/ha/yr` });
    if (num(p.hz_soil_severe_pct) != null) hz.push({ label: L('soilSevere', 'Severe or worse'), value: `${fmt(num(p.hz_soil_severe_pct)!, 0)}%` });
  }
  const lsiClass = ne ? p.hz_lsi_class_ne : p.hz_lsi_class_en;
  if (lsiClass) {
    hz.push({ label: L('lsiClass', 'Landslide class (relative)'), value: String(lsiClass) });
    if (num(p.hz_lsi_high_pct) != null) hz.push({ label: L('lsiHigh', 'High or above (relative)'), value: `${fmt(num(p.hz_lsi_high_pct)!, 0)}%` });
  }
  if (num(p.hz_fs_unsafe_pct) != null) hz.push({ label: L('fsUnsafe', 'Unsafe slope'), value: `${fmt(num(p.hz_fs_unsafe_pct)!, 0)}%` });
  if (num(p.hz_prone_pct) != null) hz.push({ label: L('prone', 'Relatively high susceptibility'), value: `${fmt(num(p.hz_prone_pct)!, 0)}%` });
  if (hz.length) out.push({ id: 'hazard', title: L('hazard', 'Hazard & erosion'), rows: hz });

  const fi: FactRow[] = [];
  const add = (key: string, label: string, suffix: string, digits = 1) => {
    const v = num(p[key]);
    if (v != null) fi.push({ label, value: `${fmt(v, digits)}${suffix ? ` ${suffix}` : ''}` });
  };
  add('fi_stock', L('stock', 'Growing stock'), 'm³/ha');
  add('fi_basal_area', L('basal', 'Basal area'), 'm²/ha');
  add('fi_aah', L('aah', 'AAH'), 'm³/ha/yr', 2);
  add('fi_mai', L('mai', 'MAI'), 'm³/ha/yr', 2);
  add('fi_mai_pct', L('maiPct', 'MAI'), '%');
  add('fi_carbon', L('carbon', 'Carbon'), 'tC/ha');
  add('fi_biomass', L('biomass', 'Biomass'), 't/ha');
  add('fi_co2', L('co2', 'CO₂ equivalent'), 'tCO₂/ha');
  add('fi_regeneration', L('regeneration', 'Regeneration'), '/ha', 0);
  add('fi_sapling', L('saplings', 'Saplings'), '/ha', 0);
  add('fi_pole', L('poles', 'Poles'), '/ha', 0);
  add('fi_tree', L('trees', 'Trees'), '/ha', 0);
  if (p.fi_condition) fi.push({ label: L('condition', 'Forest condition'), value: String(p.fi_condition) });
  if (p.fi_regen_condition) fi.push({ label: L('regenCondition', 'Regeneration condition'), value: String(p.fi_regen_condition) });
  add('fi_plots', L('fiPlots', 'Sample plots (inventory)'), '', 0);
  if (fi.length) out.push({ id: 'inventory', title: L('inventory', 'Field inventory'), rows: fi });

  return out;
}
