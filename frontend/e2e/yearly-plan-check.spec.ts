/**
 * yearly-plan-check.spec.ts — live E2E for the plan check before the operational plan document is created
 * (YEARLY_ACTIVITIES_WORKSPACE_PLAN.md §4.3, P6, D24): choosing a template for a forest whose yearly plan still has
 * unfinished activities lists them first, offers a way to fix them, and never blocks.
 *
 * READ-ONLY: it stops at "Go back and fix", so no operational plan is created. SKIPPED by default: needs a running
 * stack and E2E_YEARLY_CALC_ID (a forest the demo user owns whose yearly plan has an unfinished line).
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('yearly plan — the plan check before the plan document', () => {
  test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')

  test('choosing a template lists what is unfinished first, and going back creates nothing', async ({ page }) => {
    await login(page)
    const token = await page.evaluate(() => localStorage.getItem('access_token') || '')
    const plan = await (await page.request.get(`/api/yearly-activities/calculations/${CALC_ID}/yearly-plan`, { headers: { Authorization: `Bearer ${token}` } })).json()
    const unfinished = (plan.lines as Array<{ reviewed_at: string | null; placeholder_fields: string[] }>).filter((l) => !l.reviewed_at && l.placeholder_fields.length > 0)
    test.skip(unfinished.length === 0, 'the yearly plan has no unfinished line')

    await page.goto(`/templates?calculation_id=${CALC_ID}`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Open in builder' }).first().click()

    const check = page.getByTestId('plan-check')
    await expect(check).toBeVisible({ timeout: 30000 })
    await expect(page.getByText(`Before we create your plan: ${unfinished.length} to check`)).toBeVisible()
    await expect(check).toContainText('Nothing is blocked')
    await expect(page.getByTestId('plan-check-continue')).toHaveText('Create the plan anyway')

    await page.getByTestId('plan-check-back').click()
    await expect(check).toBeHidden({ timeout: 15000 })
    await expect(page).toHaveURL(/\/templates/) // no plan was created, so nothing navigated to it
  })

  test('a row\'s Open button goes to the yearly-activities page of the forest', async ({ page }) => {
    await login(page)
    const token = await page.evaluate(() => localStorage.getItem('access_token') || '')
    const plan = await (await page.request.get(`/api/yearly-activities/calculations/${CALC_ID}/yearly-plan`, { headers: { Authorization: `Bearer ${token}` } })).json()
    test.skip(!(plan.lines as Array<{ reviewed_at: string | null; placeholder_fields: string[] }>).some((l) => !l.reviewed_at && l.placeholder_fields.length > 0), 'the yearly plan has no unfinished line')

    await page.goto(`/templates?calculation_id=${CALC_ID}`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: 'Open in builder' }).first().click()
    await page.getByTestId('plan-check-fix').first().click()
    await expect(page).toHaveURL(new RegExp(`/calculations/${CALC_ID}/yearly-activities`), { timeout: 30000 })
    await expect(page.getByTestId('plan-table')).toBeVisible({ timeout: 60000 })
  })
})
