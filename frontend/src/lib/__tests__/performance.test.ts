/**
 * Phase 8 — lib/performance logic tests (repo logic-only pattern).
 * Verifies the pure param builders + gtag wiring of the Web Vitals /
 * measurement helpers. Sentry side is skipped (no VITE_SENTRY_DSN in tests).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { MetricType } from 'web-vitals';

const { onCLSMock, onFCPMock, onINPMock, onLCPMock, onTTFBMock } = vi.hoisted(() => ({
  onCLSMock: vi.fn(),
  onFCPMock: vi.fn(),
  onINPMock: vi.fn(),
  onLCPMock: vi.fn(),
  onTTFBMock: vi.fn(),
}));

vi.mock('web-vitals', () => ({
  onCLS: (cb: unknown) => onCLSMock(cb),
  onFCP: (cb: unknown) => onFCPMock(cb),
  onINP: (cb: unknown) => onINPMock(cb),
  onLCP: (cb: unknown) => onLCPMock(cb),
  onTTFB: (cb: unknown) => onTTFBMock(cb),
}));

import {
  initPerformanceMonitoring,
  webVitalsEventParams,
  slowRenderParams,
  measureTabSwitch,
  measureMapInit,
  onRenderCallback,
} from '../performance';

const makeMetric = (overrides: Partial<MetricType> = {}): MetricType =>
  ({
    name: 'LCP',
    value: 2500,
    rating: 'needs-improvement',
    delta: 2500,
    id: 'v1-abc',
    navigationType: 'navigate',
    navigationId: 1,
    entries: [],
    ...overrides,
  }) as MetricType;

describe('initPerformanceMonitoring', () => {
  it('registers all five supported Web Vitals once', () => {
    initPerformanceMonitoring();
    expect(onCLSMock).toHaveBeenCalledTimes(1);
    expect(onFCPMock).toHaveBeenCalledTimes(1);
    expect(onINPMock).toHaveBeenCalledTimes(1);
    expect(onLCPMock).toHaveBeenCalledTimes(1);
    expect(onTTFBMock).toHaveBeenCalledTimes(1);
  });

  it('is idempotent — a second call does not re-register', () => {
    initPerformanceMonitoring();
    expect(onLCPMock).toHaveBeenCalledTimes(1);
  });

  it('sends each metric to GA4 with Web Vitals params', () => {
    const gtag = vi.fn();
    (window as any).gtag = gtag;

    const cb = onLCPMock.mock.calls[0][0] as (metric: MetricType) => void;
    cb(makeMetric({ name: 'LCP', value: 2500, rating: 'needs-improvement' }));

    expect(gtag).toHaveBeenCalledTimes(1);
    const [, eventName, params] = gtag.mock.calls[0];
    expect(eventName).toBe('LCP');
    expect(params).toMatchObject({
      event_category: 'Web Vitals',
      value: 2500,
      non_interaction: true,
      custom_parameter_1: 'needs-improvement',
      custom_parameter_2: 'navigate',
    });
  });
});

describe('webVitalsEventParams', () => {
  it('reports CLS scaled to ms integer (Layout Shift unit)', () => {
    const params = webVitalsEventParams(makeMetric({ name: 'CLS', value: 0.123 }));
    expect(params.value).toBe(123);
  });

  it('rounds non-CLS metrics to integer ms', () => {
    expect(webVitalsEventParams(makeMetric({ name: 'LCP', value: 2500.6 })).value).toBe(2501);
  });

  it('maps rating + navigationType into custom params', () => {
    const params = webVitalsEventParams(
      makeMetric({ rating: 'good', navigationType: 'back-forward' }),
    );
    expect(params.custom_parameter_1).toBe('good');
    expect(params.custom_parameter_2).toBe('back-forward');
  });
});

describe('slowRenderParams', () => {
  it('returns null for renders at or below the 16ms threshold', () => {
    expect(slowRenderParams('Workspace', 'mount', 16)).toBeNull();
    expect(slowRenderParams('Workspace', 'update', 10)).toBeNull();
  });

  it('returns a rounded report for slow renders, preserving phase', () => {
    expect(slowRenderParams('MapCanvas', 'update', 21.7)).toEqual({
      component: 'MapCanvas',
      phase: 'update',
      value: 22,
    });
  });
});

describe('measureTabSwitch', () => {
  beforeEach(() => {
    (window as any).gtag = vi.fn();
  });
  afterEach(() => {
    delete (window as any).gtag;
  });

  it('fires a tab_switch GA4 event with from/to and rounded duration', () => {
    measureTabSwitch('workspace', 'sampling', 42.4);
    expect((window as any).gtag).toHaveBeenCalledTimes(1);
    expect((window as any).gtag).toHaveBeenCalledWith('event', 'tab_switch', {
      from_tab: 'workspace',
      to_tab: 'sampling',
      value: 42,
    });
  });

  it('does not throw when gtag is absent', () => {
    delete (window as any).gtag;
    expect(() => measureTabSwitch('a', 'b', 10)).not.toThrow();
  });
});

describe('measureMapInit', () => {
  beforeEach(() => {
    (window as any).gtag = vi.fn();
  });
  afterEach(() => {
    delete (window as any).gtag;
  });

  it('fires a map_init GA4 event with rounded duration', () => {
    measureMapInit(2345.6);
    expect((window as any).gtag).toHaveBeenCalledTimes(1);
    expect((window as any).gtag).toHaveBeenCalledWith('event', 'map_init', {
      value: 2346,
    });
  });

  it('does not throw when gtag is absent', () => {
    delete (window as any).gtag;
    expect(() => measureMapInit(100)).not.toThrow();
  });
});

describe('onRenderCallback', () => {
  beforeEach(() => {
    (window as any).gtag = vi.fn();
  });
  afterEach(() => {
    delete (window as any).gtag;
  });

  it('skips fast renders', () => {
    onRenderCallback('CalculationHeader', 'update', 8, 6, 0, 0);
    expect((window as any).gtag).not.toHaveBeenCalled();
  });

  it('fires slow_render for >16ms renders with component/phase/value', () => {
    onRenderCallback('CalculationTabs', 'mount', 24.3, 10, 0, 0);
    expect((window as any).gtag).toHaveBeenCalledWith('event', 'slow_render', {
      component: 'CalculationTabs',
      phase: 'mount',
      value: 24,
    });
  });
});
