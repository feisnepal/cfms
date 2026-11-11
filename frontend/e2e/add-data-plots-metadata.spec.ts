/**
 * add-data-plots-metadata.spec.ts — the sample-plot table and the forest-details table dropped into Add data (2026-10-13).
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
  await page.getByPlaceholder(/forest|name/i).first().fill(`E2E Plots Metadata ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

async function openAddData(page: Page) {
  await page.getByRole('button', { name: /Add data$/ }).first().click()
  await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
}


async function addWithBoundary(page: Page, name: string, csv: string, endpoint: string) {
  await openAddData(page)
  await page.locator('.ant-modal input[type="file"]').setInputFiles([
    { name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) },
    { name, mimeType: 'text/csv', buffer: Buffer.from(csv) },
  ])
  await expect(page.locator('.ant-modal').getByText(name)).toBeVisible({ timeout: 20000 })
  const call = page.waitForResponse((r) => r.url().includes(endpoint) && r.request().method() === 'POST', { timeout: 90000 })
  await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
  const importBtn = page.getByRole('button', { name: 'Import', exact: true })
  await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: /^Boundary/ }).click()
  await importBtn.click()
  await page.getByText(new RegExp(`2 of 2 · ${name.replace('.', '\\.')}`)).waitFor({ timeout: 40000 })
  await importBtn.click()
  return call
}

test.describe('Add data — sample plots and forest details', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('a forest-details file is recognised and fills the details', async ({ page }) => {
    await login(page)
    await newForest(page)
    const csv = ['forest_name,group_name,district,ward,fy_start,fy_end', 'E2E Forest,E2E CFUG,Kavre,5,2083/84,2092/93', ''].join('\n')
    const res = await (await addWithBoundary(page, 'details.csv', csv, '/forest-metadata/import'))
    expect(res.ok()).toBeTruthy()
    const body = await res.json()
    expect(body.data.group_name).toBe('E2E CFUG')
    expect(body.findings.map((f: { code: string }) => f.code)).toContain('forest_metadata.imported')
  })

  test('a sample plot outside the forest is refused with its row named', async ({ page }) => {
    await login(page)
    await newForest(page)
    // inside Nepal (the dialog then accepts the declared degrees without asking) but about 35 km from the small test forest (85.56 E, 27.41 N)
    const csv = ['plot_number,longitude,latitude,coordinate_system_epsg', '1,85.9,27.7,4326', ''].join('\n')
    const res = await (await addWithBoundary(page, 'plots.csv', csv, '/sampling/import-plots'))
    expect(res.status()).toBe(422)
    const finding = (await res.json()).detail.findings[0]
    expect(finding.code).toBe('sample_plots.outside_forest')
    expect(finding.where.rows).toEqual([2])
  })
})
