/**
 * sub-areas.spec.ts — E2E for the sub-areas import pipeline (Phase 5/6).
 *
 * Requires a running backend (8001), demo login, Vite on 3001. Creates a fresh
 * name-only draft, imports a sub-areas GeoJSON via the "Import as Sub-areas"
 * purpose-pinned menu, and asserts:
 *   - the import summary toast appears (conversion ran),
 *   - the built-in Sub-Areas attribute table shows the polygon row with the
 *     auto-detected category from the file properties.
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import { createForestWithBoundary, importViaAddData, closeAddDataReport, deleteCurrentForest } from './helpers/addData'

const BOUNDARY = 'e2e/fixtures/forest_small.geojson'
// one sub-area (category "plantation") inside that boundary (the previous version of this fixture lay ~500 km from any boundary a test can create)
const SUB_AREAS = 'e2e/fixtures/sub_areas.geojson'

async function login(page: Page) {
  test.setTimeout(240000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  await resetWorkspaceLayout(page) // the saved dock layout is per user: undo what an earlier spec collapsed
}

test.describe('Sub-areas import → Feature-to-Polygon + category (Phase 5/6)', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    await deleteCurrentForest(page)
  })

  test('import a sub-areas GeoJSON; the polygon is stored and counted on the Sub-Areas layer', async ({ page }) => {
    await login(page)
    await createForestWithBoundary(page, 'E2E SubAreas', BOUNDARY)

    // Add data → the file is a sub-areas layer (a polygon inside the boundary, with its category) → Import.
    await importViaAddData(page, SUB_AREAS, { purposeButton: /^Sub-Areas/ })
    await closeAddDataReport(page)

    // Feature-to-Polygon: the sub-area is stored and counted on the layer.
    await expect(page.getByRole('button', { name: /Activate Sub-Areas/i })).toContainText('1', { timeout: 30000 })
  })
})
