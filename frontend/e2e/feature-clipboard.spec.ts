/**
 * feature-clipboard.spec.ts — toolbar Copy / Paste / Paste-as-layer / multi-Delete
 * against the live stack.
 *
 * Opt-in: set E2E_CLIPBOARD_CALC_ID to a calculation you own that HAS a forest
 * boundary and NO sub-areas yet (the spec creates two, and removes everything it
 * made). Credentials come from E2E_EMAIL / E2E_PASSWORD (default: the demo user).
 *
 *   E2E_CLIPBOARD_CALC_ID=<uuid> npx playwright test e2e/feature-clipboard.spec.ts
 *
 * The sub-areas layer is the interesting target: the server clips a pasted
 * feature to the forest and subtracts every existing sub-area, so this proves
 * the "exact position, never overlapping" rule end to end, and that Ctrl+Z
 * undoes a multi-delete and a paste as single steps.
 */
import { test, expect, type Page } from '@playwright/test'

const CALC_ID = process.env.E2E_CLIPBOARD_CALC_ID
const EMAIL = process.env.E2E_EMAIL ?? 'demo@forest.com'
const PASSWORD = process.env.E2E_PASSWORD ?? 'Demo1234'

// Do not inherit the shared demo storageState — log in as the chosen user.
test.use({ storageState: { cookies: [], origins: [] } })

interface SubArea { id: string; name: string; category: string }

async function login(page: Page) {
  // The app defaults to Nepali; the assertions below read the English labels.
  await page.addInitScript(() => localStorage.setItem('i18nextLng', 'en'))
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', EMAIL)
  await page.fill('input[name="password"]', PASSWORD)
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

async function token(page: Page): Promise<string> {
  return (await page.evaluate(() => localStorage.getItem('access_token'))) ?? ''
}

async function listSubAreas(page: Page): Promise<SubArea[]> {
  const res = await page.request.get(`/api/forests/calculations/${CALC_ID}/sub-areas`, {
    headers: { Authorization: `Bearer ${await token(page)}` },
  })
  expect(res.ok()).toBeTruthy()
  const body = await res.json()
  return (Array.isArray(body) ? body : body.sub_areas ?? []) as SubArea[]
}

async function createSubArea(page: Page, name: string, category: string, x0: number, x1: number) {
  const res = await page.request.post(`/api/forests/calculations/${CALC_ID}/sub-areas`, {
    headers: { Authorization: `Bearer ${await token(page)}` },
    data: {
      name, category, is_excluded: false,
      geometry: {
        type: 'Polygon',
        coordinates: [[[x0, 27.0003], [x1, 27.0003], [x1, 27.0017], [x0, 27.0017], [x0, 27.0003]]],
      },
    },
  })
  expect(res.ok(), await res.text()).toBeTruthy()
}

async function removeAllSubAreas(page: Page) {
  for (const sa of await listSubAreas(page)) {
    await page.request.delete(`/api/forests/calculations/${CALC_ID}/sub-areas/${sa.id}`, {
      headers: { Authorization: `Bearer ${await token(page)}` },
    })
  }
}

interface ImportLayer { id: number; name: string; purpose: string; feature_count: number; is_draft: boolean }

async function listLayers(page: Page): Promise<ImportLayer[]> {
  const res = await page.request.get(`/api/v1/workspace/${CALC_ID}/import-layers`, {
    headers: { Authorization: `Bearer ${await token(page)}` },
  })
  expect(res.ok()).toBeTruthy()
  return (await res.json()) as ImportLayer[]
}

const toast = (page: Page, text: RegExp) => page.locator('.ant-message-notice', { hasText: text }).first()
const btn = (page: Page, name: string) => page.getByRole('button', { name, exact: true })

async function openSubAreasLayer(page: Page) {
  await page.goto(`/calculations/${CALC_ID}?tab=forest-data&context=unified`, { waitUntil: 'load', timeout: 60000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 30000 })
  // A designer / super admin opening a forest with no plan is offered "Start an
  // Operational Plan" over the map — unrelated to this spec, so dismiss it.
  const planPrompt = page.locator('.ant-modal-wrap', { hasText: 'Start an Operational Plan' })
  await planPrompt.waitFor({ state: 'visible', timeout: 6000 }).then(async () => {
    await page.keyboard.press('Escape')
    await expect(planPrompt).toBeHidden()
  }).catch(() => undefined)
  await page.getByTestId('layer-item').filter({ hasText: /Sub-?Areas/i }).first().click()
  await expect(page.getByTestId('attribute-table')).toBeVisible({ timeout: 15000 })
}

async function selectBothRows(page: Page) {
  const rows = page.getByTestId('attribute-table').getByRole('row').filter({ hasText: /Ridge|Nursery/ })
  await expect(rows).toHaveCount(2, { timeout: 15000 })
  await rows.nth(0).click()
  await rows.nth(1).click({ modifiers: ['Control'] })
}

test.describe('Toolbar feature clipboard (live)', () => {
  test.skip(!CALC_ID, 'set E2E_CLIPBOARD_CALC_ID to run against a live forest')
  test.describe.configure({ mode: 'serial' })
  test.setTimeout(240000)

  test('copy → multi-delete (one confirm) → paste exactly → refuse overlap → undo both', async ({ page }) => {
    await login(page)
    await removeAllSubAreas(page)
    await createSubArea(page, 'Ridge', 'protected', 84.0004, 84.0018)
    await createSubArea(page, 'Nursery', 'plantation', 84.0022, 84.0036)
    expect(await listSubAreas(page)).toHaveLength(2)

    try {
      await openSubAreasLayer(page)

      // The old, unwired Duplicate button is gone; the four new ones are there.
      await expect(btn(page, 'Duplicate')).toHaveCount(0)
      await expect(btn(page, 'Copy')).toBeVisible()
      await expect(btn(page, 'Paste')).toBeVisible()
      await expect(btn(page, 'Paste as layer')).toBeVisible()
      await expect(btn(page, 'Delete')).toBeVisible()

      // Nothing on the clipboard yet: Paste says why, Paste-as-layer too.
      await expect(btn(page, 'Paste')).toBeDisabled()
      await expect(btn(page, 'Paste as layer')).toBeDisabled()

      // ── Copy the two selected sub-areas ───────────────────────────────────
      await selectBothRows(page)
      await btn(page, 'Copy').click()
      await expect(toast(page, /Copied 2 feature/)).toBeVisible()
      await expect(btn(page, 'Paste')).toBeEnabled()

      // ── Delete both behind ONE confirm ────────────────────────────────────
      await btn(page, 'Delete').click()
      const confirm = page.locator('.ant-modal-confirm')
      await expect(confirm).toBeVisible()
      await expect(confirm).toContainText(/Delete 2 feature/)
      await confirm.getByRole('button', { name: /Delete/ }).click()
      await expect(toast(page, /Deleted 2 feature/)).toBeVisible()
      await expect.poll(async () => (await listSubAreas(page)).length).toBe(0)

      // ── Paste: back at the exact same place, names + categories intact ────
      await btn(page, 'Paste').click()
      await expect(toast(page, /Pasted 2 feature/)).toBeVisible()
      await expect.poll(async () => (await listSubAreas(page)).length).toBe(2)
      const pasted = await listSubAreas(page)
      expect(pasted.map((s) => s.name).sort()).toEqual(['Nursery', 'Ridge'])
      expect(pasted.find((s) => s.name === 'Ridge')?.category).toBe('protected')

      // ── Paste again: everything overlaps what is already there → refused ──
      await btn(page, 'Paste').click()
      await expect(toast(page, /Nothing was pasted|refused/)).toBeVisible({ timeout: 20000 })
      expect(await listSubAreas(page)).toHaveLength(2) // still exactly two: no overlap created

      // ── Ctrl+Z ×2: the (only successful) paste, then the multi-delete ─────
      await page.locator('body').click({ position: { x: 5, y: 5 } })
      await page.keyboard.press('Control+z')
      await expect.poll(async () => (await listSubAreas(page)).length, { timeout: 20000 }).toBe(0)
      await page.keyboard.press('Control+z')
      await expect.poll(async () => (await listSubAreas(page)).length, { timeout: 20000 }).toBe(2)
      expect((await listSubAreas(page)).map((s) => s.name).sort()).toEqual(['Nursery', 'Ridge'])
    } finally {
      await removeAllSubAreas(page)
    }
  })

  test('paste as a new layer works even where a plain paste does not', async ({ page }) => {
    await login(page)
    await removeAllSubAreas(page)
    await createSubArea(page, 'Ridge', 'protected', 84.0004, 84.0018)
    await createSubArea(page, 'Nursery', 'plantation', 84.0022, 84.0036)
    const layersBefore = new Set((await listLayers(page)).map((l) => l.id))

    try {
      await openSubAreasLayer(page)
      await selectBothRows(page)
      await btn(page, 'Copy').click()
      await expect(toast(page, /Copied 2 feature/)).toBeVisible()

      // Pasting into the Blocks layer is refused (blocks must tile the boundary)…
      await page.getByTestId('layer-item').filter({ hasText: /Blocks/ }).first().click()
      await expect(btn(page, 'Paste')).toBeDisabled()
      await expect(btn(page, 'Paste').first()).toHaveAttribute('title', /can't receive pasted features/)
      // …but Paste-as-layer is still available and turns the clipboard into a new layer.
      await expect(btn(page, 'Paste as layer')).toBeEnabled()
      await btn(page, 'Paste as layer').click()
      await expect(toast(page, /Created layer|created as a draft/)).toBeVisible({ timeout: 40000 })

      // The layer exists on the server with both features, and shows in the panel.
      await expect.poll(async () => (await listLayers(page)).filter((l) => !layersBefore.has(l.id)).length,
        { timeout: 20000 }).toBe(1)
      const created = (await listLayers(page)).find((l) => !layersBefore.has(l.id))!
      expect(created.purpose).toBe('other')
      expect(created.feature_count).toBe(2)
      expect(created.name).toMatch(/Sub-Areas \(copy\)/)
      await expect(page.getByText(/Sub-Areas \(copy\)/).first()).toBeVisible({ timeout: 15000 })

      // The new layer is now the active one and can itself take a paste: the two
      // copied polygons are appended (each as its own feature), then undone.
      await expect(btn(page, 'Paste')).toBeEnabled()
      await btn(page, 'Paste').click()
      await expect(toast(page, /Pasted 2 feature/)).toBeVisible({ timeout: 20000 })
      const featureCount = async () => (await listLayers(page)).find((l) => l.id === created.id)?.feature_count
      await expect.poll(featureCount, { timeout: 20000 }).toBe(4)

      await page.locator('body').click({ position: { x: 5, y: 5 } })
      await page.keyboard.press('Control+z')
      await expect.poll(featureCount, { timeout: 20000 }).toBe(2)
    } finally {
      for (const l of await listLayers(page)) {
        if (layersBefore.has(l.id)) continue
        await page.request.delete(`/api/v1/workspace/${CALC_ID}/import-layers/${l.id}`, {
          headers: { Authorization: `Bearer ${await token(page)}` },
        })
      }
      await removeAllSubAreas(page)
    }
  })
})
