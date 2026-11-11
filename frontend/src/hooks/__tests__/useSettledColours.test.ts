import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSettledColours, SAVE_SETTLE_MS } from '../useSettledColours';
import { useWorkspaceStore } from '../../store/workspaceStore';

describe('useSettledColours — tiles must not be re-requested before the colours are saved', () => {
  beforeEach(() => { vi.useFakeTimers(); useWorkspaceStore.setState({ layerRenderers: {} }); });
  afterEach(() => vi.useRealTimers());

  it('is the same until the colours stop changing and the save has had time, then changes once', () => {
    const { result } = renderHook(() => useSettledColours('hazard_soil'));
    const before = result.current;
    act(() => useWorkspaceStore.getState().setLayerRenderer('analysis:hazard_soil', { mode: 'indexed', colors: { '1': '#112233' } } as never));
    expect(result.current).toBe(before); // the live value moved, the version has not
    act(() => { vi.advanceTimersByTime(SAVE_SETTLE_MS - 100); });
    expect(result.current).toBe(before);
    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current).not.toBe(before);
    const after = result.current;
    act(() => useWorkspaceStore.getState().setLayerRenderer('analysis:hazard_soil', null));
    act(() => { vi.advanceTimersByTime(SAVE_SETTLE_MS + 10); });
    expect(result.current).toBe('0'); // back to the system colours
    expect(after).not.toBe('0');
  });
  it('is "0" with nothing saved, and for no map', () => {
    expect(renderHook(() => useSettledColours('hazard_lsi')).result.current).toBe('0');
    expect(renderHook(() => useSettledColours(null)).result.current).toBe('0');
  });
});
