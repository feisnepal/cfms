import { test, expect, type Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import { openPanelButtons } from './helpers/dock'

// Any forest the demo user owns will do; the specs create no data. Set E2E_CALC_ID to one (a seeded forest with a boundary is best).
const WS_URL = `/workspace/${process.env.E2E_CALC_ID || '0c0bff72-ff00-419f-8826-4e456c67da13'}`
const PANELS = [
  { id: 'layers', label: 'Layers' },
  { id: 'basemap', label: 'Basemap' },
  { id: 'imported', label: 'Imported Layers' },
  { id: 'raster', label: 'Raster Layers' },
  { id: 'attributeTable', label: 'Attribute Table...' },
  { id: 'legend', label: 'Legend' },
]

const resetLayout = resetWorkspaceLayout // shared, self-checking: see helpers/resetLayout.ts

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('Workspace Dock Panels', () => {
  test.describe.configure({ mode: 'serial' })
  test.beforeEach(async ({ page }) => {
    test.setTimeout(120000)
    await login(page)
    await resetLayout(page)
  })

  // One panel per dock position (owner rule 2026-10-11): Layers (left) and the Attribute Table (right) are the home panels and are open by
  // default; Basemap, Imported Layers and Raster Layers share the left position, Legend shares the right one, and each opens on request
  // and replaces the panel that was there.
  const HOME = ['layers', 'attributeTable']
  const ON_REQUEST = PANELS.filter((p) => !HOME.includes(p.id))

  test('opens with Layers and the Attribute Table; the other four panels wait to be asked for', async ({ page }) => {
    page.on('pageerror', (err) => console.log(`PAGE EXCEPTION: ${err.message}`))
    await page.goto(WS_URL, { waitUntil: 'load', timeout: 60000 })
    for (const id of HOME) await expect(page.getByTestId(id)).toBeVisible({ timeout: 30000 })
    for (const p of ON_REQUEST) await expect(page.getByTestId(p.id)).not.toBeVisible()
  })

  test('shows only the Layers button until it is opened, then the other panel toggles', async ({ page }) => {
    await page.goto(WS_URL, { waitUntil: 'load', timeout: 60000 })
    await page.evaluate(() => localStorage.removeItem('cfms.workspace.headerPanelsOpen'))
    await page.reload({ waitUntil: 'load' })
    const toggles = page.locator('.workspace-panel-toggles .panel-toggle-btn')
    await expect(toggles).toHaveCount(1, { timeout: 30000 })
    await openPanelButtons(page)
    // an open panel offers "Hide", a closed one "Show"
    await expect(page.getByRole('button', { name: `Hide ${PANELS.find((x) => x.id === 'attributeTable')!.label} panel` })).toBeVisible()
    for (const p of ON_REQUEST) {
      await expect(page.getByRole('button', { name: `Show ${p.label} panel` })).toBeVisible()
    }
  })

  test('opening a panel replaces the one in its position, and closing it brings the home panel back', async ({ page }) => {
    await page.goto(WS_URL, { waitUntil: 'load', timeout: 60000 })
    const raster = page.getByTestId('raster')
    const layers = page.getByTestId('layers')
    await expect(layers).toBeVisible({ timeout: 30000 })
    await expect(raster).not.toBeVisible()

    await openPanelButtons(page)
    await page.getByRole('button', { name: 'Show Raster Layers panel' }).click()
    await expect(raster).toBeVisible({ timeout: 10000 })
    await expect(layers).not.toBeVisible({ timeout: 10000 })
    await expect(page.getByRole('button', { name: 'Hide Raster Layers panel' })).toBeVisible()

    await page.getByRole('button', { name: 'Hide Raster Layers panel' }).click()
    await expect(raster).not.toBeVisible({ timeout: 10000 })
    await expect(layers).toBeVisible({ timeout: 10000 })
  })

  test('a panel opened on request is still open after a reload', async ({ page }) => {
    await page.goto(WS_URL, { waitUntil: 'load', timeout: 60000 })
    const legend = page.getByTestId('legend')
    await expect(page.getByTestId('attributeTable')).toBeVisible({ timeout: 30000 })
    await expect(legend).not.toBeVisible()

    await openPanelButtons(page)
    await page.getByRole('button', { name: 'Show Legend panel' }).click()
    await expect(legend).toBeVisible({ timeout: 10000 })
    await expect(page.getByTestId('attributeTable')).not.toBeVisible({ timeout: 10000 }) // the legend took the right position

    // wait until the layout has reached the server (it is saved a moment after the click)
    await page.waitForFunction(async (panelId) => {
      const token = localStorage.getItem('access_token')
      const res = await fetch(
        `/api/v1/workspace/layout?layout_key=workspace&_=${Date.now()}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {} },
      )
      if (!res.ok) return false
      const d = await res.json()
      return d.layout_json?.collapsed?.[panelId] === false
    }, 'legend', { timeout: 15000 })

    await page.waitForTimeout(3000) // the dock saves the sizes of its positions a moment after the toggle: let both reach the server
    await page.reload({ waitUntil: 'load', timeout: 60000 })
    await page.waitForTimeout(2000) // the saved layout is applied to both positions a moment after the page loads
    await expect(page.getByTestId('legend')).toBeVisible({ timeout: 20000 })
    await expect(page.getByTestId('attributeTable')).not.toBeVisible({ timeout: 20000 })
    await openPanelButtons(page)
    await expect(page.getByRole('button', { name: 'Hide Legend panel' })).toBeVisible()

    await page.getByRole('button', { name: 'Hide Legend panel' }).click()
    await expect(page.getByTestId('legend')).not.toBeVisible({ timeout: 10000 })
    await expect(page.getByTestId('attributeTable')).toBeVisible({ timeout: 10000 })
    await resetLayout(page)
  })
})
