import { test, expect } from '@playwright/test'

// The workspace header's lifecycle badge/actions are driven by
// `useCalculationContext`, which polls the REAL source
// `GET /api/forests/calculations/{id}` (with the `map_lifecycle_status`
// field). Register the mock on the exact calc-meta URL so sub-resources
// (`/blocks`, `/boundary`, `/geometry`, …) keep hitting the live backend.
const CALC_ID = process.env.E2E_CALC_ID || '0c0bff72-ff00-419f-8826-4e456c67da13' // a forest the demo user owns; set E2E_CALC_ID
const CALC_URL = `**/api/forests/calculations/${CALC_ID}`

function calcResponse(lifecycle: string, status: string) {
  return {
    id: CALC_ID,
    user_id: '68646d11-ba45-4a39-8ab5-951c90786f2a',
    uploaded_filename: 'draft',
    forest_name: 'छिमेकी',
    block_name: null,
    status,
    processing_time_seconds: null,
    error_message: null,
    created_at: '2026-08-30T09:12:08.648028+05:45',
    updated_at: '2026-08-30T09:12:08.648028+05:45',
    completed_at: '2026-08-30T14:57:08.646978+05:45',
    is_draft: false,
    map_lifecycle_status: lifecycle,
    geometry: {
      type: 'Polygon',
      coordinates: [[[86.5, 27.5], [86.6, 27.5], [86.6, 27.6], [86.5, 27.6], [86.5, 27.5]]],
    },
    result_data: {},
    draft_data: null,
    unified_shell_enabled: true,
  }
}

test.describe('Map Workspace', () => {
  test.describe.configure({ mode: 'serial' })
  test.beforeEach(async ({ page }) => {
    test.setTimeout(120000)
    await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
    await page.fill('input[name="email"]', 'demo@forest.com')
    await page.fill('input[name="password"]', 'Demo1234')
    await page.click('button[type="submit"]')
    await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  })

test('loads workspace page', async ({ page }) => {
    page.on('console', msg => {
      if (msg.type() === 'error') console.log(`PAGE ERROR: ${msg.text()}`)
    })
    page.on('pageerror', err => console.log(`PAGE EXCEPTION: ${err.message}`))
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 15000 })
  })

  test('displays layer panel', async ({ page }) => {
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    await expect(page.getByTestId('layer-panel')).toBeVisible({ timeout: 20000 })
  })

  test('displays attribute table', async ({ page }) => {
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    const layerItem = page.getByTestId('layer-item').first()
    await expect(layerItem).toBeVisible({ timeout: 30000 })
    const layerNameBtn = layerItem.locator('.layer-name-btn')
    await layerNameBtn.click({ force: true })
    await page.waitForTimeout(2000)
    await expect(page.getByTestId('attribute-table').first()).toBeVisible({ timeout: 20000 })
  })

  test('selects layer from panel', async ({ page }) => {
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    const layerItem = page.getByTestId('layer-item').first()
    await expect(layerItem).toBeVisible({ timeout: 30000 })
    const layerName = await layerItem.locator('.layer-name').textContent()
    console.log(`Clicking layer: ${layerName}`)
    const layerNameBtn = layerItem.locator('.layer-name-btn')
    await layerNameBtn.click({ force: true })
    await page.waitForTimeout(2000)
    await expect(layerItem).toHaveClass(/active/)
  })

  test('switching the active layer deactivates the previous one (owner directive 2026-10-02: panel is the only way to arm a layer)', async ({ page }) => {
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    const layerItems = page.getByTestId('layer-item')
    await expect(layerItems.first()).toBeVisible({ timeout: 30000 })
    const count = await layerItems.count()
    expect(count).toBeGreaterThan(1)

    const first = layerItems.nth(0)
    const second = layerItems.nth(1)

    await first.locator('.layer-name-btn').click({ force: true })
    await page.waitForTimeout(1000)
    await expect(first).toHaveClass(/active/)

    await second.locator('.layer-name-btn').click({ force: true })
    await page.waitForTimeout(1000)
    await expect(second).toHaveClass(/active/)
    // Only one layer is armed for selection at a time -- the previous one
    // must lose `active` the moment a different layer is picked from the panel.
    await expect(first).not.toHaveClass(/active/)
  })

  test('shows lifecycle badge in header', async ({ page }) => {
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    const badge = page.locator('.lifecycle-badge')
    await expect(badge).toBeVisible({ timeout: 15000 })
    const text = await badge.textContent()
    expect(['Draft', 'Submitted', 'Calculating…', 'Completed', 'Locked']).toContain(text)
  })

  test('shows submit button when in draft state', async ({ page }) => {
    // Mock the real calc-meta source (registers BEFORE goto so the first
    // getCalculation/poll request is intercepted)
    await page.route(CALC_URL, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(calcResponse('draft', 'pending')),
      })
    })
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    // The lifecycle action buttons are icon-only (📤/↩/👁/🔓) -- only their
    // aria-label carries the name now, so match by accessible role+name
    // rather than visible text (WorkspaceHeader.tsx).
    const submitBtn = page.getByRole('button', { name: 'Submit to Analysis' })
    await expect(submitBtn).toBeVisible({ timeout: 10000 })
  })

  test('shows review button when in submitted state', async ({ page }) => {
    await page.route(CALC_URL, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(calcResponse('submitted', 'pending')),
      })
    })
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    // Scoped to `.lifecycle-actions` -- "Review" alone is not a unique
    // accessible name on this page (e.g. tab/step labels elsewhere).
    const reviewBtn = page.locator('.lifecycle-actions').getByRole('button', { name: 'Review', exact: true })
    await expect(reviewBtn).toBeVisible({ timeout: 10000 })
  })

  test('shows unlock button when in locked state', async ({ page }) => {
    await page.route(CALC_URL, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(calcResponse('locked', 'completed')),
      })
    })
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    const unlockBtn = page.locator('.lifecycle-actions').getByRole('button', { name: 'Unlock', exact: true })
    await expect(unlockBtn).toBeVisible({ timeout: 10000 })
  })

  test('shows calculating badge with progress bar', async ({ page }) => {
    await page.route(CALC_URL, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(calcResponse('calculating', 'processing')),
      })
    })
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    await expect(page.locator('.lifecycle-badge')).toContainText('Calculating')
  })

  test('opens DFO review panel on Review button click', async ({ page }) => {
    await page.route(CALC_URL, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(calcResponse('submitted', 'pending')),
      })
    })
    await page.route('**/api/calculations/*/dfo-approve', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ map_lifecycle_status: 'locked' }) })
    })
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    await page.locator('.lifecycle-actions').getByRole('button', { name: 'Review', exact: true }).click()
    await expect(page.locator('h2', { hasText: 'DFO Review' })).toBeVisible({ timeout: 5000 })
  })
})
