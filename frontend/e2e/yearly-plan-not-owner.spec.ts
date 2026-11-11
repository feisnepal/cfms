/**
 * yearly-plan-not-owner.spec.ts — live E2E for D9 (YEARLY_ACTIVITIES_WORKSPACE_PLAN.md P4, YA-4.9): only the OWNER
 * plans a forest's yearly activities — a super-admin is not the owner. Opened as the demo super-admin on a forest
 * that belongs to someone else, the map workspace shows a plain message and offers nothing to change.
 *
 * READ-ONLY. SKIPPED by default: needs a running stack and E2E_YEARLY_OTHER_CALC_ID = a calculation owned by a
 * DIFFERENT user than the login below (that user must be able to open it, i.e. be a super-admin).
 *
 * The login is demo@forest.com unless E2E_SUPER_EMAIL / E2E_SUPER_PASSWORD name another account. When the account is NOT a super-admin
 * (the demo user in some databases is a plain user, who cannot open another owner's forest at all) the browser half is skipped with that
 * reason; the API half - the plan routes answer 404 to anyone but the owner - still runs.
 */
import { test, expect, Page } from '@playwright/test'

const OTHER = process.env.E2E_YEARLY_OTHER_CALC_ID || ''
const RUN = Boolean(OTHER)
const URL = `/calculations/${OTHER}?tab=forest-data&context=unified`

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', process.env.E2E_SUPER_EMAIL || 'demo@forest.com')
  await page.fill('input[name="password"]', process.env.E2E_SUPER_PASSWORD || 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('yearly plan — not the owner (D9)', () => {
  test.skip(!RUN, 'set E2E_YEARLY_OTHER_CALC_ID to run against a live stack')

  test('a super-admin on someone else’s forest gets 404 from the plan routes, a plain message, and no way to change the plan', async ({ page }) => {
    await login(page)
    const token = await page.evaluate(() => localStorage.getItem('access_token') || '')
    for (const path of ['yearly-plan', 'yearly-plan/health', 'drawn-features']) {
      const res = await page.request.get(`/api/yearly-activities/calculations/${OTHER}/${path}`, { headers: { Authorization: `Bearer ${token}` } })
      expect(res.status(), path).toBe(404)
    }

    const me = await page.request.get('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } })
    const role = me.ok() ? String((await me.json()).role ?? '').toLowerCase() : ''
    test.skip(role !== 'super_admin', `the browser half needs a super-admin login (this one is "${role}"): set E2E_SUPER_EMAIL / E2E_SUPER_PASSWORD`)

    await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
    // the Yearly plan button sits behind the header's "Layers" button
    const disclosure = page.getByTestId('panel-toggles-disclosure')
    await expect(disclosure).toBeVisible({ timeout: 60000 })
    if ((await disclosure.getAttribute('aria-expanded')) !== 'true') await disclosure.click()
    await expect(page.getByTestId('open-yearly-plan')).toBeVisible({ timeout: 60000 })

    // nothing that plans is offered on the map
    await expect(page.getByTestId('next-step-bar')).toHaveCount(0)
    await expect(page.getByTestId('activity-wizard')).toHaveCount(0)
    await expect(page.getByTestId('table-add-activity')).toHaveCount(0)

    // the plan table says why, in plain words, with nothing to press
    await page.getByTestId('open-yearly-plan').click()
    await expect(page.getByTestId('plan-table-not-owner')).toHaveText('Only the owner of this forest can see and change its yearly plan.', { timeout: 30000 })
    await expect(page.getByTestId('plan-table-failed')).toHaveCount(0)
    await expect(page.getByTestId('plan-table-add')).not.toBeVisible()
    await page.screenshot({ path: 'test-results/yearly-plan-not-owner.png' })
  })
})
