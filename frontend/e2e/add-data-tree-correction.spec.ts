/**
 * add-data-tree-correction.spec.ts - a tree table with points just outside the forest boundary, dropped into Add data: the same correction
 * preview the Tree mapping tab shows opens (instead of "open the Tree mapping tab"), accepting it processes the file, and declining it
 * leaves nothing behind that would stop the next upload.
 *
 * Requires the stack and the demo login. Each test makes its own fresh forest and deletes it afterwards.
 */
import { test, expect, Page } from '@playwright/test'
import fs from 'node:fs'
import { resetWorkspaceLayout } from './helpers/resetLayout'

const BOUNDARY = 'e2e/fixtures/small_boundary.geojson' // 85.55-85.57 E, 27.40-27.42 N
const API = 'http://localhost:8001'

/** 24 trees inside the boundary and 3 about 100 m outside it: 11% outside, within the tolerance, so the server proposes corrections. */
function treeCsv(): string {
  const rows = ['species,height_m,dia_cm,class,LONGITUDE,LATITUDE']
  for (let i = 0; i < 24; i++) rows.push(`Shorea robusta,${12 + (i % 5)},${20 + (i % 9)},1,${(85.553 + 0.0007 * i).toFixed(6)},${(27.405 + 0.0006 * i).toFixed(6)}`)
  for (let i = 0; i < 3; i++) rows.push(`Shorea robusta,15,25,1,${(85.5712 + 0.0001 * i).toFixed(6)},${(27.41 + 0.001 * i).toFixed(6)}`)
  return rows.join('\n') + '\n'
}

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
  await page.getByPlaceholder(/forest|name/i).first().fill(`E2E Tree Correction ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

/** Drop the boundary and the tree table together; import the boundary, then arrive at the tree table's Import Layer dialog. */
async function dropTrees(page: Page) {
  await page.getByRole('button', { name: /Add data$/ }).first().click()
  await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
  await page.locator('.ant-modal input[type="file"]').setInputFiles([
    { name: 'forest_boundary.geojson', mimeType: 'application/geo+json', buffer: fs.readFileSync(BOUNDARY) },
    { name: 'tree_mapping.csv', mimeType: 'text/csv', buffer: Buffer.from(treeCsv()) },
  ])
  await expect(page.locator('.ant-modal').getByText('tree_mapping.csv')).toBeVisible({ timeout: 20000 })
  await page.locator('.ant-modal').getByRole('button', { name: /^Add/ }).click()
  const importBtn = page.getByRole('button', { name: 'Import', exact: true })
  await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: /^Boundary/ }).click()
  await importBtn.click()
  await page.getByText(/2 of 2 · tree_mapping\.csv/).waitFor({ timeout: 40000 })
  await importBtn.click()
}

const calcId = (page: Page) => page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]

test.describe('Add data - a tree table with points outside the boundary', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    const id = calcId(page)
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`${API}/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('the correction preview opens here, and accepting it processes the trees', async ({ page }) => {
    await login(page)
    await newForest(page)
    await dropTrees(page)
    await expect(page.getByText('Boundary Validation Warning')).toBeVisible({ timeout: 60000 })
    await expect(page.getByText(/Open the .* tab and upload the file there/)).toHaveCount(0)
    await page.getByRole('button', { name: /Accept Corrections/ }).click()
    await expect(page.getByText('Boundary Validation Warning')).toHaveCount(0, { timeout: 90000 })

    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    const check = await page.request.get(`${API}/api/inventory/by-calculation/${calcId(page)}/check`, { headers: { Authorization: `Bearer ${token}` } })
    expect(check.ok()).toBeTruthy()
    const body = await check.json()
    expect(body.exists).toBe(true)
  })

  test('declining leaves nothing behind: the next upload is not refused as "already exists"', async ({ page }) => {
    await login(page)
    await newForest(page)
    await dropTrees(page)
    await expect(page.getByText('Boundary Validation Warning')).toBeVisible({ timeout: 60000 })
    await page.getByRole('button', { name: /Cancel Upload/ }).click()
    await expect(page.getByText('Boundary Validation Warning')).toHaveCount(0)

    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    const check = await page.request.get(`${API}/api/inventory/by-calculation/${calcId(page)}/check`, { headers: { Authorization: `Bearer ${token}` } })
    expect(check.ok()).toBeTruthy()
    expect((await check.json()).exists).toBe(false)
  })
})
