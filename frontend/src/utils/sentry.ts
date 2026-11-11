/**
 * Frontend error monitoring via Sentry.
 *
 * No-op when `VITE_SENTRY_DSN` is unset (the local/dev default), so the app
 * behaves identically with or without Sentry. When set (staging/prod), it
 * captures unhandled exceptions and (Phase 8) enables automatic browser
 * tracing — pageload + SPA navigation transactions that Web Vitals
 * measurements from `lib/performance.ts` attach to.
 *
 * Importing this module for its side effect (init) is enough; `initSentry` is
 * also exported for explicit control.
 */
const SENTRY_DSN = (import.meta.env.VITE_SENTRY_DSN as string | undefined) || '';

let initialized = false;

export function initSentry(): void {
  if (initialized || !SENTRY_DSN) return;
  initialized = true;
  import('@sentry/react').then((Sentry) => {
    Sentry.init({
      dsn: SENTRY_DSN,
      // Captures unhandled exceptions and promise rejections globally.
      // browserTracingIntegration (v8) instruments pageload + history
      // navigations automatically; Web Vitals measurements attach to the
      // active pageload transaction. Route-tree coupling is deliberately
      // avoided (reactRouterV7BrowserTracingIntegration not wired).
      integrations: [Sentry.browserTracingIntegration()],
      tracesSampleRate: 0.1,
      environment: import.meta.env.MODE,
    });
  });
}

initSentry();
