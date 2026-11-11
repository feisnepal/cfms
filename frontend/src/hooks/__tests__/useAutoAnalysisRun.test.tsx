/** Follows the automatic user group analysis: polls while it runs and tells the workspace when a run finishes. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';

const getAnalysisStatus = vi.fn();
vi.mock('../../services/api', () => ({ userGroupApi: { getAnalysisStatus: (...a: any[]) => getAnalysisStatus(...a) } }));

import { useAutoAnalysisRun } from '../useAutoAnalysisRun';
import { useWorkspaceStore } from '../../store/workspaceStore';

const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };

beforeEach(() => {
  vi.useFakeTimers();
  getAnalysisStatus.mockReset();
  useWorkspaceStore.setState({ userGroupAnalysis: null, geometryVersion: 0 } as never);
});
afterEach(() => vi.useRealTimers());

describe('useAutoAnalysisRun', () => {
  it('keeps asking while the analysis runs and calls onFinished exactly once when it ends', async () => {
    getAnalysisStatus
      .mockResolvedValueOnce({ state: 'running', steps: {} })
      .mockResolvedValueOnce({ state: 'running', steps: {} })
      .mockResolvedValue({ state: 'done', finished_at: '2026-10-12T10:00:00Z', steps: { settlements: 'done', land_cover: 'done' } });
    const onFinished = vi.fn();
    renderHook(() => useAutoAnalysisRun('c1', onFinished));
    await flush();
    expect(useWorkspaceStore.getState().userGroupAnalysis?.state).toBe('running');
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(useWorkspaceStore.getState().userGroupAnalysis?.state).toBe('running');
    expect(onFinished).not.toHaveBeenCalled();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(useWorkspaceStore.getState().userGroupAnalysis).toMatchObject({ state: 'done', finishedAt: '2026-10-12T10:00:00Z' });
    expect(onFinished).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(getAnalysisStatus).toHaveBeenCalledTimes(3); // stopped polling once it was done
  });

  it('does not announce a finish for an analysis it never saw running (opening a forest that was analysed long ago)', async () => {
    getAnalysisStatus.mockResolvedValue({ state: 'done', steps: {} });
    const onFinished = vi.fn();
    renderHook(() => useAutoAnalysisRun('c1', onFinished));
    await flush();
    expect(useWorkspaceStore.getState().userGroupAnalysis?.state).toBe('done');
    expect(onFinished).not.toHaveBeenCalled();
  });

  it('asks again when the geometry changes, because a changed polygon starts a new run on the server', async () => {
    getAnalysisStatus.mockResolvedValue({ state: 'done', steps: {} });
    renderHook(() => useAutoAnalysisRun('c1'));
    await flush();
    expect(getAnalysisStatus).toHaveBeenCalledTimes(1);
    await act(async () => { useWorkspaceStore.setState({ geometryVersion: 1 } as never); });
    await flush();
    expect(getAnalysisStatus).toHaveBeenCalledTimes(2);
  });

  it('shows no status (rather than a wrong one) when the status cannot be read', async () => {
    useWorkspaceStore.setState({ userGroupAnalysis: { state: 'running' } } as never);
    getAnalysisStatus.mockRejectedValue(new Error('offline'));
    renderHook(() => useAutoAnalysisRun('c1'));
    await flush();
    expect(useWorkspaceStore.getState().userGroupAnalysis).toBeNull();
  });
});
