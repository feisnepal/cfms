/**
 * Turning a finished wizard into requests, and running them (plan §4.4, §5.1).
 *
 *   - no places (an activity that needs no map, "whole forest", "decide later"):
 *       one `POST …/yearly-plan` — the plan line, its year rows and the numbers in ONE transaction;
 *   - places: one `POST …/activity-features` per place. The FIRST creates the plan line with the person's
 *       numbers (so it is reviewed); the others find the line and only add a place;
 *   - "different each year": once the line exists, one `PUT …/yearly-plan/{line}` sets the individual years.
 *
 * A place that fails to save is reported and can be tried again; the ones that saved are never repeated.
 */
import type { NumberParser, Place, WizardState } from './wizardMachine';
import { yearAmounts } from './wizardNumbers';

export interface PlanLineBody {
  potential_activity_id: number;
  years: number[];
  quantity?: number;
  budget?: number;
  year_values?: Array<{ year: number; quantity: number; budget: number }>;
  whole_forest?: boolean;
}

export interface FeatureBody {
  potential_activity_id: number;
  feature_type: 'point' | 'line' | 'polygon';
  geometry: string;
  years: number[];
  name?: string;
  quantity?: number;
  budget?: number;
}

export interface WizardPlan {
  /** set when there are no places to draw */
  line?: PlanLineBody;
  /** one per place, in order */
  features: FeatureBody[];
  /** the individual years, sent after the line exists ("different each year" with places) */
  yearValues: Array<{ year: number; quantity: number; budget: number }>;
}

const FEATURE_TYPE: Record<string, FeatureBody['feature_type']> = {
  Point: 'point',
  LineString: 'line',
  Polygon: 'polygon',
};

export const featureTypeOf = (place: Place): FeatureBody['feature_type'] | null => FEATURE_TYPE[place.geometry.type] ?? null;

/** What to send for this wizard. Throws when the wizard is not finished (no activity, or nothing valid to send). */
export function buildWizardPlan(state: WizardState, parse: NumberParser): WizardPlan {
  const activity = state.activity;
  if (!activity) throw new Error('no activity chosen');
  const amounts = yearAmounts(state, parse);
  const first = amounts[0];
  const numbers = state.existing || !first ? {} : { quantity: first.quantity, budget: first.budget };
  const perYear = !state.existing && !state.same ? amounts : [];
  const years = state.existing && state.existing.years.length > 0 ? state.existing.years : state.years;

  const usePlaces = activity.requiresMap && state.where === 'map' && state.places.length > 0;
  if (!usePlaces) {
    return {
      line: {
        potential_activity_id: activity.id,
        years,
        ...numbers,
        ...(perYear.length > 0 ? { year_values: perYear } : {}),
        ...(state.where === 'whole' ? { whole_forest: true } : {}),
      },
      features: [],
      yearValues: [],
    };
  }
  const features = state.places.map<FeatureBody>((place) => {
    const type = featureTypeOf(place);
    if (!type) throw new Error('unsupported place: ' + place.geometry.type);
    return {
      potential_activity_id: activity.id,
      feature_type: type,
      geometry: JSON.stringify(place.geometry),
      years,
      ...(state.name.trim() ? { name: state.name.trim() } : {}),
      ...numbers,
    };
  });
  return { features, yearValues: perYear };
}

export interface WizardApi {
  addLine: (body: PlanLineBody) => Promise<{ plan_line: { id: string; version: number } }>;
  createFeature: (body: FeatureBody) => Promise<{ plan_line: { id: string; version: number } }>;
  updateLine: (
    lineId: string,
    edit: { years: Array<{ year: number; quantity: number; budget: number }>; expected_version?: number },
  ) => Promise<{ plan_line: { id: string; version: number } }>;
}

export interface SaveOutcome {
  ok: boolean;
  lineId: string | null;
  version: number | null;
  /** indexes of the places that did NOT save */
  failedPlaces: number[];
  error: unknown;
}

/**
 * Run a wizard plan. Never throws: the outcome says what saved and what did not. `only` limits the places
 * (a retry after a partial failure sends just the ones that failed).
 */
export async function runWizardPlan(plan: WizardPlan, api: WizardApi, only?: number[]): Promise<SaveOutcome> {
  const outcome: SaveOutcome = { ok: true, lineId: null, version: null, failedPlaces: [], error: null };
  try {
    if (plan.line) {
      const res = await api.addLine(plan.line);
      outcome.lineId = res.plan_line.id;
      outcome.version = res.plan_line.version;
      return outcome;
    }
    for (let i = 0; i < plan.features.length; i += 1) {
      if (only && !only.includes(i)) continue;
      try {
        const res = await api.createFeature(plan.features[i]);
        outcome.lineId = res.plan_line.id;
        outcome.version = res.plan_line.version;
      } catch (err) {
        outcome.ok = false;
        outcome.failedPlaces.push(i);
        outcome.error = err;
      }
    }
    if (outcome.ok && plan.yearValues.length > 0 && outcome.lineId) {
      const res = await api.updateLine(outcome.lineId, {
        years: plan.yearValues,
        expected_version: outcome.version ?? undefined,
      });
      outcome.version = res.plan_line.version;
    }
  } catch (err) {
    outcome.ok = false;
    outcome.error = err;
  }
  return outcome;
}
