/**
 * Puts what each cached hazard map says about a unit onto the unit feature's own properties, next to the `sfm_*`
 * ones (lib/sfmFeatureProps.ts) — so the automatic labels and the attribute-table columns read one place.
 *
 * Source: `GET /calculations/{id}/hazard-units`. A layer that is not computed, or a unit it has no valid cell for,
 * simply leaves its keys off.
 */
import type { Feature } from 'geojson';

export interface HazardUnitLayers {
  soil?: { mean: number | null; severe_pct: number; area_ha: number };
  lsi?: { dominant: { index: number; label_en: string; label_ne: string }; high_pct: number };
  fs?: { unstable_pct: number; unsafe_pct: number };
  prone?: { high_pct: number };
}

/** Per unit name, the four layers' rows (the response, turned inside out). */
export type HazardUnits = Record<string, HazardUnitLayers>;

export interface HazardUnitsResponse {
  layers: Partial<Record<'soil' | 'lsi' | 'fs' | 'prone', Record<string, unknown>>>;
  missing: string[];
}

export const HZ_PROP_KEYS = [
  'hz_soil_mean',
  'hz_soil_severe_pct',
  'hz_lsi_class_en',
  'hz_lsi_class_ne',
  'hz_lsi_high_pct',
  'hz_fs_unstable_pct',
  'hz_fs_unsafe_pct',
  'hz_prone_pct',
] as const;

export function unitsByName(res: HazardUnitsResponse | null | undefined): HazardUnits {
  const out: HazardUnits = {};
  if (!res) return out;
  for (const key of ['soil', 'lsi', 'fs', 'prone'] as const) {
    for (const [name, row] of Object.entries(res.layers?.[key] ?? {})) {
      (out[name] ??= {})[key] = row as never;
    }
  }
  return out;
}

export function hazardPropsFor(u: HazardUnitLayers): Record<string, unknown> {
  const p: Record<string, unknown> = {};
  if (u.soil) {
    p.hz_soil_mean = u.soil.mean;
    p.hz_soil_severe_pct = u.soil.severe_pct;
  }
  if (u.lsi) {
    p.hz_lsi_class_en = u.lsi.dominant.label_en;
    p.hz_lsi_class_ne = u.lsi.dominant.label_ne;
    p.hz_lsi_high_pct = u.lsi.high_pct;
  }
  if (u.fs) {
    p.hz_fs_unstable_pct = u.fs.unstable_pct;
    p.hz_fs_unsafe_pct = u.fs.unsafe_pct;
  }
  if (u.prone) p.hz_prone_pct = u.prone.high_pct;
  return p;
}

/** Same array back (by reference) when there is nothing to merge. */
export function mergeHazardProps(features: Feature[] | null, units: HazardUnits | undefined): Feature[] | null {
  if (!features || !units || Object.keys(units).length === 0) return features;
  return features.map((f) => {
    const hit = units[String(f.properties?.name ?? '')];
    return hit ? { ...f, properties: { ...f.properties, ...hazardPropsFor(hit) } } : f;
  });
}
