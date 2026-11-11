/**
 * data-template.spec.ts — the "Download data template" zip and the coordinate system a file declares.
 *   - the button next to "Add data" downloads a real zip with the Excel and CSV templates and the README;
 *   - a file that declares its coordinate system in `coordinate_system_epsg` is checked against its numbers in Add data:
 *     confirmed when it fits, named and blocked when it does not.
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
  await page.getByPlaceholder(/forest|name/i).first().fill(`E2E Templates ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

const HEADER = 'block_name,sample_plot_number,longitude,latitude,coordinate_system_epsg,tree_species_scientific,tree_dbh_cm,tree_height_m'
const csv = (lon: string, lat: string, epsg: string) =>
  [HEADER, ...[0, 1, 2].map((i) => `B1,${i + 1},${(Number(lon) + i * 40).toFixed(1)},${(Number(lat) + i * 30).toFixed(1)},${epsg},Shorea robusta,${40 + i * 5},18`)].join('\n') + '\n'

test.describe('Data template', () => {
  test.describe.configure({ mode: 'serial' })

  test.afterEach(async ({ page }) => {
    const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
    if (!id) return
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
  })

  test('the button next to Add data downloads the zip of templates', async ({ page }) => {
    await login(page)
    await newForest(page)
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 60000 }),
      page.getByRole('button', { name: /Download data template/i }).first().click(),
    ])
    expect(download.suggestedFilename()).toMatch(/^Forest_Data_Templates.*\.zip$/)
    const bytes = fs.readFileSync((await download.path()) as string)
    expect(bytes.subarray(0, 2).toString('latin1')).toBe('PK') // a real zip
    const names = bytes.toString('latin1') // file names sit uncompressed in the zip headers
    for (const n of ['00_READ_ME.txt', 'excel/03_Field_Inventory.xlsx', 'excel/05_Households_and_Committees.xlsx', 'excel/01_Forest_Boundary_Stations.xlsx']) {
      expect(names).toContain(n)
    }
  })

  test('the same button is inside the Add data dialog', async ({ page }) => {
    await login(page)
    await newForest(page)
    await page.getByRole('button', { name: /Add data$/ }).first().click()
    const dialog = page.locator('.ant-modal')
    await expect(dialog.getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
    await expect(dialog.getByRole('button', { name: /Download data template/i })).toBeVisible()
  })

  test('a declared coordinate system that fits the numbers is confirmed', async ({ page }) => {
    await login(page)
    await newForest(page)
    await page.getByRole('button', { name: /Add data$/ }).first().click()
    await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
    await page.locator('.ant-modal input[type="file"]').setInputFiles({ name: 'plots1.csv', mimeType: 'text/csv', buffer: Buffer.from(csv('356841.9', '3031794.4', '32645')) })
    const box = page.locator('.ant-modal').getByTestId('coordinate-system')
    await expect(box).toBeVisible({ timeout: 20000 })
    await expect(box).toContainText('Declared in the file')
    await expect(box).toContainText('UTM zone 45N')
  })

  test('a declaration the numbers contradict is named and blocks Add', async ({ page }) => {
    await login(page)
    await newForest(page)
    await page.getByRole('button', { name: /Add data$/ }).first().click()
    await expect(page.locator('.ant-modal').getByText('Click or drag files here')).toBeVisible({ timeout: 10000 })
    // the file says degrees (4326) but the numbers are UTM metres
    await page.locator('.ant-modal input[type="file"]').setInputFiles({ name: 'plots2.csv', mimeType: 'text/csv', buffer: Buffer.from(csv('356841.9', '3031794.4', '4326')) })
    const mismatch = page.locator('.ant-modal').getByTestId('declared-mismatch')
    await expect(mismatch).toBeVisible({ timeout: 20000 })
    await expect(mismatch).toContainText('declares Degrees (WGS 84), but the numbers fit UTM zone 45N')
  })
})
