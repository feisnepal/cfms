import { expect, type Page } from '@playwright/test'

/** The panel buttons and the "Yearly plan" button sit behind the header's single "Layers" button (owner rule 2026-10-10): open it first. */
export async function openPanelButtons(page: Page): Promise<void> {
  const disclosure = page.getByTestId('panel-toggles-disclosure')
  await expect(disclosure).toBeVisible({ timeout: 60000 })
  if ((await disclosure.getAttribute('aria-expanded')) !== 'true') await disclosure.click()
}
