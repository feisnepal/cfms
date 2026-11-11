/**
 * Browser storage must not survive from one test into the next.
 *
 * jsdom builds one `window` per test FILE, not per test, so `sessionStorage`
 * and `localStorage` are shared by every test in a file. Nothing cleared them.
 *
 * That made `SamplingTabModeDriven` intermittently red in CI. `SamplingTab`
 * seeds both `designs` and `successResult` from sessionStorage under a key
 * derived from `calculationId`, and every test in that file uses `"calc-1"` —
 * so one test's low-coverage result was still on screen during the next test's
 * first render, and the "Low Tree-Cover Coverage" warning appeared in a test
 * that required its absence.
 *
 * It survived three green runs before failing, because it is timing-dependent:
 * under `--coverage` the async list call resolves later, widening the window in
 * which the stale seed is displayed.
 *
 * These tests pin the cleanup in `src/test/setup.ts`. They must run in the
 * order written — the second only means anything after the first has polluted
 * storage — which is why they are `it` blocks in one file rather than separate
 * files, and why the writes are deliberately not cleaned up locally.
 */
import { describe, it, expect } from 'vitest'

const KEY = 'storage-isolation-probe'

describe('storage isolation between tests', () => {
  it('deliberately leaves data behind in both stores', () => {
    sessionStorage.setItem(KEY, 'from the first test')
    localStorage.setItem(KEY, 'from the first test')

    // Confirms the write actually happened, so a passing second test cannot be
    // explained by storage being unavailable in this environment.
    expect(sessionStorage.getItem(KEY)).toBe('from the first test')
    expect(localStorage.getItem(KEY)).toBe('from the first test')
  })

  it('does not see the previous test data', () => {
    expect(sessionStorage.getItem(KEY)).toBeNull()
    expect(localStorage.getItem(KEY)).toBeNull()
    expect(sessionStorage.length).toBe(0)
    expect(localStorage.length).toBe(0)
  })
})
