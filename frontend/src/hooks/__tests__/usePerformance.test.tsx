/**
 * Phase 8 — usePerformance hook tests (renderHook, no real Sentry).
 * Verifies tab-switch timing only fires on real changes, API timing maps
 * success/failure statuses, map op timers are one-shot, and the resource
 * monitor flags slow assets via a stubbed PerformanceObserver.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  useTabSwitchTiming,
  useApiTiming,
  useMapOperationTimer,
  useMountTiming,
  useResourceLoading,
} from '../usePerformance';

const { measureTabSwitch, measureMapOperation, measureApiCall } = vi.hoisted(() => ({
  measureTabSwitch: vi.fn(),
  measureMapOperation: vi.fn(),
  measureApiCall: vi.fn(),
}));

vi.mock('../../lib/performance', () => ({
  measureTabSwitch,
  measureMapOperation,
  measureApiCall,
}));

describe('useTabSwitchTiming', () => {
  beforeEach(() => vi.clearAllMocks());

  it('does not measure on initial mount (no actual switch)', () => {
    renderHook(({ tab }) => useTabSwitchTiming(tab), { initialProps: { tab: 'workspace' } });
    expect(measureTabSwitch).not.toHaveBeenCalled();
  });

  it('measures once when the tab actually changes', () => {
    const { rerender } = renderHook(({ tab }) => useTabSwitchTiming(tab), {
      initialProps: { tab: 'workspace' },
    });
    rerender({ tab: 'sampling' });

    expect(measureTabSwitch).toHaveBeenCalledTimes(1);
    expect(measureTabSwitch.mock.calls[0][0]).toBe('workspace');
    expect(measureTabSwitch.mock.calls[0][1]).toBe('sampling');
    expect(typeof measureTabSwitch.mock.calls[0][2]).toBe('number');
  });

  it('does not re-measure when switching back to the same tab', () => {
    const { rerender } = renderHook(({ tab }) => useTabSwitchTiming(tab), {
      initialProps: { tab: 'workspace' },
    });
    rerender({ tab: 'workspace' });
    expect(measureTabSwitch).not.toHaveBeenCalled();
  });
});

describe('useApiTiming', () => {
  beforeEach(() => vi.clearAllMocks());

  it('records a successful call with status 200 and returns the value', async () => {
    const { result } = renderHook(() => useApiTiming());
    const timed = result.current;

    const value = await act(async () => timed('/api/calculations/1', Promise.resolve(42)));

    expect(value).toBe(42);
    expect(measureApiCall).toHaveBeenCalledTimes(1);
    const [endpoint, duration, status] = measureApiCall.mock.calls[0];
    expect(endpoint).toBe('/api/calculations/1');
    expect(status).toBe(200);
    expect(duration).toBeGreaterThanOrEqual(0);
  });

  it('records a failure with status 500 when the error has no status', async () => {
    const { result } = renderHook(() => useApiTiming());
    const timed = result.current;

    await expect(
      act(async () => timed('/api/fail', Promise.reject(new Error('boom')))),
    ).rejects.toThrow('boom');

    expect(measureApiCall).toHaveBeenCalledTimes(1);
    expect(measureApiCall.mock.calls[0][2]).toBe(500);
  });

  it('propagates the HTTP status on errored responses', async () => {
    const { result } = renderHook(() => useApiTiming());
    const timed = result.current;
    const err = new Error('forbidden') as Error & { status: number };
    err.status = 403;

    await expect(act(async () => timed('/api/x', Promise.reject(err)))).rejects.toThrow(
      'forbidden',
    );
    expect(measureApiCall.mock.calls[0][2]).toBe(403);
  });
});

describe('useMapOperationTimer', () => {
  beforeEach(() => vi.clearAllMocks());

  it('measures a start/end pair and deletes the timer afterwards', () => {
    const { result } = renderHook(() => useMapOperationTimer());

    act(() => result.current.start('digitize'));
    act(() => result.current.end('digitize', { ok: true }));

    expect(measureMapOperation).toHaveBeenCalledTimes(1);
    expect(measureMapOperation.mock.calls[0][0]).toBe('digitize');
    expect(measureMapOperation.mock.calls[0][2]).toMatchObject({ ok: true });
  });

  it('is a no-op when ending an unknown/expired operation', () => {
    const { result } = renderHook(() => useMapOperationTimer());
    act(() => result.current.end('never-started'));
    expect(measureMapOperation).not.toHaveBeenCalled();
  });
});

describe('useMountTiming', () => {
  beforeEach(() => vi.clearAllMocks());

  it('marks the component mount for PerformanceObserver consumers', () => {
    const markSpy = vi.spyOn(performance, 'mark').mockImplementation(() => ({
      name: '',
      entryType: 'mark',
      startTime: 0,
      duration: 0,
      detail: null,
    }) as PerformanceMark);
    renderHook(() => useMountTiming('MapWorkspace'));
    expect(markSpy).toHaveBeenCalledWith('MapWorkspace-mounted');
    markSpy.mockRestore();
  });
});

describe('useResourceLoading', () => {
  beforeEach(() => vi.clearAllMocks());

  it('flags slow resources (>1s) to GA4 and disconnects on unmount', () => {
    const listeners: Array<(list: unknown) => void> = [];
    let disconnected = 0;

    class FakeObserver {
      constructor(cb: (list: unknown) => void) {
        listeners.push(cb);
      }
      observe() {
        /* no-op */
      }
      disconnect() {
        disconnected += 1;
      }
    }

    vi.stubGlobal('PerformanceObserver', FakeObserver);
    (window as any).gtag = vi.fn();

    const { unmount } = renderHook(() => useResourceLoading());

    const entry = { entryType: 'resource', name: 'https://cdn.example/leaflet.js', duration: 1500 };
    act(() => {
      listeners[0]?.({ getEntries: () => [entry] });
    });

    expect((window as any).gtag).toHaveBeenCalledWith(
      'event',
      'slow_resource',
      expect.objectContaining({ resource: 'leaflet.js', value: 1500 }),
    );

    unmount();
    expect(disconnected).toBe(1);

    vi.unstubAllGlobals();
    delete (window as any).gtag;
  });

  it('ignores fast resources', () => {
    const listeners: Array<(list: unknown) => void> = [];
    class FakeObserver {
      constructor(cb: (list: unknown) => void) {
        listeners.push(cb);
      }
      observe() {
        /* no-op */
      }
      disconnect() {
        /* no-op */
      }
    }
    vi.stubGlobal('PerformanceObserver', FakeObserver);
    (window as any).gtag = vi.fn();

    renderHook(() => useResourceLoading());
    act(() => {
      listeners[0]?.({ getEntries: () => [{ entryType: 'resource', name: 'a.js', duration: 10 }] });
    });

    expect((window as any).gtag).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
    delete (window as any).gtag;
  });
});
