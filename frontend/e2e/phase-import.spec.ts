/**
 * phase-import.spec.ts — Phase U-7 E2E for the unified geometry import flows (U-5/U-6), on the Add data entry point:
 *   - a compartments file on a forest with a boundary: the two compartments are added and the rest of the boundary is filled by a remainder
 *     compartment (invariant C, remainder-compartmenting);
 *   - importing the same compartments again asks for confirmation first (needs_confirmation), then replaces them.
 *
 * Imports start from the header's "Add data" dialog (UP-4); the old "Imported Layers → Add layer" menu is off screen once a forest has
 * geometry. Requires the backend and Vite (3001) and the demo login. Each test makes its own forest (about 430 ha, inside the boundary rules)
 * and removes it afterwards, so a rerun's boundary never overlaps an earlier one.
 * (The old "first Block becomes the boundary" shortcut is not reachable from Add data, which is boundary-first.)
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import { createForestWithBoundary, importViaAddData, closeAddDataReport, deleteCurrentForest } from './helpers/addData'

const BOUNDARY = 'e2e/fixtures/forest_small.geojson'
// two compartments inside that boundary; the rest of the boundary becomes a remainder compartment
const COMPARTMENTS = 'e2e/fixtures/compartments_small.geojson'

async function login(page: Page) {
  test.setTimeout(240000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  await resetWorkspaceLayout(page) // the saved dock layout is per user: undo what an earlier spec collapsed
}

test.describe('Unified geometry import (U-5/U-6)', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    await deleteCurrentForest(page)
  })

  test('compartments import adds the units and fills the rest of the boundary (invariant C)', async ({ page }) => {
    await login(page)
    await createForestWithBoundary(page, 'E2E Unified', BOUNDARY)

    // The first compartments import has nothing to replace: no confirmation. 2 imported + the auto-derived remainder = 3.
    await importViaAddData(page, COMPARTMENTS)
    await closeAddDataReport(page)
    await expect(page.locator('.ant-modal', { hasText: /Overwrite Existing Data/i })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /Activate Compartments/i })).toContainText('3', { timeout: 30000 })
  })

  test('compartment replace requires pre-flight confirm then overwrites', async ({ page }) => {
    await login(page)
    await createForestWithBoundary(page, 'E2E Unified', BOUNDARY)

    await importViaAddData(page, COMPARTMENTS)
    await closeAddDataReport(page)
    const compsBtn = page.getByRole('button', { name: /Activate Compartments/i })
    await expect(compsBtn).toContainText('3', { timeout: 30000 })

    // The same file again: derived data exists, so a Replace-confirm ("Overwrite Existing Data?") must appear first.
    await importViaAddData(page, COMPARTMENTS)
    const overwriteDialog = page.locator('.ant-modal', { hasText: /Overwrite Existing Data/i })
    await expect(overwriteDialog).toBeVisible({ timeout: 15000 })
    await overwriteDialog.getByRole('button', { name: /Overwrite/i }).click({ force: true })

    // Overwrite completes: the compartments are replaced, still 3 including the remainder.
    await expect(compsBtn).toContainText('3', { timeout: 30000 })
  })
})
