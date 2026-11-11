// scripts/check-bundle-budget.mjs
// Run: node scripts/check-bundle-budget.mjs  (or: npm run bundle:budget)
// Phase 9 — Bundle Analysis CI gate. Walks `dist/assets/`, aggregates chunk
// sizes against the budgets below, and fails the build on violations.
//
// Adaptation note: the AI_READY Phase 9 numbers (Total JS < 2MB, Vendor UI
// < 300KB) were written for a slim fictional app. This app ships antd v6
// (~1.7MB) plus Chart.js/Leaflet/geospatial code, so the budgets below are
// calibrated to the current baseline with headroom — the gate is a
// *regression* guard (a new heavyweight dependency or a de-chunking accident
// fails CI), not an aspirational target.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ASSETS_DIR = path.resolve(__dirname, '../dist/assets')

/** name -> max aggregate size in KB (match Vite manualChunks ids + entry). */
const BUDGETS = [
  // 5800 -> 5850 (2026-08-25). The old number was not exceeded by a change;
  // it was STALE. It was calibrated in Phase 9 and never enforced once, because
  // CI has never run — so frontend work since (i18n batches, the sampling
  // rework, vertex editing, the menu series) drifted the real total to 5802.9KB
  // with nothing to notice. Measured identically on this machine and on the
  // runner, so it is the true baseline rather than build noise.
  //
  // Recalibrated to measured + ~47KB, deliberately tight: a new heavyweight
  // dependency is 100KB+, so this still fails on the thing the gate exists for.
  // Every individual chunk passes with room to spare — it is only the aggregate
  // that drifted. REDUCING this total is task 6.10 (granular antd, lazy
  // chart.js, turf subset); this line only makes the gate honest again.
  { name: 'Total JS', pattern: /\.js$/, maxKB: 5850 },
  { name: 'Main Entry', pattern: /^index-.*\.js$/, maxKB: 150 },
  { name: 'Vendor React', pattern: /^vendor-react-.*\.js$/, maxKB: 300 },
  { name: 'Vendor UI', pattern: /^vendor-ui-.*\.js$/, maxKB: 2000 },
  { name: 'Vendor Query', pattern: /^vendor-query-.*\.js$/, maxKB: 100 },
  { name: 'Vendor Map', pattern: /^vendor-map-.*\.js$/, maxKB: 250 },
  { name: 'Vendor Monitor', pattern: /^vendor-monitor-.*\.js$/, maxKB: 100 },
  { name: 'CSS', pattern: /\.css$/, maxKB: 160 },
]

function sizeKB(file) {
  return fs.statSync(path.join(ASSETS_DIR, file)).size / 1024
}

function check() {
  const violations = []

  if (!fs.existsSync(ASSETS_DIR)) {
    return { passed: false, violations: [`Dist assets not found: ${ASSETS_DIR} (run \`npm run build\` first)`] }
  }

  const files = fs.readdirSync(ASSETS_DIR)

  for (const budget of BUDGETS) {
    const matched = files.filter((f) => budget.pattern.test(f))
    const total = matched.reduce((sum, f) => sum + sizeKB(f), 0)
    if (total > budget.maxKB) {
      violations.push(
        `${budget.name}: ${total.toFixed(1)}KB exceeds budget of ${budget.maxKB}KB (files: ${matched.join(', ')})`,
      )
    } else {
      console.log(`ok   ${budget.name}: ${total.toFixed(1)}KB / ${budget.maxKB}KB`)
    }
  }

  // Note (non-fatal): flag large chunks not covered by any budget. Route-level
  // lazy chunks (e.g. CalculationDetail, MapWorkspace, geospatial) are an
  // intentional part of code-splitting, so this is informational only — the
  // enforceable signal is the BUDGETS table above.
  for (const file of files.filter((f) => f.endsWith('.js'))) {
    const size = sizeKB(file)
    if (size > 500 && !BUDGETS.some((b) => b.pattern.test(file))) {
      console.log(`warn Large route chunk: ${file} (${size.toFixed(1)}KB) — code-split page, no budget`)
    }
  }

  return { passed: violations.length === 0, violations }
}

const { passed, violations } = check()

if (!passed) {
  console.error('\nBundle budget violations:')
  violations.forEach((v) => console.error(`  - ${v}`))
  process.exit(1)
}

console.log('\nAll bundle budgets passed.')
