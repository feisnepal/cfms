/**
 * hooks/usePerformance.ts — React hooks for performance telemetry (Phase 8,
 * Tabbed Calculation Detail plan).
 *
 * Every hook degrades to a no-op when Sentry is unconfigured and GA4 (gtag)
 * is absent, so dev/local behaviour is unchanged.
 */
import { useCallback, useEffect, useRef } from 'react';
import { measureApiCall, measureMapOperation, measureTabSwitch } from '../lib/performance';

const SLOW_MOUNT_THRESHOLD_MS = 100;
const SLOW_RESOURCE_THRESHOLD_MS = 1000;
const IS_DEV = import.meta.env.DEV;

const gtag = (): ((...args: unknown[]) => void) | undefined => {
  const g = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
  return typeof g === 'function' ? g : undefined;
};

export const useTabSwitchTiming = (activeTab: string): void => {
  const lastTabRef = useRef<string>(activeTab);
  const startTimeRef = useRef<number>(performance.now());

  useEffect(() => {
    const now = performance.now();
    const duration = now - startTimeRef.current;
    const fromTab = lastTabRef.current;

    if (fromTab !== activeTab) {
      measureTabSwitch(fromTab, activeTab, duration);
    }

    lastTabRef.current = activeTab;
    startTimeRef.current = now;
  }, [activeTab]);
};

export const useMapOperationTimer = (): {
  start: (operationId: string) => void;
  end: (operationId: string, metadata?: Record<string, unknown>) => void;
} => {
  const timers = useRef<Map<string, number>>(new Map());

  const start = useCallback((operationId: string) => {
    timers.current.set(operationId, performance.now());
  }, []);

  const end = useCallback((operationId: string, metadata?: Record<string, unknown>) => {
    const startTime = timers.current.get(operationId);
    if (startTime === undefined) return;
    const duration = performance.now() - startTime;
    measureMapOperation(operationId, duration, metadata);
    timers.current.delete(operationId);
  }, []);

  return { start, end };
};

export const useApiTiming = (): (<T>(endpoint: string, promise: Promise<T>) => Promise<T>) =>
  useCallback(async <T>(endpoint: string, promise: Promise<T>): Promise<T> => {
    const start = performance.now();
    try {
      const result = await promise;
      measureApiCall(endpoint, performance.now() - start, 200);
      return result;
    } catch (error) {
      const status =
        typeof (error as { status?: unknown } | null)?.status === 'number'
          ? ((error as { status: number }).status)
          : 500;
      measureApiCall(endpoint, performance.now() - start, status);
      throw error;
    }
  }, []);

export const useMountTiming = (componentName: string): void => {
  const startTime = useRef(performance.now());

  useEffect(() => {
    const duration = performance.now() - startTime.current;

    if (duration > SLOW_MOUNT_THRESHOLD_MS) {
      if (IS_DEV) {
        console.warn(`[Perf] ${componentName} mounted in ${duration.toFixed(1)}ms`);
      }
      gtag()?.('event', 'slow_mount', {
        component: componentName,
        value: Math.round(duration),
      });
    }

    performance.mark(`${componentName}-mounted`);
  }, [componentName]);
};

export const useResourceLoading = (): void => {
  useEffect(() => {
    if (typeof PerformanceObserver === 'undefined') return;

    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.entryType !== 'resource') continue;
        const resource = entry as PerformanceResourceTiming;
        if (resource.duration <= SLOW_RESOURCE_THRESHOLD_MS) continue;

        if (IS_DEV) {
          console.warn(
            `[Perf] Slow resource: ${resource.name} (${resource.duration.toFixed(0)}ms)`,
          );
        }
        gtag()?.('event', 'slow_resource', {
          resource: resource.name.split('/').pop(),
          value: Math.round(resource.duration),
        });
      }
    });

    observer.observe({ entryTypes: ['resource'] });
    return () => observer.disconnect();
  }, []);
};
