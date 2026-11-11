/**
 * op-chapter-link.spec.ts - the "write it in the Operational Plan" link of a hand-written report section opens the plan on THAT chapter,
 * even when the report's section title is longer than the plan's chapter title ("व्यवस्थापन कार्ययोजनाको पुनरावलोकन, अनुगमन, मूल्याङ्कन" in the
 * report, "पुनरावलोकन, अनुगमन, मूल्याङ्कन" in the plan).
 *
 * SKIPPED unless E2E_CALC_ID names a forest the demo user owns (backend/scripts/seed_e2e_forests.py). It makes a plan for the forest when
 * there is none and removes it again.
 */
import { test, expect } from '@playwright/test'

const CALC_ID = process.env.E2E_CALC_ID || ''
const API = 'http://localhost:8001'

const SECTIONS: Array<{ title: string; chapter: RegExp }> = [
  { title: 'व्यवस्थापन कार्ययोजनाको पुनरावलोकन, अनुगमन, मूल्याङ्कन', chapter: /Monitoring and Evaluation|पुनरावलोकन, अनुगमन, मूल्याङ्कन/ },
  { title: 'वन पैदावारमा आधारित आय-आर्जन, सिप विकास, उद्योग तथा पर्यापर्यटन सम्बन्धी व्यवस्था', chapter: /Income|आय-आर्जन/ },
  { title: 'विगतका वन व्यवस्थापन कार्ययोजनाको समीक्षा', chapter: /Previous Plan Review|विगतका वन व्यवस्थापन कार्ययोजनाको समीक्षा/ },
]

test.describe('Operational Plan chapter link', () => {
  test.skip(!CALC_ID, 'set E2E_CALC_ID to a forest the demo user owns')
  test.describe.configure({ mode: 'serial' })

  let planId: string | null = null
  let headers: Record<string, string> = {}

  test.beforeAll(async ({ browser }) => {
    test.setTimeout(120000)
    const page = await browser.newPage()
    await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
    await page.fill('input[name="email"]', 'demo@forest.com')
    await page.fill('input[name="password"]', 'Demo1234')
    await page.click('button[type="submit"]')
    await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    const have = await page.request.get(`${API}/api/operational-plans/calculation/${CALC_ID}`, { headers })
    if (have.status() === 404) {
      const made = await page.request.post(`${API}/api/operational-plans?plan_regime=brief_fmp&plan_stage=new`, {
        headers,
        data: { calculation_id: CALC_ID, forest_name: 'E2E' },
      })
      expect(made.ok()).toBeTruthy()
      planId = (await made.json()).id
    }
    await page.close()
  })

  test.afterAll(async ({ request }) => {
    if (planId) await request.delete(`${API}/api/operational-plans/${planId}`, { headers })
  })

  for (const s of SECTIONS) {
    test(`"${s.title.slice(0, 40)}…" opens its own chapter, not just the page`, async ({ page }) => {
      test.setTimeout(120000)
      await page.goto('/login', { waitUntil: 'networkidle', timeout: 60000 })
      await page.fill('input[name="email"]', 'demo@forest.com')
      await page.fill('input[name="password"]', 'Demo1234')
      await page.click('button[type="submit"]')
      await page.waitForURL(/\/my-uploads/, { timeout: 30000 })
      await page.goto(`/calculations/${CALC_ID}?surface=plan%2Fmgmtplan&node=${encodeURIComponent(s.title)}`, { waitUntil: 'load', timeout: 60000 })
      // the open chapter's heading is the one with a section number above it
      await expect(page.locator('h2').filter({ hasText: s.chapter }).first()).toBeVisible({ timeout: 60000 })
    })
  }
})
