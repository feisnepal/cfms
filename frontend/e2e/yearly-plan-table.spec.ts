/**
 * yearly-plan-table.spec.ts — live E2E for the Yearly Plan table on the MAP workspace
 * (YEARLY_ACTIVITIES_WORKSPACE_PLAN.md P4): the Features | Plan switch, Table B (one row per plan line, the
 * ten-year grid, the Location cell) and the quantity column of the places table.
 *
 * Read-only, except the last test: it adds a throwaway plan line through the API, confirms it in the UI and deletes it
 * again (also in afterAll if it failed half way), so the forest ends as it started. SKIPPED by default: needs a running backend (port 8001) and a calculation the
 * demo user owns. Set E2E_YEARLY_CALC_ID.
 *
 * The map page is heavy and its endpoints are rate-limited (429 on back-to-back loads), so the page is opened
 * ONCE and shared by the tests (they only read and switch views).
 */
import { test, expect, request, Page } from '@playwright/test'
import { openPanelButtons } from './helpers/dock'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const URL = `/calculations/${CALC_ID}?tab=forest-data&context=unified`
const API = `/api/yearly-activities/calculations/${CALC_ID}`

interface ApiYear { year: number; quantity: number; budget: number; planned: boolean }
interface ApiLine {
  id: string
  potential_activity_id: number
  reviewed_at: string | null
  placeholder_fields: string[]
  years: ApiYear[]
  feature_count: number
  location_mode: string
  location_units?: string[]
}
interface ApiPlace { proposed_activity_id: string; plan_quantity: number | null; plan_unit: string | null; shared_count: number }

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

const token = (page: Page) => page.evaluate(() => localStorage.getItem('access_token') || '')

async function apiGet<T>(page: Page, path: string): Promise<T> {
  const res = await page.request.get(`${API}${path}`, { headers: { Authorization: `Bearer ${await token(page)}` } })
  expect(res.ok()).toBeTruthy()
  return (await res.json()) as T
}

const planLines = async (page: Page) => (await apiGet<{ lines: ApiLine[] }>(page, '/yearly-plan')).lines
const places = (page: Page) => apiGet<ApiPlace[]>(page, '/drawn-features')

async function openActivityTable(page: Page) {
  await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
  await expect(page.getByTestId('layer-item').first()).toBeVisible({ timeout: 60000 })
  await page.getByTestId('layer-item').filter({ hasText: 'Activity Features' }).first().click({ button: 'right' })
  await page.getByText('Show attributes').click()
  await expect(page.getByTestId('table-view-switch')).toBeVisible({ timeout: 30000 })
}

const showPlan = async (page: Page) => {
  await page.getByTestId('table-view-switch').getByText('Yearly plan').click()
  await expect(page.getByTestId('plan-table')).toBeVisible({ timeout: 30000 })
}
const showPlaces = async (page: Page) => {
  await page.getByTestId('table-view-switch').getByText('Places on the map').click()
  await expect(page.getByTestId('plan-table')).toHaveCount(0)
}

test.describe('yearly plan table — on the map', () => {
  test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')
  test.describe.configure({ mode: 'serial' })

  let page: Page

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await login(page)
    await openActivityTable(page)
  })

  let throwaway: string | undefined

  // Cleanup must not depend on the browser page (it may be closed by a timeout or a crash): it logs in on its own.
  const deleteThrowaway = async () => {
    if (!throwaway) return
    const id = throwaway
    const api = await request.newContext({ baseURL: 'http://localhost:3001' })
    try {
      const login = await api.post('/api/auth/login', { data: { email: 'demo@forest.com', password: 'Demo1234' } })
      const { access_token } = (await login.json()) as { access_token: string }
      const res = await api.delete(`/api/yearly-activities/proposed-activities/${id}`, {
        headers: { Authorization: `Bearer ${access_token}` },
      })
      if (res.ok()) throwaway = undefined
    } finally {
      await api.dispose()
    }
  }

  /** A plan line at the starting numbers (1 x NPR 5,000) for an activity that needs no map and is not in the plan. */
  const createThrowaway = async (): Promise<string> => {
    const list = await page.request.get('/api/yearly-activities/potential-activities', {
      params: { is_active: 'true' },
      headers: { Authorization: `Bearer ${await token(page)}` },
    })
    expect(list.ok()).toBeTruthy()
    const masters = (await list.json()) as Array<{ id: number; requires_map: boolean }>
    const taken = new Set((await planLines(page)).map((l) => l.potential_activity_id))
    const master = masters.find((m) => !m.requires_map && !taken.has(m.id))
    test.skip(!master, 'every activity that needs no map is already in the plan')
    const created = await page.request.post(`${API}/proposed-activities`, {
      headers: { Authorization: `Bearer ${await token(page)}`, 'Content-Type': 'application/json' },
      data: { potential_activity_id: master!.id, default_quantity: 1, default_yearly_budget: 5000 },
    })
    expect(created.ok()).toBeTruthy()
    throwaway = ((await created.json()) as { id: string }).id
    return throwaway
  }

  test.afterAll(async () => {
    try {
      await deleteThrowaway()
    } finally {
      await page?.close()
    }
  })

  test('the Yearly plan view lists one row per plan line, and the switch goes back to the places', async () => {
    const expected = (await planLines(page)).length
    await showPlan(page)
    if (expected === 0) {
      await expect(page.getByTestId('plan-table-empty')).toBeVisible()
    } else {
      await expect(page.getByTestId('plan-table').locator('tr[data-row-key]')).toHaveCount(expected, { timeout: 30000 })
      await expect(page.getByTestId('plan-table-summary')).toContainText(`Activities in the plan: ${expected}`)
    }
    await page.screenshot({ path: 'test-results/yearly-plan-table.png' })
    await showPlaces(page)
    await expect(page.locator('[role="row"].table-row').first()).toBeVisible({ timeout: 30000 })
  })

  test('the plan table has the add-activity button and the export menu', async () => {
    await showPlan(page)
    await expect(page.getByTestId('plan-table-add')).toBeVisible()
    await expect(page.getByTestId('plan-export')).toBeVisible()
    await expect(page.getByTestId('plan-table-full-plan')).toBeVisible() // the way to the full page (P5)
    await showPlaces(page)
  })

  test('every year cell of every plan line agrees with the plan the server sends', async () => {
    const lines = await planLines(page)
    test.skip(lines.length === 0, 'the forest has no plan line')
    await showPlan(page)
    await expect(page.getByTestId('plan-table').locator('tr[data-row-key]')).toHaveCount(lines.length, { timeout: 30000 })
    for (const line of lines) {
      for (const y of line.years) {
        const cell = page.getByTestId(`year-${line.id}-${y.year}`)
        await expect(cell).toHaveAttribute('data-planned', String(y.planned))
        if (!y.planned) await expect(cell).toHaveText('—')
      }
    }
    await expect(page.getByTestId('plan-table-grid-hint')).toBeVisible()
    await showPlaces(page)
  })

  test("every row's Location cell says only what applies to that line", async () => {
    const lines = await planLines(page)
    test.skip(lines.length === 0, 'the forest has no plan line')
    await showPlan(page)
    await expect(page.getByTestId('plan-table').locator('tr[data-row-key]')).toHaveCount(lines.length, { timeout: 30000 })
    for (const line of lines) {
      const row = page.locator(`tr[data-row-key="${line.id}"]`)
      if (line.feature_count > 0) {
        await expect(page.getByTestId(`select-places-${line.id}`)).toHaveText(`Places: ${line.feature_count}`)
        const units = (line.location_units ?? []).join(', ')
        if (units) await expect(page.getByTestId(`location-units-${line.id}`)).toHaveText(`In ${units}`)
      } else if (line.location_mode === 'whole_forest') {
        await expect(page.getByTestId(`whole-forest-${line.id}`)).toBeVisible()
      } else if (line.location_mode === 'needs_location') {
        await expect(page.getByTestId(`show-on-map-${line.id}`)).toBeVisible()
      } else {
        // needs no map: nothing to say, nothing to press
        await expect(row.getByTestId(`select-places-${line.id}`)).toHaveCount(0)
        await expect(row.getByTestId(`show-on-map-${line.id}`)).toHaveCount(0)
        await expect(row.getByTestId(`whole-forest-${line.id}`)).toHaveCount(0)
      }
    }
    await showPlaces(page)
  })

  test("the places table shows each place's plan quantity, tagged shared when places share it", async () => {
    const all = await places(page)
    test.skip(all.length === 0, 'the forest has no drawn place')
    const cells = page.getByTestId('feature-quantity')
    await expect(cells).toHaveCount(all.length, { timeout: 30000 })
    const first = all[0]
    const shown = await cells.allTextContents()
    expect(shown.some((t) => t.includes(String(first.plan_quantity)) && (!first.plan_unit || t.includes(first.plan_unit)))).toBeTruthy()
    // a "shared ×N" tag exists exactly as often as a place has siblings
    await expect(page.getByTestId('feature-shared-tag')).toHaveCount(all.filter((p) => p.shared_count > 1).length)
  })

  test("the place count of a plan row selects that line's places on the map", async () => {
    const withPlaces = (await planLines(page)).find((l) => l.feature_count > 0)
    test.skip(!withPlaces, 'no plan line has a drawn place')
    await showPlan(page)
    await page.getByTestId(`select-places-${withPlaces!.id}`).click()
    await showPlaces(page)
    await expect(page.locator('.table-row.selected')).toHaveCount(withPlaces!.feature_count, { timeout: 30000 })
  })

  test('"Wider view" shows the same plan in a large panel, and the activity column is not pinned in the narrow dock', async () => {
    const lines = await planLines(page)
    test.skip(lines.length === 0, 'the forest has no plan line')
    await showPlan(page)
    // narrow dock: nothing is pinned, so nothing can cover the columns scrolled to
    await expect(page.locator('[data-testid="plan-table"] .ant-table-cell-fix-start')).toHaveCount(0)
    await page.getByTestId('plan-table-expand').click()
    const wide = page.locator('.ant-drawer').getByTestId('plan-table')
    await expect(wide).toBeVisible({ timeout: 30000 })
    await expect(wide.locator('tr[data-row-key]')).toHaveCount(lines.length, { timeout: 30000 })
    await expect(wide.getByTestId('plan-table-expand')).toHaveCount(0)
    // the wide copy is wide enough to show the whole grid without hiding a column behind a pinned one
    const box = await wide.boundingBox()
    expect(box!.width).toBeGreaterThan(900)
    await page.screenshot({ path: 'test-results/yearly-plan-wide.png' })
    await page.keyboard.press('Escape')
    await expect(page.locator('.ant-drawer-open')).toHaveCount(0, { timeout: 15000 })
    await showPlaces(page)
  })

  test('the header "Yearly plan" button opens the plan even when another layer is active', async () => {
    await page.getByTestId('layer-item').filter({ hasText: 'Compartments' }).first().click()
    await expect(page.getByTestId('table-view-switch')).toHaveCount(0) // the switch belongs to the Activity Features layer
    await openPanelButtons(page) // the button sits behind the header's Layers button
    await page.getByTestId('open-yearly-plan').click()
    await expect(page.getByTestId('plan-table')).toBeVisible({ timeout: 30000 })
    await expect(page.getByTestId('table-view-switch')).toBeVisible() // so the way back is there
    await showPlaces(page)
    // leave the page as the other tests expect it: the Activity Features layer active
    await page.getByTestId('layer-item').filter({ hasText: 'Activity Features' }).first().click({ button: 'right' })
    await page.getByText('Show attributes').click()
    await expect(page.getByTestId('table-view-switch')).toBeVisible({ timeout: 15000 })
  })

  test('the Next-step bar opens the plan in the workspace instead of a new browser tab', async () => {
    // the previous test left the Activity Features layer active, which is when the bar shows
    await page.getByTestId('next-step-bar').waitFor({ timeout: 15000 }).catch(() => undefined) // it appears once the health is read
    const action = page.getByTestId('next-step-bar-action')
    test.skip((await action.count()) === 0 || !(await action.textContent())?.includes('Open the yearly plan'), 'the next step is not an "open the plan" step')
    const tabs = page.context().pages().length
    await action.click()
    await expect(page.getByTestId('plan-table')).toBeVisible({ timeout: 30000 })
    expect(page.context().pages().length).toBe(tabs) // nothing opened beside this page
    await showPlaces(page)
  })

  test('the plan check warns before an export, lists what is unfinished, and never blocks', async () => {
    const lines = await planLines(page)
    const unfinished = lines.filter((l) => !l.reviewed_at && l.placeholder_fields.length > 0)
    test.skip(unfinished.length === 0, 'every plan line is finished')
    await showPlan(page)
    await page.getByTestId('plan-export').click()
    await page.getByText('Yearly plan (CSV)').click()
    const check = page.getByTestId('plan-check')
    await expect(check).toBeVisible({ timeout: 15000 })
    await expect(page.getByText(`Before we export the plan: ${unfinished.length} to check`)).toBeVisible()
    await expect(page.getByTestId('plan-check-row')).toHaveCount(unfinished.length)
    await expect(check).toContainText('still the starting values')

    // going back exports nothing
    let downloaded = false
    page.once('download', () => { downloaded = true })
    await page.getByTestId('plan-check-back').click()
    await expect(check).toBeHidden({ timeout: 15000 })
    expect(downloaded).toBe(false)

    // going on makes the file anyway
    await page.getByTestId('plan-export').click()
    const downloading = page.waitForEvent('download')
    await page.getByText('Yearly plan (CSV)').click()
    await page.getByTestId('plan-check-continue').click()
    expect((await downloading).suggestedFilename()).toMatch(/\.csv$/)
    await showPlaces(page)
  })

  test('what the drawn places measure is offered as the quantity — and only applied when pressed', async () => {
    test.setTimeout(120000)
    const headers = { Authorization: `Bearer ${await token(page)}`, 'Content-Type': 'application/json' }
    // a ~30 m fire line (unit: kilometres) drawn next to an existing place, so it lies inside the forest
    const existing = ((await places(page))[0] as unknown as { geometry: string })
    test.skip(!existing, 'the forest has no drawn place to draw next to')
    const [lon, lat] = (JSON.parse(existing.geometry) as { coordinates: [number, number] }).coordinates
    const created = await page.request.post(`${API}/activity-features`, {
      headers,
      data: {
        potential_activity_id: 12,
        feature_type: 'line',
        geometry: JSON.stringify({ type: 'LineString', coordinates: [[lon, lat], [lon + 0.0003, lat]] }),
        years: [1],
        quantity: 1,
        budget: 1000,
      },
    })
    expect(created.ok()).toBeTruthy()
    const made = (await created.json()) as { feature: { id: string }; plan_line: { id: string } }
    const id = made.plan_line.id
    try {
      await showPlan(page)
      await showPlaces(page)
      await showPlan(page) // the table re-reads the plan when it is shown again
      const hint = page.getByTestId(`measured-hint-${id}`)
      await expect(hint).toBeVisible({ timeout: 30000 })
      await expect(hint).toContainText('Drawn on the map')
      const measured = ((await planLines(page)).find((l) => l.id === id) as unknown as { measured_quantity: number }).measured_quantity
      expect(measured).toBeGreaterThan(0)
      expect(measured).toBeLessThan(0.1)
      // offered, not applied: the quantity is still what was entered
      expect(((await planLines(page)).find((l) => l.id === id) as unknown as { default_quantity: number }).default_quantity).toBe(1)

      await page.getByTestId(`use-measured-${id}`).click()
      await expect(hint).toHaveCount(0, { timeout: 30000 })
      const after = (await planLines(page)).find((l) => l.id === id) as unknown as { default_quantity: number }
      expect(after.default_quantity).toBeCloseTo(measured, 2)
    } finally {
      await page.request.delete(`${API}/activity-features/${made.feature.id}`, { headers, params: { remove_plan_line: 'true' } }).catch(() => undefined)
      await showPlaces(page).catch(() => undefined)
    }
  })

  test('the Review column agrees with the server for every line', async () => {
    const lines = await planLines(page)
    test.skip(lines.length === 0, 'the forest has no plan line')
    await showPlan(page)
    await expect(page.getByTestId('plan-table').locator('tr[data-row-key]')).toHaveCount(lines.length, { timeout: 30000 })
    for (const line of lines) {
      const tagged = !line.reviewed_at && line.placeholder_fields.length > 0
      await expect(page.getByTestId(`review-badge-${line.id}`)).toHaveCount(tagged ? 1 : 0)
      await expect(page.getByTestId(`review-confirmed-${line.id}`)).toHaveCount(line.reviewed_at ? 1 : 0)
    }
    await showPlaces(page)
  })

  test('a line at the starting numbers is tagged, and one press of "These numbers are right" confirms it', async () => {
    test.setTimeout(120000)
    await createThrowaway()

    try {
      // the table re-reads the plan when it is shown again
      await showPlan(page)
      await showPlaces(page)
      await showPlan(page)
      await expect(page.getByTestId(`review-badge-${throwaway}`)).toBeVisible({ timeout: 30000 })
      await page.getByTestId(`review-confirm-${throwaway}`).click()
      await expect(page.getByTestId(`review-confirmed-${throwaway}`)).toBeVisible({ timeout: 30000 })
      await expect(page.getByTestId(`review-badge-${throwaway}`)).toHaveCount(0)
      const after = (await planLines(page)).find((l) => l.id === throwaway)
      expect(after?.reviewed_at).toBeTruthy()
    } finally {
      await deleteThrowaway()
      await showPlaces(page).catch(() => undefined) // the throwaway is gone either way; do not hide the real failure
    }
  })

  test('editing in the table: the first value fills the rest, Undo puts it back, a quantity and a 0/0 year save at once', async () => {
    test.setTimeout(120000)
    const id = await createThrowaway()
    const line = async () => (await planLines(page)).find((l) => l.id === id) as ApiLine & { default_quantity: number; default_yearly_budget: number; years: ApiYear[] }
    try {
      await showPlan(page)
      await showPlaces(page)
      await showPlan(page)
      await expect(page.getByTestId(`year-edit-${id}-1`)).toBeVisible({ timeout: 30000 })

      // 1. the first value typed for ONE year is used for every year still at the starting value
      await page.getByTestId(`year-edit-${id}-1`).click()
      await page.getByTestId(`year-edit-${id}-1-budget`).fill('80000')
      await page.getByTestId(`year-edit-${id}-1-save`).click()
      await expect(page.getByTestId('plan-table-status')).toHaveAttribute('data-kind', 'filled', { timeout: 30000 })
      await expect(page.getByTestId('plan-table-status')).toContainText('Used for all years')
      let now = await line()
      expect(now.years.every((y) => y.budget === 80000)).toBe(true)
      expect(now.reviewed_at).toBeNull() // only the budget was typed: the quantity is still the starting value

      // 2. Undo puts the numbers back exactly
      await page.getByTestId('plan-table-undo').click()
      await expect(page.getByTestId('plan-table-status')).toHaveAttribute('data-kind', 'undone', { timeout: 30000 })
      now = await line()
      expect(now.years.every((y) => y.budget === 5000 && y.quantity === 1)).toBe(true)
      expect(now.default_yearly_budget).toBe(5000)
      expect(now.reviewed_at).toBeNull()

      // 3. the usual quantity, typed once, is used for the years still at 1
      await page.getByTestId(`default-quantity-${id}`).click()
      await page.getByTestId(`default-quantity-${id}-input`).fill('3')
      await page.getByTestId(`default-quantity-${id}-input`).press('Enter')
      await expect(page.getByTestId('plan-table-status')).toHaveAttribute('data-kind', 'filled', { timeout: 30000 })
      now = await line()
      expect(now.default_quantity).toBe(3)
      expect(now.years.every((y) => y.quantity === 3)).toBe(true)

      // 4. 0 and 0 in one year: it becomes a dimmed dash, and the other years are untouched
      await page.getByTestId(`year-edit-${id}-4`).click()
      await page.getByTestId(`year-edit-${id}-4-quantity`).fill('0')
      await page.getByTestId(`year-edit-${id}-4-budget`).fill('0')
      await page.getByTestId(`year-edit-${id}-4-save`).click()
      await expect(page.getByTestId(`year-${id}-4`)).toHaveAttribute('data-planned', 'false', { timeout: 30000 })
      await expect(page.getByTestId(`year-${id}-4`)).toHaveText('—')
      await expect(page.getByTestId(`year-${id}-5`)).toHaveAttribute('data-planned', 'true')
      now = await line()
      expect(now.years.find((y) => y.year === 4)).toMatchObject({ quantity: 0, budget: 0, planned: false })

      // 5. an invalid value is refused on the screen and nothing is sent
      await page.getByTestId(`default-quantity-${id}`).click()
      await page.getByTestId(`default-quantity-${id}-input`).fill('0')
      await page.getByTestId(`default-quantity-${id}-input`).press('Enter')
      await expect(page.getByTestId(`default-quantity-${id}-invalid`)).toBeVisible()
      expect((await line()).default_quantity).toBe(3)
    } finally {
      await deleteThrowaway()
      await showPlaces(page).catch(() => undefined)
    }
  })
})
