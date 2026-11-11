/**
 * useWorkflowReadiness — the staleness contract. WORKSPACE_FLOW_NAV_PLAN P3.
 *
 * The hook exists to answer three questions for the strip, the badges and the
 * stepper, so the tests concentrate on the parts that are easy to get subtly
 * wrong and impossible to notice:
 *
 *  1. **It never enforces.** A failed readiness read leaves the workspace usable
 *     and every step reachable. This is the governing rule, and the only way to
 *     keep it is to assert it.
 *  2. **Staleness is a flag, not a state change.** A step whose completion
 *     predates a geometry bump stays *done*; the hook adds a flag and changes
 *     nothing else. Making staleness clear completion would be the system
 *     enforcing, which is exactly what it must not do.
 *  3. **The clock is recorded once, then compared.** First sighting of a done step
 *     records the current version and is not a flag. Only a *later* bump flags.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const readinessMock = vi.fn();

// `vi.mock` paths resolve relative to THIS file, not to the hook, so the path is
// `../../services/api` even though the hook writes `'../services/api'`.
vi.mock('../../services/api', () => ({
  workflowApi: { readiness: (...args: unknown[]) => readinessMock(...args) },
}));

import { useWorkflowReadiness } from '../useWorkflowReadiness';

const CALC = 'c1';
const KEY = `cfms.workflowSeen:${CALC}`;

const payload = (over: Partial<Record<string, unknown>> = {}) => ({
  geometry_version: 4,
  map_finished: true,
  steps: {
    sampling: { done: true, status: 'available', reason_en: '', reason_ne: '', hint_en: '', hint_ne: '' },
    fieldinventory: { done: false, status: 'partial', reason_en: 'No inventory.', reason_ne: 'x', hint_en: 'y', hint_ne: 'z' },
  },
  done_count: 1,
  tracked_count: 2,
  non_tracked: ['treemodel'],
  ...over,
});

beforeEach(() => {
  localStorage.clear();
  readinessMock.mockReset();
});

describe('useWorkflowReadiness', () => {
  it('loads and exposes per-step completion', async () => {
    readinessMock.mockResolvedValue(payload());
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isDone('sampling')).toBe(true);
    expect(result.current.isDone('fieldinventory')).toBe(false);
    // progress counts the REQUIRED steps (the 10 the user must act on); the server's own tally is not used
    expect(result.current.doneCount).toBe(1);
    expect(result.current.totalCount).toBe(10);
    expect(result.current.mapFinished).toBe(true);
  });

  it('records the clock on first sighting, without flagging', async () => {
    // Seeing a done step for the first time establishes the baseline. Flagging
    // here would tell the user their work is stale the moment they open it.
    readinessMock.mockResolvedValue(payload({ geometry_version: 4 }));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.stale).toEqual([]);
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ sampling: 4 });
  });

  it('flags a step whose completion predates a later geometry change', async () => {
    localStorage.setItem(KEY, JSON.stringify({ sampling: 2 }));
    readinessMock.mockResolvedValue(payload({ geometry_version: 4 }));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.stale).toEqual([{ step: 'sampling', seen: 2 }]);
  });

  it('does not flag a step that is not done yet', async () => {
    // Nothing to be stale relative to.
    localStorage.setItem(KEY, JSON.stringify({ fieldinventory: 1 }));
    readinessMock.mockResolvedValue(payload({ geometry_version: 4 }));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.stale).toEqual([]);
  });

  it('staleness does not clear completion', async () => {
    localStorage.setItem(KEY, JSON.stringify({ sampling: 1 }));
    readinessMock.mockResolvedValue(payload({ geometry_version: 9 }));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.stale.length).toBe(1));
    // Still done. The user decides whether to revisit; the system does not decide
    // for them.
    expect(result.current.isDone('sampling')).toBe(true);
  });

  it('does not flag when the clock has not moved', async () => {
    localStorage.setItem(KEY, JSON.stringify({ sampling: 4 }));
    readinessMock.mockResolvedValue(payload({ geometry_version: 4 }));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.stale).toEqual([]);
  });

  it('a failed read reports an error and does not throw', async () => {
    // A readiness strip that 500s, or a forest that is offline, must not take the
    // workspace with it.
    readinessMock.mockRejectedValue(new Error('network down'));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('network down');
    expect(result.current.readiness).toBeNull();
    // Everything reports "not done", which is a display state, not a lock.
    expect(result.current.isDone('sampling')).toBe(false);
    expect(result.current.doneCount).toBe(0);
    expect(result.current.totalCount).toBe(10);
  });

  it('recovers on refresh after a failure', async () => {
    readinessMock.mockRejectedValueOnce(new Error('offline'));
    const { result } = renderHook(() => useWorkflowReadiness(CALC));
    await waitFor(() => expect(result.current.error).toBe('offline'));

    readinessMock.mockResolvedValue(payload());
    await act(async () => {
      await result.current.refresh();
    });
    expect(result.current.error).toBeNull();
    expect(result.current.isDone('sampling')).toBe(true);
  });

  it('tolerates corrupt storage', async () => {
    localStorage.setItem(KEY, '{not json');
    readinessMock.mockResolvedValue(payload());
    const { result } = renderHook(() => useWorkflowReadiness(CALC));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.stale).toEqual([]);
    expect(result.current.isDone('sampling')).toBe(true);
  });

  it('does nothing without a calculation id', async () => {
    readinessMock.mockResolvedValue(payload());
    const { result } = renderHook(() => useWorkflowReadiness(undefined));
    await waitFor(() => expect(result.current.readiness).toBeNull());
    expect(readinessMock).not.toHaveBeenCalled();
  });
});
