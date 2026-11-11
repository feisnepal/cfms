/**
 * A failed save/load, worded for the user (YEARLY_ACTIVITIES_WORKSPACE_PLAN §4.6).
 *
 * The legacy pages used to show `Failed to save: {{detail}}` — the server's raw validation sentence
 * ("Input should be greater than 0") — or "Unknown error occurred". Neither says whether the data is
 * safe or what to do. The server's own text is never shown: the reason is classified, and the wording
 * comes from the `yearlyPlan.error.*` catalogue.
 */
import type { TFunction } from 'i18next';

export type PlanErrorKind = 'saveConnection' | 'saveInvalid' | 'saveConflict' | 'notOwner' | 'saveGeneric';

interface HttpishError {
  response?: { status?: number };
  /** the fetch-based routes' error (ActivityFeatureApiError) carries the status itself */
  status?: number;
  request?: unknown;
  code?: string;
}

/** What went wrong, from the error alone. */
export function planErrorKind(error: unknown): PlanErrorKind {
  const e = (error ?? {}) as HttpishError;
  const status = e.response?.status ?? e.status;
  if (status === 409) return 'saveConflict';
  // D9: only the owner reaches the plan routes — for anyone else (a super-admin included) they answer 404
  if (status === 404) return 'notOwner';
  if (status === 400 || status === 422) return 'saveInvalid';
  // axios: a request that got no response at all is a connection problem; fetch rejects with a TypeError
  if (!e.response && status === undefined && (e.code === 'ERR_NETWORK' || e.request || error instanceof TypeError)) {
    return 'saveConnection';
  }
  return 'saveGeneric';
}

/** Plain words for a failed save. Never contains the server's text. */
export function planSaveErrorMessage(error: unknown, t: TFunction): string {
  return t(`yearlyPlan.error.${planErrorKind(error)}`) as string;
}

/**
 * Plain words for a failed edit in the activity-features table. The generic case says the table shows the
 * last saved values (the messages above talk about typed quantities, which is not what happened here).
 */
export function planTableErrorMessage(error: unknown, t: TFunction): string {
  const kind = planErrorKind(error);
  if (kind === 'saveConflict' || kind === 'saveConnection' || kind === 'notOwner') return t(`yearlyPlan.error.${kind}`) as string;
  return t('yearlyPlan.error.tableFailed') as string;
}
