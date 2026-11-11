import { describe, expect, it } from 'vitest';
import { parseLocaleNumber } from '../../../i18n/numberFormat';
import type { YearlyPlanLine } from '../../../services/api';
import { changedFields, checkAmount, defaultEdit, saveOutcome, undoEdit, yearEdit } from '../planEdit';

const cell = { year: 1, planned: true, quantity: 1, budget: 5000 };
const year = (y: number, quantity = 1, budget = 5000) => ({ year: y, quantity, budget, planned: quantity > 0 || budget > 0, has_row: true });
const line = (over: Partial<YearlyPlanLine> = {}): YearlyPlanLine =>
  ({
    id: 'L',
    version: 4,
    default_quantity: 1,
    default_yearly_budget: 5000,
    reviewed_at: null,
    years: Array.from({ length: 10 }, (_, i) => year(i + 1)),
    ...over,
  }) as YearlyPlanLine;

describe('checkAmount', () => {
  const ok = (field: 'quantity' | 'budget', kind: 'default' | 'year', text: string) => checkAmount(field, kind, text, parseLocaleNumber);

  it('accepts a number, with either language’s digits and grouping', () => {
    expect(ok('budget', 'year', '5000')).toEqual({ ok: true, value: 5000 });
    expect(ok('budget', 'year', '5,000')).toEqual({ ok: true, value: 5000 });
    expect(ok('budget', 'year', '५०००')).toEqual({ ok: true, value: 5000 });
    expect(ok('quantity', 'year', '0.5')).toEqual({ ok: true, value: 0.5 });
  });
  it('a year may be 0 in either field — nothing planned needs both at 0', () => {
    expect(ok('quantity', 'year', '0')).toEqual({ ok: true, value: 0 });
    expect(ok('budget', 'year', '0')).toEqual({ ok: true, value: 0 });
  });
  it('the usual quantity of an activity stays above 0, but its usual budget may be 0 (D17)', () => {
    expect(ok('quantity', 'default', '0')).toEqual({ ok: false, reason: 'notPositive' });
    expect(ok('budget', 'default', '0')).toEqual({ ok: true, value: 0 });
  });
  it('refuses an empty field, text that is not a number, and a negative number', () => {
    expect(ok('budget', 'year', '  ')).toEqual({ ok: false, reason: 'empty' });
    expect(ok('budget', 'year', 'abc')).toEqual({ ok: false, reason: 'notNumber' });
    expect(ok('budget', 'year', '-5')).toEqual({ ok: false, reason: 'negative' });
  });
});

describe('what is sent', () => {
  it('a year edit sends only the fields that changed, with the version it was read at', () => {
    expect(changedFields(cell, { quantity: 1, budget: 7000 })).toEqual({ budget: 7000 });
    expect(changedFields(cell, { quantity: 2, budget: 5000 })).toEqual({ quantity: 2 });
    expect(changedFields(cell, { quantity: 1, budget: 5000 })).toEqual({});
    expect(yearEdit(line(), 3, { budget: 7000 })).toEqual({ years: [{ year: 3, budget: 7000 }], expected_version: 4 });
  });
  it('changing the usual quantity or budget sends just that one', () => {
    expect(defaultEdit(line(), { quantity: 3 })).toEqual({ default_quantity: 3, expected_version: 4 });
    expect(defaultEdit(line(), { budget: 0 })).toEqual({ default_yearly_budget: 0, expected_version: 4 });
  });
  it('Undo sends the usual numbers and ALL ten years explicitly, at the version now, and unreviews a line that was not reviewed', () => {
    const before = line({ years: Array.from({ length: 10 }, (_, i) => year(i + 1, i === 0 ? 0 : 1, i === 0 ? 0 : 5000)) });
    const edit = undoEdit(before, 9);
    expect(edit.years).toHaveLength(10);
    expect(edit.years![0]).toEqual({ year: 1, quantity: 0, budget: 0 }); // a 0 is restored as a 0
    expect(edit).toMatchObject({ default_quantity: 1, default_yearly_budget: 5000, expected_version: 9, unreview: true });
  });
  it('Undo leaves a line that was already reviewed reviewed', () => {
    expect(undoEdit(line({ reviewed_at: '2026-09-21T00:00:00Z' }), 5).unreview).toBe(false);
  });
});

describe('saveOutcome', () => {
  it('says "filled" only when the first-value rule filled other years', () => {
    expect(saveOutcome([2, 3, 4])).toBe('filled');
    expect(saveOutcome([])).toBe('saved');
  });
});
