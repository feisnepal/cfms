import type { YearlyPlanLine } from '../../services/api';

export type TableView = 'features' | 'plan';

/** The ten years of a plan, in the order the grid shows them. */
export const PLAN_YEAR_NUMBERS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

export interface YearCell {
  year: number;
  /** false ⇔ quantity 0 and budget 0: nothing is planned that year (the one rule of plan §5.4) */
  planned: boolean;
  quantity: number;
  budget: number;
}

/**
 * One year of a plan line as the grid shows it. The server already sends the *effective* values (the year's own
 * value, or the line's default when the year has none), so this only guards against a missing year or a value
 * that is not a number — a missing year is "not planned", never an error.
 */
export function yearCell(line: Pick<YearlyPlanLine, 'years'>, year: number): YearCell {
  const row = line.years.find((y) => y.year === year);
  const quantity = Number(row?.quantity);
  const budget = Number(row?.budget);
  const q = Number.isFinite(quantity) ? quantity : 0;
  const b = Number.isFinite(budget) ? budget : 0;
  return { year, planned: q > 0 || b > 0, quantity: q, budget: b };
}

/**
 * The plan's lines in the order a person reads them: by programme, then by activity name, so the table does not
 * jump about when a number is edited (the server returns them in id order).
 */
export function sortPlanLines(lines: YearlyPlanLine[]): YearlyPlanLine[] {
  const key = (l: YearlyPlanLine) => `${l.program ?? ''}\u0000${l.activity ?? ''}`;
  return [...lines].sort((a, b) => key(a).localeCompare(key(b)) || a.id.localeCompare(b.id));
}

/** The whole plan's budget: the sum of each line's own total (a zero budget counts as zero, never as missing). */
export function planTotalBudget(lines: YearlyPlanLine[]): number {
  return lines.reduce((sum, l) => sum + (Number.isFinite(Number(l.total_budget)) ? Number(l.total_budget) : 0), 0);
}
