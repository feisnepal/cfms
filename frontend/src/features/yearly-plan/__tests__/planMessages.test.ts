import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import en from '../../../i18n/locales/en.json';
import ne from '../../../i18n/locales/ne.json';
import { describeCode, describeIssue, describeNextStep, stepKey } from '../planMessages';
import { planErrorKind, planSaveErrorMessage } from '../planErrors';
import type { YearlyPlanHealth } from '../../../services/api';

type Bundle = Record<string, unknown>;

/** A tiny `t` over the REAL catalogue: nested keys, `_one` / `_other`, `{{x}}` interpolation. */
function makeT(bundle: Bundle): TFunction {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Bundle | undefined)?.[part], bundle);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    let node = lookup(key);
    if (node === undefined && typeof values.count === 'number') {
      node = lookup(`${key}_${values.count === 1 ? 'one' : 'other'}`);
    }
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return t as unknown as TFunction;
}

const tEn = makeT(en);
const tNe = makeT(ne);

const summary = { ready: 1, needs_attention: 2, total: 3, total_budget: 1250000 };

describe('stepKey', () => {
  it('words a placeholder line by what is still a starting value', () => {
    expect(stepKey('PLACEHOLDER_NUMBERS', { fields: ['quantity', 'budget'] })).toBe('PLACEHOLDER_both');
    expect(stepKey('PLACEHOLDER_NUMBERS', { fields: ['quantity'] })).toBe('PLACEHOLDER_quantity');
    expect(stepKey('PLACEHOLDER_NUMBERS', { fields: ['budget'] })).toBe('PLACEHOLDER_budget');
    expect(stepKey('NO_LOCATION', {})).toBe('NO_LOCATION');
  });
});

describe('describeCode', () => {
  it('names the activity and the place to act', () => {
    const view = describeCode('NO_LOCATION', {}, 'show_on_map', 'L1', 'Nursery construction', tEn);
    expect(view.text).toBe(
      '“Nursery construction” has no place on the map yet. Show where you will do it so it appears on the map and in the plan.',
    );
    expect(view.button).toBe('Show on map');
    expect(view.action).toBe('show_on_map');
    expect(view.activityId).toBe('L1');
  });

  it('says only the quantity is a starting value when only the quantity is', () => {
    const view = describeCode('PLACEHOLDER_NUMBERS', { fields: ['quantity'] }, 'enter_numbers', 'L1', 'Trail', tEn);
    expect(view.text).toContain('The quantity for “Trail” is still the starting value (1 every year)');
    expect(view.text).not.toContain('budget');
    expect(view.confirmable).toBe(true);
  });

  it('puts the years and the unusual amount in the sentence', () => {
    const years = describeCode('FEATURE_YEAR_UNPLANNED', { years: [4, 5] }, 'plan_year', 'L1', 'Road', tEn);
    expect(years.text).toContain('Year 4, 5');
    const amount = describeCode('UNUSUAL_AMOUNT', { yearly_budget: 5000000 }, 'check_amount', 'L1', 'Road', tEn);
    expect(amount.text).toContain('NPR 5,000,000 a year');
  });

  it('a step that is only informational cannot be confirmed away by mistake', () => {
    expect(describeCode('NO_LOCATION', {}, 'show_on_map', 'L1', 'A', tEn).confirmable).toBe(false);
    expect(describeCode('NOT_PLANNED_ANY_YEAR', {}, 'choose_years', 'L1', 'A', tEn).confirmable).toBe(false);
  });
});

describe('describeNextStep / describeIssue', () => {
  const health = (step: Partial<YearlyPlanHealth['next_step']>): YearlyPlanHealth => ({
    summary,
    next_step: { code: 'ALL_READY', activity_id: null, params: {}, action: 'create_plan', ...step },
    items: [],
    plan_issues: [],
  });

  it('all ready reports the count and the ten-year total', () => {
    const view = describeNextStep(health({}), tEn);
    expect(view.text).toBe('Your yearly plan is ready: 3 activities, NPR 1,250,000 over 10 years.');
    expect(view.button).toBe('Create the plan');
  });

  it('an empty plan asks for the first activity', () => {
    const view = describeNextStep(health({ code: 'EMPTY_PLAN', action: 'add_first_activity' }), tEn);
    expect(view.text).toContain("You haven't planned any activity yet");
    expect(view.button).toBe('Add your first activity');
  });

  it('a checklist row is worded like the card', () => {
    const view = describeIssue(
      { code: 'NOT_PLANNED_ANY_YEAR', severity: 'todo', params: {}, action: 'choose_years' },
      'L2',
      'Fire line',
      tEn,
    );
    expect(view.text).toBe('“Fire line” is not planned in any year. Choose the years you will do it.');
  });
});

describe('the catalogue', () => {
  const KEYS = [
    'EMPTY_PLAN',
    'NO_LOCATION',
    'PLACEHOLDER_quantity',
    'PLACEHOLDER_budget',
    'PLACEHOLDER_both',
    'NOT_PLANNED_ANY_YEAR',
    'FEATURE_YEAR_UNPLANNED',
    'UNUSUAL_AMOUNT',
    'NO_BUDGET_ANY_YEAR',
    'ALL_READY',
  ];

  it.each(KEYS)('%s has a sentence and a button in BOTH languages', (key) => {
    for (const [t, bundle] of [[tEn, en], [tNe, ne]] as const) {
      const text = t(`yearlyPlan.next.${key}.text`, { activity: 'X', years: '1', amount: '1', activities: '1', total: '1' });
      const button = t(`yearlyPlan.next.${key}.button`);
      expect(text).not.toBe(`yearlyPlan.next.${key}.text`);
      expect(button).not.toBe(`yearlyPlan.next.${key}.button`);
      expect(bundle).toBeTruthy();
    }
  });

  it.each(KEYS)('%s: every {{placeholder}} of the English is also in the Nepali', (key) => {
    const pick = (b: Bundle) =>
      ((b.yearlyPlan as Bundle).next as Bundle)[key] as { text: string };
    const names = (s: string) => [...s.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]);
    const enNames = names(pick(en).text);
    const neNames = names(pick(ne).text);
    for (const name of enNames) expect(neNames).toContain(name);
  });

  it('the Nepali uses the system\'s own words for activity, quantity and budget', () => {
    const both = (ne.yearlyPlan.next.PLACEHOLDER_both as { text: string }).text;
    expect(both).toContain('परिमाण');
    expect(both).toContain('बजेट');
    expect(ne.yearlyPlan.next.NO_LOCATION.text).toContain('योजना');
    expect(ne.yearlyPlan.next.EMPTY_PLAN.text).toContain('क्रियाकलाप');
  });
});

describe('planSaveErrorMessage — the server\'s own words never reach the user', () => {
  const raw = 'Input should be greater than 0';

  it('classifies the reason', () => {
    expect(planErrorKind({ response: { status: 409, data: { detail: raw } } })).toBe('saveConflict');
    expect(planErrorKind({ response: { status: 422, data: { detail: raw } } })).toBe('saveInvalid');
    expect(planErrorKind({ response: { status: 500 } })).toBe('saveGeneric');
    expect(planErrorKind({ request: {}, code: 'ERR_NETWORK' })).toBe('saveConnection');
    expect(planErrorKind(new Error('boom'))).toBe('saveGeneric');
    expect(planErrorKind(undefined)).toBe('saveGeneric');
  });

  it('shows the catalogue wording, never the raw detail, in both languages', () => {
    const err = { response: { status: 422, data: { detail: raw } } };
    const english = planSaveErrorMessage(err, tEn);
    const nepali = planSaveErrorMessage(err, tNe);
    expect(english).not.toContain('Input should be');
    expect(english).toContain('Nothing was changed');
    expect(nepali).toContain('केही परिवर्तन भएको छैन');
  });

  it('says the data is safe on an unknown failure', () => {
    expect(planSaveErrorMessage({ response: { status: 500 } }, tEn)).toContain('Your data is safe');
  });
});
