/**
 * The wizard's step machine (P3, YA-3.1): every path the plan describes in §4.4 / §4.4b, on the pure reducer.
 */
import { describe, expect, it } from 'vitest';
import type { CatalogueActivity } from '../../../lib/activitySearch';
import {
  canAdvance,
  initialWizard,
  stepsFor,
  wizardReducer,
  yearsOfPreset,
  type WizardAction,
  type WizardState,
} from '../wizard/wizardMachine';

const parse = (t: string) => (t.trim() === '' ? NaN : Number(t.replace(/,/g, '')));

const activity = (over: Partial<CatalogueActivity> = {}): CatalogueActivity => ({
  id: 1,
  name: 'नर्सरी निर्माण',
  nameEn: 'Build a nursery',
  searchTerms: null,
  programme: 'वन विकासका कार्यहरु',
  project: 'वन विकास',
  unit: 'वटा',
  requiresMap: true,
  mapKind: 'nursery',
  description: null,
  ...over,
});
const training = activity({ id: 41, name: 'नर्सरी व्यवस्थापन तालिम', unit: 'पटक', requiresMap: false, mapKind: null });
const POINT: GeoJSON.Geometry = { type: 'Point', coordinates: [85, 27] };
const EXISTING = { id: 'L1', version: 3, years: [1, 2], wholeForest: false };

const run = (actions: WizardAction[], from: WizardState = initialWizard()) =>
  actions.reduce((s, a) => wizardReducer(s, a), from);

describe('which steps a wizard goes through', () => {
  it('starts at WHAT with nothing chosen', () => {
    expect(initialWizard().step).toBe('what');
    expect(stepsFor(initialWizard())).toEqual(['what']);
  });

  it('a mappable new activity: WHERE, WHEN, HOW MUCH, CONFIRM (NAME only once there are places)', () => {
    const s = run([{ type: 'chooseActivity', activity: activity(), existing: null }]);
    expect(s.step).toBe('where');
    expect(stepsFor(s)).toEqual(['what', 'where', 'when', 'howMuch', 'confirm']);
    const drawn = run([{ type: 'addPlace', place: { geometry: POINT } }], s);
    expect(stepsFor(drawn)).toEqual(['what', 'where', 'when', 'howMuch', 'name', 'confirm']);
  });

  it('an activity that needs no map has no WHERE and no NAME step at all (§4.4b)', () => {
    const s = run([{ type: 'chooseActivity', activity: training, existing: null }]);
    expect(s.step).toBe('when');
    expect(stepsFor(s)).toEqual(['what', 'when', 'howMuch', 'confirm']);
  });

  it('an activity already in the plan skips WHEN and HOW MUCH and goes straight to "show where"', () => {
    const s = run([{ type: 'chooseActivity', activity: activity(), existing: EXISTING }]);
    expect(s.step).toBe('where');
    expect(s.years).toEqual([1, 2]); // the new place belongs to the line's planned years
    expect(stepsFor(s)).toEqual(['what', 'where', 'confirm']);
  });

  it('"Decide later" and "Whole forest" leave nothing to draw and have no NAME step', () => {
    const chosen = run([{ type: 'chooseActivity', activity: activity(), existing: null }]);
    for (const where of ['later', 'whole'] as const) {
      const s = run([{ type: 'setWhere', where }], chosen);
      expect(stepsFor(s)).toEqual(['what', 'where', 'when', 'howMuch', 'confirm']);
    }
  });
});

describe('moving between steps', () => {
  it('next and back walk the steps and stop at both ends', () => {
    let s = run([{ type: 'chooseActivity', activity: training, existing: null }]);
    expect(s.step).toBe('when');
    s = run([{ type: 'next' }, { type: 'next' }, { type: 'next' }], s);
    expect(s.step).toBe('confirm');
    s = run([{ type: 'back' }, { type: 'back' }, { type: 'back' }, { type: 'back' }, { type: 'back' }], s);
    expect(s.step).toBe('what');
  });

  it('"skip" on WHERE is "Decide later"; on NAME it keeps the name empty', () => {
    let s = run([{ type: 'chooseActivity', activity: activity(), existing: null }, { type: 'skip' }]);
    expect(s.where).toBe('later');
    expect(s.step).toBe('when');
    s = run([
      { type: 'chooseActivity', activity: activity(), existing: null },
      { type: 'addPlace', place: { geometry: POINT } },
      { type: 'goto', step: 'name' },
      { type: 'setName', name: 'A' },
      { type: 'skip' },
    ]);
    expect(s.name).toBe('');
    expect(s.step).toBe('confirm');
  });

  it('"goto" refuses a step the wizard does not have', () => {
    const s = run([{ type: 'chooseActivity', activity: training, existing: null }, { type: 'goto', step: 'where' }]);
    expect(s.step).toBe('when');
  });

  it('a different WHERE answer forgets the drawn places', () => {
    const s = run([
      { type: 'chooseActivity', activity: activity(), existing: null },
      { type: 'addPlace', place: { geometry: POINT } },
      { type: 'setWhere', where: 'whole' },
    ]);
    expect(s.places).toEqual([]);
  });

  it('drawing a place is the answer "show on the map"; places can be removed again', () => {
    let s = run([{ type: 'chooseActivity', activity: activity(), existing: null }, { type: 'addPlace', place: { geometry: POINT } }, { type: 'addPlace', place: { geometry: POINT } }]);
    expect(s.where).toBe('map');
    expect(s.places).toHaveLength(2);
    s = run([{ type: 'removePlace', index: 0 }], s);
    expect(s.places).toHaveLength(1);
  });
});

describe('what lets the person move on', () => {
  const at = (step: WizardState['step'], over: Partial<WizardState> = {}): WizardState => ({ ...initialWizard(), activity: activity(), step, ...over });

  it('WHAT needs an activity', () => {
    expect(canAdvance(initialWizard(), parse)).toBe(false);
    expect(canAdvance(at('what'), parse)).toBe(true);
  });

  it('WHERE needs an answer, and "show on the map" needs at least one place', () => {
    expect(canAdvance(at('where'), parse)).toBe(false);
    expect(canAdvance(at('where', { where: 'later' }), parse)).toBe(true);
    expect(canAdvance(at('where', { where: 'whole' }), parse)).toBe(true);
    expect(canAdvance(at('where', { where: 'map' }), parse)).toBe(false);
    expect(canAdvance(at('where', { where: 'map', places: [{ geometry: POINT }] }), parse)).toBe(true);
  });

  it('WHEN needs at least one year', () => {
    expect(canAdvance(at('when', { years: [] }), parse)).toBe(false);
    expect(canAdvance(at('when', { years: [3] }), parse)).toBe(true);
  });

  it('HOW MUCH: quantity above 0, budget 0 or more — a zero budget is fine', () => {
    expect(canAdvance(at('howMuch'), parse)).toBe(false);
    expect(canAdvance(at('howMuch', { quantity: '2', budget: '0' }), parse)).toBe(true);
    expect(canAdvance(at('howMuch', { quantity: '0', budget: '100' }), parse)).toBe(false);
    expect(canAdvance(at('howMuch', { quantity: '2', budget: '-1' }), parse)).toBe(false);
    expect(canAdvance(at('howMuch', { quantity: 'abc', budget: '5' }), parse)).toBe(false);
  });

  it('HOW MUCH, different each year: every chosen year needs its own numbers', () => {
    const s = at('howMuch', { same: false, years: [1, 2], yearValues: { 1: { quantity: '1', budget: '10' } } });
    expect(canAdvance(s, parse)).toBe(false);
    expect(canAdvance({ ...s, yearValues: { ...s.yearValues, 2: { quantity: '2', budget: '0' } } }, parse)).toBe(true);
  });

  it('NAME is optional; CONFIRM is the end', () => {
    expect(canAdvance(at('name'), parse)).toBe(true);
    expect(canAdvance(at('confirm'), parse)).toBe(false);
  });
});

describe('years and numbers', () => {
  it('year presets', () => {
    expect(yearsOfPreset('this')).toEqual([1]);
    expect(yearsOfPreset('first5')).toEqual([1, 2, 3, 4, 5]);
    expect(yearsOfPreset('every')).toHaveLength(10);
  });

  it('years are sorted, unique and kept to 1–10; numbers typed for a dropped year are forgotten', () => {
    let s = run([
      { type: 'chooseActivity', activity: training, existing: null },
      { type: 'setYears', years: [3, 1, 3, 11, 0] },
    ]);
    expect(s.years).toEqual([1, 3]);
    s = run([{ type: 'setSame', same: false }, { type: 'setYearValue', year: 3, quantity: '5', budget: '50' }, { type: 'setYears', years: [1] }], s);
    expect(s.yearValues).toEqual({});
  });

  it('a year row starts from the shared numbers and changes only what was edited', () => {
    const s = run([
      { type: 'chooseActivity', activity: training, existing: null },
      { type: 'setNumbers', quantity: '2', budget: '1000' },
      { type: 'setYearValue', year: 1, budget: '3000' },
    ]);
    expect(s.yearValues[1]).toEqual({ quantity: '2', budget: '3000' });
  });
});

describe('after a save', () => {
  it('"add another place" keeps the activity and goes back to WHERE for the now-existing line', () => {
    const s = run(
      [
        { type: 'chooseActivity', activity: activity(), existing: null },
        { type: 'addPlace', place: { geometry: POINT } },
        { type: 'addAnotherPlace', existing: { id: 'L9', version: 1, years: [1, 2, 3], wholeForest: false } },
      ],
    );
    expect(s.step).toBe('where');
    expect(s.places).toEqual([]);
    expect(s.years).toEqual([1, 2, 3]);
    expect(stepsFor(s)).toEqual(['what', 'where', 'confirm']); // the numbers are not asked again
  });

  it('restart forgets everything', () => {
    const s = run([{ type: 'chooseActivity', activity: activity(), existing: null }, { type: 'restart' }]);
    expect(s).toEqual(initialWizard());
  });
});
