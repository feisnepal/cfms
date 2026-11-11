/**
 * yearly-plan-home.spec.ts — live E2E for the yearly-activities screens after P5 of
 * YEARLY_ACTIVITIES_WORKSPACE_PLAN.md, on BOTH: the standalone page and the Reports-tab screen.
 *
 * The shared plan panel opens on "Your plan" (D20); numbers save at once with Undo (D21) — there is no "Save All";
 * the add-activity questions replace the old "Choose"; where an activity applies is chosen in one dialog; and a
 * change made elsewhere (the map, another tab) is never silently overwritten (a stale save is refused and explained).
 *
 * SKIPPED by default: needs a running stack and E2E_YEARLY_CALC_ID (a forest the demo user owns whose plan does
 * not contain activities 130 "scholarship" and 12 "fire line"). Every line the spec creates is removed again,
 * through its own login, so a crash or a closed page cannot leave one behind.
 */
import { test, expect, request, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const API = `/api/yearly-activities`
const PLAN = `${API}/calculations/${CALC_ID}/yearly-plan`
const NO_MAP = 130 // scholarship: needs no map
const MAPPABLE = 12 // fire line: can be drawn on the map
const SCREENS: Array<[string, string]> = [
  ['standalone page', `/calculations/${CALC_ID}/yearly-activities`],
  ['Reports tab', `/calculations/${CALC_ID}?tab=reports-outputs&context=yearlyactivities`],
]

interface ApiYear { year: number; quantity: number; budget: number; planned: boolean }
interface ApiLine {
  id: string
  potential_activity_id: number
  version: number
  reviewed_at: string | null
  default_quantity: number
  default_yearly_budget: number
  assign_to_all_blocks: boolean
  total_budget: number
  years: ApiYear[]
}

/** An API client with its own login: independent of any browser page. */
async function withApi<T>(run: (get: (path: string) => Promise<any>, send: (method: 'post' | 'put' | 'delete', path: string, data?: unknown) => Promise<any>) => Promise<T>): Promise<T> {
  const api = await request.newContext({ baseURL: 'http://localhost:3001' })
  try {
    const login = await api.post('/api/auth/login', { data: { email: 'demo@forest.com', password: 'Demo1234' } })
    const headers = { Authorization: `Bearer ${((await login.json()) as { access_token: string }).access_token}`, 'Content-Type': 'application/json' }
    return await run(
      async (path) => (await api.get(path, { headers })).json(),
      async (method, path, data) => api[method](path, { headers, data }),
    )
  } finally {
    await api.dispose()
  }
}

const planLines = (): Promise<ApiLine[]> => withApi(async (get) => (await get(PLAN)).lines)

async function removeLinesFor(...activityIds: number[]) {
  await withApi(async (get, send) => {
    for (const line of ((await get(PLAN)).lines as ApiLine[]).filter((l) => activityIds.includes(l.potential_activity_id))) {
      await send('delete', `${API}/proposed-activities/${line.id}`)
    }
  })
}

/** A plan line at the starting numbers (1 × NPR 5,000), created through the API. */
async function createLine(activityId: number): Promise<string> {
  return withApi(async (_get, send) => {
    const res = await send('post', `${API}/calculations/${CALC_ID}/proposed-activities`, {
      potential_activity_id: activityId,
      default_quantity: 1,
      default_yearly_budget: 5000,
    })
    expect(res.ok()).toBeTruthy()
    return ((await res.json()) as { id: string }).id
  })
}

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

async function openScreen(page: Page, url: string) {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('plan-table')).toBeVisible({ timeout: 60000 })
}

for (const [name, url] of SCREENS) {
  test.describe(`yearly plan — ${name}`, () => {
    test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')
    test.describe.configure({ mode: 'serial' })

    test.beforeEach(async ({ page }) => {
      await removeLinesFor(NO_MAP, MAPPABLE) // never start from a leftover
      await login(page)
    })
    test.afterEach(async () => {
      await removeLinesFor(NO_MAP, MAPPABLE)
    })

    test('opens on "Your plan": the editable table, no "Save All"', async ({ page }) => {
      const expected = (await planLines()).length
      await openScreen(page, url)
      await expect(page.getByRole('tab', { name: 'Your plan' })).toHaveAttribute('aria-selected', 'true')
      await expect(page.getByRole('tab', { name: 'Browse all activities' })).toHaveAttribute('aria-selected', 'false')
      await expect(page.getByTestId('plan-table').locator('tr[data-row-key]')).toHaveCount(expected, { timeout: 30000 })
      await expect(page.getByRole('button', { name: /save all/i })).toHaveCount(0)
      await page.screenshot({ path: `test-results/yearly-home-${name.replace(' ', '-')}.png` })
    })

    test('a number saves at once, the first value fills the rest, and Undo puts it back', async ({ page }) => {
      test.setTimeout(120000)
      const id = await createLine(NO_MAP)
      await openScreen(page, url)
      if (name === 'Reports tab') {
        // this address now opens step 15, where the year cells are typed into: one number per cell, the Budget view for money
        await expect(page.getByTestId(`year-input-${id}-1`)).toBeVisible({ timeout: 30000 })
        await page.getByTestId('plan-metric-switch').getByText('Budget').click()
        const cell = page.getByTestId(`year-input-${id}-1`)
        await cell.click()
        await cell.fill('80000')
        await cell.press('Enter')
      } else {
        await expect(page.getByTestId(`year-edit-${id}-1`)).toBeVisible({ timeout: 30000 })
        await page.getByTestId(`year-edit-${id}-1`).click()
        await page.getByTestId(`year-edit-${id}-1-budget`).fill('80000')
        await page.getByTestId(`year-edit-${id}-1-save`).click()
      }
      await expect(page.getByTestId('plan-table-status')).toHaveAttribute('data-kind', 'filled', { timeout: 30000 })
      let now = (await planLines()).find((l) => l.id === id)!
      expect(now.years.every((y) => y.budget === 80000)).toBe(true) // no "Save All" was pressed

      await page.getByTestId('plan-table-undo').click()
      await expect(page.getByTestId('plan-table-status')).toHaveAttribute('data-kind', 'undone', { timeout: 30000 })
      now = (await planLines()).find((l) => l.id === id)!
      expect(now.years.every((y) => y.budget === 5000 && y.quantity === 1)).toBe(true)
      expect(now.reviewed_at).toBeNull()
    })

    test('adding an activity that needs no map: the questions, then its row — no place question, no page change', async ({ page }) => {
      test.setTimeout(120000)
      const before = (await planLines()).length
      await openScreen(page, url)

      await page.getByRole('tab', { name: 'Browse all activities' }).click()
      await page.getByTestId('activity-search').fill('scholarship')
      await page.getByTestId(`activity-row-${NO_MAP}`).getByRole('button', { name: 'Choose' }).click()
      await expect(page.getByTestId('activity-wizard')).toBeVisible()
      await expect(page.getByTestId('wizard-when')).toBeVisible()
      await expect(page.getByTestId('wizard-where')).toHaveCount(0)
      await page.getByTestId('preset-first5').click()
      await page.getByTestId('wizard-next').click()
      await page.getByTestId('numbers-quantity').fill('2')
      await page.getByTestId('numbers-budget').fill('5000')
      await expect(page.getByTestId('numbers-total')).toContainText('NPR 25,000')
      await page.getByTestId('wizard-next').click()
      await page.getByTestId('wizard-save').click()
      await expect(page.getByTestId('activity-wizard')).toHaveCount(0, { timeout: 15000 })

      const line = (await planLines()).find((l) => l.potential_activity_id === NO_MAP)!
      expect(line.total_budget).toBe(25000)
      expect(line.reviewed_at).not.toBeNull()
      await expect(page.getByRole('tab', { name: 'Your plan' })).toHaveAttribute('aria-selected', 'true')
      await expect(page.getByTestId('plan-table').locator('tr[data-row-key]')).toHaveCount(before + 1, { timeout: 30000 })
      if (name === 'Reports tab') {
        // step 15's grid: a planned year shows its quantity, an unplanned one is empty
        await expect(page.getByTestId(`year-input-${line.id}-1`)).toHaveValue('2')
        await expect(page.getByTestId(`year-input-${line.id}-6`)).toHaveValue('')
      } else {
        await expect(page.getByTestId(`year-${line.id}-1`)).toHaveAttribute('data-planned', 'true')
        await expect(page.getByTestId(`year-${line.id}-6`)).toHaveAttribute('data-planned', 'false')
      }
    })

    test('an activity that can be drawn: "whole forest" or "decide later" here, and the drawing is done on the map', async ({ page }) => {
      await openScreen(page, url)
      await page.getByTestId('plan-table-add').click()
      await page.getByTestId('activity-search').last().fill('fire line')
      await page.getByTestId(`activity-row-${MAPPABLE}`).getByRole('button', { name: 'Choose' }).click()
      const where = page.getByTestId('wizard-where')
      await expect(where).toBeVisible()
      await expect(where.getByTestId('where-map')).toHaveCount(0) // nothing to draw on here
      await expect(where.getByText('It applies to the whole forest', { exact: true })).toBeVisible()
      await expect(where.getByText('Decide later', { exact: true })).toBeVisible()
      await expect(page.getByTestId('wizard-no-draw')).toBeVisible()
      await expect(page.getByTestId('wizard-edit-on-map')).toBeVisible()
    })

    test('where an activity applies: a chosen block is named in the table, and the whole forest says so', async ({ page }) => {
      test.setTimeout(120000)
      const id = await createLine(MAPPABLE)
      await openScreen(page, url)
      const row = page.locator(`tr[data-row-key="${id}"]`)
      await expect(row).toContainText('Not shown on the map yet', { timeout: 30000 }) // nothing chosen yet

      // one block
      await page.getByTestId(`location-details-${id}`).click()
      await expect(page.getByRole('checkbox', { name: 'All blocks' })).not.toBeChecked() // nothing was chosen
      await page.getByRole('checkbox', { name: 'C-1', exact: true }).check()
      await page.getByRole('button', { name: 'Save' }).click()
      await expect(page.getByTestId(`assigned-units-${id}`)).toHaveText('In C-1', { timeout: 30000 })
      await expect(row).not.toContainText('Not shown on the map yet') // it now counts as located
      let now = (await planLines()).find((l) => l.id === id)!
      expect(now.assign_to_all_blocks).toBe(false)

      // the whole forest
      await page.getByTestId(`location-details-${id}`).click()
      await expect(page.getByRole('checkbox', { name: 'C-1', exact: true })).toBeChecked() // what was chosen is shown
      await page.getByRole('checkbox', { name: 'All blocks' }).check()
      await page.getByRole('button', { name: 'Save' }).click()
      await expect(page.getByTestId(`whole-forest-${id}`)).toBeVisible({ timeout: 30000 })
      now = (await planLines()).find((l) => l.id === id)!
      expect(now.assign_to_all_blocks).toBe(true)
    })

    test('"Edit on map" opens the forest’s map workspace', async ({ page }) => {
      await openScreen(page, url)
      await page.getByTestId('plan-home-edit-on-map').click()
      await expect(page).toHaveURL(new RegExp(`/calculations/${CALC_ID}\\?.*surface=base/unified`), { timeout: 30000 })
    })

    test('a change made elsewhere is never overwritten: a stale save is refused, explained, and the table shows what is there now', async ({ page }) => {
      test.setTimeout(120000)
      const id = await createLine(NO_MAP)
      await openScreen(page, url)
      const grid = name === 'Reports tab' // this address now opens step 15, where the year cells are typed into
      if (grid) {
        await expect(page.getByTestId(`year-input-${id}-1`)).toBeVisible({ timeout: 30000 })
        await page.getByTestId('plan-metric-switch').getByText('Budget').click()
      } else {
        await expect(page.getByTestId(`year-edit-${id}-1`)).toBeVisible({ timeout: 30000 })
      }
      const stale = (await planLines()).find((l) => l.id === id)!

      // "the map, or another tab" changes the same activity after this screen read it (two typed years: no fill)
      await withApi(async (_get, send) => {
        const res = await send('put', `${PLAN}/${id}`, {
          years: [{ year: 2, budget: 9999 }, { year: 3, budget: 9999 }],
          expected_version: stale.version,
        })
        expect(res.ok()).toBeTruthy()
      })

      // this screen still holds the older version: saving from it must be refused
      if (grid) {
        const cell = page.getByTestId(`year-input-${id}-1`)
        await cell.click()
        await cell.fill('7000')
        await cell.press('Enter')
      } else {
        await page.getByTestId(`year-edit-${id}-1`).click()
        await page.getByTestId(`year-edit-${id}-1-budget`).fill('7000')
        await page.getByTestId(`year-edit-${id}-1-save`).click()
      }
      await expect(page.locator('.ant-message')).toContainText('was changed while you were editing', { timeout: 15000 })

      // nothing of this screen's entry was applied, and the other change is intact
      const now = (await planLines()).find((l) => l.id === id)!
      expect(now.years.find((y) => y.year === 1)!.budget).toBe(5000)
      expect(now.years.find((y) => y.year === 2)!.budget).toBe(9999)
      // and the table was re-read: it shows the other change, not the old numbers
      if (grid) await expect(page.getByTestId(`year-input-${id}-2`)).toHaveValue('9999', { timeout: 30000 })
      else await expect(page.getByTestId(`year-${id}-2`)).toContainText('9,999', { timeout: 30000 })
    })
  })
}
