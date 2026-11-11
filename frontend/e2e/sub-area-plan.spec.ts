/**
 * sub-area-plan.spec.ts - live check of "sub-areas must be tied to the yearly plan" (owner rule 2026-10-08).
 *
 * Needs a forest owned by demo@forest.com with at least one leaf unit and NO sub-areas / plan lines:
 *   E2E_SUBAREA_PLAN_CALC_ID=<id> npx playwright test e2e/sub-area-plan.spec.ts
 * Skipped without the variable. It leaves the forest as it found it (sub-areas and plan lines are removed in afterAll).
 */
import { test, expect, request, Page } from '@playwright/test'

const CALC = process.env.E2E_SUBAREA_PLAN_CALC_ID
const API = 'http://localhost:8001'

async function token(): Promise<string> {
  const ctx = await request.newContext()
  const r = await ctx.post(`${API}/api/auth/login`, { data: { email: 'demo@forest.com', password: 'Demo1234' } })
  return (await r.json()).access_token
}

async function cleanup() {
  const ctx = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${await token()}` } })
  await ctx.delete(`${API}/api/forests/calculations/${CALC}/sub-areas?plan_lines=delete`)
}

test.describe('sub-areas are tied to the yearly plan', () => {
  test.skip(!CALC, 'set E2E_SUBAREA_PLAN_CALC_ID')
  test.describe.configure({ mode: 'serial' })
  let page: Page

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(240000)
    await cleanup()
    page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
    await page.goto('/login', { waitUntil: 'networkidle' })
    await page.fill('input[name="email"]', 'demo@forest.com')
    await page.fill('input[name="password"]', 'Demo1234')
    await page.click('button[type="submit"]')
    await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
    await page.waitForLoadState('networkidle')
    for (let i = 0; i < 3; i += 1) {
      await page.goto(`/calculations/${CALC}`, { waitUntil: 'load' })
      await page.waitForTimeout(2500) // a login redirect can still land after the goto
      if (await page.getByTestId('workspace-container').isVisible()) break
    }
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
    await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 30000 })
  })

  test.afterAll(async () => {
    await cleanup()
    await page?.close()
  })

  async function api() {
    return request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${await token()}` } })
  }

  async function drawInBlockOne() {
    const pts = [[27.4975, 83.4840], [27.4975, 83.4885], [27.5005, 83.4885], [27.5005, 83.4840]]
    const xy = await page.evaluate((latlngs) => {
      const map = (window as any).__mapInstance
      const rect = map.getContainer().getBoundingClientRect()
      return latlngs.map(([lat, lng]: number[]) => {
        const p = map.latLngToContainerPoint([lat, lng])
        return [rect.left + p.x, rect.top + p.y]
      })
    }, pts)
    for (const [x, y] of xy) {
      await page.mouse.click(x, y)
      await page.waitForTimeout(250)
    }
    await page.keyboard.press('Enter')
  }

  test('drawing a sub-area asks "What will you do here?"; "Decide later" leaves it needing a plan', async () => {
    await page.getByText('Sub-Areas').first().click({ button: 'right' })
    await page.getByText('Add sub-area').click()
    await page.getByRole('button', { name: /Plantation/i }).first().click()
    await drawInBlockOne()
    await expect(page.getByText('What will you do here?')).toBeVisible({ timeout: 20000 })
    await expect(page.getByText(/Suggested for this kind/)).toBeVisible()
    await page.screenshot({ path: 'e2e-results-subarea-4.png' })
    await page.getByTestId('sub-area-plan-later').click()
    await expect(page.getByText('What will you do here?')).toBeHidden()
    const status = await (await (await api()).get(`${API}/api/yearly-activities/calculations/${CALC}/sub-areas/plan-status`)).json()
    expect(status.needs_plan).toBe(1)
    expect(status.sub_areas[0].state).toBe('needs_plan')
  })

  test('the plan toolbar shows the badge; the list plans it with the suggested activity', async () => {
    await page.getByText('Yearly plan', { exact: true }).first().click()
    const badge = page.getByTestId('sub-area-plan-badge')
    await expect(badge).toBeVisible({ timeout: 20000 })
    await page.screenshot({ path: 'e2e-results-subarea-5.png' })
    await badge.click()
    await expect(page.getByText('Sub-areas that need a plan')).toBeVisible()
    await page.getByRole('button', { name: /Add to the plan/ }).first().click()
    await expect(page.getByText('Every sub-area is tied to the yearly plan.')).toBeVisible({ timeout: 20000 })
    await page.screenshot({ path: 'e2e-results-subarea-6.png' })
    await page.getByTestId('sub-area-plan-later').click()
    await expect(badge).toBeHidden({ timeout: 20000 })
  })

  test('the server agrees: health is clean and a planned sub-area is not deleted silently', async () => {
    const ctx = await api()
    const status = await (await ctx.get(`${API}/api/yearly-activities/calculations/${CALC}/sub-areas/plan-status`)).json()
    expect(status.needs_plan).toBe(0)
    const health = await (await ctx.get(`${API}/api/yearly-activities/calculations/${CALC}/yearly-plan/health`)).json()
    expect(health.plan_issues.map((i: { code: string }) => i.code)).not.toContain('SUB_AREA_NO_PLAN')
    const id = status.sub_areas[0].id
    const refused = await ctx.delete(`${API}/api/forests/calculations/${CALC}/sub-areas/${id}`)
    expect(refused.status()).toBe(409)
    expect((await refused.json()).detail.lines.length).toBeGreaterThan(0)
  })
})
