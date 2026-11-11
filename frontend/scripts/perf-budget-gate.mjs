// scripts/perf-budget-gate.mjs
// Phase 10 — Performance Budget CI gate. Runs Lighthouse against the app's
// real routes (list + tabbed detail, default + reports tab), compares the
// worst-case metrics to a checked-in `.lighthouse-baseline.json`, and fails
// on >= regressionThreshold or > absoluteMax.
//
// Node ESM, zero new dependencies: Lighthouse is invoked on demand via `npx`
// (the repo does not ship `@lhci/cli`, `tsx`, or `lighthouse` as a dependency),
// consistent with Phase 9's `check-bundle-budget.mjs`.
//
// Usage:
//   npm run perf:collect                 # run Lighthouse on all routes -> lighthouse-reports/
//   npm run perf:baseline                # collect + write .lighthouse-baseline.json
//   npm run perf:check                   # collect + compare vs baseline (exit 1 on regression)
//   npm run perf:validate                # validate config + baseline shape (no Lighthouse; runs in normal CI)
//
// Env:
//   LIGHTHOUSE_BASE_URL  default http://localhost:4173  (where the app is served)
//   LIGHTHOUSE_CALC_ID   demo calc id; defaults to the shared e2e demo calc
import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import {
  PERF_BUDGETS,
  LIGHTHOUSE_PATHS,
  PERFORMANCE_TARGET,
} from './perf-budget.config.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(__dirname, '..')
const BASELINE_FILE = path.join(REPO_ROOT, '.lighthouse-baseline.json')
const REPORT_DIR = path.join(REPO_ROOT, 'lighthouse-reports')

const BASE_URL = (process.env.LIGHTHOUSE_BASE_URL || 'http://localhost:4173').replace(/\/$/, '')
const CALC_ID = process.env.LIGHTHOUSE_CALC_ID || '15f64467-c857-4948-bb42-34eefadb88bc'
const CHROME_FLAGS = '--headless --no-sandbox'

const args = process.argv.slice(2)
const isValidate = args.includes('--validate')
const isSaveBaseline = args.includes('--save-baseline')
const performCollect = args.includes('--collect') || !isValidate
const isCheck = args.includes('--check') || (!args.includes('--collect') && !isValidate)

/** Build the ordered list of fully-qualified Lighthouse URLs. */
function resolveUrls() {
  return LIGHTHOUSE_PATHS.map((p) => `${BASE_URL}${p.replace('{calcId}', CALC_ID)}`)
}

/** slug for a URL -> a stable report filename. */
function slugForUrl(url) {
  const parsed = new URL(url)
  const pathPart = parsed.pathname.replace(/\//g, '_').replace(/^_/, '')
  const tab = parsed.searchParams.get('tab')
  return tab ? `${pathPart}__tab_${tab}` : pathPart
}

/** Extract the metrics we gate on from a Lighthouse JSON report. */
function extractMetrics(report) {
  const audits = report.audits || {}
  return {
    'largest-contentful-paint': audits['largest-contentful-paint']?.numericValue ?? 0,
    'first-contentful-paint': audits['first-contentful-paint']?.numericValue ?? 0,
    'total-blocking-time': audits['total-blocking-time']?.numericValue ?? 0,
    'cumulative-layout-shift': audits['cumulative-layout-shift']?.numericValue ?? 0,
    'speed-index': audits['speed-index']?.numericValue ?? 0,
    interactive: audits['interactive']?.numericValue ?? 0,
    'performance-score': Math.round((report.categories?.performance?.score ?? 0) * 100),
  }
}

function formatValue(metric, value) {
  if (metric === 'cumulative-layout-shift') return value.toFixed(3)
  if (value < 1000) return `${Math.round(value)}ms`
  return `${(value / 1000).toFixed(2)}s`
}

function formatPercent(decimal) {
  return `${(decimal * 100).toFixed(1)}%`
}

/** Run Lighthouse on a single URL (npx --yes auto-installs on demand). */
function runLighthouse(url, outPath) {
  fs.mkdirSync(path.dirname(outPath), { recursive: true })
  const cmd =
    `npx --yes lighthouse "${url}" --output=json --output-path="${outPath}" ` +
    `--chrome-flags="${CHROME_FLAGS}" --preset=desktop --only-categories=performance,accessibility`
  try {
    execSync(cmd, { stdio: 'inherit', timeout: 180000 })
  } catch (e) {
    throw new Error(
      `Lighthouse failed for ${url}. Is Chrome installed? (sudo apt install chromium; or set CHROME_PATH)\n${e.message}`,
    )
  }
  return JSON.parse(fs.readFileSync(outPath, 'utf8'))
}

/** Run Lighthouse across all routes and return a map of slug -> metrics. */
function collect() {
  const results = {}
  for (const url of resolveUrls()) {
    const slug = slugForUrl(url)
    const outPath = path.join(REPORT_DIR, `${slug}.json`)
    console.log(`\nRunning Lighthouse: ${url} -> ${path.relative(REPO_ROOT, outPath)}`)
    const report = runLighthouse(url, outPath)
    results[slug] = { url, metrics: extractMetrics(report) }
  }
  return results
}

/** Worst-case (max) value across routes for every gated metric. */
function worstCase(results) {
  const worst = {}
  for (const { metrics } of Object.values(results)) {
    for (const [k, v] of Object.entries(metrics)) {
      worst[k] = Math.max(worst[k] ?? 0, v)
    }
  }
  return worst
}

/**
 * Persist a machine-readable summary (per-route + worst-case) so CI can post
 * a PR comment from `scripts/post-perf-comment.mjs`.
 */
function writeSummary(results, worst) {
  fs.mkdirSync(REPORT_DIR, { recursive: true })
  fs.writeFileSync(
    path.join(REPORT_DIR, 'summary.json'),
    JSON.stringify({ generatedAt: new Date().toISOString(), routes: results, worst }, null, 2),
  )
  console.log(`\nSummary written to ${path.relative(REPO_ROOT, path.join(REPORT_DIR, 'summary.json'))}`)
}

function checkBudgets(current, baseline) {
  const violations = []
  const improvements = []

  for (const budget of PERF_BUDGETS) {
    const curr = current[budget.metric]
    const base = baseline?.[budget.metric]

    if (curr === undefined) {
      violations.push(`Missing metric: ${budget.metric}`)
      continue
    }
    if (curr > budget.absoluteMax) {
      violations.push(
        `${budget.label}: ${formatValue(budget.metric, curr)} exceeds absolute max of ` +
          `${formatValue(budget.metric, budget.absoluteMax)}`,
      )
      continue
    }
    if (base !== undefined && base > 0) {
      const regression = (curr - base) / base
      if (regression > budget.regressionThreshold) {
        violations.push(
          `${budget.label}: ${formatValue(budget.metric, curr)} is ` +
            `${formatPercent(regression)} above baseline ${formatValue(budget.metric, base)} ` +
            `(limit ${formatPercent(budget.regressionThreshold)})`,
        )
      } else if (regression < -0.05) {
        improvements.push(
          `${budget.label}: ${formatValue(budget.metric, curr)} is ` +
            `${formatPercent(-regression)} faster than baseline`,
        )
      }
    }
  }

  if (baseline === null && current['performance-score'] < PERFORMANCE_TARGET * 100) {
    violations.push(
      `Performance score ${current['performance-score']} is below target ` +
        `${Math.round(PERFORMANCE_TARGET * 100)} (no baseline yet — run \`npm run perf:baseline\`)`,
    )
  }

  return { passed: violations.length === 0, violations, improvements }
}

function validate() {
  const problems = []
  const known = new Set([...PERF_BUDGETS.map((b) => b.metric), 'performance-score'])

  if (!fs.existsSync(BASELINE_FILE)) {
    problems.push(`Missing baseline: ${BASELINE_FILE} — run \`npm run perf:baseline\` against a healthy environment.`)
  } else {
    let raw
    try {
      raw = JSON.parse(fs.readFileSync(BASELINE_FILE, 'utf8'))
    } catch {
      problems.push(`Baseline ${BASELINE_FILE} is not valid JSON.`)
      raw = null
    }
    if (raw && raw.metrics) {
      for (const key of Object.keys(raw.metrics)) {
        if (!known.has(key)) problems.push(`Baseline has unknown metric: ${key}`)
      }
    }
  }

  if (LIGHTHOUSE_PATHS.length < 3) {
    problems.push('LIGHTHOUSE_PATHS should include the list + detail (workspace + reports) pages.')
  }

  if (problems.length) {
    console.error('Perf gate validation:')
    problems.forEach((p) => console.error(`  - ${p}`))
    return false
  }

  console.log('Perf gate config + baseline OK.')
  return true
}

// ─── Modes ───────────────────────────────────────────────────────────
if (isValidate) {
  process.exit(validate() ? 0 : 1)
}

if (!fs.existsSync(BASELINE_FILE) && isCheck && !isSaveBaseline) {
  console.warn(`No baseline at ${BASELINE_FILE}. Run \`npm run perf:baseline\` to create one.`)
}

const results = collect()
const current = worstCase(results)
writeSummary(results, current)

console.log('\nWorst-case metrics across routes:')
Object.entries(current).forEach(([k, v]) => console.log(`  ${k}: ${formatValue(k, v)}`))

if (isSaveBaseline) {
  const payload = { generatedAt: new Date().toISOString(), baseUrl: BASE_URL, metrics: current }
  fs.writeFileSync(BASELINE_FILE, JSON.stringify(payload, null, 2))
  console.log(`\nBaseline saved to ${BASELINE_FILE}. Commit it.`)
  process.exit(0)
}

if (!isCheck) {
  // `--collect` mode: reports are gathered; no gate. `--check` / no-arg runs
  // the comparison below.
  console.log('\nCollect only (no gate). Run `npm run perf:check` to enforce budgets.')
  process.exit(0)
}

const baselineRaw = fs.existsSync(BASELINE_FILE) ? JSON.parse(fs.readFileSync(BASELINE_FILE, 'utf8')) : null
const { passed, violations, improvements } = checkBudgets(current, baselineRaw?.metrics ?? null)

if (improvements.length) {
  console.log('\nImprovements:')
  improvements.forEach((i) => console.log(`  OK ${i}`))
}
if (!passed) {
  console.error('\nPerformance budget violations:')
  violations.forEach((v) => console.error(`  FAIL ${v}`))
  console.error('\nIf this is an intentional, benchmarked improvement, run `npm run perf:baseline` to re-baseline.')
  process.exit(1)
}
console.log('\nAll performance budgets passed.')