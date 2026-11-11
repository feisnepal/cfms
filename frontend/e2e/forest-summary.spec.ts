/**
 * forest-summary.spec.ts - live E2E for the floating Forest summary panel (FOREST_SUMMARY_PANEL_PLAN.md, FP-10).
 *
 * SKIPPED unless E2E_FOREST_SUMMARY_CALC_ID names a forest the signed-in user may open (owner, a same-organisation DFO or
 * a super admin). Sign in with E2E_EMAIL / E2E_PASSWORD (default demo@forest.com / Demo1234), or hand over a ready token
 * in E2E_ACCESS_TOKEN. Read-only on the forest: it never answers a decision (that is covered by the API tests); the only
 * thing it writes is the panel's own saved position, which it puts back.
 *
 *   cd frontend && E2E_FOREST_SUMMARY_CALC_ID=<id> npx playwright test e2e/forest-summary.spec.ts --reporter=line
 */
import { test, expect, type Page } from '@playwright/test'

const CALC_ID = process.env.E2E_FOREST_SUMMARY_CALC_ID || ''
const TOKEN = process.env.E2E_ACCESS_TOKEN || ''

async function signIn(page: Page) {
  if (TOKEN) {
    await page.addInitScript((t) => window.localStorage.setItem('access_token', t), TOKEN)
    return
  }
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', process.env.E2E_EMAIL || 'demo@forest.com')
  await page.fill('input[name="password"]', process.env.E2E_PASSWORD || 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('Forest summary panel', () => {
  test.skip(!CALC_ID, 'set E2E_FOREST_SUMMARY_CALC_ID to a forest the user may open')
  test.describe.configure({ mode: 'serial' })

  let page: Page
  const panel = () => page.getByTestId('forest-summary-panel')
  const box = async () => (await panel().boundingBox())!

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(180000)
    page = await (await browser.newContext({ storageState: undefined })).newPage()
    await signIn(page)
    await page.goto(`/workspace/${CALC_ID}`, { waitUntil: 'load', timeout: 60000 })
    await expect(page.getByTestId('workspace-container')).toBeVisible({ timeout: 30000 })
  })
  test.afterAll(async () => page.context().close())

  test('opens by default with the summary, or says what is missing', async () => {
    await expect(panel()).toBeVisible({ timeout: 30000 })
    await expect(page.getByTestId('forest-summary')).toBeVisible({ timeout: 60000 }) // prepares itself once if needed
    await expect(page.getByTestId('tile-area')).toBeVisible()
    await expect(page.getByTestId('forest-summary-basis')).toContainText(/Basis|आधार/)
  })

  test('is a floating panel above the map and moves when its header is dragged', async () => {
    const before = await box()
    const header = page.getByTestId('forest-summary-panel-header')
    const h = (await header.boundingBox())!
    await page.mouse.move(h.x + 120, h.y + 12)
    await page.mouse.down()
    await page.mouse.move(h.x + 120 + 90, h.y + 12 + 50, { steps: 8 })
    await page.mouse.up()
    const after = await box()
    expect(Math.round(after.x - before.x)).toBeGreaterThanOrEqual(85)
    expect(Math.round(after.y - before.y)).toBeGreaterThanOrEqual(45)
    // it stays on top of the map: the element at its centre is inside the panel
    const onTop = await page.evaluate(
      ({ x, y }) => !!document.elementFromPoint(x, y)?.closest('[data-testid="forest-summary-panel"]'),
      { x: after.x + after.width / 2, y: after.y + 60 },
    )
    expect(onTop).toBe(true)
  })

  test('keeps its place after a reload (saved per user and forest)', async () => {
    const moved = await box()
    await page.waitForTimeout(1500) // the save is debounced
    await page.reload({ waitUntil: 'load' })
    await expect(panel()).toBeVisible({ timeout: 30000 })
    await page.waitForTimeout(1500)
    const again = await box()
    expect(Math.abs(again.x - moved.x)).toBeLessThan(3)
    expect(Math.abs(again.y - moved.y)).toBeLessThan(3)
  })

  test('collapses to its header and expands again', async () => {
    await page.getByRole('button', { name: /Collapse|संकुचित/ }).click()
    await expect(page.getByTestId('forest-summary')).toHaveCount(0)
    await expect(panel()).toBeVisible()
    await page.getByRole('button', { name: /Expand|फैलाउनुहोस्/ }).click()
    await expect(page.getByTestId('forest-summary')).toBeVisible()
  })

  test('the Forest / User group choice reaches the server', async () => {
    const asked = page.waitForRequest((r) => /forest-summary\?/.test(r.url()) && /area=user_group/.test(r.url()))
    await page.getByRole('button', { name: /^User group$|^उपभोक्ता समूह$/ }).click()
    await asked
    await page.getByRole('button', { name: /^Forest$|^वन$/ }).click()
  })

  test('the Decisions needed tab lists the questions and who may answer', async () => {
    await page.getByRole('tab', { name: /Decisions needed|निर्णय आवश्यक/ }).click()
    await expect(page.getByTestId('decisions-tab')).toBeVisible()
    await expect(page.getByTestId('decision-landslide_method:')).toBeVisible()
    await expect(page.getByTestId('decisions-footer')).toBeVisible()
    await page.getByRole('tab', { name: /^Summary|^सारांश/ }).click()
  })

  test('the text export downloads as a .txt file', async () => {
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 30000 }),
      page.getByRole('button', { name: /Download \.txt|\.txt डाउनलोड/ }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/_ForestSummary_Report_\d{8}\.txt$/)
  })

  test('closing hides the panel and the layer-panel button brings it back', async () => {
    await page.getByRole('button', { name: /^Close$|^बन्द गर्नुहोस्$/ }).click()
    await expect(panel()).toHaveCount(0)
    await page.getByTestId('open-forest-summary').click()
    await expect(panel()).toBeVisible()
    // put the panel back where a fresh visit would find it
    const header = page.getByTestId('forest-summary-panel-header')
    const h = (await header.boundingBox())!
    const parent = (await page.locator('.workspace-map-area').boundingBox())!
    await page.mouse.move(h.x + 120, h.y + 12)
    await page.mouse.down()
    await page.mouse.move(parent.x + 16 + 120, parent.y + 16 + 12, { steps: 8 })
    await page.mouse.up()
    await page.waitForTimeout(1500)
  })
})
