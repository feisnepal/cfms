import { useEffect, useState } from 'react';
import { yearlyPlanApi } from '../../services/api';
import { planErrorKind } from './planErrors';

/**
 * Who may plan this forest's yearly activities (D9): only its owner — not a super-admin. The plan routes answer
 * 404 to anyone else, so one cheap read tells the screen up front, and it can hide what would fail instead of
 * letting a person fill in a wizard that cannot save. `unknown` (still asking, or the read failed for another
 * reason) never blocks anything: the server refuses a write anyway.
 */
export type PlanAccess = 'unknown' | 'owner' | 'notOwner';

export function usePlanAccess(calculationId: string | undefined, enabled = true): PlanAccess {
  const [access, setAccess] = useState<PlanAccess>('unknown');

  useEffect(() => {
    if (!calculationId || !enabled) return undefined;
    let cancelled = false;
    setAccess('unknown');
    yearlyPlanApi
      .getHealth(calculationId)
      .then(() => {
        if (!cancelled) setAccess('owner');
      })
      .catch((err) => {
        if (!cancelled && planErrorKind(err) === 'notOwner') setAccess('notOwner');
      });
    return () => {
      cancelled = true;
    };
  }, [calculationId, enabled]);

  return access;
}
