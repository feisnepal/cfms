import { test, expect, type Page } from '@playwright/test'

/**
 * VR-7 — end-to-end cover for the vertex-edit rules.
 *
 * This is the layer that was missing.  Every user-visible failure in this
 * feature (zero handles rendered, the wrong partner vertex moving, a false
 * "overlaps an adjacent feature", a compartment resolved to the wrong parent)
 * passed the unit suite, because each unit test built both sides of a
 * comparison in one precision space against hand-made fakes of Leaflet-Geoman.
 * Only the real library on real geometry can catch that class of bug.
 *
 * ASSERTIONS GO THROUGH THE DOM, never through `window.__*`.  Stealth drivers
 * (patchright, and Playwright with certain launch options) evaluate in an
 * ISOLATED world: they share the `document` but see none of the page's window
 * globals.  Measured on this app — `document.documentElement.dataset.geoLog`
 * readable while `window.__geoDebug`, `window.__workspaceStoreInstances` and
 * `window.__vertexDebug` all read `undefined`.  That is why MapWorkspace
 * mirrors its diagnostic dump onto `dataset.vertexDump`, and why the DEV-hook
 * style used by `tabbed-detail.spec.ts` is not reused here.
 */

// The multi-block forest.  Two adjacent blocks tiling one boundary, so the
// shared edge is interior (editable) and the outer ring is shell (locked).
const MULTI_BLOCK = process.env.E2E_MULTI_BLOCK_CALC_ID || ''
const OWNER = { email: 'super@forest.com', password: 'Super1234' }

interface VertexDump {
  layer: string
  armedFeatures: number
  expectedEditableTotal: number
  renderedMarkerTotal: number
  allMatch: boolean
  features: Array<{
    id: string
    name: string | null
    verts: number
    shared: number
    shell: number
    editable: number | string
    markersTotal: number
    markersRendered: number
    match: boolean | null
  }>
}

async function login(page: Page): Promise<void> {
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', OWNER.email)
  await page.fill('input[name="password"]', OWNER.password)
  await page.click('button[type="submit"]')
  await page.waitForURL((u) => !u.pathname.includes('/login'), { timeout: 30000 })
}

async function openMap(page: Page, calcId: string): Promise<void> {
  await page.goto(`/calculations/${calcId}/map`, { waitUntil: 'load', timeout: 60000 })
  await expect(page.locator('.leaflet-container')).toBeVisible({ timeout: 30000 })
  // Wait for real geometry, not a fixed sleep: a slow app and a broken one look
  // identical otherwise.
  await page.waitForFunction(
    () => document.querySelectorAll('.leaflet-overlay-pane path').length > 1,
    { timeout: 30000 },
  )
}

async function activateLayer(page: Page, label: RegExp): Promise<void> {
  const item = page.getByTestId('layer-item').filter({ hasText: label }).first()
  await expect(item).toBeVisible({ timeout: 20000 })
  await item.locator('.layer-name-btn').click({ force: true })
  await page.waitForTimeout(1200)
}

function vertexButton(page: Page) {
  return page.locator('button.toolbar-btn').filter({
    has: page.locator('svg.lucide-spline'),
  })
}

async function armVertexTool(page: Page): Promise<void> {
  const btn = vertexButton(page)
  await expect(btn).toBeVisible({ timeout: 20000 })
  await btn.click()
  await page.waitForFunction(
    () => !!document.documentElement.dataset.vertexDump,
    { timeout: 25000 },
  )
}

async function readDump(page: Page): Promise<VertexDump> {
  return page.evaluate(() =>
    JSON.parse(document.documentElement.dataset.vertexDump || 'null'))
}

test.describe('Vertex editing — rules on real geometry (VR-7)', () => {
  test.skip(!MULTI_BLOCK, 'SKIPPED by default: needs a forest of two adjacent blocks tiling one boundary, owned by the super@forest.com account; set E2E_MULTI_BLOCK_CALC_ID to its id.')
  test.describe.configure({ mode: 'serial' })
  test.setTimeout(240000)

  test.beforeEach(async ({ page }) => {
    await login(page)
  })

  test('the tool renders exactly the editable vertices and no others', async ({ page }) => {
    await openMap(page, MULTI_BLOCK)
    await activateLayer(page, /Blocks|ब्लक/)
    await armVertexTool(page)

    const dump = await readDump(page)
    expect(dump.layer).toBe('blocks')
    expect(dump.armedFeatures).toBeGreaterThan(1)

    // The regression that shipped: the classifier said 85 vertices were
    // editable and the mask hid all 124 markers, so the tool looked dead.
    expect(dump.expectedEditableTotal).toBeGreaterThan(0)
    expect(dump.renderedMarkerTotal).toBe(dump.expectedEditableTotal)
    expect(dump.allMatch).toBe(true)

    for (const f of dump.features) {
      expect(f.markersRendered, `${f.name}: rendered != editable`).toBe(f.editable)
      expect(f.markersRendered, `${f.name}: more handles than vertices`)
        .toBeLessThanOrEqual(f.verts)
    }
  })

  test('no visible handle sits on a locked shell vertex', async ({ page }) => {
    // VR-4 mitigation.  The mask depends on Geoman internals that unit tests
    // can only fake; this is the live check that locked vertices really do not
    // reach the screen.
    await openMap(page, MULTI_BLOCK)
    await activateLayer(page, /Blocks|ब्लक/)
    await armVertexTool(page)

    const dump = await readDump(page)
    const shellTotal = dump.features.reduce((n, f) => n + f.shell, 0)
    expect(shellTotal, 'fixture must actually contain locked vertices')
      .toBeGreaterThan(0)

    // Every rendered corner marker must be an editable one.  Since
    // rendered == editable per feature and editable excludes shell by
    // construction, a mismatch here means a shell vertex reached the DOM.
    const visible = await page.locator(
      '.marker-icon:not(.marker-icon-middle):not(.pm-locked)',
    ).count()
    expect(visible).toBe(dump.expectedEditableTotal)

    const lockedButVisible = dump.features.filter(
      (f) => typeof f.editable === 'number' && f.markersRendered > f.editable,
    )
    expect(lockedButVisible).toEqual([])
  })

  test('dragging an editable vertex saves without a revert', async ({ page }) => {
    // This test MUTATES real geometry, so it snapshots the blocks first and
    // restores them through the API afterwards.  A drag of a few pixels is
    // metres on the ground; left unrestored, every CI run would walk the
    // user's forest a little further from where they drew it.
    await openMap(page, MULTI_BLOCK)

    // The exact key — a /token/i scan can land on `token_expiry` (a number),
    // which authenticates nothing and made the snapshot come back empty.
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(token, 'auth token must be readable to restore geometry').toBeTruthy()
    const auth = { Authorization: `Bearer ${String(token).replace(/^"|"$/g, '')}` }
    const blocksUrl = `/api/forests/calculations/${MULTI_BLOCK}/blocks`

    const snapResp = await page.request.get(blocksUrl, { headers: auth })
    expect(snapResp.status(), 'snapshot request must be authorised').toBe(200)
    const snapshot = await snapResp.json()
    const original: Array<{ id: string; geometry: unknown }> =
      (snapshot.blocks ?? []).map((b: any) => ({ id: b.id, geometry: b.geometry }))
    expect(original.length).toBeGreaterThan(1)

    try {
      await activateLayer(page, /Blocks|ब्लक/)
      await armVertexTool(page)

      const handle = page.locator(
        '.marker-icon:not(.marker-icon-middle):not(.pm-locked)',
      ).first()
      await expect(handle).toBeVisible({ timeout: 15000 })
      const box = await handle.boundingBox()
      expect(box).not.toBeNull()
      const cx = box!.x + box!.width / 2
      const cy = box!.y + box!.height / 2

      await page.mouse.move(cx, cy)
      await page.mouse.down()
      for (let i = 1; i <= 6; i++) {
        await page.mouse.move(cx + i * 2, cy + i * 2, { steps: 3 })
      }
      await page.mouse.up()

      // A verdict must appear.  The breadcrumbs separate a LOCAL pre-check
      // rejection from a server one, so a failure here says which side refused.
      await page.waitForFunction(() => {
        const log = document.documentElement.dataset.geoLog || ''
        return /vertex_commit_response|vertex_revert/.test(log)
      }, { timeout: 30000 })

      const log: string[] = await page.evaluate(() =>
        JSON.parse(document.documentElement.dataset.geoLog || '[]'))
      const verdict = log.filter((l) => /vertex_commit_response|vertex_revert/.test(l)).pop() || ''

      // The bug this guards: a handle the rules rendered as editable that the
      // topology check then refuses ("Edit rejected: overlaps an adjacent
      // feature" — every editable vertex used to fail this).
      expect(verdict, `gesture was reverted: ${verdict}`).not.toContain('vertex_revert')
      expect(verdict).toContain('status=200')
      // NOTE: `sharedMoves` is deliberately not asserted here.  Whether the
      // first handle in DOM order happens to be coincident-shared, mid-edge, or
      // needs no partner at all depends on which vertex the map paints first.
      // The propagation contract is pinned on real geometry instead, over ALL
      // editable vertices, in vertexSharedMove.realdata.test.ts.
    } finally {
      // Put the forest back exactly as it was, pass or fail — as ONE atomic
      // batch.  Restoring a tiled layer feature-by-feature is not safe: after
      // the first write the restored block and its still-dragged neighbour no
      // longer share their edge, and the server repairs that torn tiling by
      // reshaping one of them.  Measured: a sequential restore silently cost
      // blocks-1 0.39 ha (~45 m Hausdorff).  A batch write never exposes the
      // intermediate state.
      const [head, ...partners] = original
      await page.request.post(
        `/api/v1/calculations/${MULTI_BLOCK}/geometry/edit-geometry`,
        {
          headers: auth,
          data: {
            layer_type: 'blocks',
            feature_id: head.id,
            geometry: head.geometry,
            shared_moves: partners.map((b) => ({ feature_id: b.id, geometry: b.geometry })),
          },
        },
      )
      const after = await (await page.request.get(blocksUrl, { headers: auth })).json()
      for (const b of original) {
        const now = (after.blocks ?? []).find((x: any) => x.id === b.id)
        expect(JSON.stringify(now?.geometry), 'geometry must be restored')
          .toBe(JSON.stringify(b.geometry))
      }
    }
  })

  test('Rule A greys the tool out on a boundary locked by structure', async ({ page }) => {
    await openMap(page, MULTI_BLOCK)
    await activateLayer(page, /Forest Boundary|वन सीमा/)

    const btn = vertexButton(page)
    await expect(btn).toBeVisible({ timeout: 20000 })
    // Blocks exist on this forest, so the boundary is locked and the tool must
    // refuse BEFORE the click rather than arming onto an empty map.
    await expect(btn).toBeDisabled()
    await expect(btn).toHaveAttribute('title', /Locked|लक/)
  })

  test('the toolbar button reads as a vertex tool', async ({ page }) => {
    await openMap(page, MULTI_BLOCK)
    await activateLayer(page, /Blocks|ब्लक/)

    const btn = vertexButton(page)
    await expect(btn).toBeVisible({ timeout: 20000 })
    // Spline (nodes on a path), not SquarePen (edit-a-record pencil).
    await expect(btn.locator('svg.lucide-spline')).toHaveCount(1)
    await expect(btn.locator('svg.lucide-square-pen')).toHaveCount(0)
    // Tooltip states the rule for this layer, and appends the shortcut once.
    const title = await btn.getAttribute('title')
    expect(title).toBeTruthy()
    expect(title!.match(/\(V\)/g) || []).toHaveLength(1)
  })
})
