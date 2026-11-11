/**
 * yearly-plan-numbers.spec.ts — live E2E for P6 of YEARLY_ACTIVITIES_WORKSPACE_PLAN.md ("numbers agree in the OP
 * export"): a real edit in the browser, and then the plan API, the table, the CSV export and the operational
 * plan's own variables (`ya_*`, what the plan document is built from) must all say the same thing.
 *
 * SKIPPED by default: needs a running stack and E2E_YEARLY_CALC_ID (a forest the demo user owns, with an
 * operational plan, whose plan does not contain activity 130 "scholarship"). The line it creates is removed again,
 * through its own login.
 */
import { test, expect, request, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const API = '/api/yearly-activities'
const NO_MAP = 130
const URL = `/calculations/${CALC_ID}/yearly-activities`

interface Line { id: string; potential_activity_id: number; total_budget: number; years: Array<{ year: number; budget: number; quantity: number }> }

async function withApi<T>(run: (get: (path: string) => Promise<any>, send: (method: 'post' | 'delete', path: string, data?: unknown) => Promise<any>, text: (path: string) => Promise<string>) => Promise<T>): Promise<T> {
  const api = await request.newContext({ baseURL: 'http://localhost:3001' })
  try {
    const login = await api.post('/api/auth/login', { data: { email: 'demo@forest.com', password: 'Demo1234' } })
    const headers = { Authorization: `Bearer ${((await login.json()) as { access_token: string }).access_token}`, 'Content-Type': 'application/json' }
    return await run(
      async (path) => (await api.get(path, { headers })).json(),
      async (method, path, data) => api[method](path, { headers, data }),
      async (path) => (await api.get(path, { headers })).text(),
    )
  } finally {
    await api.dispose()
  }
}

const lines = (): Promise<Line[]> => withApi(async (get) => (await get(`${API}/calculations/${CALC_ID}/yearly-plan`)).lines)

async function removeLine() {
  await withApi(async (get, send) => {
    for (const l of ((await get(`${API}/calculations/${CALC_ID}/yearly-plan`)).lines as Line[]).filter((x) => x.potential_activity_id === NO_MAP)) {
      await send('delete', `${API}/proposed-activities/${l.id}`)
    }
  })
}

/** A minimal CSV reader (quoted cells, doubled quotes, commas and newlines inside quotes). */
function parseCsv(text: string): string[][] {
  const rows: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  const body = text.replace(/^﻿/, '')
  for (let i = 0; i < body.length; i++) {
    const c = body[i]
    if (quoted) {
      if (c === '"' && body[i + 1] === '"') { cell += '"'; i++ } else if (c === '"') quoted = false
      else cell += c
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(cell); cell = '' }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && body[i + 1] === '\n') i++
      row.push(cell); cell = ''
      if (row.length > 1 || row[0] !== '') rows.push(row)
      row = []
    } else cell += c
  }
  if (cell !== '' || row.length) { row.push(cell); rows.push(row) }
  return rows
}

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('yearly plan — the numbers agree everywhere', () => {
  test.skip(!RUN, 'set E2E_YEARLY_CALC_ID to run against a live stack')

  test.beforeEach(async () => { await removeLine() })
  test.afterEach(async () => { await removeLine() })

  test('an edit made in the browser reaches the plan API, the table, the CSV export and the operational plan alike', async ({ page }) => {
    test.setTimeout(150000)
    // an activity at the starting numbers, then a REAL edit through the page: NPR 80,000 for Year 1, used for every year
    await withApi(async (_get, send) => {
      const res = await send('post', `${API}/calculations/${CALC_ID}/proposed-activities`, { potential_activity_id: NO_MAP, default_quantity: 1, default_yearly_budget: 5000 })
      expect(res.ok()).toBeTruthy()
    })
    const id = (await lines()).find((l) => l.potential_activity_id === NO_MAP)!.id
    await login(page)
    await page.goto(URL, { waitUntil: 'domcontentloaded' })
    await expect(page.getByTestId(`year-edit-${id}-1`)).toBeVisible({ timeout: 60000 })
    await page.getByTestId(`year-edit-${id}-1`).click()
    await page.getByTestId(`year-edit-${id}-1-budget`).fill('80000')
    await page.getByTestId(`year-edit-${id}-1-save`).click()
    await expect(page.getByTestId('plan-table-status')).toHaveAttribute('data-kind', 'filled', { timeout: 30000 })

    // 1. the plan API
    const all = await lines()
    const total = all.reduce((sum, l) => sum + l.total_budget, 0)
    const mine = all.find((l) => l.id === id)!
    expect(mine.total_budget).toBe(800000)

    // 2. the table's own total and the page's statistic
    await expect(page.getByTestId('plan-table-summary')).toContainText(`Total NPR ${total.toLocaleString('en')}`, { timeout: 30000 })
    await expect(page.getByTestId('stat-budget')).toContainText(total.toLocaleString('en'), { timeout: 30000 })

    // 3. the CSV export: the sum of its "Total budget" column
    const csv = await withApi(async (_get, _send, text) => text(`${API}/calculations/${CALC_ID}/yearly-plan/export?format=csv&lang=en`))
    const table = parseCsv(csv)
    const column = table[0].findIndex((h) => h.startsWith('Total budget'))
    expect(column).toBeGreaterThan(-1)
    const exported = table.slice(1).reduce((sum, r) => sum + Number(r[column] || 0), 0)
    expect(exported).toBe(total)

    // 4. the operational plan's variables — what the plan document is built from
    const op = await withApi(async (get) => get(`/api/operational-plans/${CALC_ID}/variable-catalog?keys=ya_total_ten_year_budget,ya_total_budget_by_year`))
    const byKey = Object.fromEntries((op.variables as Array<{ key: string; resolved: unknown }>).map((v) => [v.key, v.resolved]))
    expect(Number(byKey['ya_total_ten_year_budget'])).toBe(total)
    const perYear = Object.values(byKey['ya_total_budget_by_year'] as Record<string, number>).reduce((sum, v) => sum + Number(v), 0)
    expect(perYear).toBe(total)
  })
})
