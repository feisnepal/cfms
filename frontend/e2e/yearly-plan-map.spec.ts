/**
 * yearly-plan-map.spec.ts — E2E for the yearly plan on the MAP workspace (YEARLY_ACTIVITIES_WORKSPACE_PLAN.md
 * P2): the Next-step bar, the editable Activity Features table (name, years, symbol, with undo) and the two
 * named exports.
 *
 * SKIPPED by default: needs a running backend (port 8001) and a calculation the demo user owns that has at
 * least one drawn activity place. Set E2E_YEARLY_CALC_ID. The spec edits the first place and restores it
 * (undo, then a direct restore in afterAll), so the forest ends as it started.
 */
import { test, expect, Page } from '@playwright/test'
import { closeForestSummary } from './helpers/forestSummary'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const URL = `/calculations/${CALC_ID}?tab=forest-data&context=unified`
const API = `/api/yearly-activities/calculations/${CALC_ID}`

interface Place { id: string; name: string; years: number[]; kind: string }

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

const token = (page: Page) => page.evaluate(() => localStorage.getItem('access_token') || '')

async function places(page: Page): Promise<Place[]> {
  const res = await page.request.get(`${API}/drawn-features`, { headers: { Authorization: `Bearer ${await token(page)}` } })
  expect(res.ok()).toBeTruthy()
  const rows = (await res.json()) as Array<{ id: string; properties?: { name?: string; years?: number[] }; kind?: string }>
  return rows.map((r) => ({ id: r.id, name: r.properties?.name ?? '', years: r.properties?.years ?? [], kind: r.kind ?? '' }))
}

async function patchPlace(page: Page, id: string, body: Record<string, unknown>) {
  const res = await page.request.patch(`${API}/activity-features/${id}`, {
    headers: { Authorization: `Bearer ${await token(page)}`, 'Content-Type': 'application/json' },
    data: body,
  })
  expect(res.ok()).toBeTruthy()
}

async function openTable(page: Page) {
  await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
  await expect(page.getByTestId('layer-item').first()).toBeVisible({ timeout: 60000 })
  await closeForestSummary(page) // it floats over the map and can cover what the spec presses
  await page.getByTestId('layer-item').filter({ hasText: 'Activity Features' }).first().click({ button: 'right' })
  await page.getByText('Show attributes').click()
  await expect(page.locator('[role="row"].table-row').first()).toBeVisible({ timeout: 30000 })
}

test.describe('yearly plan — on the map', () => {
  test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')
  test.describe.configure({ mode: 'serial' })

  let original: Place | undefined

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage()
    await login(page)
    original = (await places(page))[0]
    await page.close()
  })

  test.afterAll(async ({ browser }) => {
    if (!original) return
    const page = await browser.newPage()
    await login(page)
    await patchPlace(page, original.id, { name: original.name, years: original.years, kind: original.kind })
    await page.close()
  })

  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('the Next-step bar says what to do next and can be folded away', async ({ page }) => {
    await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
    await closeForestSummary(page) // it floats over the map and can cover the pill
    const bar = page.getByTestId('next-step-bar')
    const layer = page.getByTestId('layer-item').filter({ hasText: 'Activity Features' }).first()
    await expect(layer).toBeVisible({ timeout: 60000 })
    // the bar belongs to the Activity Features layer: not there until that layer is the active one
    await expect(bar).toHaveCount(0)
    await layer.locator('.layer-name-btn').click()
    await expect(bar).toBeVisible({ timeout: 30000 })
    // ...and gone again when another layer becomes the active one
    await page.getByTestId('layer-item').filter({ hasText: 'Compartments' }).first().locator('.layer-name-btn').click()
    await expect(bar).toHaveCount(0)
    await expect(page.getByTestId('next-step-pill')).toHaveCount(0)
    await layer.locator('.layer-name-btn').click()
    await expect(bar).toBeVisible({ timeout: 30000 })
    await expect(bar).toContainText('Next step')
    await page.getByTestId('next-step-bar-hide').click()
    await expect(bar).toHaveCount(0)
    await expect(page.getByTestId('next-step-pill')).toBeVisible()
    await page.getByTestId('next-step-pill').click()
    await expect(page.getByTestId('next-step-bar')).toBeVisible()
  })

  test('a place is renamed in the table, saved, and Ctrl+Z puts the old name back', async ({ page }) => {
    test.skip(!original, 'the forest has no drawn place')
    await openTable(page)
    const row = page.locator('[role="row"].table-row').first()
    const nameCell = row.locator('[role="gridcell"].editable').first()
    // click, then Enter (the grid's keyboard way to edit a cell). A real double-click does not open the editor here, although a
    // synthetic dblclick event does: reported separately, not hidden by this test.
    await nameCell.click()
    await page.keyboard.press('Enter')
    const input = row.locator('input[type="text"], input:not([type])').last()
    await input.fill('E2E renamed place')
    await input.press('Enter')
    await expect.poll(async () => (await places(page))[0].name, { timeout: 15000 }).toBe('E2E renamed place')

    await page.locator('.attribute-table, [data-testid="attribute-table"]').first().click({ position: { x: 5, y: 5 }, force: true }).catch(() => undefined)
    await page.keyboard.press('Control+z')
    await expect.poll(async () => (await places(page))[0].name, { timeout: 15000 }).toBe(original!.name)
  })

  test('the symbol drop-down changes the place\'s map symbol', async ({ page }) => {
    test.skip(!original, 'the forest has no drawn place')
    await openTable(page)
    const select = page.locator('[role="row"].table-row').first().getByRole('combobox')
    await select.selectOption('road')
    await expect.poll(async () => (await places(page))[0].kind, { timeout: 15000 }).toBe('road')
    await select.selectOption(original!.kind || '')
    await expect.poll(async () => (await places(page))[0].kind, { timeout: 15000 }).toBe(original!.kind)
  })

  test('the years chooser saves a new set of years', async ({ page }) => {
    test.skip(!original, 'the forest has no drawn place')
    await openTable(page)
    await page.locator('[role="row"].table-row').first().getByTestId('years-cell').click()
    const chooser = page.getByTestId('years-chooser')
    await expect(chooser).toBeVisible()
    // toggle year 9 (add it, or remove it when it was there) and apply
    const had = original!.years.includes(9)
    await chooser.getByTestId('year-chip-9').click()
    await chooser.getByTestId('years-apply').click()
    await expect
      .poll(async () => (await places(page))[0].years.includes(9), { timeout: 15000 })
      .toBe(!had)
  })

  test('both named exports download from the table\'s Export menu', async ({ page }) => {
    await openTable(page)
    for (const [label, expected] of [
      ['Yearly plan (CSV)', /YearlyPlan|yearly/i],
      ['Activity features (CSV)', /ActivityFeatures|activity/i],
    ] as const) {
      await page.getByTestId('plan-export').click()
      const downloading = page.waitForEvent('download')
      await page.getByText(label).click()
      // the plan check (P6) is shown first while anything is unfinished; it never blocks
      await page.getByTestId('plan-check-continue').click({ timeout: 8000 }).catch(() => undefined)
      const download = await downloading
      expect(download.suggestedFilename()).toMatch(/\.csv$/)
      expect(download.suggestedFilename()).toMatch(expected)
    }
  })
})
