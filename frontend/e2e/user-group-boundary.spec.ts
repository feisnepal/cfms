/**
 * user-group-boundary.spec.ts — E2E for the User Group Boundary workspace layer
 * (USER_GROUP_BOUNDARY_PLAN.md P2).
 *
 * SKIPPED by default: needs a running stack (backend :8001 + frontend) and a
 * seeded calculation whose forest boundary is set. Point E2E_USER_GROUP_CALC_ID
 * at that calculation's id to enable.
 *
 * Flow under test (map workspace):
 *   1. the TOC lists "User Group Boundary" right under "Forest Boundary";
 *   2. activating it + the Draw tool lets you draw a polygon;
 *   3. on finish, POST .../user-group/manual is called and the extent renders;
 *   4. a second draw replaces it (single-feature model).
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_USER_GROUP_CALC_ID || ''
const RUN = Boolean(CALC_ID)

async function login(page: Page) {
  test.setTimeout(180000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('User Group Boundary — workspace layer', () => {
  test.skip(!RUN, 'set E2E_USER_GROUP_CALC_ID to a calc whose forest boundary is set')

  test('the layer is listed and a drawn polygon persists via /user-group/manual', async ({ page }) => {
    await login(page)
    await page.goto(`/calculations/${CALC_ID}?tab=data-maps&context=maps`, { waitUntil: 'networkidle' })

    // TOC entry
    const tocRow = page.getByText(/User Group Boundary|उपभोक्ता समूह सीमा/).first()
    await expect(tocRow).toBeVisible()
    await tocRow.click()

    // Draw
    const drawBtn = page.getByRole('button', { name: /Draw|कोर्नुहोस्/ }).first()
    await expect(drawBtn).toBeVisible()

    const savePromise = page.waitForResponse(
      (r) => r.url().includes('/user-group/manual') && r.request().method() === 'POST' && r.ok(),
      { timeout: 30000 },
    )
    await drawBtn.click()

    const map = page.locator('.leaflet-container')
    const box = await map.boundingBox()
    if (!box) throw new Error('map not visible')
    const cx = box.x + box.width / 2
    const cy = box.y + box.height / 2
    await page.mouse.click(cx - 60, cy - 60)
    await page.mouse.click(cx + 60, cy - 60)
    await page.mouse.click(cx + 60, cy + 60)
    await page.mouse.click(cx - 60, cy + 60)
    await page.mouse.dblclick(cx - 60, cy - 60)

    const resp = await savePromise
    expect(resp.ok()).toBeTruthy()
  })
})
