import { describe, expect, it } from 'vitest';
import type { YearlyPlanLine } from '../../../services/api';
import { PLAN_YEAR_NUMBERS, planTotalBudget, sortPlanLines, yearCell } from '../planTableRules';

const line = (over: Partial<YearlyPlanLine>): YearlyPlanLine => ({
  id: 'a',
  potential_activity_id: 1,
  activity: 'Nursery',
  program: 'Forest',
  unit: 'ha',
  requires_map: true,
  default_quantity: 1,
  default_yearly_budget: 0,
  years: [],
  planned_years: [],
  total_budget: 0,
  version: 1,
  reviewed_at: null,
  placeholder_fields: [],
  feature_count: 0,
  location_mode: 'places',
  assign_to_all_blocks: false,
  status: 'planned',
  notes: null,
  ...over,
});

const yr = (year: number, quantity: number, budget: number) => ({ year, quantity, budget, planned: quantity > 0 || budget > 0, has_row: true });

describe('yearCell', () => {
  it('a year is planned when the quantity or the budget is above zero', () => {
    const l = line({ years: [yr(1, 5, 5000), yr(2, 5, 0), yr(3, 0, 5000), yr(4, 0, 0)] });
    expect(yearCell(l, 1)).toEqual({ year: 1, planned: true, quantity: 5, budget: 5000 });
    expect(yearCell(l, 2)).toEqual({ year: 2, planned: true, quantity: 5, budget: 0 }); // planned, no cost
    expect(yearCell(l, 3)).toEqual({ year: 3, planned: true, quantity: 0, budget: 5000 }); // funded, no countable output
    expect(yearCell(l, 4)).toEqual({ year: 4, planned: false, quantity: 0, budget: 0 }); // not planned
  });
  it('a year the server did not send, or a value that is not a number, is "not planned" — never an error', () => {
    const l = line({ years: [{ year: 1, quantity: Number.NaN, budget: Number.NaN, planned: false, has_row: false }] });
    expect(yearCell(l, 1).planned).toBe(false);
    expect(yearCell(l, 7)).toEqual({ year: 7, planned: false, quantity: 0, budget: 0 });
  });
  it('the grid has the ten years of the plan, in order', () => {
    expect([...PLAN_YEAR_NUMBERS]).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]);
  });
});

describe('sortPlanLines', () => {
  it('orders by programme, then activity, and does not change the input', () => {
    const input = [
      line({ id: '3', program: 'B', activity: 'Zed' }),
      line({ id: '1', program: 'A', activity: 'Beta' }),
      line({ id: '2', program: 'A', activity: 'Alpha' }),
    ];
    const copy = [...input];
    expect(sortPlanLines(input).map((l) => l.id)).toEqual(['2', '1', '3']);
    expect(input).toEqual(copy);
  });
  it('is stable for two lines with the same name (a repeated name in the master list)', () => {
    const out = sortPlanLines([line({ id: 'y', activity: 'Other' }), line({ id: 'x', activity: 'Other' })]);
    expect(out.map((l) => l.id)).toEqual(['x', 'y']);
  });
});

describe('planTotalBudget', () => {
  it('adds the lines and counts a zero budget as zero', () => {
    expect(planTotalBudget([line({ total_budget: 5000 }), line({ id: 'b', total_budget: 0 }), line({ id: 'c', total_budget: 250.5 })])).toBe(5250.5);
  });
  it('is 0 for an empty plan and ignores a value that is not a number', () => {
    expect(planTotalBudget([])).toBe(0);
    expect(planTotalBudget([line({ total_budget: Number.NaN as unknown as number })])).toBe(0);
  });
});
