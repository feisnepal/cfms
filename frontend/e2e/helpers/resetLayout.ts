import { expect, Page } from '@playwright/test'

/**
 * Put the demo user's saved workspace layout back to the app's defaults: one panel per dock position - Layers (left) and the Attribute
 * Table (right) open, the other four closed until asked for (owner rule 2026-10-11, `lib/workspaceLayout.ts`).
 *
 * The layout is saved on the server per user, so a spec that collapses a panel (the dock spec does) leaves that state for every spec after it;
 * a collapsed "Imported Layers" panel hides the "Add layer" button and the import specs then fail for a reason that is not theirs. Call this
 * after login in any spec that needs the dock.
 */
const DEFAULT_LAYOUT = {
  version: 1,
  groups: {
    'workspace-horizontal': { left: 20, center: 60, right: 20 },
    'workspace-left': { layers: 100, basemap: 0, imported: 0, raster: 0 },
    'workspace-right': { attributeTable: 100, legend: 0 },
  },
  collapsed: { layers: false, basemap: true, imported: true, raster: true, attributeTable: false, legend: true },
}

/**
 * The dock saves its layout from the page that is closing, a moment AFTER the next test has started, so a single PUT can be overwritten. This
 * applies the default, waits, and checks what the server holds; it repeats until the stored layout is the default (or gives up after a few
 * rounds, leaving the spec to fail on what it sees, not hide it).
 */
export async function resetWorkspaceLayout(page: Page): Promise<void> {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  for (let round = 0; round < 4; round++) {
    const put = await page.request.put('/api/v1/workspace/layout', { headers, data: { layout_key: 'workspace', layout_json: DEFAULT_LAYOUT } })
    expect(put.ok()).toBeTruthy()
    await page.waitForTimeout(1500) // let a late save from the previous page land (it would overwrite the default)
    const got = await page.request.get('/api/v1/workspace/layout?layout_key=workspace', { headers })
    const stored = got.ok() ? (await got.json())?.layout_json : null
    if (JSON.stringify(stored?.collapsed) === JSON.stringify(DEFAULT_LAYOUT.collapsed) && stored?.groups?.['workspace-left']?.layers === 100) return
  }
}
