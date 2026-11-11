/**
 * auto-divide.spec.ts — E2E for "Divide by natural feature…": once a forest has blocks / compartments the
 * whole-forest Auto-create is switched off, so the same four sources (rivers & ridges, slope, aspect, canopy)
 * are offered for ONE selected block / compartment instead, saved as its children.
 *
 * READ-ONLY: it opens the designer on a selected compartment and looks at the preview — it never presses Create,
 * so the forest is left exactly as it was.
 *
 * SKIPPED by default: needs a running stack and E2E_AUTODIVIDE_CALC_ID = a calculation the demo user owns that has
 * at least two compartments and no sub-compartments.
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_AUTODIVIDE_CALC_ID || process.env.E2E_YEARLY_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const URL = `/calculations/${CALC_ID}?tab=forest-data&context=unified`

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

const token = (page: Page) => page.evaluate(() => localStorage.getItem('access_token') || '')

async function compartments(page: Page): Promise<Array<{ id: string; name: string }>> {
  const res = await page.request.get(`/api/compartments/calculations/${CALC_ID}/compartment-tree`, {
    headers: { Authorization: `Bearer ${await token(page)}` },
  })
  expect(res.ok()).toBeTruthy()
  return ((await res.json()) as { blocks: Array<{ id: string; name: string }> }).blocks
}

async function openMenuOn(page: Page, layerLabel: string) {
  const row = page.getByTestId('layer-item').filter({ hasText: layerLabel }).first()
  await expect(row).toBeVisible({ timeout: 60000 })
  await row.click({ button: 'right' })
}

// Divide, polygon-from-points, style, copy/paste and export sit in the layer menu's Advanced fly-out (a tap opens it)
async function openAdvanced(page: Page) {
  await page.getByRole('menuitem', { name: /^Advanced/i }).click()
}

test.describe('divide a selected feature by a natural feature', () => {
  test.skip(!RUN, 'set E2E_AUTODIVIDE_CALC_ID (or E2E_YEARLY_CALC_ID) to run against a live stack')
  test.describe.configure({ mode: 'serial' })

  let page: Page
  let comps: Array<{ id: string; name: string }> = []

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage()
    await login(page)
    comps = await compartments(page)
    await page.goto(URL, { waitUntil: 'load', timeout: 60000 })
    await expect(page.getByTestId('layer-item').first()).toBeVisible({ timeout: 60000 })
  })

  test.afterAll(async () => {
    await page.close()
  })

  test('the item is on the Sub-compartments menu, and with no compartment chosen it asks for one', async () => {
    test.skip(comps.length < 2, 'needs at least two compartments')
    await openMenuOn(page, 'Sub-compartments')
    await openAdvanced(page)
    const item = page.getByText(/^Divide .* by natural feature…$/)
    await expect(item).toBeVisible()
    await item.click()
    await expect(page.getByText(/exactly one/i).first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByTestId('auto-block-designer')).toHaveCount(0)
  })

  test('with one compartment selected, the designer opens on that compartment and previews its pieces', async () => {
    test.skip(comps.length < 1, 'needs a compartment')
    const target = comps[0]
    await page.evaluate((id) => {
      const w = window as unknown as { __workspaceStore: { selectFeatures: (layer: string, ids: string[]) => void } }
      w.__workspaceStore.selectFeatures('compartments', [id])
    }, target.id)

    await openMenuOn(page, 'Sub-compartments')
    await openAdvanced(page)
    await page.getByText(/^Divide .* by natural feature…$/).click()

    const designer = page.getByTestId('auto-block-designer')
    await expect(designer).toBeVisible({ timeout: 15000 })
    await expect(designer).toContainText(`Divide ${target.name} by natural feature`)
    // the level choice is fixed by the parent
    await expect(designer.getByLabel('Compartments', { exact: true })).toHaveCount(0)

    // rivers & ridges is the source that always has something to say about a compartment
    await designer.locator('label.auto-block-segment', { hasText: /natural features/i }).click()
    await expect(page.getByTestId('auto-block-row').first()).toBeVisible({ timeout: 60000 })
    // pieces are named as the children they will become
    await expect(page.getByTestId('auto-block-row').first()).toContainText(/SC/)

    // nothing was written: the forest still has the same compartments and no sub-compartments
    const after = await compartments(page)
    expect(after.map((c) => c.id).sort()).toEqual(comps.map((c) => c.id).sort())
  })
})
