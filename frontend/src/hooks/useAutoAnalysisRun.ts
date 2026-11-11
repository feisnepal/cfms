/**
 * The automatic user group analysis, as a status on the layer (owner, 2026-10-12: nothing for the user to press, and no silent waiting).
 *
 * Reads the status stored with the calculation, keeps asking every few seconds while it is `running`, and when a run FINISHES calls
 * `onFinished` so the workspace re-reads the layer and its data. Asks again whenever the geometry changes, because a changed polygon starts
 * a new run on the server.
 */
import { useCallback, useEffect, useRef } from 'react';
import { userGroupApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';

const POLL_MS = 3000;
const GIVE_UP_AFTER_MS = 10 * 60 * 1000;

export function useAutoAnalysisRun(calculationId: string | null | undefined, onFinished?: () => void): () => Promise<void> {
  const setStatus = useWorkspaceStore((s) => s.setUserGroupAnalysis);
  const geometryVersion = useWorkspaceStore((s) => s.geometryVersion);
  const last = useRef<string>('idle');
  const finished = useRef(onFinished);
  finished.current = onFinished;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startedAt = useRef<number>(0);

  const check = useCallback(async () => {
    if (!calculationId) return;
    try {
      const st = await userGroupApi.getAnalysisStatus(calculationId);
      setStatus({ state: st.state, message: st.message ?? null, finishedAt: st.finished_at ?? null });
      if (last.current === 'running' && st.state !== 'running') finished.current?.();
      last.current = st.state;
      if (st.state === 'running' && Date.now() - startedAt.current < GIVE_UP_AFTER_MS) {
        timer.current = setTimeout(() => void check(), POLL_MS);
      }
    } catch {
      setStatus(null); // not readable (offline / no access): show nothing rather than a wrong status
    }
  }, [calculationId, setStatus]);

  useEffect(() => {
    startedAt.current = Date.now();
    void check();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [check, geometryVersion]);

  return check;
}
