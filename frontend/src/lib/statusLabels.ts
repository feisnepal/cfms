/**
 * Display keys for status values that live in the database.
 *
 * These columns store a stable English enum ('processing', 'draft', 'Common')
 * and several screens printed that value straight into the DOM, so a Nepali
 * reader saw the raw stored token. The stored value never changes — only the
 * label resolves through these maps.
 *
 * Static maps rather than `t(\`status.job.${x}\`)`: a computed key is invisible
 * to both i18n gates, and the plan's conventions forbid `t(key, 'English
 * default')`. An unknown value falls back to the raw string at the call site.
 */

/** Long-running job state — inventory calculations and tree mapping. */
export const JOB_STATUS_KEY: Record<string, string> = {
  processing: 'status.job.processing',
  completed: 'status.job.completed',
  failed: 'status.job.failed',
  corrections_applied: 'status.job.correctionsApplied',
};

/** Operational-plan review state. */
export const PLAN_STATUS_KEY: Record<string, string> = {
  draft: 'status.plan.draft',
  submitted: 'status.plan.submitted',
  approved: 'status.plan.approved',
};

/** Species rarity, stored capitalised by the API. */
export const RARITY_STATUS_KEY: Record<string, string> = {
  common: 'status.rarity.common',
  uncommon: 'status.rarity.uncommon',
  rare: 'status.rarity.rare',
  endangered: 'status.rarity.endangered',
  threatened: 'status.rarity.threatened',
  vulnerable: 'status.rarity.vulnerable',
};

/** Resolve a status through a map, falling back to the raw stored value. */
export function statusLabel(
  map: Record<string, string>,
  value: string | null | undefined,
  t: (k: string) => string,
): string {
  if (!value) return '';
  const key = map[value] ?? map[value.toLowerCase()];
  return key ? t(key) : value;
}
