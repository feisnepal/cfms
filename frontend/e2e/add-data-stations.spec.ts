/**
 * add-data-stations.spec.ts — VALIDATION_TRACKER.md C4: a survey station with one mistyped digit.
 * A field team's boundary station list (CSV, in walking order) has the 15th longitude typed with a wrong second decimal. The boundary preview flags that
 * station by its row, says what the digit most likely is, and the user can still create the boundary.
 *
 * Requires the stack (backend :8001 running this code, Vite :3001) and the demo login.
 */
import { test, expect, Page } from '@playwright/test'
import { resetWorkspaceLayout } from './helpers/resetLayout'
import fs from 'node:fs'

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
  await page.getByPlaceholder(/forest|name/i).first().fill(`E2E Stations ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

test.describe('Boundary station list — a mistyped digit (C4)', () => {
  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('the 15th station is flagged by its row with the digit that most likely fixes it', async ({ page }) => {
    await login(page)
    await newForest(page)
    await page.getByRole('button', { name: /Add data$/ }).first().click()
    await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
    await page.locator('.ant-modal input[type="file"]').setInputFiles({ name: 'stations.csv', mimeType: 'text/csv', buffer: fs.readFileSync('e2e/fixtures/boundary_stations_typo.csv') })
    await expect(page.locator('.ant-modal').getByText(/boundary|matched/i).first()).toBeVisible({ timeout: 20000 })
    await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
    await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
    await page.getByRole('button', { name: /^Boundary/ }).click()
    await page.getByRole('button', { name: 'Import', exact: true }).click()

    const box = page.getByTestId('station-issues')
    await expect(box).toBeVisible({ timeout: 40000 })
    await expect(box).toContainText('1 station(s) look mistyped')
    await expect(box).toContainText('Row 16') // the 15th station is spreadsheet row 16 (row 1 is the header)
    await expect(box).toContainText('should be')
    await expect(page.getByRole('button', { name: /Create Boundary/i })).toBeEnabled() // advice only: the user decides
  })
})
