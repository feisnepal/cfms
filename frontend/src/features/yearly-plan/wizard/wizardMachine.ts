/**
 * The "add an activity" wizard as a pure state machine (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.4).
 *
 * One question at a time — WHAT → WHERE → WHEN → HOW MUCH → NAME → CONFIRM — where each answer reshapes the
 * next step:
 *
 *   - an activity that needs no map has no WHERE step and no place anywhere (§4.4b);
 *   - an activity already in the plan skips WHEN and HOW MUCH (its numbers exist) and goes to "show where";
 *   - NAME exists only when there are drawn places to name;
 *   - "Decide later" and "Applies to the whole forest" leave nothing to draw.
 *
 * The reducer holds only what the person has answered. Nothing here talks to the server or the map, so every
 * path can be tested exhaustively.
 */
import type { CatalogueActivity } from '../../../lib/activitySearch';
import { ACTIVITY_KINDS, type KindGeom } from '../../../lib/activityKinds';

export type WizardStep = 'what' | 'where' | 'when' | 'howMuch' | 'name' | 'confirm';
export type WhereAnswer = 'map' | 'whole' | 'later';

/** The plan line an activity already has (so its numbers and years are not asked again). */
export interface ExistingLine {
  id: string;
  version: number;
  /** the plan years the line is planned in */
  years: number[];
  wholeForest: boolean;
}

export interface Place {
  geometry: GeoJSON.Geometry;
}

export interface YearNumbers {
  quantity: string;
  budget: string;
}

/** The shape a mappable activity is drawn as: its map symbol's own, else the person's choice (default: an area). */
export function drawGeomOf(activity: (Pick<CatalogueActivity, 'mapKind'> & { mapGeom?: CatalogueActivity['mapGeom'] }) | null): KindGeom {
  if (activity?.mapGeom) return activity.mapGeom; // the activity's own shape wins over its kind's (owner, 2026-10-15)
  const kind = activity?.mapKind ? ACTIVITY_KINDS[activity.mapKind] : undefined;
  return kind?.geom ?? 'polygon';
}

export interface WizardState {
  step: WizardStep;
  activity: CatalogueActivity | null;
  existing: ExistingLine | null;
  where: WhereAnswer | null;
  places: Place[];
  /** which drawing tool WHERE arms */
  drawGeom: KindGeom;
  years: number[];
  /** "Same every year" (the default) vs "Different each year" */
  same: boolean;
  /** what the person typed — kept as text so nothing is rounded or reformatted under them */
  quantity: string;
  budget: string;
  yearValues: Record<number, YearNumbers>;
  name: string;
}

export const PLAN_YEARS: readonly number[] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

export const initialWizard = (): WizardState => ({
  step: 'what',
  activity: null,
  existing: null,
  where: null,
  places: [],
  drawGeom: 'polygon',
  years: [1],
  same: true,
  quantity: '',
  budget: '',
  yearValues: {},
  name: '',
});

/** Presets of the WHEN step. "This year" is plan year 1. */
export type YearPreset = 'this' | 'first5' | 'every';
export const yearsOfPreset = (preset: YearPreset): number[] =>
  preset === 'this' ? [1] : preset === 'first5' ? [1, 2, 3, 4, 5] : [...PLAN_YEARS];

/** The steps this wizard will go through, given the answers so far. */
export function stepsFor(state: Pick<WizardState, 'activity' | 'existing' | 'where' | 'places'>): WizardStep[] {
  const steps: WizardStep[] = ['what'];
  if (!state.activity) return steps;
  if (state.activity.requiresMap) steps.push('where');
  if (!state.existing) steps.push('when', 'howMuch');
  if (state.activity.requiresMap && state.where === 'map' && state.places.length > 0) steps.push('name');
  steps.push('confirm');
  return steps;
}

/** A typed amount as a number, or NaN. Accepts either language's digits and thousands commas. */
export type NumberParser = (text: string) => number;

/** Is the WHEN step complete? At least one plan year. */
export const yearsChosen = (state: Pick<WizardState, 'years'>): boolean => state.years.length > 0;

/** Is a quantity / budget pair acceptable? Quantity must be above 0; a budget may be 0 (voluntary work). */
export function numbersValid(quantity: string, budget: string, parse: NumberParser): boolean {
  const q = parse(quantity);
  const b = parse(budget);
  return Number.isFinite(q) && q > 0 && Number.isFinite(b) && b >= 0;
}

/** Are the numbers step's answers complete and acceptable? */
export function howMuchValid(state: WizardState, parse: NumberParser): boolean {
  if (state.same) return numbersValid(state.quantity, state.budget, parse);
  return state.years.length > 0 && state.years.every((y) => {
    const row = state.yearValues[y];
    return row !== undefined && numbersValid(row.quantity, row.budget, parse);
  });
}

/** Can the person move on from the current step? */
export function canAdvance(state: WizardState, parse: NumberParser): boolean {
  switch (state.step) {
    case 'what':
      return state.activity !== null;
    case 'where':
      return state.where !== null && (state.where !== 'map' || state.places.length > 0);
    case 'when':
      return yearsChosen(state);
    case 'howMuch':
      return howMuchValid(state, parse);
    case 'name':
      return true;
    default:
      return false;
  }
}

export type WizardAction =
  | { type: 'chooseActivity'; activity: CatalogueActivity; existing: ExistingLine | null }
  | { type: 'setWhere'; where: WhereAnswer }
  | { type: 'setDrawGeom'; geom: KindGeom }
  | { type: 'addPlace'; place: Place }
  | { type: 'removePlace'; index: number }
  | { type: 'setYears'; years: number[] }
  | { type: 'setSame'; same: boolean }
  | { type: 'setNumbers'; quantity?: string; budget?: string }
  | { type: 'setYearValue'; year: number; quantity?: string; budget?: string }
  | { type: 'setName'; name: string }
  | { type: 'goto'; step: WizardStep }
  | { type: 'next' }
  | { type: 'back' }
  | { type: 'skip' }
  | { type: 'restart' }
  /** after a save: keep the activity and its numbers, forget the places (the "add another place" path) */
  | { type: 'addAnotherPlace'; existing: ExistingLine };

const sortedUnique = (years: number[]): number[] =>
  [...new Set(years.filter((y) => PLAN_YEARS.includes(y)))].sort((a, b) => a - b);

function move(state: WizardState, delta: 1 | -1): WizardState {
  const steps = stepsFor(state);
  const at = steps.indexOf(state.step);
  const next = steps[Math.min(Math.max(at + delta, 0), steps.length - 1)];
  return next === state.step ? state : { ...state, step: next };
}

export function wizardReducer(state: WizardState, action: WizardAction): WizardState {
  switch (action.type) {
    case 'chooseActivity': {
      const { activity, existing } = action;
      const base = initialWizard();
      // places drawn BEFORE the activity was chosen ("draw first, then say what it is") are kept for a mappable one
      const places = activity.requiresMap ? state.places : [];
      // an activity already in the plan: its years are the years the new place will belong to
      const next: WizardState = {
        ...base,
        activity,
        existing,
        places,
        drawGeom: drawGeomOf(activity),
        years: existing && existing.years.length > 0 ? existing.years : base.years,
        where: !activity.requiresMap ? null : places.length > 0 ? 'map' : existing?.wholeForest ? 'whole' : null,
      };
      return move({ ...next, step: 'what' }, 1);
    }
    case 'setWhere':
      // a different answer forgets the drawn places (they would be orphaned)
      return {
        ...state,
        where: action.where,
        places: action.where === 'map' ? state.places : [],
      };
    case 'setDrawGeom':
      return { ...state, drawGeom: action.geom };
    case 'addPlace':
      return { ...state, where: 'map', places: [...state.places, action.place] };
    case 'removePlace':
      return { ...state, places: state.places.filter((_, i) => i !== action.index) };
    case 'setYears': {
      const years = sortedUnique(action.years);
      // keep numbers typed for years that are still chosen
      const yearValues = Object.fromEntries(
        Object.entries(state.yearValues).filter(([y]) => years.includes(Number(y))),
      ) as Record<number, YearNumbers>;
      return { ...state, years, yearValues };
    }
    case 'setSame':
      return { ...state, same: action.same };
    case 'setNumbers':
      return {
        ...state,
        quantity: action.quantity ?? state.quantity,
        budget: action.budget ?? state.budget,
      };
    case 'setYearValue': {
      const current = state.yearValues[action.year] ?? { quantity: state.quantity, budget: state.budget };
      return {
        ...state,
        yearValues: {
          ...state.yearValues,
          [action.year]: {
            quantity: action.quantity ?? current.quantity,
            budget: action.budget ?? current.budget,
          },
        },
      };
    }
    case 'setName':
      return { ...state, name: action.name };
    case 'goto':
      return stepsFor(state).includes(action.step) ? { ...state, step: action.step } : state;
    case 'next':
      return move(state, 1);
    case 'back':
      return move(state, -1);
    case 'skip':
      // "Decide later" is how a mappable activity's WHERE step is skipped; NAME is optional anyway
      if (state.step === 'where') return move({ ...state, where: 'later', places: [] }, 1);
      if (state.step === 'name') return move({ ...state, name: '' }, 1);
      return state;
    case 'restart':
      return initialWizard();
    case 'addAnotherPlace':
      return {
        ...state,
        existing: action.existing,
        years: action.existing.years.length > 0 ? action.existing.years : state.years,
        where: 'map',
        places: [],
        name: '',
        step: 'where',
      };
    default:
      return state;
  }
}
