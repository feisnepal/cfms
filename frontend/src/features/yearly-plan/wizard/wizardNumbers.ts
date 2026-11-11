/**
 * The numbers of the wizard (plan §4.7): what the drawn places measure, the per-year amounts, the totals, and
 * the "unusual amount" hint. Pure functions; the parser for typed text is passed in so the caller decides how
 * digits are read (both languages' digits, thousands commas).
 */
import area from '@turf/area';
import length from '@turf/length';
import type { NumberParser, Place, WizardState } from './wizardMachine';

// ------------------------------------------------------------------------------- measuring places

export type MeasureKind = 'ha' | 'km' | 'count';

// The units of the master list, as `yearly_plan_service` reads them.
const HA = new Set(['हेक्टर', 'ha', 'hectare', 'hectares']);
const KM = new Set(['कि.मि.', 'km', 'kilometer', 'kilometre']);
const COUNT = new Set(['वटा', 'स्थान', 'each', 'place', 'places', 'number']);

/** What the drawn places can tell about the activity's unit, or null when they cannot. */
export function measureKind(unit: string | undefined | null): MeasureKind | null {
  const u = (unit ?? '').trim();
  if (HA.has(u)) return 'ha';
  if (KM.has(u)) return 'km';
  if (COUNT.has(u)) return 'count';
  return null;
}

/** The total the drawn places measure for `unit` (hectares of polygons, km of lines, or a count of places). */
export function measurePlaces(places: Place[], unit: string | undefined | null): number | null {
  const kind = measureKind(unit);
  if (!kind || places.length === 0) return null;
  if (kind === 'count') return places.length;
  let total = 0;
  for (const place of places) {
    const feature = { type: 'Feature', properties: {}, geometry: place.geometry } as GeoJSON.Feature;
    if (kind === 'ha' && (place.geometry.type === 'Polygon' || place.geometry.type === 'MultiPolygon')) {
      total += area(feature) / 10000;
    } else if (kind === 'km' && (place.geometry.type === 'LineString' || place.geometry.type === 'MultiLineString')) {
      total += length(feature, { units: 'kilometers' });
    }
  }
  return total > 0 ? total : null;
}

/** A measured amount as text for the quantity field: at most 3 decimals, no trailing zeros. */
export function measuredText(value: number): string {
  return String(Number(value.toFixed(3)));
}

// -------------------------------------------------------------------------------- per-year amounts

export interface YearAmount {
  year: number;
  quantity: number;
  budget: number;
}

/** The amounts of each chosen year, from what was typed. Years whose text is not a number count as 0. */
export function yearAmounts(state: WizardState, parse: NumberParser): YearAmount[] {
  const num = (text: string) => {
    const n = parse(text);
    return Number.isFinite(n) ? n : 0;
  };
  return state.years.map((year) => {
    const row = state.same ? { quantity: state.quantity, budget: state.budget } : state.yearValues[year];
    return { year, quantity: num(row?.quantity ?? ''), budget: num(row?.budget ?? '') };
  });
}

export const totalBudgetOf = (amounts: YearAmount[]): number => amounts.reduce((sum, a) => sum + a.budget, 0);
export const peakBudgetOf = (amounts: YearAmount[]): number => amounts.reduce((max, a) => Math.max(max, a.budget), 0);

// -------------------------------------------------------------------------------- unusual amounts

/** Same thresholds as `plan_health_service` (D23), so the wizard warns about what the check would have raised. */
export const UNUSUAL_ABSOLUTE = 1_000_000;
export const UNUSUAL_MEDIAN_FACTOR = 20;
export const MIN_OTHERS_FOR_MEDIAN = 3;

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * Is the largest yearly budget of this line unusual? `othersMax` is each OTHER plan line's largest yearly
 * budget. A wizard-created line is created reviewed, so the plan-health check no longer raises this for it —
 * the wizard therefore says it before saving.
 */
export function isUnusualAmount(peakYearlyBudget: number, othersMax: number[]): boolean {
  if (peakYearlyBudget > UNUSUAL_ABSOLUTE) return true;
  return (
    othersMax.length >= MIN_OTHERS_FOR_MEDIAN && peakYearlyBudget > UNUSUAL_MEDIAN_FACTOR * median(othersMax)
  );
}
