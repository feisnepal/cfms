/**
 * Puts the Sustainable-FM classification onto the unit features' own properties.
 *
 * The colour presets, the attribute table and the labels all read a feature's `properties`; the SFM data arrives
 * separately (`store.sfmBlockTypes`, keyed by unit name). Merging it ONCE here — in `useLayerData` — means all three
 * see the same values, and a unit the SFM tab has not classified simply carries no `sfm_*` keys.
 */
import type { Feature } from 'geojson';
import type { SfmBlockTypeInfo } from '../services/api';

/** Neutral class for a unit with no type (non-forest, or no sample plots): never drawn as "Type 0". */
export const SFM_NO_TYPE = 'none';

/** The SFM slope bands the zone classifier stores as 1-4 (कार्यविधि bands) — the same names the print map uses. */
export const SFM_SLOPE_BAND_LABEL: Record<number, string> = { 1: '<19°', 2: '19–31°', 3: '31–45°', 4: '>45°' };

/** A band code (1-4) as its name; a name already given passes through; anything else is no band. */
export function slopeBandLabel(v: unknown): string | null {
  if (v == null || v === '') return null;
  const n = Number(v);
  if (Number.isInteger(n) && SFM_SLOPE_BAND_LABEL[n]) return SFM_SLOPE_BAND_LABEL[n];
  return typeof v === 'string' ? v : null;
}

export const SFM_PROP_KEYS = [
  'sfm_type',
  'sfm_state',
  'sfm_land_class',
  'sfm_plot_count',
  'sfm_orientation',
  'sfm_gs',
  'sfm_slope_band',
] as const;

export function sfmPropsFor(info: SfmBlockTypeInfo): Record<(typeof SFM_PROP_KEYS)[number], unknown> {
  return {
    // string keys: the categorized renderer matches on String(value)
    sfm_type: info.type_no != null ? String(info.type_no) : SFM_NO_TYPE,
    sfm_state: info.state,
    sfm_land_class: info.land_class,
    sfm_plot_count: info.plot_count,
    sfm_orientation: info.orientation ?? SFM_NO_TYPE,
    sfm_gs: info.gs_ge40_m3_per_ha ?? null,
    sfm_slope_band: slopeBandLabel(info.slope_band),
  };
}

/** Same array back (by reference) when there is nothing to merge, so memoised consumers do not re-run. */
export function mergeSfmProps(
  features: Feature[] | null,
  info: Record<string, SfmBlockTypeInfo> | undefined,
): Feature[] | null {
  if (!features || !info || Object.keys(info).length === 0) return features;
  return features.map((f) => {
    const hit = info[String(f.properties?.name ?? '')];
    return hit ? { ...f, properties: { ...f.properties, ...sfmPropsFor(hit) } } : f;
  });
}
