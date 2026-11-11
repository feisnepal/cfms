/**
 * tabbed-detail.spec.ts — E2E for the tabbed calculation shell.
 *
 * WORKSPACE_FLOW_NAV_PLAN P4. The shell is now four **phases of the work**
 * (`base`, `field`, `analysis`, `plan`) containing seventeen numbered steps, with a
 * guided stepper above the panels and a readiness strip in the rail.
 *
 * Requires a running backend (port 8001) + the frontend dev server (3001). The
 * Playwright webServer (playwright.config.ts) boots Vite with DEV enabled so the
 * `__mapInstance` / `__workspaceStore` / `__crashWorkspace` test hooks exposed by
 * `WorkspaceTab` are available.
 *
 * The calculation is resolved at runtime, not hardcoded. The previous version
 * pinned `15f64467-…`, that calculation was deleted from the database, and the
 * whole suite silently became unrunnable. `resolveCalcId` now finds a calculation
 * that actually has a boundary, and `E2E_CALC_ID` overrides it.
 */
import { test, expect, Page } from '@playwright/test'

/** The four groups, in workflow order. The order is the whole point. */
const GROUPS = {
  base: 'Base',
  field: 'Field Work',
  analysis: 'Analysis',
  plan: 'Plan & Submission',
} as const

type GroupId = keyof typeof GROUPS

const tabPanel = (page: Page, id: GroupId) => page.getByTestId(`tab-${id}`)
const tabRole = (page: Page, group: GroupId) =>
  page.getByRole('tab', { name: new RegExp(`^${GROUPS[group]}$`) })

/**
 * A step in the rail, matched on its composed accessible name ("<n>. <label>").
 *
 * Scoped to the rail strip: the stepper's progress segments carry the same label
 * in their `title`, so an unscoped lookup matches the step twice and trips
 * strict mode.
 */
const stepIn = (page: Page, label: RegExp) =>
  page.getByTestId('workflow-rail').getByRole('button', { name: label })

async function login(page: Page) {
  test.setTimeout(180000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

/**
 * A calculation that has a boundary, so the map actually mounts.
 *
 * The list endpoint returns a trimmed payload with no `geometry`, so each
 * candidate is probed individually. Order is otherwise arbitrary, which is
 * exactly the point: the suite must not depend on a fixture UUID surviving.
 */
async function resolveCalcId(page: Page): Promise<string> {
  const override = process.env.E2E_CALC_ID
  if (override) return override

  const id = await page.evaluate(async () => {
    const token = localStorage.getItem('access_token')
    const headers = { Authorization: `Bearer ${token}` }
    const listed = await fetch('/api/forests/calculations', { headers }).then((r) =>
      r.ok ? r.json() : [],
    )
    const rows: { id: string }[] = Array.isArray(listed) ? listed : (listed?.calculations ?? [])
    for (const row of rows) {
      const full = await fetch(`/api/forests/calculations/${row.id}`, { headers }).then((r) =>
        r.ok ? r.json() : null,
      )
      if (full?.geometry) return row.id
    }
    return null
  })

  if (!id) {
    throw new Error(
      'No calculation with a boundary is reachable as demo@forest.com. ' +
        'Seed one, or set E2E_CALC_ID.',
    )
  }
  return id
}

let cachedCalcId: string | null = null

/** Shortcut: login, resolve the fixture, land on the tabbed shell with the map up. */
/**
 * Wait until the map has stopped moving on its own.
 *
 * The workspace fits itself to the forest once the boundary and layers land.
 * That `fitBounds` is async, so a test that grabs the view the instant
 * `__mapInstance` exists is racing it: its own `setView` gets overwritten by the
 * app's initial fit and the assertion reads the fitted zoom, not the one under
 * test. Requiring the view to hold still for a beat removes the race.
 */
async function waitForMapSettled(page: Page) {
  await page.waitForFunction(
    () => {
      const m = (window as any).__mapInstance
      if (!m) return false
      const w = window as any
      const c = m.getCenter()
      const key = `${m.getZoom()}:${c.lat.toFixed(5)}:${c.lng.toFixed(5)}`
      if (w.__mapSettleKey !== key) {
        w.__mapSettleKey = key
        w.__mapSettleAt = Date.now()
        return false
      }
      return Date.now() - (w.__mapSettleAt ?? 0) > 1000
    },
    undefined,
    { timeout: 30000 },
  )
}

async function openTabbed(page: Page, query = '') {
  await login(page)
  if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
  const url = `/calculations/${cachedCalcId}/tabbed${query}`
  await page.goto(url, { waitUntil: 'load', timeout: 60000 })
  await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 20000 })
  // Wait for the Leaflet engine to be up (dev-only __mapInstance hook). Tab
  // clicks queue behind heavy layer init, which delays the panel render well
  // past the default assertion timeout under contention.
  await page.waitForFunction(() => !!(window as any).__mapInstance, undefined, { timeout: 20000 })
  await waitForMapSettled(page)
}

test.describe('Tabbed calculation shell — four phases, seventeen steps', () => {
  test.describe.configure({ mode: 'serial' })

  test('Base is active by default and the map renders', async ({ page }) => {
    await openTabbed(page)

    await expect(tabPanel(page, 'base')).toBeVisible()
    // Map canvas is mounted and Leaflet has a real container.
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 20000 })
    await expect(page.locator('.leaflet-container')).toBeAttached()
    // The merged ActivityRail is the only nav.
    await expect(page.locator('.calc-activity-rail')).toBeVisible()
    await expect(tabPanel(page, 'plan')).not.toBeVisible()
  })

  test('the stepper shows the position in the flow and the current step', async ({ page }) => {
    await openTabbed(page)
    const stepper = page.getByTestId('workflow-stepper')
    await expect(stepper).toBeVisible()
    // Step 1 of 15 (the registry's spine length), and the step is the map.
    await expect(stepper).toContainText('Step 1 of 15')
    // 15 progress segments, one per step.
    await expect(stepper.locator('ol li')).toHaveCount(15)
  })

  test('the readiness strip reports progress', async ({ page }) => {
    await openTabbed(page)
    const strip = page.getByTestId('workflow-readiness')
    await expect(strip).toBeVisible()
    // Whatever the count, the strip must state it — an empty strip is the old bug.
    await expect(strip).toContainText(/steps done|steps done/)
  })

  test('switching phases swaps panels and syncs ?surface=', async ({ page }) => {
    await openTabbed(page)

    // Panel assertions use 20s timeouts: under map-init contention a
    // click-to-render switch is delayed past the 5s default.
    await tabRole(page, 'field').click()
    await expect(tabPanel(page, 'field')).toBeVisible({ timeout: 20000 })
    await expect(tabPanel(page, 'base')).not.toBeVisible()
    await expect(page).toHaveURL(/surface=field/)

    await tabRole(page, 'analysis').click()
    await expect(tabPanel(page, 'analysis')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(/surface=analysis/)

    await tabRole(page, 'plan').click()
    await expect(tabPanel(page, 'plan')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(/surface=plan/)

    await tabRole(page, 'base').click()
    await expect(tabPanel(page, 'base')).toBeVisible({ timeout: 20000 })
  })

  test('map instance survives a phase switch (no remount) and keeps zoom/centre', async ({ page }) => {
    await openTabbed(page)

    // page.evaluate serialises objects across the CDP boundary, so its return
    // values are CLONES — compare instance identity INSIDE the page. Playwright's
    // `expect` is a Node-side helper and is not available in page context, so a
    // missing instance is reported by throwing here.
    await page.evaluate(() => {
      const m = (window as any).__mapInstance
      if (!m) throw new Error('__mapInstance is not exposed — cannot test remount')
      ;(window as unknown as Record<string, unknown>).__mapBefore = m
    })
    await page.evaluate(() => {
      ;(window as any).__mapInstance?.setView([27.7, 85.3], 12)
    })

    await tabRole(page, 'plan').click()
    await expect(tabPanel(page, 'plan')).toBeVisible({ timeout: 20000 })
    await tabRole(page, 'base').click()
    await expect(tabPanel(page, 'base')).toBeVisible({ timeout: 20000 })

    const noRemount = await page.evaluate(
      () => (window as any).__mapBefore === (window as any).__mapInstance,
    )
    expect(noRemount).toBe(true)

    const state = await page.evaluate(() => {
      const m = (window as any).__mapInstance
      return m ? { zoom: m.getZoom(), center: m.getCenter() } : null
    })
    expect(state?.zoom).toBe(12)
    expect(state?.center.lat).toBeCloseTo(27.7, 1)
    expect(state?.center.lng).toBeCloseTo(85.3, 1)
  })

  test("the stepper's Next walks the flow and never blocks", async ({ page }) => {
    await openTabbed(page)
    const stepper = page.getByTestId('workflow-stepper')

    // The target of `Next` depends on the fixture: it prefers the next INCOMPLETE
    // input step, so on a calculation that already has geometry, fieldbook data
    // and a sampling design it legitimately skips several completed steps. Assert
    // the rule (advance, stay reachable, Back returns) rather than a fixed index,
    // which would only hold for a virgin calculation.
    const stepNumber = async (): Promise<{ n: number; total: number }> => {
      const m = (await stepper.innerText()).match(/Step\s+(\d+)\s+of\s+(\d+)/i)
      if (!m) throw new Error(`stepper has no "Step N of M" heading`)
      return { n: Number(m[1]), total: Number(m[2]) }
    }

    const start = await stepNumber()
    expect(start.total).toBe(15)
    expect(start.n).toBe(1)

    // The chevron is a distinct control from the Next button, and both obey the
    // same rule.
    await stepper.getByTestId('workflow-stepper-next').click()
    // Poll the step number itself: the total is 15 from the start, so waiting on
    // it would pass before Next had navigated anywhere.
    await expect
      .poll(async () => (await stepNumber()).n, { timeout: 20000 })
      .toBeGreaterThan(start.n)

    // Never enforced: whatever step Next landed on is actually mounted, and the
    // address bar names a real canonical surface.
    await expect(page.getByTestId('workflow-rail')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(/surface=[a-z-]+(\/|%2F)[a-z0-9-]+/)

    // Back is a step back through the spine, not a reset to the first step.
    const landed = (await stepNumber()).n
    await stepper.getByTestId('workflow-stepper-back').click()
    await expect.poll(async () => (await stepNumber()).n, { timeout: 20000 }).toBe(landed - 1)
  })

  test('a step whose prerequisites are unmet is still reachable', async ({ page }) => {
    // The governing rule: sequence, never enforce. The demo forest has no
    // sampling design, so Field Inventory's prerequisite is unmet — the step
    // must still be clickable and must still render.
    await openTabbed(page)
    await tabRole(page, 'field').click()
    await expect(tabPanel(page, 'field')).toBeVisible({ timeout: 20000 })

    // The rail names each step "<n>. <label>", so match the rendered label —
    // an i18n key never appears in an accessible name.
    const inventory = stepIn(page, /Field Inventory$/)
    await expect(inventory).toBeEnabled()
    await inventory.click()
    await expect(tabPanel(page, 'field')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(/surface=field/)
  })

  test('deep link to an analysis step mounts the map in the background', async ({ page }) => {
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}/tabbed?surface=analysis/hazarderosion`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(tabPanel(page, 'analysis')).toBeVisible({ timeout: 20000 })
    // The Base panel is display-hidden but still attached, so the map survives.
    const workspace = page.getByTestId('workspace-container')
    await expect(workspace).toBeAttached()
    await expect(workspace).not.toBeVisible()
  })

  test('an unrecognised surface falls back to the Map', async ({ page }) => {
    // Fail-closed resolution: a wrong link lands on the Map, not a blank panel.
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}/tabbed?surface=analysis/nope`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(tabPanel(page, 'base')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(/surface=base(%2F|\/)unified/)
  })

  test('unsaved edits: leaving shows the confirmation; Stay keeps you put', async ({ page }) => {
    await openTabbed(page)

    // No modal when clean.
    await tabRole(page, 'field').click()
    await expect(tabPanel(page, 'field')).toBeVisible({ timeout: 20000 })
    await tabRole(page, 'base').click()
    await expect(tabPanel(page, 'base')).toBeVisible({ timeout: 20000 })

    await page.evaluate(() => (window as any).__workspaceStore?.setDirty(true))
    await tabRole(page, 'field').click()

    await expect(page.getByText('Unsaved changes')).toBeVisible({ timeout: 20000 })

    // Stay -> still where we were, modal dismissed.
    await page.getByRole('button', { name: 'Stay' }).click()
    await expect(page.getByText('Unsaved changes')).toBeHidden()
    await expect(tabPanel(page, 'base')).toBeVisible()

    // Retry, and Discard & leave this time.
    await tabRole(page, 'field').click()
    await expect(page.getByText('Unsaved changes')).toBeVisible({ timeout: 20000 })
    await page.getByRole('button', { name: 'Discard & leave' }).click()
    await expect(tabPanel(page, 'field')).toBeVisible({ timeout: 20000 })
    await expect(page).toHaveURL(/surface=field/)
  })

  test('Ctrl+1..4 address the four phases', async ({ page }) => {
    await openTabbed(page)
    for (const [digit, group] of [
      ['1', 'base'],
      ['2', 'field'],
      ['3', 'analysis'],
      ['4', 'plan'],
    ] as const) {
      await page.keyboard.press(`Control+${digit}`)
      await expect(tabPanel(page, group), `Ctrl+${digit} -> ${group}`).toBeVisible({
        timeout: 20000,
      })
      await expect(page).toHaveURL(new RegExp(`surface=${group}`))
    }
  })

  test('a crash in one phase is isolated; the rest of the shell still works', async ({ page }) => {
    await page.addInitScript(() => {
      ;(window as any).__crashWorkspace = true
    })
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}/tabbed`, {
      waitUntil: 'load',
      timeout: 60000,
    })

    await expect(page.locator('.tab-error-fallback')).toBeVisible({ timeout: 20000 })
    await expect(page.getByText('Reload this tab')).toBeVisible()

    // ...while the rest of the page keeps working.
    await tabRole(page, 'plan').click()
    await expect(tabPanel(page, 'plan')).toBeVisible({ timeout: 20000 })
  })

  test('panel receives focus when the active phase changes', async ({ page }) => {
    await openTabbed(page)
    await tabRole(page, 'plan').click()
    await expect(page.locator('.tab-panels')).toBeFocused({ timeout: 20000 })
  })
})

/**
 * The legacy compatibility layer. Every pre-P2b surface id must still resolve —
 * in both URL shapes — or every existing bookmark and any link already sent to
 * someone breaks. This is the single most valuable thing to keep testing here.
 */
test.describe('Legacy deep links still resolve', () => {
  test.describe.configure({ mode: 'serial' })

  const CASES: { from: string; expect: RegExp; label: string }[] = [
    { from: 'forest-data/unified', expect: /surface=base(%2F|\/)unified/, label: 'the map' },
    // Sub-Areas and Compartments were removed: the Map now owns that work (D3).
    { from: 'forest-data/subareas', expect: /surface=base(%2F|\/)unified/, label: 'Sub-Areas -> Map' },
    { from: 'forest-data/compartments', expect: /surface=base(%2F|\/)unified/, label: 'Compartments -> Map' },
    { from: 'data-maps/maps', expect: /surface=base(%2F|\/)unified/, label: 'Maps -> Map' },
    // Total Inventory merged into Field Inventory's Results tab (D4).
    { from: 'data-maps/totalinventory', expect: /surface=field(%2F|\/)fieldinventory/, label: 'Total Inventory' },
    // The Reports metadata form became the Forest Metadata tab (D6).
    { from: 'reports-outputs/reports', expect: /surface=field(%2F|\/)fieldinventory/, label: 'Reports' },
    // Yearly Activities merged into the Operational Plan (D9).
    { from: 'reports-outputs/yearlyactivities', expect: /surface=plan(%2F|\/)yearly/, label: 'Yearly Activities' },
    { from: 'data-maps/hazarderosion', expect: /surface=analysis(%2F|\/)hazarderosion/, label: 'Hazard & Erosion' },
    { from: 'sampling-model/fieldbook', expect: /surface=field(%2F|\/)fieldbook/, label: 'Fieldbook' },
  ]

  for (const c of CASES) {
    test(`?surface=${c.from} resolves (${c.label})`, async ({ page }) => {
      await login(page)
      if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
      await page.goto(`/calculations/${cachedCalcId}/tabbed?surface=${c.from}`, {
        waitUntil: 'load',
        timeout: 60000,
      })
      await expect(page).toHaveURL(c.expect, { timeout: 20000 })
    })
  }

  test('the same id resolves through the legacy ?tab=&context= pair', async ({ page }) => {
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    const slash = 'data-maps/totalinventory'.indexOf('/')
    const tab = 'data-maps/totalinventory'.slice(0, slash)
    const ctx = 'data-maps/totalinventory'.slice(slash + 1)
    await page.goto(`/calculations/${cachedCalcId}/tabbed?tab=${tab}&context=${ctx}`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(page).toHaveURL(/surface=field(%2F|\/)fieldinventory/, { timeout: 20000 })
  })

  test('a legacy context id with no registry entry still renders the map', async ({ page }) => {
    // `block_naming` used to render a blank panel. It is on the passthrough
    // allowlist and now opens the map on the block-naming view.
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/workspace/${cachedCalcId}?context=block_naming`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(page).toHaveURL(/surface=base(%2F|\/)block_naming/, { timeout: 20000 })
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 20000 })
  })
})

/**
 * Every legacy calculation URL folds into the one shell.
 */
test.describe('Single Workspace — canonical shell + redirects', () => {
  test.describe.configure({ mode: 'serial' })

  test('/calculations/:id renders the workspace shell', async ({ page }) => {
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}`, { waitUntil: 'load', timeout: 60000 })
    await expect(tabRole(page, 'base')).toBeVisible({ timeout: 20000 })
  })

  test('/calculations/:id/tabbed canonicalises to ?surface=', async ({ page }) => {
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}/tabbed?tab=data-maps&context=mgmtplan`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(page).toHaveURL(/surface=plan(%2F|\/)mgmtplan$/, { timeout: 20000 })
    await expect(page).not.toHaveURL(/\/tabbed/)
  })

  test('/calculations/:id/operational-plan folds into plan > mgmtplan', async ({ page }) => {
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}/operational-plan`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(page).toHaveURL(/surface=plan(%2F|\/)mgmtplan/, { timeout: 20000 })
  })

  test('legacy /calculations/:id/workspace redirects to the canonical shell', async ({ page }) => {
    await login(page)
    if (!cachedCalcId) cachedCalcId = await resolveCalcId(page)
    await page.goto(`/calculations/${cachedCalcId}/workspace`, {
      waitUntil: 'load',
      timeout: 60000,
    })
    await expect(page).toHaveURL(/\/calculations\/[^/?]+\?surface=base(%2F|\/)unified/)
    await expect(page).not.toHaveURL(/\/tabbed/)
  })
})

/**
 * The collapsible rail and the Ctrl+K palette, which now lists 17 steps across
 * four phases.
 */
test.describe('Collapsible rail + Ctrl+K', () => {
  test.describe.configure({ mode: 'serial' })

  // The toggle is one control whose accessible name reflects the state it will
  // move to: "Collapse / expand section navigation" when expanded, "Show section
  // navigation" when compact. Locating it by a single name only works in one of
  // the two states, so match either here and assert the transition explicitly.
  const railToggle = (page: import('@playwright/test').Page) =>
    page
      .getByRole('button', { name: /Collapse \/ expand section navigation|Show section navigation/i })
      .first()

  test('collapsing the rail survives a reload', async ({ page }) => {
    await openTabbed(page)
    const collapse = railToggle(page)
    await expect(collapse).toBeVisible({ timeout: 20000 })
    // Drive to the compact state from wherever we start, then assert the label
    // reflects it. Clicking while already compact would expand instead.
    if ((await collapse.getAttribute('aria-label')) === 'Collapse / expand section navigation') {
      await collapse.click()
    }
    await expect(
      page.getByRole('button', { name: 'Show section navigation', exact: true }),
    ).toBeVisible()
    await page.reload({ waitUntil: 'load', timeout: 60000 })
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 20000 })
    // The compact rail keeps the toggle but drops the text labels.
    await expect(
      page.getByRole('button', { name: 'Analysis', exact: true }),
    ).toHaveCount(0)
    await expect(
      page.getByRole('button', { name: 'Show section navigation', exact: true }),
    ).toBeVisible()
  })

  test('Ctrl+K opens the palette and jumps to a step in another phase', async ({ page }) => {
    await openTabbed(page)
    await page.keyboard.press('Control+k')
    const search = page.getByPlaceholder('Jump to a section…')
    await expect(search).toBeVisible({ timeout: 10000 })
    await search.fill('biodiversity')
    await search.press('Enter')
    // biodiversity moved from data-maps to the `field` phase.
    await expect(page).toHaveURL(/surface=field(%2F|\/)biodiversity/, { timeout: 20000 })
  })
})
