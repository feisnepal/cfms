import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    include: ['src/**/*.{test,spec}.{ts,tsx}'],

    // CI's `test-frontend` job failed on ONE test — an ImportPurposeDialog case
    // that timed out at the 5000ms default — while passing locally. It is not a
    // flake and not test pollution; it is the default timeout being too tight
    // for this suite. Measured on the same commit:
    //
    //   that test alone, no coverage      864ms
    //   that test alone, with coverage   1966ms   (v8 instrumentation, 2.3x)
    //   in the full suite with coverage  9036ms   (parallel load, 10.5x)
    //
    // The load factor is the dominant term and CI is worse than this machine:
    // ubuntu-latest gives 2 cores against 89 jsdom environments, and the run's
    // own breakdown puts 1517s in `environment` — more than the 222s actually
    // spent executing tests. Twenty tests already report over 5000ms and pass,
    // because the reported duration includes hooks while the timeout applies
    // only to the body; this one crossed the line in the body. The suite has
    // been running with no margin, and which test loses is a coin flip.
    //
    // Raised rather than worked around: the test is deterministic, it just
    // needs headroom. 15s keeps a genuine hang surfacing quickly enough to
    // diagnose, at ~3x the worst body time observed under load.
    testTimeout: 15000,
    hookTimeout: 15000,

    // H1.9 / S1-22: there was no coverage measurement of any kind, so 724
    // frontend tests could not be related to the ~105k lines they nominally
    // cover. Measure now, gate in task 4.2 — a threshold set before a baseline
    // exists is a guess.
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary', 'html', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.{test,spec}.{ts,tsx}',
        'src/**/__tests__/**',
        'src/test/**',
        'src/vite-env.d.ts',
        // 40,858 lines generated from the OpenAPI schema. Counting it would
        // inflate the denominator and tell us nothing about tested behaviour.
        'src/types/digitize-api.ts',
      ],
      // No thresholds yet — deliberately. See task 4.2.
    },
  },
})
