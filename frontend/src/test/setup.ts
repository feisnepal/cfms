/**
 * Vitest test setup — global mocks and lifecycle hooks.
 *
 * Starts and stops the MSW mock server around all tests. Extends
 * vitest matchers with @testing-library/jest-dom assertions.
 */
import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './mocks/server'
import i18n from '../i18n'

// jsdom gaps that antd components (Segmented, Select, Tooltip) reach for.
if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

// antd Table / Grid subscribe to `window.matchMedia` on mount (responsive
// breakpoints); jsdom does not implement it.
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener() {},
      removeListener() {},
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() {
        return false
      },
    }),
  })
}

beforeAll(async () => {
  server.listen({ onUnhandledRequest: 'error' })
  // Deterministic English for assertions — the app boots to `ne`, but tests
  // assert on English labels, so pin the language before any component renders.
  await i18n.changeLanguage('en')
})
afterEach(() => {
  server.resetHandlers()

  // Browser storage is shared by every test in a file — jsdom builds one
  // window per FILE, not per test — and nothing was clearing it.
  //
  // That made `SamplingTabModeDriven` intermittently red in CI. SamplingTab
  // seeds BOTH `designs` and `successResult` from sessionStorage under a key
  // derived from calculationId, and every test in that file uses "calc-1". So
  // one test's low-coverage result survived into the next test's first render
  // and paired with a different test's design metadata, and the "Low
  // Tree-Cover Coverage" warning appeared where the test required its absence.
  //
  // It is order- and timing-dependent, which is why it survived three green
  // runs and then failed: with `--coverage` the async list call resolves later,
  // widening the window in which the stale seed is on screen.
  //
  // Cleared globally rather than in that one file, because any component
  // restoring state from storage has exactly this hazard, and a test that
  // passes only because of what a previous test left behind is not a test.
  try {
    sessionStorage.clear()
    localStorage.clear()
  } catch {
    // Some environments deny storage access; nothing to clean up if so.
  }
})
afterAll(() => server.close())
