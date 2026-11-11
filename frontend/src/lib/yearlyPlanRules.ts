/**
 * The frontend twin of `backend/app/services/yearly_plan_rules.py` — one definition of a
 * *planned year* for the yearly activity plan (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.4).
 *
 * A year is planned when its quantity is > 0 OR its budget is > 0; both 0 means "not planned that
 * year". A stored 0 is a real value — never "use the default" (`0 || fallback` was the defect).
 */

/** A number from an API value (Decimal arrives as a string). Only null / '' / NaN use the fallback;
 *  a real 0 stays 0. */
export function parseAmount(value: unknown, fallback: number): number {
  if (value === null || value === undefined || value === '') return fallback;
  const n = typeof value === 'number' ? value : parseFloat(String(value));
  return Number.isFinite(n) ? n : fallback;
}

/** Planned in a year <=> quantity > 0 or budget > 0. */
export function isPlanned(quantity: unknown, budget: unknown): boolean {
  return (Number(quantity) || 0) > 0 || (Number(budget) || 0) > 0;
}

/** `isPlanned` for a `{ quantity, budget }` year cell. */
export function isPlannedYear(year: { quantity?: unknown; budget?: unknown }): boolean {
  return isPlanned(year.quantity, year.budget);
}
