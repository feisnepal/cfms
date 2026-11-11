/**
 * useWorkflowReadiness — how far along the work is, and what is stale.
 * WORKSPACE_FLOW_NAV_PLAN §8.3, phase P3.
 *
 * One call feeds three surfaces: the readiness strip, the per-step badges, and
 * the staleness flag. They used to be separate concerns each page answered for
 * itself, which is why the old rail could say nothing at all.
 *
 * The governing rule, restated because this hook is the easiest place to break
 * it: **the system sequences, it never enforces.** Nothing here disables a step,
 * returns a refusal, or hides a surface. An incomplete step is reported and stays
 * fully reachable. `Skip for now` in the stepper advances without marking a step
 * done; this hook is what makes that honest, because progress is reported
 * separately from navigation.
 *
 * Staleness is client-observed, and that is a deliberate limitation rather than
 * an oversight. No column anywhere records the value of
 * `calculations.geometry_version` at the moment a step was completed, so there is
 * no server-side "sampling was designed at version 7" to compare against. Adding
 * that column now would leave every existing row NULL — permanently "unknown" —
 * and a migration whose backfill is a guess is worse than an honest approximation.
 * The clock is a monotonic counter, so the client records what it last saw and
 * flags a step whose completion predates a later bump. The label says exactly
 * that: "changed since you completed this".
 */
import { REQUIRED_STEPS } from '../components/calculation/workflowSteps';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { workflowApi, type WorkflowReadiness, type WorkflowStepState } from '../services/api';

/** Per-step id -> the `geometry_version` the client last saw that step done. */
const SEEN_PREFIX = 'cfms.workflowSeen:';

function readSeen(calculationId: string): Record<string, number> {
  try {
    const raw = localStorage.getItem(SEEN_PREFIX + calculationId);
    return raw ? (JSON.parse(raw) as Record<string, number>) : {};
  } catch {
    // Corrupt or unavailable storage is not a reason to fail the workspace.
    return {};
  }
}

function writeSeen(calculationId: string, seen: Record<string, number>): void {
  try {
    localStorage.setItem(SEEN_PREFIX + calculationId, JSON.stringify(seen));
  } catch {
    /* quota or private mode — staleness degrades to off, nothing else */
  }
}

export interface StaleFlag {
  step: string;
  seen: number;
}

export interface UseWorkflowReadiness {
  loading: boolean;
  error: string | null;
  readiness: WorkflowReadiness | null;
  /** Completion per step id. Absent means the server has no rule for it. */
  steps: Record<string, WorkflowStepState>;
  /** Steps flagged as completed before a later geometry change. */
  stale: StaleFlag[];
  doneCount: number;
  totalCount: number;
  mapFinished: boolean;
  isDone: (stepId: string) => boolean;
  /** Re-read on demand — used after a write, and by the strip's refresh. */
  refresh: () => Promise<void>;
}

export function useWorkflowReadiness(calculationId: string | undefined): UseWorkflowReadiness {
  const [readiness, setReadiness] = useState<WorkflowReadiness | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState<StaleFlag[]>([]);
  // Read inside `refresh` without making it a dependency, so the callback stays
  // stable and a re-render cannot loop the poll.
  const seenRef = useRef<Record<string, number>>({});

  useEffect(() => {
    seenRef.current = calculationId ? readSeen(calculationId) : {};
    setStale([]);
  }, [calculationId]);

  const refresh = useCallback(async () => {
    if (!calculationId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await workflowApi.readiness(calculationId);
      setReadiness(data);

      // Record the clock for every step that is done, then flag the ones whose
      // recorded version is behind the current one.
      const seen = { ...seenRef.current };
      const flags: StaleFlag[] = [];
      const current = data.geometry_version;
      if (typeof current === 'number') {
        for (const [stepId, state] of Object.entries(data.steps ?? {})) {
          if (!state.done) continue;
          const previous = seen[stepId];
          if (previous === undefined) {
            seen[stepId] = current;
          } else if (current > previous) {
            flags.push({ step: stepId, seen: previous });
          }
        }
        if (Object.keys(seen).length !== Object.keys(seenRef.current).length) {
          seenRef.current = seen;
          writeSeen(calculationId, seen);
        }
      }
      setStale(flags);
    } catch (e) {
      // A readiness strip that 500s, or a forest offline, must not take the
      // workspace with it. Report and carry on with no readiness data.
      setError(e instanceof Error ? e.message : String(e));
      setReadiness(null);
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const steps = useMemo(() => readiness?.steps ?? {}, [readiness]);

  const isDone = useCallback(
    (stepId: string) => steps[stepId]?.done === true,
    [steps],
  );

  return {
    loading,
    error,
    readiness,
    steps,
    stale,
    // Progress is over the REQUIRED steps only (the ones the user must act on); the system-completed ones do not pad it.
    doneCount: REQUIRED_STEPS.filter((st) => steps[st.id]?.done === true).length,
    totalCount: REQUIRED_STEPS.length,
    mapFinished: readiness?.map_finished ?? false,
    isDone,
    refresh,
  };
}

export default useWorkflowReadiness;
