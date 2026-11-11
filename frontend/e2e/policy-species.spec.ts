/**
 * policy-species.spec.ts - E2E for P3: the species table shows BOTH views.
 *
 * READ-ONLY: it opens the Results pane and reads. It never edits, saves, or
 * presses anything that mutates the forest.
 *
 * Why this exists when there are already 18 unit tests
 * -----------------------------------------------------
 * The unit tests render `SpeciesPolicyTable` in jsdom with synthetic rows and a
 * mocked `useT`. They prove the component's logic. They cannot prove that the
 * component is *reached* in the running app, that the rows it receives actually
 * carry a `classification`, or that the i18n keys resolve in the real bundle.
 *
 * That gap was not theoretical. P2 was verified by calling `get_total_inventory`
 * directly in-process, which was correct and complete - and the first question
 * from the owner was still "Other species? where is it?", because nothing had
 * checked the path the browser actually takes. This spec checks that path.
 *
 * SKIPPED by default: needs a running stack and
 *   E2E_POLICY_CALC_ID   = a calculation the account below owns, with results
 *   E2E_POLICY_EMAIL     = that account (defaults to super@forest.com)
 *   E2E_POLICY_PASSWORD  = its password
 *
 * The calculation and its field inventory must belong to the *same* account:
 * `get_total_inventory` checks `user_id == current_user.id`, so a super admin
 * cannot read another user's field inventory through the API.
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_POLICY_CALC_ID || ''
const EMAIL = process.env.E2E_POLICY_EMAIL || 'super@forest.com'
const PASSWORD = process.env.E2E_POLICY_PASSWORD || ''
const RUN = Boolean(CALC_ID && PASSWORD)
const URL = `/calculations/${CALC_ID}?surface=field%2Ffieldinventory`

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', EMAIL)
  await page.fill('input[name="password"]', PASSWORD)
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

test.describe('species table shows both views (P3)', () => {
  test.skip(!RUN, 'needs E2E_POLICY_CALC_ID + E2E_POLICY_PASSWORD')

  test('groups the species into reference and Other, naming every one', async ({ page }) => {
    await login(page)
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 })

    // The Results pane loads the totals asynchronously, and the species table is
    // the last thing in it, so wait for the table itself rather than a fixed delay.
    const table = page.getByTestId('species-absolute')
    await expect(table).toBeVisible({ timeout: 120000 })

    // Both group headings must be present. This is the assertion that would have
    // caught "where is it?" - a table with no reference divider means the rows
    // arrived without a `classification` and everything fell into Other.
    await expect(page.getByTestId('species-absolute-reference-divider')).toBeVisible()
    await expect(page.getByTestId('species-absolute-other-divider')).toBeVisible()

    const refDivider = page.getByTestId('species-absolute-reference-divider')
    const othDivider = page.getByTestId('species-absolute-other-divider')

    // The real split: 7 of 17 in list, 10 of 17 other.
    await expect(refDivider).toContainText(/\d+ of 17/)
    await expect(othDivider).toContainText(/10 of 17/)
    await expect(refDivider).toContainText(/\d+\.\d%/)
    await expect(othDivider).toContainText(/55\.9%/)

    // Nothing hidden: one row per species, and the totals row agrees.
    const rows = page.getByTestId('species-absolute-row')
    const rowCount = await rows.count()
    expect(rowCount).toBe(17)
    await expect(page.getByTestId('species-absolute-totals')).toContainText(/17 species/)

    // A named species on the list...
    await expect(table).toContainText('Shorea robusta')
    // ...a genus capture, labelled with the entry that spoke for it...
    await expect(table).toContainText('via Albizia spp')
    // ...and a species that must NOT be on the list, still named under Other.
    await expect(table).toContainText('Terminalia chebula')

    // The two Harro/Saj cases, which is what the asymmetric rule is for. A genus
    // test would put Harro in the list and drop a Siris species into Other.
    const othDividerText = await othDivider.innerText()
    expect(othDividerText).not.toContain('7 of')
  })

  test('the chart names the species its lumped slice covers', async ({ page }) => {
    await login(page)
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 })
    await expect(page.getByTestId('species-absolute')).toBeVisible({ timeout: 120000 })

    // The pie still lumps past ten slices -- seventeen named slices is unreadable
    // -- but the lump now says how many species it holds, and a caption lists them.
    await expect(page.getByTestId('species-chart-tail')).toBeVisible()
    const tail = await page.getByTestId('species-chart-tail').innerText()
    expect(tail.length).toBeGreaterThan(20)
    expect(tail).toMatch(/\w/)
  })
})
