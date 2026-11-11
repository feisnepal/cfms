import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const get = vi.fn();
const put = vi.fn();
vi.mock('../../services/api', () => ({ default: { get: (...a: unknown[]) => get(...a), put: (...a: unknown[]) => put(...a) } }));

import { mergeSaved, useFloatingPanelState } from '../useFloatingPanelState';

const defaults = { position: { x: 16, y: 16 }, collapsed: false, open: true };
const settle = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};

describe('mergeSaved', () => {
  it('takes what is valid and ignores the rest', () => {
    expect(mergeSaved(defaults, { position: { x: 50, y: 60 }, collapsed: true, open: false })).toEqual({
      position: { x: 50, y: 60 }, collapsed: true, open: false,
    });
    expect(mergeSaved(defaults, { position: { x: 'a', y: 1 }, collapsed: 'yes' })).toEqual(defaults);
    expect(mergeSaved(defaults, null)).toEqual(defaults);
  });
});

describe('useFloatingPanelState', () => {
  beforeEach(() => {
    get.mockReset();
    put.mockReset();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it('starts from the defaults, then applies the saved layout', async () => {
    get.mockResolvedValue({ data: { layout_json: { position: { x: 200, y: 80 }, collapsed: true, open: true } } });
    const { result } = renderHook(() => useFloatingPanelState('forest-summary:c1', defaults));
    expect(result.current.state).toEqual(defaults);
    await waitFor(() => expect(result.current.state.position).toEqual({ x: 200, y: 80 }));
    expect(result.current.state.collapsed).toBe(true);
    expect(get).toHaveBeenCalledWith('/api/v1/workspace/layout', { params: { layout_key: 'forest-summary:c1' } });
  });

  it('runs on the defaults when loading fails, and never throws', async () => {
    get.mockRejectedValue(new Error('offline'));
    const { result } = renderHook(() => useFloatingPanelState('forest-summary:c1', defaults));
    await settle();
    expect(result.current.state).toEqual(defaults);
    act(() => result.current.update({ collapsed: true }));
    expect(result.current.state.collapsed).toBe(true);
  });

  it('saves the last change once, after a pause, under the forest key', async () => {
    get.mockResolvedValue({ data: { layout_json: null } });
    put.mockResolvedValue({});
    const { result } = renderHook(() => useFloatingPanelState('forest-summary:c1', defaults));
    await settle();
    act(() => result.current.update({ position: { x: 1, y: 2 } }));
    act(() => result.current.update({ position: { x: 3, y: 4 } }));
    expect(put).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(700);
    });
    expect(put).toHaveBeenCalledTimes(1);
    expect(put.mock.calls[0][1]).toMatchObject({ layout_key: 'forest-summary:c1', layout_json: { position: { x: 3, y: 4 }, version: 1 } });
  });

  it('a failed save is swallowed', async () => {
    get.mockResolvedValue({ data: { layout_json: null } });
    put.mockRejectedValue(new Error('403'));
    const { result } = renderHook(() => useFloatingPanelState('k', defaults));
    await settle();
    act(() => result.current.update({ open: false }));
    await act(async () => {
      vi.advanceTimersByTime(700);
    });
    expect(result.current.state.open).toBe(false);
  });

  it('does nothing on the server without a forest key', async () => {
    const { result } = renderHook(() => useFloatingPanelState(null, defaults));
    act(() => result.current.update({ collapsed: true }));
    await act(async () => {
      vi.advanceTimersByTime(700);
    });
    expect(get).not.toHaveBeenCalled();
    expect(put).not.toHaveBeenCalled();
  });
});
