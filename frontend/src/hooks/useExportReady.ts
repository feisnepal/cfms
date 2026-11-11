import { useEffect, useState } from 'react';
import { operationalPlanApi } from '../services/api';

/**
 * Is this forest ready to export? The answer is the export gate's own (`export-requirements`), not the rail's progress count:
 * the rail also counts steps the gate does not require (the map, the area detail), so "all counted steps done" and "can export"
 * are not the same thing. `refreshKey` re-asks when the workflow readiness changed.
 */
export function useExportReady(calculationId: string | undefined, refreshKey: unknown): boolean {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!calculationId) {
      setReady(false);
      return;
    }
    let alive = true;
    operationalPlanApi
      .getExportRequirementsForCalculation(calculationId)
      .then((r) => alive && setReady(r.ready === true))
      .catch(() => alive && setReady(false)); // not the owner, or offline: no hand-off is offered
    return () => {
      alive = false;
    };
  }, [calculationId, refreshKey]);
  return ready;
}
