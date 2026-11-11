// scripts/check-security-rules.mjs
// Run: node scripts/check-security-rules.mjs              (or: npm run lint:security)
//      node scripts/check-security-rules.mjs --update     (or: npm run lint:security:update)
//
// Security-rule baseline ratchet (H4.6 / S2-42 / S3-09). Same contract as the
// lint/tsc/ruff ratchets: fails on NEW violations of the three security rules,
// and the baseline may only shrink. When it shrinks, run --update to lock it in.
//
// The rules live in eslint.security.config.mjs, deliberately separate from the
// main eslint config so the fragile 152-error lint baseline is untouched: this
// family starts with ~700 known violations that are existing debt (DEV-gated
// logs and raw fetch/token reads that predate the axios client), and a ratchet
// with a hard wall would have been turned off on day one.
//
// Same shape as check-eslint-baseline.mjs: keyed `file|rule` with counts, NOT
// line numbers, so a gate that cried wolf on every unrelated edit would not be
// switched off.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const BASELINE = path.join(ROOT, 'security-rules-baseline.json')
const UPDATE = process.argv.includes('--update')

/** Current security-rule findings, keyed `path|rule`. */
function collect() {
  let raw
  try {
    raw = execFileSync(
      process.execPath,
      [path.join(ROOT, 'node_modules', 'eslint', 'bin', 'eslint.js'),
        '-c', path.join(ROOT, 'eslint.security.config.mjs'),
        'src', '--ext', '.ts,.tsx', '-f', 'json'],
      { cwd: ROOT, encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024 },
    )
  } catch (e) {
    // eslint exits non-zero when it finds errors; the JSON is still on stdout.
    raw = e.stdout
    if (!raw) throw e
  }
  const found = {}
  for (const file of JSON.parse(raw)) {
    const rel = path.relative(ROOT, file.filePath).split(path.sep).join('/')
    for (const m of file.messages) {
      if (m.severity !== 2) continue
      const key = `${rel}|${m.ruleId ?? 'parse-error'}`
      found[key] = (found[key] ?? 0) + 1
    }
  }
  return found
}

const found = collect()
const total = Object.values(found).reduce((a, b) => a + b, 0)
const exists = fs.existsSync(BASELINE)
const baseline = exists ? JSON.parse(fs.readFileSync(BASELINE, 'utf-8')) : { total: 0, violations: {} }
const known = baseline.violations ?? {}

console.log(`security-rule violations: ${total}   baseline: ${baseline.total ?? 0}`)

const worse = Object.entries(found).filter(([k, n]) => n > (known[k] ?? 0))
const fixed = Object.entries(known).reduce(
  (acc, [k, n]) => acc + Math.max(0, n - (found[k] ?? 0)), 0,
)

function save() {
  fs.writeFileSync(BASELINE, JSON.stringify({
    _comment: 'Known security-rule violations (H4.6, severity 2 only), keyed file|rule. '
      + 'Rules: no-console-outside-dev, no-restricted-syntax (fetch, access_token read). '
      + 'Expected to SHRINK. Regenerate with: npm run lint:security:update',
    total,
    violations: Object.fromEntries(Object.entries(found).sort(([a], [b]) => a.localeCompare(b))),
  }, null, 1) + '\n')
}

if (UPDATE) {
  if (!exists) {
    save()
    console.log(`seed baseline created with ${total} known violation(s)`)
    process.exit(0)
  }
  if (worse.length) {
    console.error('\nRefusing to record growth — the baseline may only shrink:')
    for (const [k, n] of worse.sort()) console.error(`  ${k}: ${known[k] ?? 0} -> ${n}`)
    process.exit(1)
  }
  save()
  console.log(`baseline updated: ${baseline.total ?? 0} -> ${total}`)
  process.exit(0)
}

if (worse.length) {
  console.error(`\nFAILED: ${worse.length} new security-rule violation(s):`)
  for (const [k, n] of worse.sort()) {
    const [file, rule] = k.split('|')
    console.error(`  ${file}  ${rule}: ${known[k] ?? 0} -> ${n}`)
  }
  console.error('\nFix them, or run `npm run lint:security:update` if they are deliberate.')
  process.exit(1)
}

if (fixed) {
  console.log(`\n${fixed} violation(s) fixed since the baseline. `
    + 'Run `npm run lint:security:update` to lock that in so they cannot come back.')
}
console.log('passed — no new security-rule violations.')