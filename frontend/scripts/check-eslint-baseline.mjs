// scripts/check-eslint-baseline.mjs
// Run: node scripts/check-eslint-baseline.mjs           (or: npm run lint)
//      node scripts/check-eslint-baseline.mjs --update  (or: npm run lint:update)
//
// ESLint baseline ratchet — fail on NEW errors, not the known ones (H4.1).
//
// Why this exists
// ---------------
// `ci.yml` ran `npx eslint src --ext .ts,.tsx || true`. The suppression hid 152
// errors, and while most are cosmetic (react/prop-types, unescaped entities),
// six are real defects — three conditional-hook violations that break React's
// hook ordering, and three missing `key` props that make React mis-reconcile
// lists. They survived because the tool that found them was told to exit 0.
//
// Errors only. The 4,130 warnings are dominated by no-explicit-any (2,104) and
// jsdoc rules, which belong to tasks 4.5 and 6.8 respectively and would drown
// the signal here.
//
// Mirrors scripts/check-tsc-baseline.mjs and backend/scripts/check_ruff_baseline.py
// — same baseline shape, same --update flag, same "expected to SHRINK" contract.
//
// What counts as "the same error": FILE + RULE, with a count. Not line numbers:
// they move whenever anything above them is edited, and a gate that cries wolf
// on every unrelated edit gets switched off. The trade is that swapping one
// prop-types error for another in the same file passes unnoticed — worth it for
// a gate that stays on.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const BASELINE = path.join(ROOT, 'eslint-baseline.json')
const UPDATE = process.argv.includes('--update')

/** Current ERROR-severity findings, keyed `path|rule`. */
function collect() {
  let raw
  try {
    // eslint's JS entry, not `npx`: Node on Windows refuses to spawnSync a
    // .cmd shim without `shell: true` (EINVAL), and enabling a shell to run a
    // linter is a worse trade than naming the script directly.
    raw = execFileSync(
      process.execPath,
      [path.join(ROOT, 'node_modules', 'eslint', 'bin', 'eslint.js'),
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
const baseline = exists ? JSON.parse(fs.readFileSync(BASELINE, 'utf-8')) : { total: 0, errors: {} }
const known = baseline.errors ?? {}

console.log(`eslint errors: ${total}   baseline: ${baseline.total ?? 0}`)

const worse = Object.entries(found).filter(([k, n]) => n > (known[k] ?? 0))
const fixed = Object.entries(known).reduce(
  (acc, [k, n]) => acc + Math.max(0, n - (found[k] ?? 0)), 0,
)

function save() {
  fs.writeFileSync(BASELINE, JSON.stringify({
    _comment: 'Known ESLint errors (severity 2 only), keyed file|rule. Expected to SHRINK. '
      + 'Regenerate with: npm run lint:update',
    total,
    errors: Object.fromEntries(Object.entries(found).sort(([a], [b]) => a.localeCompare(b))),
  }, null, 1) + '\n')
}

if (UPDATE) {
  // Seeding: with no baseline on disk every finding reads as growth, and the
  // guard below would refuse to write the very first one.
  if (!exists) {
    save()
    console.log(`baseline created with ${total} known error(s)`)
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
  console.error(`\nFAILED: ${worse.length} new ESLint error(s):`)
  for (const [k, n] of worse.sort()) {
    const [file, rule] = k.split('|')
    console.error(`  ${file}  ${rule}: ${known[k] ?? 0} -> ${n}`)
  }
  console.error('\nFix them, or run `npm run lint:update` if they are deliberate.')
  process.exit(1)
}

if (fixed) {
  console.log(`\n${fixed} error(s) fixed since the baseline. `
    + 'Run `npm run lint:update` to lock that in so they cannot come back.')
}
console.log('passed — no new ESLint errors.')
