/**
 * yearly-plan-wizard.spec.ts — E2E for the add-activity wizard on the MAP workspace
 * (YEARLY_ACTIVITIES_WORKSPACE_PLAN.md P3): an activity that needs no map goes straight to the plan; a mappable
 * one is drawn on the live map, its quantity pre-filled from the drawing.
 *
 * SKIPPED by default: needs a running backend (port 8001) and a calculation the demo user owns whose plan does
 * not yet contain the activities used below (ids 130 "scholarship" and 12 "fire line"). Set E2E_YEARLY_CALC_ID.
 * Every line and place the spec creates is removed again in afterEach.
 */
import { test, expect, Page } from '@playwright/test'
import { openPanelButtons } from './helpers/dock'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const URL = `/calculations/${CALC_ID}?tab=forest-data&context=unified`
const API = `/api/yearly-activities`

interface Line { id: string; potential_activity_id: number; reviewed_at: string | null; planned_years: number[]; total_budget: number; feature_count: number; default_quantity: number }

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

const auth = async (page: Page) => ({ Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('access_token') || '')}` })

async function planLines(page: Page): Promise<Line[]> {
  const res = await page.request.get(`${API}/calculations/${CALC_ID}/yearly-plan`, { headers: await auth(page) })
  expect(res.ok()).toBeTruthy()
  return ((await res.json()) as { lines: Line[] }).lines
}

/** Remove what a test added: its places (with the line) or its plain line. */
async function cleanup(page: Page, activityId: number) {
  const headers = await auth(page)
  const line = (await planLines(page)).find((l) => l.potential_activity_id === activityId)
  if (!line) return
  const feats = await page.request.get(`${API}/calculations/${CALC_ID}/drawn-features`, { headers })
  for (const f of (await feats.json()) as Array<{ id: string; proposed_activity_id: string }>) {
    if (f.proposed_activity_id === line.id) {
      await page.request.delete(`${API}/calculations/${CALC_ID}/activity-features/${f.id}?remove_plan_line=false`, { headers })
    }
  }
  await page.request.delete(`${API}/proposed-activities/${line.id}`, { headers })
}

async function openWizard(page: Page) {
  await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
  const layer = page.getByTestId('layer-item').filter({ hasText: 'Activity Features' }).first()
  await expect(layer).toBeVisible({ timeout: 60000 })
  await layer.locator('.layer-name-btn').click() // the Next-step bar shows only while the Activity Features layer is active
  await expect(page.getByTestId('next-step-bar')).toBeVisible({ timeout: 30000 })
  await page.getByTestId('next-step-bar-add').click()
  await expect(page.getByTestId('activity-wizard')).toBeVisible()
}

async function pick(page: Page, word: string, id: number) {
  await page.getByTestId('activity-search').fill(word)
  await page.getByTestId(`activity-row-${id}`).getByRole('button', { name: 'Choose' }).click()
}

test.describe('yearly plan — the add-activity wizard on the map', () => {
  test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')
  test.describe.configure({ mode: 'serial' })

  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1600, height: 950 })
    await login(page)
  })

  test.afterEach(async ({ page }) => {
    await login(page).catch(() => undefined)
    for (const id of [130, 12]) await cleanup(page, id)
  })

  test('an activity that needs no map: years, numbers, save — it reaches the plan reviewed, with no place question', async ({ page }) => {
    await openWizard(page)
    await pick(page, 'scholarship', 130)
    await expect(page.getByTestId('wizard-when')).toBeVisible()
    await expect(page.getByTestId('wizard-where')).toHaveCount(0)
    await page.getByTestId('preset-first5').click()
    await page.getByTestId('wizard-next').click()
    await page.getByTestId('numbers-quantity').fill('2')
    await page.getByTestId('numbers-budget').fill('5000')
    await expect(page.getByTestId('numbers-total')).toContainText('NPR 25,000')
    await page.getByTestId('wizard-next').click()
    await expect(page.getByTestId('confirm-sentence')).toContainText('NPR 25,000 in total')
    await page.screenshot({ path: 'test-results/wizard-confirm.png' })
    await page.getByTestId('wizard-save').click()
    await expect(page.getByTestId('activity-wizard')).toHaveCount(0, { timeout: 15000 })

    const line = (await planLines(page)).find((l) => l.potential_activity_id === 130)
    expect(line).toBeTruthy()
    expect(line!.reviewed_at).not.toBeNull() // the person typed the numbers
    expect(line!.planned_years).toEqual([1, 2, 3, 4, 5])
    expect(line!.total_budget).toBe(25000)
  })

  test('a mappable activity is drawn on the live map and its quantity comes from the drawing', async ({ page }) => {
    await openWizard(page)
    await pick(page, 'fire line', 12)
    await expect(page.getByTestId('wizard-where')).toBeVisible()
    await page.getByText('Show it on the map', { exact: true }).click()
    await expect(page.getByText('Click the map to draw the line, then press the ✓ button (or Enter) to finish. You can add more.')).toBeVisible()

    // draw a line on the map (left-centre, clear of the bar and the card)
    const map = page.locator('.leaflet-container').first()
    const box = (await map.boundingBox())!
    // the card covers the right of the map: draw well to the left of it
    const x = box.x + 40
    const y = box.y + box.height * 0.6
    await page.mouse.move(x, y)
    await page.mouse.click(x, y)
    await page.mouse.move(x + 120, y + 30)
    await page.mouse.click(x + 120, y + 30)
    await page.mouse.move(x + 240, y + 10)
    await page.mouse.click(x + 240, y + 10)
    await page.getByRole('button', { name: "Finish this place's shape" }).click() // the draw engine finishes a line from its confirm bar (or Enter)

    await expect(page.getByText('Places drawn: 1')).toBeVisible({ timeout: 10000 })
    await page.screenshot({ path: 'test-results/wizard-drawn.png' })
    await page.getByTestId('wizard-next').click() // WHEN
    await page.getByTestId('wizard-next').click() // HOW MUCH
    const quantity = await page.getByTestId('numbers-quantity').inputValue()
    expect(Number(quantity)).toBeGreaterThan(0) // measured from the line, in kilometres
    await expect(page.getByTestId('numbers-measured')).toContainText('Drawn:')
    await page.getByTestId('numbers-budget').fill('12000')
    await page.getByTestId('wizard-next').click() // NAME
    await page.getByTestId('name-input').fill('E2E fire line')
    await page.getByTestId('wizard-next').click() // CONFIRM
    await expect(page.getByTestId('confirm-sentence')).toContainText('E2E fire line')
    await page.getByTestId('wizard-save').click()
    await expect(page.getByTestId('activity-wizard')).toHaveCount(0, { timeout: 15000 })

    const line = (await planLines(page)).find((l) => l.potential_activity_id === 12)
    expect(line).toBeTruthy()
    expect(line!.feature_count).toBe(1)
    expect(line!.reviewed_at).not.toBeNull()
    expect(Math.abs(line!.default_quantity - Number(quantity))).toBeLessThan(0.01)
  })

  test('an activity that applies to the whole forest is saved without drawing anything', async ({ page }) => {
    await openWizard(page)
    await pick(page, 'fire line', 12)
    await page.getByText('It applies to the whole forest', { exact: true }).click()
    await page.getByTestId('wizard-next').click()
    await page.getByTestId('wizard-next').click()
    await page.getByTestId('numbers-quantity').fill('3')
    await page.getByTestId('numbers-budget').fill('0')
    await expect(page.getByTestId('numbers-zero')).toBeVisible()
    await page.getByTestId('wizard-next').click()
    await page.getByTestId('wizard-save').click()
    await expect(page.getByTestId('activity-wizard')).toHaveCount(0, { timeout: 15000 })
    const line = (await planLines(page)).find((l) => l.potential_activity_id === 12)
    expect(line).toBeTruthy()
    expect(line!.feature_count).toBe(0)
  })

  test('from the Yearly plan view: an activity that needs no map is added and appears in the table, without leaving the workspace', async ({ page }) => {
    await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
    await openPanelButtons(page) // the button sits behind the header's Layers button
    await expect(page.getByTestId('open-yearly-plan')).toBeVisible({ timeout: 60000 })
    await page.getByTestId('open-yearly-plan').click()
    await expect(page.getByTestId('plan-table')).toBeVisible({ timeout: 30000 })
    const before = (await planLines(page)).length // from the API: the table may still be loading its rows

    await page.getByTestId('plan-table-add').click()
    await expect(page.getByTestId('activity-wizard')).toBeVisible()
    await pick(page, 'scholarship', 130)
    await expect(page.getByTestId('wizard-where')).toHaveCount(0) // no place question for an activity that needs no map
    await page.getByTestId('preset-first5').click()
    await page.getByTestId('wizard-next').click()
    await page.getByTestId('numbers-quantity').fill('2')
    await page.getByTestId('numbers-budget').fill('5000')
    await page.getByTestId('wizard-next').click()
    await page.getByTestId('wizard-save').click()
    await expect(page.getByTestId('activity-wizard')).toHaveCount(0, { timeout: 15000 })

    const line = (await planLines(page)).find((l) => l.potential_activity_id === 130)
    expect(line).toBeTruthy()
    // its row is in the table now, with its ten-year grid; nothing was opened beside this page
    await expect(page.locator('[data-testid="plan-table"] tr[data-row-key]')).toHaveCount(before + 1, { timeout: 30000 })
    await expect(page.getByTestId(`year-${line!.id}-1`)).toHaveAttribute('data-planned', 'true')
    await expect(page.getByTestId(`year-${line!.id}-6`)).toHaveAttribute('data-planned', 'false')
    await expect(page.getByTestId(`select-places-${line!.id}`)).toHaveCount(0) // no place, no map words
    await expect(page.getByTestId(`show-on-map-${line!.id}`)).toHaveCount(0)
    expect(page.url()).toContain(`/calculations/${CALC_ID}`)
    expect(page.context().pages().length).toBe(1)
  })
})
