import type { PlanLineEdit, YearlyPlanLine } from '../../services/api';
import type { YearCell } from './planTableRules';

/**
 * Editing numbers in the Yearly plan table (plan §4.7, §4.8). Pure functions: what was typed is checked here, and
 * the request to the server is built here — the server applies the first-value rule (D15), so the client sends
 * only what the person actually changed and never a whole line that would look like ten typed years.
 */
export type PlanField = 'quantity' | 'budget';
export type AmountKind = 'default' | 'year';
export type AmountCheck =
  | { ok: true; value: number }
  | { ok: false; reason: 'empty' | 'notNumber' | 'negative' | 'notPositive' };

/**
 * Check one typed amount. A year may be 0 in either field ("nothing planned" needs both 0); the line's usual
 * quantity must stay above 0 (D17) and its usual budget may be 0.
 */
export function checkAmount(
  field: PlanField,
  kind: AmountKind,
  text: string,
  parse: (text: string) => number,
): AmountCheck {
  if (String(text ?? '').trim() === '') return { ok: false, reason: 'empty' };
  const value = parse(text);
  if (!Number.isFinite(value)) return { ok: false, reason: 'notNumber' };
  if (value < 0) return { ok: false, reason: 'negative' };
  if (field === 'quantity' && kind === 'default' && value === 0) return { ok: false, reason: 'notPositive' };
  return { ok: true, value };
}

/** Only the fields that differ from what the cell shows now (an unchanged field is never sent). */
export function changedFields(cell: YearCell, typed: { quantity: number; budget: number }): { quantity?: number; budget?: number } {
  const out: { quantity?: number; budget?: number } = {};
  if (typed.quantity !== cell.quantity) out.quantity = typed.quantity;
  if (typed.budget !== cell.budget) out.budget = typed.budget;
  return out;
}

/** The request for changing one year of a line. */
export function yearEdit(line: Pick<YearlyPlanLine, 'version'>, year: number, changes: { quantity?: number; budget?: number }): PlanLineEdit {
  return { years: [{ year, ...changes }], expected_version: line.version };
}

/** The request for changing the line's usual quantity or budget. */
export function defaultEdit(line: Pick<YearlyPlanLine, 'version'>, changes: { quantity?: number; budget?: number }): PlanLineEdit {
  const edit: PlanLineEdit = { expected_version: line.version };
  if (changes.quantity !== undefined) edit.default_quantity = changes.quantity;
  if (changes.budget !== undefined) edit.default_yearly_budget = changes.budget;
  return edit;
}

/**
 * The request that puts a line back as it was before an edit: the usual numbers and ALL ten years, explicitly.
 * Ten typed years never trigger the first-value rule again, so the numbers come back exactly; `unreview` clears
 * the reviewed flag an edit may have set when the line was not reviewed before.
 */
export function undoEdit(before: YearlyPlanLine, versionNow: number): PlanLineEdit {
  return {
    default_quantity: before.default_quantity,
    default_yearly_budget: before.default_yearly_budget,
    years: before.years.map((y) => ({ year: y.year, quantity: y.quantity, budget: y.budget })),
    expected_version: versionNow,
    unreview: before.reviewed_at === null,
  };
}

/** The result of a save, reduced to what the screen says about it. */
export function saveOutcome(filledYears: number[]): 'filled' | 'saved' {
  return filledYears.length > 0 ? 'filled' : 'saved';
}
