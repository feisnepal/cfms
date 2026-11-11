/**
 * Plain words for a failed save (P1) and, since P2, for a failed edit in the activity-features table, whose
 * errors come from `fetch` (a status on the error itself, or a TypeError when the network is down).
 */
import { describe, expect, it } from 'vitest';
import en from '../../../i18n/locales/en.json';
import { ActivityFeatureApiError } from '../../../lib/activityFeaturePayload';
import { planErrorKind, planSaveErrorMessage, planTableErrorMessage } from '../planErrors';

const t = ((key: string) => key.split('.').reduce<unknown>((n, p) => (n as Record<string, unknown>)?.[p], en) as string) as never;

describe('planErrorKind', () => {
  it('reads an axios-style response status', () => {
    expect(planErrorKind({ response: { status: 409 } })).toBe('saveConflict');
    expect(planErrorKind({ response: { status: 422 } })).toBe('saveInvalid');
    expect(planErrorKind({ response: { status: 500 } })).toBe('saveGeneric');
  });

  it('reads the status carried by a fetch-based error', () => {
    expect(planErrorKind(new ActivityFeatureApiError({ detail: 'x' }, 409))).toBe('saveConflict');
    expect(planErrorKind(new ActivityFeatureApiError({ detail: 'x' }, 500))).toBe('saveGeneric');
  });

  it('a 404 from a plan route means the person is not the owner (D9: a super-admin included)', () => {
    expect(planErrorKind({ response: { status: 404 } })).toBe('notOwner');
    expect(planErrorKind(new ActivityFeatureApiError({ detail: 'x' }, 404))).toBe('notOwner');
    expect(planSaveErrorMessage({ response: { status: 404 } }, t)).toBe(en.yearlyPlan.error.notOwner);
    expect(planTableErrorMessage(new ActivityFeatureApiError({}, 404), t)).toBe(en.yearlyPlan.error.notOwner);
  });

  it('a fetch that never got an answer (TypeError) is a connection problem', () => {
    expect(planErrorKind(new TypeError('Failed to fetch'))).toBe('saveConnection');
    expect(planErrorKind({ code: 'ERR_NETWORK' })).toBe('saveConnection');
  });
});

describe('planTableErrorMessage', () => {
  it('a conflict and a lost connection use the shared wording', () => {
    expect(planTableErrorMessage(new ActivityFeatureApiError({}, 409), t)).toBe(en.yearlyPlan.error.saveConflict);
    expect(planTableErrorMessage(new TypeError('Failed to fetch'), t)).toBe(en.yearlyPlan.error.saveConnection);
  });

  it('anything else says the table shows the last saved values, never the server text', () => {
    const msg = planTableErrorMessage(new ActivityFeatureApiError({ detail: 'relation missing' }, 500), t);
    expect(msg).toBe(en.yearlyPlan.error.tableFailed);
    expect(msg).not.toContain('relation');
  });

  it('a rejected value is not blamed on "quantity and budget" (that wording is for the plan numbers)', () => {
    expect(planTableErrorMessage(new ActivityFeatureApiError({ detail: 'x' }, 422), t)).toBe(en.yearlyPlan.error.tableFailed);
    expect(planSaveErrorMessage({ response: { status: 422 } }, t)).toBe(en.yearlyPlan.error.saveInvalid);
  });
});
