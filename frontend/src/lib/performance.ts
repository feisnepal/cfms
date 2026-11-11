/**
 * lib/performance.ts — Web Vitals + performance measurement helpers (Phase 8,
 * Tabbed Calculation Detail plan).
 *
 * Sentry calls are no-ops unless `VITE_SENTRY_DSN` is set (see utils/sentry.ts
 * for the guarded init). GA4 (gtag) calls are no-ops unless `window.gtag` is a
 * function. Pure param builders are exported separately so the repo's
 * logic-only test pattern can assert them without a renderer or a DSN.
 */
import { onCLS, onFCP, onINP, onLCP, onTTFB, type MetricType } from 'web-vitals';
import * as Sentry from '@sentry/react';

const SENTRY_DSN = (import.meta.env.VITE_SENTRY_DSN as string | undefined) || '';
const IS_DEV = import.meta.env.DEV;

export const SLOW_RENDER_THRESHOLD_MS = 16;

type Gtag = (...args: unknown[]) => void;

const gtag = (): Gtag | undefined => {
  const g = (window as unknown as { gtag?: Gtag }).gtag;
  return typeof g === 'function' ? g : undefined;
};

const isSentryEnabled = (): boolean => Boolean(SENTRY_DSN);

let vitalsRegistered = false;

/**
 * Registers Web Vitals listeners once. Should be called from the entry point
 * (main.tsx) before React renders so LCP/FCP/CLS windows are not missed.
 */
export const initPerformanceMonitoring = (): void => {
  if (vitalsRegistered) return;
  vitalsRegistered = true;

  const report = (metric: MetricType): void => {
    if (isSentryEnabled()) {
      Sentry.setMeasurement(
        metric.name,
        metric.value,
        metric.name === 'CLS' ? 'none' : 'millisecond',
      );
    }
    gtag()?.('event', metric.name, webVitalsEventParams(metric));
    if (IS_DEV) {
      console.info(`[Web Vital] ${metric.name}:`, {
        value: metric.value,
        rating: metric.rating,
        id: metric.id,
      });
    }
  };

  onCLS(report);
  onFCP(report);
  onINP(report);
  onLCP(report);
  onTTFB(report);
};

export interface WebVitalsEventParams {
  event_category: string;
  value: number;
  event_label: string;
  non_interaction: boolean;
  custom_parameter_1: string;
  custom_parameter_2: string;
}

export const webVitalsEventParams = (metric: MetricType): WebVitalsEventParams => ({
  event_category: 'Web Vitals',
  value: Math.round(metric.name === 'CLS' ? metric.value * 1000 : metric.value),
  event_label: metric.id,
  non_interaction: true,
  custom_parameter_1: metric.rating,
  custom_parameter_2: metric.navigationType,
});

export interface SlowRenderParams {
  component: string;
  phase: 'mount' | 'update';
  value: number;
}

export const slowRenderParams = (
  id: string,
  phase: 'mount' | 'update',
  actualDuration: number,
): SlowRenderParams | null =>
  actualDuration > SLOW_RENDER_THRESHOLD_MS
    ? { component: id, phase, value: Math.round(actualDuration) }
    : null;

export const measureTabSwitch = (fromTab: string, toTab: string, duration: number): void => {
  const value = Math.round(duration);
  if (isSentryEnabled()) {
    // `measurements.tab-switch` backs the "Tab Switch > 100ms" metric alert +
    // dashboard widget (Phase 10). Kept alongside the message so both the
    // alertable measurement and the human-readable breadcrumb exist.
    Sentry.setMeasurement('tab-switch', value, 'millisecond');
    Sentry.captureMessage('Tab Switch', {
      level: 'info',
      tags: { from_tab: fromTab, to_tab: toTab },
      extra: { duration_ms: value },
    });
  }
  gtag()?.('event', 'tab_switch', { from_tab: fromTab, to_tab: toTab, value });
};

/**
 * Phase 10 — map-init measurement. Call once the Leaflet map chunk resolves
 * and the workspace mounts; feeds `measurements.map-init` so the "Map Init
 * Time > 3s" critical alert (PagerDuty) and dashboard widget have a real
 * signal. GA4 mirror: `map_init`.
 */
export const measureMapInit = (duration: number): void => {
  const value = Math.round(duration);
  if (isSentryEnabled()) {
    Sentry.setMeasurement('map-init', value, 'millisecond');
  }
  gtag()?.('event', 'map_init', { value });
};

export const measureMapOperation = (
  operation: string,
  duration: number,
  metadata?: Record<string, unknown>,
): void => {
  if (!isSentryEnabled()) return;
  Sentry.addBreadcrumb({
    category: 'map',
    message: `Map operation: ${operation}`,
    data: { duration_ms: Math.round(duration), ...metadata },
    level: 'info',
  });
};

export const measureApiCall = (endpoint: string, duration: number, status: number): void => {
  if (!isSentryEnabled()) return;
  Sentry.addBreadcrumb({
    category: 'api',
    message: `API ${endpoint}`,
    data: { duration_ms: Math.round(duration), status },
    level: status >= 400 ? 'warning' : 'info',
  });
};

export const startSpan = (name: string, op: string) =>
  isSentryEnabled() ? Sentry.startInactiveSpan({ name, op }) : null;

export const onRenderCallback = (
  id: string,
  phase: 'mount' | 'update' | 'nested-update',
  actualDuration: number,
  baseDuration: number,
  _startTime: number,
  _commitTime: number,
): void => {
  const report = slowRenderParams(id, phase === 'nested-update' ? 'update' : phase, actualDuration);
  if (!report) return;

  if (isSentryEnabled()) {
    Sentry.captureMessage('Slow React Render', {
      level: 'warning',
      tags: { component: id, phase },
      extra: { actualDuration: report.value, baseDuration: Math.round(baseDuration) },
    });
  }
  gtag()?.('event', 'slow_render', report);
};

export const shouldTrackRenders = (): boolean =>
  IS_DEV || import.meta.env.VITE_PERF_PROFILER === 'true';
