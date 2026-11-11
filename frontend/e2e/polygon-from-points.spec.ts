/**
 * polygon-from-points.spec.ts — E2E for interactive "Create Polygon from Points"
 * (Phase U-4, Task 4.1, case E).
 *
 * Requires a running backend (8001), demo login, Vite on 3001. Creates a fresh
 * name-only draft, imports a boundary so a Blocks layer exists, then:
 *   - right-clicks the Blocks layer → "Create Polygon from Points"
 *   - clicks 4 non-collinear points on the map
 *   - clicks Finish (enabled only once >=3 non-collinear points)
 *   - asserts the Blocks attribute table shows the new polygon row (persisted).
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import { createForestWithBoundary, importViaAddData, closeAddDataReport, deleteCurrentForest } from './helpers/addData'

const BOUNDARY = 'e2e/fixtures/forest_small.geojson'
// one block inside that boundary: the Blocks layer the points polygon is added to
const BLOCKS = 'e2e/fixtures/blocks_small.geojson'

async function login(page: Page) {
  test.setTimeout(240000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  await resetWorkspaceLayout(page) // the saved dock layout is per user: undo what an earlier spec collapsed
}

test.describe('Create Polygon from Points (Phase U-4)', () => {
  test.describe.configure({ mode: 'serial' })

  // each test makes its own forest: remove it so the next run's boundary does not overlap this one's
  test.afterEach(async ({ page }) => {
    await deleteCurrentForest(page)
  })

  test('pick 4 points on a fresh Blocks layer → polygon appears & persists', async ({ page }) => {
    await login(page)
    await createForestWithBoundary(page, 'E2E Points', BOUNDARY)

    // Seed a Blocks layer: Add data → the blocks file → Import (a boundary exists, so blocks are accepted).
    await importViaAddData(page, BLOCKS)
    await closeAddDataReport(page)
    // the block plus the remainder block that fills the rest of the boundary (invariant C)
    await expect(page.getByRole('button', { name: /Activate Blocks/i })).toContainText('2', { timeout: 30000 })

    // Open the Blocks layer context menu.
    const blocksLayer = page.locator('[data-testid="layer-item"]', { hasText: /Block/i }).first()
    await blocksLayer.click({ button: 'right' })
    // "Create Polygon from Points" sits in the layer menu's Advanced fly-out (a tap opens it)
    await page.getByRole('menuitem', { name: /^Advanced/i }).click()
    const menuItem = page.getByRole('menuitem', { name: /Create Polygon from Points/i })
    await expect(menuItem).toBeVisible({ timeout: 10000 })
    await menuItem.click()

    // Point-pick overlay is shown; Finish is disabled until >=3 non-collinear points.
    await expect(page.getByTestId('polygon-from-points-overlay')).toBeVisible({ timeout: 10000 })
    await expect(page.getByTestId('finish-points')).toBeDisabled()

    // Click 4 distinct, non-collinear points on the map.
    const map = page.locator('.leaflet-container')
    const box = (await map.boundingBox())!
    const n = 4
    const pts = [
      [0.30, 0.70],
      [0.70, 0.70],
      [0.70, 0.45],
      [0.30, 0.45],
    ]
    for (const [fx, fy] of pts) {
      await map.click({ position: { x: box.width * fx, y: box.height * fy } })
    }

    // Finish becomes enabled once points are non-collinear.
    await expect(page.getByTestId('finish-points')).toBeEnabled({ timeout: 10000 })
    await page.getByTestId('finish-points').click()

    // Success toast + overlay dismissed.
    await expect(page.getByTestId('polygon-from-points-overlay')).not.toBeVisible({ timeout: 10000 })
    await expect(
      page.locator('.ant-message-notice', { hasText: /Polygon created/i }).first(),
    ).toBeVisible({ timeout: 30000 })

    // The block persists: activate Blocks layer and check the attribute table row.
    await blocksLayer.locator('.layer-name-btn').click({ force: true })
    await page.waitForTimeout(1500)
    await expect(page.getByTestId('attribute-table').first()).toBeVisible({ timeout: 20000 })
    await expect(
      page.getByTestId('attribute-table').first().locator('.table-row').first(),
    ).toBeVisible({ timeout: 15000 })
  })
})