import { test, expect, type Page } from '@playwright/test'

const EDIT_CALC_ID = process.env.E2E_EDIT_CALC_ID || ''
const CALCULATION_ID = EDIT_CALC_ID
const API = `/api/v1/calculations/${CALCULATION_ID}`

async function login(page: Page): Promise<void> {
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

async function openUnified(page: Page): Promise<void> {
  await page.goto(`/calculations/${CALCULATION_ID}/unified`, { waitUntil: 'load', timeout: 60000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 20000 })
  await page.waitForTimeout(3000)
}

async function activateLayer(page: Page, label: RegExp): Promise<void> {
  const item = page
    .getByTestId('layer-item')
    .filter({ hasText: label })
    .first()
  await expect(item).toBeVisible({ timeout: 20000 })
  await item.locator('.layer-name-btn').click({ force: true })
  await page.waitForTimeout(1200)
}

test.describe('Unified Editing — UE-4.3', () => {
  test.skip(!EDIT_CALC_ID, 'SKIPPED by default: needs a demo-owned forest with a boundary and at least two blocks; set E2E_EDIT_CALC_ID to its id.')
  test.describe.configure({ mode: 'serial' })
  test.setTimeout(240000)

  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('toolbar gating is geometry-driven across layers', async ({ page }) => {
    await openUnified(page)

    const toolbar = page.locator('.geometry-toolbar')

// Blocks → Polygon ⇒ Split + Merge + Vertices + Move all allowed
    await activateLayer(page, /Blocks/)
    await expect(toolbar.locator('button:has-text("Split")')).toBeVisible({ timeout: 10000 })
    await expect(toolbar.locator('button:has-text("Merge")')).toBeVisible()
    await expect(toolbar.locator('button:has-text("Vertices")')).toBeVisible()
    await expect(toolbar.locator('button:has-text("Move")')).toBeVisible()

    // Boundary → Polygon ⇒ the same polygon toolset is offered
    await activateLayer(page, /Forest Boundary/)
    await expect(toolbar.locator('button:has-text("Split")')).toBeVisible({ timeout: 10000 })

    // Undo/Redo are present and initially disabled
    await expect(toolbar.locator('button[aria-label="Undo"]')).toBeDisabled()
    await expect(toolbar.locator('button[aria-label="Redo"]')).toBeDisabled()
  })

  test('split a block → Ctrl+Z restores the exact row (self-healing)', async ({ page }) => {
    await openUnified(page)
    await activateLayer(page, /Blocks/)

    // Select a real top-level block row by name (row 1 is always in view).
    const row = page.locator('.table-row', { hasText: 'दुनेटार' }).first()
    await expect(row).toBeVisible({ timeout: 20000 })
    await row.click()
    await page.waitForTimeout(1200)
    await expect(row).toHaveAttribute('aria-selected', 'true', { timeout: 10000 })

    // Arm Split
    const toolbar = page.locator('.geometry-toolbar')
    await toolbar.locator('button:has-text("Split")').click({ force: true })
    await page.waitForTimeout(1200)

    // Draw a 3-point cut through the SELECTED block's own projected bbox so the
    // cut is guaranteed to cross दुनेटार. Use the __testOnly dev hook to
    // center the map on the feature, then click through its path bbox.
    const zoomed = await page.evaluate(() => {
      const t = (window as unknown as { __testOnly?: { zoomToFeature: (fid: string) => { ok: boolean; error?: string } } }).__testOnly;
      return t?.zoomToFeature('57b12842-13dc-44f3-aa2f-577daba1cc09') ?? { ok: false, error: 'no __testOnly' };
    })
    expect(zoomed.ok).toBe(true)
    await page.waitForTimeout(1500)

    const box = await page.evaluate(() => {
      const t = (window as unknown as { __testOnly?: { getPathCenter: (fid: string) => { x: number; y: number; w: number; h: number } | null } }).__testOnly;
      return t?.getPathCenter('57b12842-13dc-44f3-aa2f-577daba1cc09') ?? null;
    })
    expect(box).not.toBeNull()
    const pts = [
      [box.x - box.w * 0.3, box.y],
      [box.x, box.y - box.h * 0.2],
      [box.x + box.w * 0.3, box.y],
    ]
    for (const [x, y] of pts) {
      await page.mouse.click(x, y)
      await page.waitForTimeout(600)
    }

    // Preview chips appear
    await expect(page.locator('.split-chip').first()).toBeVisible({ timeout: 10000 })
    const chips = await page.evaluate(() =>
      Array.from(document.querySelectorAll('.split-chip')).map((el) => el.textContent.trim()))
    expect(chips.length).toBeGreaterThanOrEqual(2)

    // Finish & Split → backend commits
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/geometry/cut-polygon') && r.request().method() === 'POST', { timeout: 30000 }),
      page.locator('button[aria-label="Finish split"]').click({ force: true }),
    ])
    expect(resp.status()).toBe(200)
    await page.waitForTimeout(1200)

    // The source row now has split pieces (row names gain a -N suffix).
    await expect(
      page.locator('.table-row', { hasText: /दुनेटार-\d+/ }).first(),
    ).toBeVisible({ timeout: 15000 })

    // UNDO → the source row returns exactly; pieces disappear
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(2500)
    await expect(page.locator('.table-row', { hasText: 'दुनेटार' }).first()).toBeVisible()
    await expect(page.locator('.table-row', { hasText: /दुनेटार-\d+/ })).toHaveCount(0)
  })

  test('merge two blocks → Ctrl+Z restores both sources (self-healing)', async ({ page }) => {
    await openUnified(page)
    await activateLayer(page, /Blocks/)

    const rowA = page.locator('.table-row', { hasText: 'दुनेटार' }).first()
    const rowB = page.locator('.table-row', { hasText: 'टिकाराम-2' }).first()
    await expect(rowA).toBeVisible({ timeout: 20000 })
    await expect(rowB).toBeVisible({ timeout: 20000 })

    await rowA.click()
    await page.keyboard.down('Control')
    await rowB.click()
    await page.keyboard.up('Control')
    await page.waitForTimeout(1200)
    await expect(rowB).toHaveAttribute('aria-selected', 'true', { timeout: 5000 })

    const toolbar = page.locator('.geometry-toolbar')
    await expect(toolbar.locator('button:has-text("Merge")')).toBeEnabled({ timeout: 10000 })

    // Merge posts then the confirm appears
    const [resp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes('/geometry/merge-features') && r.request().method() === 'POST', { timeout: 30000 }),
      (async () => {
        await toolbar.locator('button:has-text("Merge")').click({ force: true })
        await page.waitForTimeout(800)
        await page.locator('button:has-text("Merge")').last().click({ force: true }).catch(() => {})
      })(),
    ])
    expect(resp.status()).toBe(200)
    await page.waitForTimeout(1500)

    // A merged row is produced (its name contains the sources).
    await expect(
      page.locator('.table-row', { hasText: /दुनेटार/ }).first(),
    ).toBeVisible()
    await expect(
      page.locator('.table-row', { hasText: /\d+ दुनेटार/ }).first(),
    ).toBeVisible({ timeout: 15000 })

    // UNDO → both sources return
    await page.keyboard.press('Control+z')
    await page.waitForTimeout(2500)
    await expect(page.locator('.table-row', { hasText: 'दुनेटार' }).first()).toBeVisible({ timeout: 10000 })
    await expect(page.locator('.table-row', { hasText: 'टिकाराम-2' }).first()).toBeVisible({ timeout: 10000 })
  })

  test('boundary edit-geometry is guarded from the unified route', async ({ page }) => {
    await openUnified(page)
    const resp = await page.request.post(`${API}/geometry/edit-geometry`, {
      headers: { 'Content-Type': 'application/json' },
      data: { layer_type: 'boundary', feature_id: 'boundary', geometry: { type: 'Polygon', coordinates: [[[3, 3], [8, 3], [8, 8], [3, 8], [3, 3]]] } },
    })
    expect(resp.status()).toBe(400)
    const body = await resp.json()
    expect(JSON.stringify(body)).toContain('boundary toolbar')
  })

  test('imported-layer split tool is offered and armed', async ({ page }) => {
    await openUnified(page)
    await activateLayer(page, /ImpSelTest/)

    const toolbar = page.locator('.geometry-toolbar')
    await expect(toolbar.locator('button:has-text("Split")')).toBeVisible({ timeout: 15000 })

    // Select the imported feature row then arm Split
    const row = page.locator('.table-row').first()
    await expect(row).toBeVisible({ timeout: 10000 })
    await row.click()
    await page.waitForTimeout(1000)
    await toolbar.locator('button:has-text("Split")').click({ force: true })
    await page.waitForTimeout(1000)
    await expect(page.locator('button[aria-label="Finish split"]')).toBeVisible({ timeout: 10000 })
  })
})
