/**
 * sustainable-fm.spec.ts — E2E for the "Sustainable Forest Management" context
 * in the calc shell (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4 / P9 / P10 / P11).
 *
 * SKIPPED by default: needs a running backend (port 8001) + a seeded
 * calculation with ≥ 2 forest blocks / compartments. Set E2E_SFM_CALC_ID.
 * Verified 2026-09-11 against छिमेकी (0c0bff72-ff00-419f-8826-4e456c67da13):
 * 4 compartments, slope-class bands 1–2, demo@forest.com owns it.
 *
 * Notes for anyone re-running this:
 *  - the map panel keeps fetching preview blobs, so `networkidle` never settles
 *    — every nav waits on a content selector instead;
 *  - the tab renders three antd tables (Felling series / Blocks / Sampling
 *    plan), so row locators are scoped to the "Blocks" table by its title;
 *  - a block-override PATCH and a params save each force a full
 *    `build_sfm(force=True)` rebuild. Until SFM P14 this took ~60–120 s even
 *    on a 4-compartment forest (a `river.river84::geography` cast defeated its
 *    GiST index, forcing a 24.8k-row sequential scan per unit); P14 rewrote
 *    that query to buffer the query geometry once and intersect natively, so
 *    the rebuild is now sub-second and these round-trips are gated live;
 *  - antd v6 Select options don't reliably fire `onChange` on a Playwright
 *    click — the override test drives the row's `<Select>` by keyboard.
 *
 * Live coverage:
 *   1. the tab loads — block table + felling-series strip + summary bar + the
 *      params panel all render;
 *   2. changing a block's type override persists across a reload;
 *   3. (P9) accepting a working-circle proposal drops the allowable harvest
 *      (self-skips when the forest has no proposal);
 *   4. (P10) the params panel round-trips a "crown-density estimate source"
 *      override — Save → reload → provenance chip reads "forest";
 *   5. (P11) the slope-class helper lists the bands and "Generate draft"
 *      produces an editable protected-sub-area draft + the §23.2 checklist
 *      hint + a copy-GeoJSON button (falls back to a gentler class, then
 *      self-skips, when nothing is steep enough).
 */
import { test, expect, Locator, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_SFM_CALC_ID || ''
const RUN = Boolean(CALC_ID)
const SFM_URL = `/calculations/${CALC_ID}?tab=data-maps&context=sustainablefm`

async function login(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

/** The "Blocks" antd table (one of three on the tab). */
function blockTable(page: Page): Locator {
  return page
    .locator('.ant-table')
    .filter({ has: page.locator('.ant-table-title', { hasText: 'Blocks' }) })
}

async function goToSfm(page: Page) {
  await page.goto(SFM_URL, { waitUntil: 'domcontentloaded' })
  await expect(
    page.locator('h3', { hasText: 'Sustainable Forest Management' }),
  ).toBeVisible({ timeout: 60000 })
  await expect(blockTable(page).locator('.ant-table-row').first()).toBeVisible({
    timeout: 30000,
  })
}

test.describe('Sustainable Forest Management tab', () => {
  test.skip(!RUN, 'set E2E_SFM_CALC_ID to a calc with forest blocks')
  test.describe.configure({ timeout: 120000 })

  test('the tab loads with its tables, summary bar and params panel', async ({
    page,
  }) => {
    await login(page)
    await goToSfm(page)

    // three antd tables + the summary bar + the felling-series strip
    await expect(blockTable(page).locator('.ant-table-row')).not.toHaveCount(0)
    await expect(
      page.locator('.ant-table-title', { hasText: 'Felling series' }),
    ).toBeVisible()
    await expect(
      page.getByText('Allowable annual harvest (production regulation)'),
    ).toBeVisible()

    // the per-forest params panel expands and shows the P10 estimate selector
    await page.getByText('SFM parameters', { exact: true }).click()
    await expect(page.getByText('Crown-density estimate source')).toBeVisible({
      timeout: 10000,
    })
  })

  // ── P4 — block type override round-trip ─────────────────────────────────
  test('changing a block type override persists a reload', async ({ page }) => {
    await login(page)
    await goToSfm(page)
    const firstRow = () => blockTable(page).locator('.ant-table-row').first()
    // this antd build renders the chosen label as the text of
    // `.ant-select-content` (class `…-has-value`), not a child
    // `.ant-select-selection-item` span
    const selItem = () =>
      firstRow().locator('.ant-select-content.ant-select-content-has-value')

    // antd v6 options don't reliably fire onChange on a Playwright click —
    // drive the row's <Select> by keyboard. A beat after opening lets the
    // dropdown actually mount before ArrowDown, or the keypress is dropped.
    const select = firstRow().getByRole('combobox')
    await select.focus()
    await select.press('Enter')
    await page.waitForTimeout(300)
    await select.press('ArrowDown')
    await page.waitForTimeout(300)
    await select.press('Enter')

    await expect(selItem()).toHaveText(/Type \d+/, { timeout: 30000 })
    const chosen = ((await selItem().innerText()).match(/Type \d+/) || [''])[0]
    await goToSfm(page)
    await expect(selItem()).toHaveText(new RegExp(chosen), { timeout: 20000 })

    // cleanup — clear the override so re-runs start from the same state
    await firstRow().locator('.ant-select').first().hover()
    await firstRow().locator('.ant-select-clear').click({ force: true })
    await expect(selItem()).toHaveCount(0, { timeout: 30000 })
  })

  test('accepting a working-circle proposal drops the allowable harvest', async ({
    page,
  }) => {
    await login(page)
    await goToSfm(page)

    const accept = page.getByRole('button', { name: /^Accept$|स्वीकार/ }).first()
    test.skip(
      (await accept.count()) === 0,
      'no working-circle proposal on this forest',
    )

    const readHarvest = async () => {
      const txt = await page
        .getByText(/Allowable annual harvest|उत्पादन नियमन अनुसारको/i)
        .locator('xpath=../div[2]')
        .innerText()
      return parseFloat(txt.replace(/[^\d.]/g, '')) || 0
    }
    const before = await readHarvest()
    await accept.click()
    await goToSfm(page)

    expect(await readHarvest()).toBeLessThan(before)
    await expect(
      page.locator('.ant-tag-green', { hasText: '✓' }).first(),
    ).toBeVisible()
  })

  // ── P10 — per-forest params panel round-trip ────────────────────────────
  test('crown-density estimate source override saves, persists, and clears', async ({
    page,
  }) => {
    await login(page)
    await goToSfm(page)

    const sourceLabel = page.getByText('Crown-density estimate source')
    const provTag = page.getByText(/crown_density_estimate_source:\s*forest/)
    const save = page.getByRole('button', { name: /^Save$/ })

    // idempotent expand (clicking an open Collapse would close it)
    const openPanel = async () => {
      if (!(await sourceLabel.isVisible())) {
        await page.getByText('SFM parameters', { exact: true }).click()
      }
      await expect(sourceLabel).toBeVisible({ timeout: 10000 })
    }

    await openPanel()
    await sourceLabel
      .locator('xpath=ancestor::div[1]')
      .getByRole('combobox')
      .click()
    await page.getByText('canopy raster', { exact: true }).click()
    await expect(save).toBeEnabled()
    await save.click()
    await expect(page.getByText(/Parameters updated|अद्यावधिक/i)).toBeVisible({
      timeout: 20000,
    })

    // reload — the override now reports provenance "forest"
    await goToSfm(page)
    await expect(provTag).toBeVisible({ timeout: 20000 })

    // clean up — the panel's own field state (`patch`) is session-local and
    // resets to empty on reload, so a per-field "Clear this override" never
    // reappears for a value saved in an earlier session; "Reset to default"
    // is the panel's actual undo for a persisted override.
    await openPanel()
    const reset = page.getByRole('button', { name: /^Reset to default$/ })
    await expect(reset).toBeEnabled()
    await reset.click()
    await expect(page.getByText(/Parameters updated|अद्यावधिक/i)).toBeVisible({
      timeout: 20000,
    })
    await expect(provTag).toHaveCount(0, { timeout: 20000 })
  })

  // ── P11 — slope-class helper + assisted protection digitizing ───────────
  test('slope-class helper lists the bands and drafts a protection sub-area', async ({
    page,
  }) => {
    await login(page)
    await goToSfm(page)

    await expect(page.getByText('Slope-class digitizing aid')).toBeVisible({
      timeout: 20000,
    })

    if (
      (await page.getByText(/No slope raster covers this forest/i).count()) > 0
    ) {
      test.skip(true, 'slope_regulation does not cover this forest')
      return
    }

    // the slope-class vectorise runs ST_DumpAsPolygons over the whole forest
    const generate = page.getByRole('button', { name: /Generate draft/i })
    await expect(generate).toBeVisible({ timeout: 60000 })
    await expect(
      page.getByText(/(< 19°|19–31°|31–45°|> 45°)/).first(),
    ).toBeVisible()

    const draftAppeared = () =>
      page.getByText(/check the .?23\.2 exclusions before saving/i)
    const nothingSteep = () => page.getByText(/No slope band that steep/i)
    const bandSelect = page
      .getByText('Draft a protected sub-area from slope class')
      .locator(
        'xpath=ancestor::*[contains(@class,"ant-space-item")]/following-sibling::*[1]',
      )
      .getByRole('combobox')

    // try the default class (≥ 31°); if nothing is that steep, drop to ≥ 19–31°
    await generate.click()
    await expect
      .poll(async () =>
        (await draftAppeared().count()) + (await nothingSteep().count()) > 0
          ? 'settled'
          : 'pending',
      )
      .toBe('settled')

    if ((await nothingSteep().count()) > 0) {
      await bandSelect.click()
      await page.getByText('≥ 19–31°', { exact: true }).click()
      await generate.click()
      await expect
        .poll(async () =>
          (await draftAppeared().count()) + (await nothingSteep().count()) > 0
            ? 'settled'
            : 'pending',
        )
        .toBe('settled')
    }

    if ((await draftAppeared().count()) > 0) {
      await expect(draftAppeared()).toBeVisible()
      await expect(page.getByText('Dominant slope')).toBeVisible()
      await expect(
        page.getByRole('button', { name: /Copy polygon GeoJSON/i }),
      ).toBeVisible()
    } else {
      await expect(nothingSteep()).toBeVisible()
    }
  })
})
