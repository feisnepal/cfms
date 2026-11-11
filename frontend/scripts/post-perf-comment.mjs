// scripts/post-perf-comment.mjs
// Phase 10 — posts a Lighthouse perf-gate summary as a PR comment from CI.
// Reads `lighthouse-reports/summary.json` (written by perf-budget-gate.mjs)
// and calls `gh api` to comment. Requires GITHUB_TOKEN (or a GH PAT) and the
// standard GH_* / GITHUB_REPOSITORY + PR_NUMBER env vars.
//
// Usage:
//   PR_NUMBER=123 node scripts/post-perf-comment.mjs
import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SUMMARY_FILE = path.resolve(__dirname, '../lighthouse-reports/summary.json')
const LABELS = {
  'largest-contentful-paint': 'LCP',
  'first-contentful-paint': 'FCP',
  'total-blocking-time': 'TBT',
  'cumulative-layout-shift': 'CLS',
  'speed-index': 'SI',
  interactive: 'TTI',
  'performance-score': 'Perf score',
}

function main() {
  const pr = process.env.PR_NUMBER
  if (!pr) {
    console.error('PR_NUMBER env var is required.')
    process.exit(1)
  }
  if (!fs.existsSync(SUMMARY_FILE)) {
    console.error(`Missing ${SUMMARY_FILE} — run perf-budget-gate.mjs --collect first.`)
    process.exit(1)
  }

  const { routes, worst } = JSON.parse(fs.readFileSync(SUMMARY_FILE, 'utf8'))
  const rows = Object.entries(worst)
    .map(([k, v]) => `| ${LABELS[k] ?? k} | ${v} |`)
    .join('\n')
  const routeList = Object.entries(routes)
    .map(([slug, r]) => `- ${slug}: ${r.url}`)
    .join('\n')

  const body =
    '## ⚡ Lighthouse Perf Gate\n\n' +
    'Worst-case metrics across audited routes:\n\n' +
    '| Metric | Value |\n|---|---|\n' +
    rows +
    '\n\nAudited routes:\n' +
    routeList +
    '\n\n_Run via `.github/workflows/performance.yml`. Full reports in the workflow artifacts._'

  const repo = process.env.GITHUB_REPOSITORY
  if (!repo) {
    console.error('GITHUB_REPOSITORY env var is required.')
    process.exit(1)
  }

  const json = JSON.stringify({ body })
  execSync(
    `gh api repos/${repo}/issues/${pr}/comments -f body="${json}"`,
    { stdio: 'inherit' },
  )
  console.log('Perf gate comment posted to PR #' + pr)
}

main()