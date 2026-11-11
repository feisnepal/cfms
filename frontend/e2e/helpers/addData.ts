import { expect, Page } from '@playwright/test'

/**
 * Import one file through the header's "Add data" dialog - the single place imports start from (UPLOAD_EXPERIENCE_PLAN.md, UP-4).
 *
 * The older "Imported Layers -> Add layer" menu only exists while a forest has no geometry; once it has some, the Basemap / Imported Layers /
 * Raster panels are not on screen and imports go through Add data. The file is dropped in the dialog, identified (by its name here), added, and the
 * per-file dialog that follows is confirmed with its preselected purpose. `purposeButton` is for a file whose purpose must be picked by hand
 * (a boundary).
 *
 * Resolves once the per-file dialog has been confirmed; the caller asserts the outcome (a replace-confirm, a count, a layer ...).
 */
export async function importViaAddData(
  page: Page,
  file: string | { name: string; mimeType: string; buffer: Buffer },
  opts: { purposeButton?: RegExp } = {},
): Promise<void> {
  await page.getByRole('button', { name: /Add data$/ }).first().click()
  const dialog = page.locator('.ant-modal', { hasText: 'Click or drag files here' })
  await expect(dialog).toBeVisible({ timeout: 15000 })
  await dialog.locator('input[type="file"]').setInputFiles(file as never)
  // classified (by name or by content) before it can be added
  await expect(dialog.getByText(/matched by (name|content)|has no boundary yet, so this looks like it/)).toBeVisible({ timeout: 20000 })
  await dialog.getByRole('button', { name: /^Add/ }).click()
  await expect(page.getByRole('heading', { name: 'Import Layer' })).toBeVisible({ timeout: 20000 })
  if (opts.purposeButton) await page.getByRole('button', { name: opts.purposeButton }).click()
  await page.getByRole('button', { name: 'Import', exact: true }).click()
}

/** After the last file: wait for the report in the Add-data dialog and close it. */
export async function closeAddDataReport(page: Page): Promise<void> {
  const done = page.locator('.ant-modal').getByRole('button', { name: 'Done' })
  await expect(done).toBeVisible({ timeout: 40000 })
  await done.click()
}

/** Create a fresh name-only forest from My CFOPs and open its workspace. */
export async function createForest(page: Page, label: string): Promise<void> {
  await page.goto('/my-uploads', { waitUntil: 'load', timeout: 60000 })
  await page.getByRole('button', { name: /Create New|Create CFOP/i }).first().click()
  await page.getByPlaceholder(/forest|name/i).first().fill(`${label} ${Date.now()}`)
  await page.getByRole('button', { name: /Create.*Open Workspace/i }).click()
  await page.waitForURL(/\/calculations\/[0-9a-f-]+(\?|$)/, { timeout: 30000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
}

/** A fresh forest whose boundary is the given file, added through Add data; resolves once the boundary is in (the empty-forest banner is gone). */
export async function createForestWithBoundary(page: Page, label: string, boundaryFile: string): Promise<void> {
  await createForest(page, label)
  await expect(page.getByTestId('no-geometry-banner')).toBeVisible({ timeout: 20000 })
  await importViaAddData(page, boundaryFile, { purposeButton: /^Boundary/ })
  await closeAddDataReport(page)
  await expect(page.getByTestId('no-geometry-banner')).toBeHidden({ timeout: 30000 })
}

/** Delete the forest the page is on. Each spec makes its own forest; leaving them would make the next run's boundary overlap this one's. */
export async function deleteCurrentForest(page: Page): Promise<void> {
  const id = page.url().match(/\/calculations\/([0-9a-f-]+)/)?.[1]
  if (!id) return
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  await page.request.delete(`http://localhost:8001/api/forests/calculations/${id}`, { headers: { Authorization: `Bearer ${token}` } })
}
