// scripts/perf-budget.config.mjs
// Shared Lighthouse performance thresholds + test-URL list for the Phase 10
// performance gate (scripts/perf-budget-gate.mjs).
//
// Values are the plan's thresholds — see TABBED_CALCULATION_DETAIL_PLAN_AI_READY
// Phase 10 §2:
//   LCP 2.5s baseline / +10% regression / 4.0s absolute max
//   FCP 1.8s            / +15%             / 3.0s
//   TBT 200ms           / +20%             / 600ms
//   CLS 0.10            / +30%             / 0.25

export const PERF_BUDGETS = [
  { metric: 'largest-contentful-paint', label: 'LCP',  baseline: 2500, regressionThreshold: 0.10, absoluteMax: 4000, unit: 'ms' },
  { metric: 'first-contentful-paint',   label: 'FCP',  baseline: 1800, regressionThreshold: 0.15, absoluteMax: 3000, unit: 'ms' },
  { metric: 'total-blocking-time',      label: 'TBT',  baseline: 200,  regressionThreshold: 0.20, absoluteMax: 600,  unit: 'ms' },
  { metric: 'cumulative-layout-shift',  label: 'CLS',  baseline: 0.1,  regressionThreshold: 0.30, absoluteMax: 0.25, unit: 'score' },
  { metric: 'speed-index',              label: 'SI',   baseline: 3400, regressionThreshold: 0.10, absoluteMax: 5000, unit: 'ms' },
  { metric: 'interactive',              label: 'TTI',  baseline: 3800, regressionThreshold: 0.10, absoluteMax: 6000, unit: 'ms' },
];

// Minimum Lighthouse category scores asserted by lighthouserc.js.
export const PERFORMANCE_TARGET = 0.9;
export const ACCESSIBILITY_TARGET = 0.95;

// Real routes (list page + the tabbed detail page, default- and reports-tab).
// `{calcId}` is substituted from LIGHTHOUSE_CALC_ID (see perf-budget-gate.mjs).
export const LIGHTHOUSE_PATHS = [
  '/my-uploads',
  '/calculations/{calcId}/tabbed',
  '/calculations/{calcId}/tabbed?tab=reports',
];