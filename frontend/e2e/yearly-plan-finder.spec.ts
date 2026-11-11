/**
 * yearly-plan-finder.spec.ts — E2E for the activity finder (YEARLY_ACTIVITIES_WORKSPACE_PLAN.md §4.11, P1b) on
 * both yearly-activities screens: the legacy page and the Reports-tab screen.
 *
 * Since P5 the finder is the "Browse all activities" tab of the shared plan panel (the screens open on "Your plan").
 * SKIPPED by default: needs a running backend (port 8001) with the master list seeded
 * (`python -m scripts.seed_activity_search_terms`) and a calculation the demo user owns.
 * Set E2E_YEARLY_CALC_ID. Read-only: nothing is ever chosen, so no plan line is created.
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const SCREENS: Array<[string, string]> = [
  ['legacy page', `/calculations/${CALC_ID}/yearly-activities`],
  ['Reports tab', `/calculations/${CALC_ID}?tab=reports-outputs&context=yearlyactivities`],
]

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('yearly plan — the activity finder', () => {
  test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')

  for (const [name, url] of SCREENS) {
    test.describe(name, () => {
      test.beforeEach(async ({ page }) => {
        await login(page)
        await page.goto(url, { waitUntil: 'domcontentloaded' })
        // the screens open on "Your plan" (D20); the finder is the "Browse all activities" tab
        await expect(page.getByTestId('plan-home')).toBeVisible({ timeout: 60000 })
        await page.getByRole('tab', { name: 'Browse all activities' }).click()
        await expect(page.getByTestId('activity-picker')).toBeVisible({ timeout: 30000 })
        // the list arrives after the panel opens: wait for it, so typing never races the load
        await expect(page.getByTestId('activity-count')).toContainText('169 of 169', { timeout: 30000 })
      })

      test('lists all 169 activities and says you can type in Nepali or English', async ({ page }) => {
        await expect(page.getByTestId('activity-count')).toContainText('169 of 169')
        await expect(page.getByText('You can type in Nepali or English.')).toBeVisible()
      })

      test('an English word finds the Nepali activity, with its English name and map badge', async ({ page }) => {
        await page.getByTestId('activity-search').fill('nursery')
        await expect(page.getByTestId('activity-count')).toContainText('5 of 169')
        const row = page.getByTestId('activity-row-1')
        await expect(row).toContainText('नर्सरी निर्माण')
        await expect(row).toContainText('Build a nursery')
        await expect(page.getByTestId('map-badge-1')).toContainText('Can be shown on the map as a point')
        await page.screenshot({ path: `test-results/yearly-finder-${name.replace(' ', '-')}-search.png`, fullPage: false })
      })

      test('a Nepali spelling variant still finds it (वन for the list\'s बन)', async ({ page }) => {
        await page.getByTestId('activity-search').fill('वन सिमांकन')
        await expect(page.getByTestId('activity-row-10')).toBeVisible()
      })

      test('a search that matches nothing offers suggestions and the browse tree, never a blank panel', async ({ page }) => {
        await page.getByTestId('activity-search').fill('xyzqq')
        await expect(page.getByTestId('no-match')).toContainText('Nothing matches')
        await expect(page.getByTestId('suggestions').locator('li')).toHaveCount(3)
        await expect(page.getByTestId('browse-tree')).toBeVisible()
      })

      test('the "Can be shown on the map" chip narrows the list', async ({ page }) => {
        await page.getByTestId('chip-map').click()
        await expect(page.getByTestId('activity-count')).toContainText('76 of 169')
      })

      test('the arrow keys move through the results', async ({ page }) => {
        const search = page.getByTestId('activity-search')
        await search.fill('nursery')
        await search.press('ArrowDown')
        await expect(search).toHaveAttribute('aria-activedescendant', 'ap-opt-1')
        await search.press('ArrowDown')
        await expect(search).toHaveAttribute('aria-activedescendant', 'ap-opt-2')
        await search.press('Escape')
        await expect(search).toHaveValue('')
      })

      test('a group opens to show its activities', async ({ page }) => {
        await page.getByTestId('tree-programme-toggle').first().click()
        await expect(page.getByTestId('activity-row-1')).toBeVisible()
      })
    })
  }
})
