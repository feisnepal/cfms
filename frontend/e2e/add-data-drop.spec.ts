/**
 * add-data-drop.spec.ts — UP-4.X exit check (UPLOAD_EXPERIENCE_PLAN.md): the drop flow of "Add data".
 *   - a household list with a name that says nothing is identified BY ITS CONTENT and imports with no extra question;
 *   - a household list named like a boundary file is NOT silently treated as a boundary: the dialog says what it looks like
 *     and offers to switch.
 *
 * Requires the stack (backend :8001, Vite :3001) and the demo login. Each test makes its own fresh forest.
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import fs from 'node:fs'

const BOUNDARY = 'e2e/fixtures/small_boundary.geojson'
const HOUSEHOLDS = 'e2e/fixtures/households_neutral_name.csv'

async function login(page: Page) {
  test.setTimeout(240000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
  await resetWorkspaceLayout(page) // the saved dock layout is per user: undo what an earlier spec collapsed
}

async function newForest(page: Page) {
  await page.goto('/my-uploads', { waitUntil: 'load', timeout: 60000 })
  await page.getByRole('button', { name: /Create New|Create CFOP/i }).first().click()
  await page.getByPlaceholder(/forest|name/i).first().fill(`E2E AddData ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

async function openAddData(page: Page) {
  await page.getByRole('button', { name: /Add data$/ }).first().click()
  await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
}

test.describe('Add data — the drop flow (UP-4)', () => {
  test.describe.configure({ mode: 'serial' })

  // each test makes its own forest: remove it afterwards so a rerun never overlaps the boundary of an earlier run
  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('a household list with a neutral name is identified by its content and imports', async ({ page }) => {
    await login(page)
    await newForest(page)
    await openAddData(page)
    await page.locator('.ant-modal input[type="file"]').setInputFiles([{ name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) }, { name: 'data1.csv', mimeType: 'text/csv', buffer: fs.readFileSync(HOUSEHOLDS) }])  // a boundary in the same drop, so Add data is not stopped by "boundary first"
    await expect(page.locator('.ant-modal').getByText('matched by content')).toBeVisible({ timeout: 20000 })
    await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
    // each file opens its own per-file dialog (the owner's placement) with the purpose already chosen: confirm it.
    // The boundary is first and needs its purpose picked; the households need nothing else.
    const importBtn = page.getByRole('button', { name: 'Import', exact: true })
    await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
    await page.getByRole('button', { name: /^Boundary/ }).click()
    await importBtn.click()
    await expect(page.getByText(/2 of 2 · data1\.csv/)).toBeVisible({ timeout: 40000 })
    await importBtn.click()
    // the report is shown inside the dialog once the file is handled
    await expect(page.locator('.ant-modal').getByText(/Every file imported cleanly/)).toBeVisible({ timeout: 40000 })
  })

  test('a household list named like a boundary file gets a clear redirect', async ({ page }) => {
    await login(page)
    await newForest(page)
    await openAddData(page)
    await page.locator('.ant-modal input[type="file"]').setInputFiles({
      name: 'forest_boundary.csv',
      mimeType: 'text/csv',
      buffer: fs.readFileSync(HOUSEHOLDS),
    })
    await expect(page.locator('.ant-modal').getByText(/This looks like/)).toBeVisible({ timeout: 20000 })
    await expect(page.locator('.ant-modal').getByRole('button', { name: /^Use / })).toBeVisible()
  })

  test('dropping a file anywhere on the workspace opens Add data with it already in', async ({ page }) => {
    await login(page)
    await newForest(page)
    await page.evaluate(() => {
      const dt = new DataTransfer()
      dt.items.add(new File(['x'], 'forest_boundary.kml'))
      for (const type of ['dragenter', 'dragover', 'drop']) {
        window.dispatchEvent(new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true }))
      }
    })
    await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('.ant-modal').getByText('forest_boundary.kml')).toBeVisible()
    await expect(page.locator('.ant-modal').getByText('matched by name')).toBeVisible({ timeout: 15000 })
  })
})
