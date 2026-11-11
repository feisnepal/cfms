/**
 * name-first-creation.spec.ts — E2E for the purpose-first creation flow
 * (NAME_FIRST_CREATION_PLAN.md, Phases 5–8).
 *
 * Requires a running backend (port 8001) + demo login. Playwright's webServer
 * boots Vite on port 3001. Selectors target the real implementation:
 * - "+ Create New" name-only modal in MyUploads
 * - `/calculations/{id}/tabbed` workspace (`workspace-container`)
 * - "No geometry yet" banner (`no-geometry-banner`)
 * - the header's "Add data" dialog → the per-file Import Layer dialog (Boundary purpose → boundary_geom)
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import { createForest, importViaAddData, closeAddDataReport, deleteCurrentForest } from './helpers/addData'

// ~130 ha, inside the 1,000 ha limit (the older boundary.* fixtures are ~10,900 ha and are refused by the boundary rules)
const FIXTURE = 'e2e/fixtures/forest_small.geojson'
const KMZ_FIXTURE = 'e2e/fixtures/forest_small.kmz'
const BLOCKS_ZIP_FIXTURE = 'e2e/fixtures/blocks.zip'

async function login(page: Page) {
  test.setTimeout(180000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  await resetWorkspaceLayout(page) // the saved dock layout is per user: undo what an earlier spec collapsed
}

test.describe('Name-first CFOP creation → purpose-first geometry (Phase 8)', () => {
  test.describe.configure({ mode: 'serial' })

  // each test makes its own forest: remove it so the next run's boundary does not overlap this one's
  test.afterEach(async ({ page }) => { await deleteCurrentForest(page) })

  test('create name-only → workspace shows "No geometry yet"', async ({ page }) => {
    await login(page)
    await page.goto('/my-uploads', { waitUntil: 'load', timeout: 60000 })

    await page.getByRole('button', { name: /Create New|Create CFOP/i }).first().click()

    const name = `E2E Purpose Forest ${Date.now()}`
    const nameInput = page.getByPlaceholder(/forest|name/i).first()
    await nameInput.fill(name)
    await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()

    // Lands on the tabbed workspace for the new draft.
    await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
    await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })

    // A brand-new name-only draft has no geometry → the prominent prompt shows.
    await expect(page.getByTestId('no-geometry-banner')).toBeVisible({ timeout: 20000 })
  })

  test('import a Forest-boundary file → boundary appears, banner hides', async ({ page }) => {
    await login(page)
    await createForest(page, 'E2E Boundary Forest')
    await expect(page.getByTestId('no-geometry-banner')).toBeVisible({ timeout: 20000 })

    // Add data → the file is recognised by its name as the forest boundary → Boundary → Import.
    await importViaAddData(page, FIXTURE, { purposeButton: /^Boundary/ })
    await closeAddDataReport(page)

    // Purpose-first: the file becomes the forest boundary, not a silent layer.
    await expect(page.getByTestId('no-geometry-banner')).toBeHidden({ timeout: 30000 })
  })

  test('a Block file alone is held back until the forest has a boundary', async ({ page }) => {
    // Add data is boundary-first (the old "first Block becomes the boundary" shortcut lived in the Imported Layers menu): a blocks file dropped
    // on a forest with no boundary is not accepted, and the dialog says why.
    await login(page)
    await createForest(page, 'E2E BlockFirst Forest')
    await expect(page.getByTestId('no-geometry-banner')).toBeVisible({ timeout: 20000 })

    await page.getByRole('button', { name: /Add data$/ }).first().click()
    const dialog = page.locator('.ant-modal', { hasText: 'Click or drag files here' })
    await dialog.locator('input[type="file"]').setInputFiles(BLOCKS_ZIP_FIXTURE)
    await expect(dialog.getByText(/bundle · 1 layers|matched by (name|content)/)).toBeVisible({ timeout: 20000 })
    await expect(dialog.getByText('This forest has no boundary yet')).toBeVisible()
    await expect(dialog.getByRole('button', { name: /^Add/ })).toBeDisabled()
    await expect(page.getByTestId('no-geometry-banner')).toBeVisible() // nothing was imported
  })

  test('import a KMZ Forest-boundary file → boundary appears, banner hides', async ({ page }) => {
    await login(page)
    await createForest(page, 'E2E KMZ Forest')
    await expect(page.getByTestId('no-geometry-banner')).toBeVisible({ timeout: 20000 })

    // KMZ (binary ZIP) is unzipped into its KML document on the way in.
    await importViaAddData(page, KMZ_FIXTURE, { purposeButton: /^Boundary/ })
    await closeAddDataReport(page)
    await expect(page.getByTestId('no-geometry-banner')).toBeHidden({ timeout: 30000 })
  })
})
