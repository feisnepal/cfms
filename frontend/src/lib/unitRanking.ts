/**
 * "Which units are at the top and the bottom of the active map?" — a short ranked list a user can jump from.
 *
 * Pure: reads the per-unit numbers the workspace already holds (SFM block types, the active field-inventory map, the hazard
 * summaries), so it costs no request. Only maps whose per-unit fact is a NUMBER are ranked (stock, soil loss, the landslide /
 * stability shares, every numeric field-inventory map); a class map such as forest type has no order, so it returns null.
 */
import { isFiMap, type AnalysisMapId } from './analysisMaps';
import type { HazardUnits } from './hazardFeatureProps';
import type { UnitMapData } from './unitMapProps';
import type { SfmBlockTypeInfo } from '../services/api';

export interface RankedUnit {
  name: string;
  value: number;
  text: string;
}

export interface Ranking {
  /** highest first; when there are few units this holds all of them and `bottom` is empty */
  top: RankedUnit[];
  bottom: RankedUnit[];
  total: number;
  /** what the number means, e.g. "highest growing stock first" is the default; true = the HIGH end is the risky one */
  highIsWorse: boolean;
}

export interface RankingContext {
  sfmBlockTypes?: Record<string, SfmBlockTypeInfo>;
  unitMap?: UnitMapData | null;
  hazardUnits?: HazardUnits;
}

const N = 5;

function entries(id: AnalysisMapId, c: RankingContext): { all: RankedUnit[]; highIsWorse: boolean } | null {
  if (id === 'sfm_stock') {
    const all = Object.entries(c.sfmBlockTypes ?? {})
      .filter(([, i]) => i.gs_ge40_m3_per_ha != null)
      .map(([name, i]) => ({ name, value: Number(i.gs_ge40_m3_per_ha), text: `${Number(i.gs_ge40_m3_per_ha).toFixed(0)} m³/ha` }));
    return { all, highIsWorse: false };
  }
  if (isFiMap(id)) {
    if (!c.unitMap || c.unitMap.state !== 'ready') return null;
    const all: RankedUnit[] = [];
    for (const [name, u] of Object.entries(c.unitMap.units)) {
      if (typeof u.value === 'number' && Number.isFinite(u.value)) all.push({ name, value: u.value, text: u.text ?? String(u.value) });
    }
    return { all, highIsWorse: false };
  }
  const hz = c.hazardUnits ?? {};
  const pick = (read: (u: HazardUnits[string]) => number | null | undefined, text: (v: number) => string): RankedUnit[] =>
    Object.entries(hz).flatMap(([name, u]) => {
      const v = read(u);
      return v == null || !Number.isFinite(v) ? [] : [{ name, value: v, text: text(v) }];
    });
  if (id === 'hazard_soil') return { all: pick((u) => u.soil?.mean, (v) => `${v.toFixed(1)} t/ha/yr`), highIsWorse: true };
  if (id === 'hazard_lsi') return { all: pick((u) => u.lsi?.high_pct, (v) => `${v.toFixed(0)}% High+`), highIsWorse: true };
  if (id === 'hazard_fs') return { all: pick((u) => u.fs?.unsafe_pct, (v) => `${v.toFixed(0)}% unsafe`), highIsWorse: true };
  if (id === 'hazard_prone') return { all: pick((u) => u.prone?.high_pct, (v) => `${v.toFixed(0)}% high`), highIsWorse: true };
  return null;
}

/** `null` when the map has no per-unit number to rank (or none of its units has one). */
export function rankUnits(id: AnalysisMapId | null | undefined, c: RankingContext): Ranking | null {
  if (!id) return null;
  const e = entries(id, c);
  if (!e || e.all.length === 0) return null;
  const sorted = [...e.all].sort((a, b) => b.value - a.value || a.name.localeCompare(b.name));
  if (sorted.length <= 2 * N) return { top: sorted, bottom: [], total: sorted.length, highIsWorse: e.highIsWorse };
  return { top: sorted.slice(0, N), bottom: sorted.slice(-N).reverse(), total: sorted.length, highIsWorse: e.highIsWorse };
}
