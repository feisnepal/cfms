import type { Page } from '@playwright/test'

/**
 * The Forest summary is a floating panel that opens on top of the map and can sit over the controls a spec needs to press (it covered the
 * Next-step pill). Close it; the choice is saved with the forest, so it stays closed on the next visit. Safe to call when it is not there.
 */
export async function closeForestSummary(page: Page): Promise<void> {
  const panel = page.getByTestId('forest-summary-panel')
  // it appears a moment after the map; if it was closed on an earlier visit it never does
  await panel.waitFor({ state: 'visible', timeout: 8000 }).catch(() => undefined)
  if (await panel.isVisible().catch(() => false)) {
    // a plain DOM click: the panel is still settling into place when it appears, which Playwright's "stable" wait would wait on
    await panel.getByRole('button', { name: 'Close' }).evaluate((b) => (b as HTMLElement).click())
    await panel.waitFor({ state: 'hidden', timeout: 10000 }).catch(() => undefined)
  }
}
