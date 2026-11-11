/**
 * hazard-erosion.spec.ts — E2E for the dedicated "Hazard & Erosion" context in
 * the calculation shell (HAZARD_EROSION_CONTEXT_PLAN.md P6).
 *
 * SKIPPED by default: needs a running backend (port 8001) + a seeded
 * calculation. Set E2E_HAZARD_EROSION_CALC_ID to that calculation's id to
 * enable. Works with any forest — the panels degrade to their empty states when
 * the RUSLE / LSI / household layers are not computed yet.
 *
 * Flow under test (data-maps → hazarderosion context):
 *   1. the context renders the header (forest name + physiography zone) and the
 *      five prereq pills;
 *   2. either the "nothing to analyse yet" result OR the map / params / tables /
 *      narration panels are shown;
 *   3. the narration language toggle switches ने ↔ EN and the "Insert into the
 *      Operational Plan" button is present.
 */
import { test, expect, Page } from '@playwright/test'

const CALC_ID = process.env.E2E_HAZARD_EROSION_CALC_ID || ''
const RUN = Boolean(CALC_ID)

async function login(page: Page) {
  test.setTimeout(180000)
  await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
  await page.fill('input[name="email"]', 'demo@forest.com')
  await page.fill('input[name="password"]', 'Demo1234')
  await page.click('button[type="submit"]')
  await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
}

async function openContext(page: Page) {
  await page.goto(
    `/calculations/${CALC_ID}?tab=data-maps&context=hazarderosion`,
    { waitUntil: 'networkidle' },
  )
}

test.describe('Hazard & Erosion context', () => {
  test.skip(!RUN, 'set E2E_HAZARD_EROSION_CALC_ID to a seeded calculation id')

  test('renders the header, prereq pills and either the empty state or the panels', async ({
    page,
  }) => {
    await login(page)
    await openContext(page)

    // header + the five prereq pills (labels are i18n; match on the tag text)
    await expect(
      page.getByText(/Hazard & Erosion|प्रकोप र क्षय/).first(),
    ).toBeVisible()
    for (const label of [/DEM|रास्टर/, /Soil|माटो/, /Geology|भूगर्भ/, /Household|घरधुरी/, /User group|उपभोक्ता/]) {
      await expect(page.getByText(label).first()).toBeVisible()
    }

    const emptyState = page.getByText(/Nothing to analyse yet|अझै विश्लेषण/)
    const mapPanel = page.getByText(/Data tables|तथ्यांक तालिका|Interpretation|व्याख्या/)
    await expect(emptyState.or(mapPanel).first()).toBeVisible({ timeout: 20000 })
  })

  test('the narration toggle and OP-insert button are present when data exists', async ({
    page,
  }) => {
    await login(page)
    await openContext(page)

    const heading = page.getByText(/Interpretation|व्याख्या/)
    // only assert the rest when the narration section actually rendered
    if (await heading.isVisible().catch(() => false)) {
      await page.getByRole('radio', { name: /नेपाली/ }).click()
      await page.getByRole('radio', { name: /^EN$/ }).click()
      await expect(
        page.getByRole('button', {
          name: /Insert .* Operational Plan|कार्ययोजनामा .* थप्नुहोस्/,
        }),
      ).toBeVisible()
    }
  })
})
