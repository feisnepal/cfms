/**
 * add-data-coordinates.spec.ts — VALIDATION_TRACKER.md step C2: Add data asks for the coordinate system of a field-inventory table.
 *   - UTM coordinates (headed Easting / Northing) are detected, shown pre-selected, and the zone is SENT with the upload;
 *   - numbers that fit both UTM zones inside Nepal are not guessed: the dialog asks and keeps "Add" disabled until the user chooses.
 *
 * Requires the stack (backend :8001 running the C2 code, Vite :3001) and the demo login. Each test makes its own fresh forest.
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import fs from 'node:fs'

const BOUNDARY = 'e2e/fixtures/small_boundary.geojson' // about 85.56 E, 27.41 N: UTM zone 45
const FI_UTM45 = 'e2e/fixtures/field_inventory_utm45.csv'
const FI_AMBIGUOUS = 'e2e/fixtures/field_inventory_utm_ambiguous.csv'

async function login(page: Page) {
  test.setTimeout(240000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  await resetWorkspaceLayout(page)
}

async function newForest(page: Page) {
  await page.goto('/my-uploads', { waitUntil: 'load', timeout: 60000 })
  await page.getByRole('button', { name: /Create New|Create CFOP/i }).first().click()
  await page.getByPlaceholder(/forest|name/i).first().fill(`E2E Coordinates ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

async function openAddData(page: Page) {
  await page.getByRole('button', { name: /Add data$/ }).first().click()
  await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
}

test.describe('Add data — the coordinate system of a table (C2)', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('UTM zone 45 is detected, shown, and sent with the upload', async ({ page }) => {
    await login(page)
    await newForest(page)
    await openAddData(page)
    await page.locator('.ant-modal input[type="file"]').setInputFiles([
      { name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) },
      { name: 'survey1.csv', mimeType: 'text/csv', buffer: fs.readFileSync(FI_UTM45) },
    ])
    const box = page.locator('.ant-modal').getByTestId('coordinate-system')
    await expect(box).toBeVisible({ timeout: 20000 })
    await expect(box).toContainText('Coordinate system')
    await expect(box).toContainText('UTM zone 45N')
    await expect(box).toContainText('Detected from the numbers')

    // run the import and read the server's answer: `utm_converted` only appears when the chosen zone was applied to the numbers
    const upload = page.waitForResponse((r) => r.url().includes('/api/field-inventory/upload') && r.request().method() === 'POST', { timeout: 90000 })
    await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
    const importBtn = page.getByRole('button', { name: 'Import', exact: true })
    await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
    await page.getByRole('button', { name: /^Boundary/ }).click()
    await importBtn.click()
    await expect(page.getByText(/2 of 2 · survey1\.csv/)).toBeVisible({ timeout: 40000 })
    await importBtn.click()
    const res = await upload
    expect(res.ok()).toBeTruthy()
    const codes = ((await res.json()).findings ?? []).map((f: { code: string }) => f.code)
    expect(codes).toContain('coordinates.utm_converted')
    expect(codes).not.toContain('coordinates.looks_like_utm') // without the choice, the file is only flagged
  })

  test('numbers that fit both UTM zones are not guessed: the dialog asks and blocks Add', async ({ page }) => {
    await login(page)
    await newForest(page)
    await openAddData(page)
    await page.locator('.ant-modal input[type="file"]').setInputFiles([
      { name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) },
      { name: 'survey2.csv', mimeType: 'text/csv', buffer: fs.readFileSync(FI_AMBIGUOUS) },
    ])
    const box = page.locator('.ant-modal').getByTestId('coordinate-system')
    await expect(box).toBeVisible({ timeout: 20000 })
    await expect(box).toContainText('fit both UTM zones')
    await expect(page.locator('.ant-modal').getByRole('button', { name: /^Add/ })).toBeDisabled()
  })
})

test.describe('Add data — proposed corrections for refused values (step E)', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('a pole of 50 cm is refused with its row, a replacement is proposed, and applying it imports the file', async ({ page }) => {
    await login(page)
    await newForest(page)
    await openAddData(page)
    await page.locator('.ant-modal input[type="file"]').setInputFiles([
      { name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) },
      { name: 'survey3.csv', mimeType: 'text/csv', buffer: fs.readFileSync('e2e/fixtures/field_inventory_pole50.csv') },
    ])
    await expect(page.locator('.ant-modal').getByText('matched by content')).toBeVisible({ timeout: 20000 })
    await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
    const importBtn = page.getByRole('button', { name: 'Import', exact: true })
    await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
    await page.getByRole('button', { name: /^Boundary/ }).click()
    await importBtn.click()
    await expect(page.getByText(/2 of 2 · survey3.csv/)).toBeVisible({ timeout: 40000 })
    await importBtn.click()

    // the refused file is reported with its row, the old value and a proposed one
    const table = page.locator('.ant-modal').getByTestId('proposals')
    await expect(table).toBeVisible({ timeout: 40000 })
    await expect(table).toContainText('pole_dbh_cm')
    await expect(table).toContainText('50')
    await expect(table.locator('tbody tr')).toHaveCount(1)
    const proposed = Number((await table.locator('tbody tr td').nth(3).innerText()).trim())
    expect(proposed).toBeGreaterThanOrEqual(10)
    expect(proposed).toBeLessThan(30)

    // apply it: the file is imported again and the report says the value was replaced
    await page.locator('.ant-modal').getByTestId('apply-corrections').click()
    await expect(page.getByText(/1 of 1 · survey3.csv/)).toBeVisible({ timeout: 40000 })
    await importBtn.click()
    await expect(page.locator('.ant-modal').getByTestId('finding-field_inventory.corrections_applied')).toBeVisible({ timeout: 60000 })
    await expect(page.locator('.ant-modal').getByTestId('proposals')).toHaveCount(0)
  })
})

test.describe('Add data — a stem-mapping table in UTM (step C2, stem mapping)', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('the coordinate system is asked, pre-selected, and reaches the stem-mapping import', async ({ page }) => {
    await login(page)
    await newForest(page)
    await openAddData(page)
    await page.locator('.ant-modal input[type="file"]').setInputFiles([
      { name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) },
      { name: 'stems.csv', mimeType: 'text/csv', buffer: fs.readFileSync('e2e/fixtures/stems_utm45.csv') },
    ])
    const box = page.locator('.ant-modal').getByTestId('coordinate-system')
    await expect(box).toBeVisible({ timeout: 20000 })
    await expect(box).toContainText('UTM zone 45N')
    await expect(box).toContainText('Detected from the numbers')

    // the stem-mapping import is told the zone, and its validator reports THAT zone (it used to call almost every UTM file zone 44)
    const confirm = page.waitForResponse((r) => r.url().includes('/api/inventory/confirm-mapping') && r.request().method() === 'POST', { timeout: 90000 })
    await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
    const importBtn = page.getByRole('button', { name: 'Import', exact: true })
    await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
    await page.getByRole('button', { name: /^Boundary/ }).click()
    await importBtn.click()
    await expect(page.getByText(/2 of 2 · stems\.csv/)).toBeVisible({ timeout: 40000 })
    await importBtn.click()
    const report = await (await confirm).json()
    expect(report.summary.ready_for_processing).toBe(true) // the trees lie inside the forest once UTM metres are read as UTM metres (they used to be reported 100% outside)
    expect(report.data_detection.crs.epsg).toBe(32645)
  })
})
