// lighthouserc.js
// Lighthouse CI configuration (Phase 10).
//
// Tests the app's real routes: the list page plus the tabbed calculation
// detail page (default Workspace tab and Reports tab). Assertions enforce
// the plan's targets: performance >= 90, accessibility >= 95.
//
// Note: this repo's primary perf gate is `scripts/perf-budget-gate.mjs`
// (runs Lighthouse directly, no `@lhci/cli` dependency, see `npm run perf:check`).
// This file is the lhci-compatible equivalent for teams that prefer
// `npx @lhci/cli autorun`. Because package.json is `"type": "module"`,
// @lhci/cli must load this ESM config (recent versions do) — otherwise
// point LHCI at `lighthouserc.cjs` (CJS mirror).
//
// Env:
//   LHCI_BASE_URL  default http://localhost:4173 (the built app, `npm run preview`)
//   LHCI_CALC_ID   demo calc id; defaults to the shared e2e demo calc
const baseUrl = process.env.LHCI_BASE_URL || 'http://localhost:4173'
const calcId = process.env.LHCI_CALC_ID || '15f64467-c857-4948-bb42-34eefadb88bc'

export default {
  ci: {
    collect: {
      url: [
        `${baseUrl}/my-uploads`,
        `${baseUrl}/calculations/${calcId}/tabbed`,
        `${baseUrl}/calculations/${calcId}/tabbed?tab=reports`,
      ],
      numberOfRuns: 3,
      startServerCommand: 'npm run preview',
      startServerReadyPattern: 'Local:',
      startServerReadyTimeout: 20000,
    },
    assert: {
      preset: 'lighthouse:recommended',
      assertions: {
        'categories:performance': ['error', { minScore: 0.9 }],
        'categories:accessibility': ['error', { minScore: 0.95 }],
        'first-contentful-paint': ['warn', { maxNumericValue: 1800 }],
        'largest-contentful-paint': ['error', { maxNumericValue: 2500 }],
        'total-blocking-time': ['warn', { maxNumericValue: 200 }],
        'cumulative-layout-shift': ['error', { maxNumericValue: 0.1 }],
        'unused-javascript': 'off', // We code-split; Lighthouse still flags chunks
      },
    },
    upload: {
      target: 'temporary-public-storage',
      // For PR comments, set the LHCI_GITHUB_APP_TOKEN secret and use:
      //   githubStatusCheck: true,
      //   githubToken: process.env.LHCI_GITHUB_APP_TOKEN,
    },
  },
}
