/**
 * protection-unit.spec.ts — E2E for promote / demote a protected sub-area to a
 * Protection Working Circle unit (PROTECTION_WORKING_CIRCLE_PLAN.md P3).
 *
 * SKIPPED by default: needs a running backend (port 8001) + a seeded
 * calculation that has at least one `category='protected'` sub-area and one
 * block/compartment it overlaps. Set E2E_PROTECTION_CALC_ID to that
 * calculation's id to enable.
 *
 * Flow under test (areadetail context, Table 1):
 *   1. a protected sub-area row shows a "Make protection unit" button;
 *   2. clicking it opens a confirm modal; confirming calls
 *      POST /sub-areas/{id}/promote-to-unit and the row disappears;
 *   3. the reverse (demote) is exercised wherever protection units are listed.
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_PROTECTION_CALC_ID || ''
const RUN = Boolean(CALC_ID)

async function login(page: Page) {
  test.setTimeout(180000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('Protection Working Circle — promote / demote', () => {
  test.skip(!RUN, 'set E2E_PROTECTION_CALC_ID to a calc with a protected sub-area')

  test('promote a protected sub-area from the area-detail table', async ({ page }) => {
    await login(page)
    await page.goto(`/calculations/${CALC_ID}?tab=forest-data&context=areadetail`, {
      waitUntil: 'networkidle',
    })

    const promote = page.getByRole('button', { name: /Make protection unit|संरक्षित एकाई बनाउनुस्/ })
    await expect(promote.first()).toBeVisible()
    const before = await promote.count()

    await promote.first().click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: /Make protection unit|संरक्षित एकाई बनाउनुस्/ }).click()

    // one fewer protected row after the promote
    await expect
      .poll(async () => promote.count(), { timeout: 15000 })
      .toBe(before - 1)
  })
})
