// scripts/check-tsc-baseline.mjs
// Run: node scripts/check-tsc-baseline.mjs        (or: npm run typecheck)
//      node scripts/check-tsc-baseline.mjs --update
//
// TypeScript baseline ratchet — fail on NEW type errors, not on the known ones.
//
// Why this exists
// ---------------
// `tsconfig.json` has `strict: false`, and the project carries a known set of
// type errors: CURRENT_PLAN.md records "tsc 7 errors (below the 8 baseline)" as
// a SUCCESS condition. Meanwhile ci.yml ran `npx tsc --noEmit` with no `|| true`
// in two separate jobs — a hard gate that fails on any error at all.
//
// Those two positions have contradicted each other for as long as both existed.
// Nothing surfaced it because CI has never run: the repository has no git
// remote. The first push would have gone straight to red on a baseline the team
// had deliberately accepted.
//
// So: record what is known, fail on anything new. The same ratchet H1.11 applies
// to schema drift and task 4.1 applies to lint. The baseline is expected to
// shrink, and --update refuses to let it grow.
//
// What counts as "the same error"
// -------------------------------
// Keyed on FILE + TS-CODE, with a count — deliberately not on line numbers or
// message text. A line number shifts whenever anything above it is edited, and
// TS2739-style messages embed whole type literals that change with unrelated
// edits. Keying on either would produce constant false "new error" failures and
// the gate would be turned off within a week.
//
// File + code + count still catches what matters: a new file with errors, a new
// class of error in a known file, or more of an existing one.

import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const BASELINE = path.join(ROOT, 'tsc-baseline.json')

/** Run tsc and return its diagnostic lines. tsc exits non-zero when it finds errors. */
function runTsc() {
  try {
    execSync('npx tsc --noEmit', { cwd: ROOT, encoding: 'utf8', stdio: 'pipe' })
    return ''
  } catch (err) {
    // Diagnostics go to stdout; a genuine crash would leave it empty.
    const out = (err.stdout || '') + (err.stderr || '')
    if (!out.trim()) {
      console.error('tsc produced no output but failed — is it installed?')
      process.exit(2)
    }
    return out
  }
}

/** "src/x.ts(12,7): error TS2322: ..." -> { 'src/x.ts|TS2322': n } */
function tally(output) {
  const counts = {}
  const re = /^(.+?)\((\d+),(\d+)\):\s+error\s+(TS\d+):/gm
  let m
  while ((m = re.exec(output)) !== null) {
    const file = m[1].replace(/\\/g, '/')
    const key = `${file}|${m[4]}`
    counts[key] = (counts[key] || 0) + 1
  }
  return counts
}

function readBaseline() {
  if (!fs.existsSync(BASELINE)) return null
  return JSON.parse(fs.readFileSync(BASELINE, 'utf8')).errors ?? {}
}

function writeBaseline(counts) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  fs.writeFileSync(
    BASELINE,
    JSON.stringify(
      {
        _comment:
          'Known TypeScript errors, keyed file|TScode. Expected to SHRINK. ' +
          'Regenerate with: node scripts/check-tsc-baseline.mjs --update',
        total,
        errors: Object.fromEntries(Object.entries(counts).sort()),
      },
      null,
      2,
    ) + '\n',
  )
  return total
}

const update = process.argv.includes('--update')
const current = tally(runTsc())
const baseline = readBaseline()
const curTotal = Object.values(current).reduce((a, b) => a + b, 0)

if (baseline === null) {
  const total = writeBaseline(current)
  console.log(`Baseline created: ${total} known error(s).`)
  process.exit(0)
}

const added = []
const fixed = []
for (const [key, n] of Object.entries(current)) {
  const was = baseline[key] || 0
  if (n > was) added.push(`${key} (${was} -> ${n})`)
}
for (const [key, was] of Object.entries(baseline)) {
  const n = current[key] || 0
  if (n < was) fixed.push(`${key} (${was} -> ${n})`)
}

if (update) {
  if (added.length) {
    console.error('Refusing to update: the baseline would GROW.')
    added.forEach((a) => console.error(`  + ${a}`))
    process.exit(1)
  }
  const total = writeBaseline(current)
  console.log(`Baseline updated: ${total} known error(s) (${fixed.length} improved).`)
  process.exit(0)
}

if (fixed.length) {
  console.log(`${fixed.length} baseline entr(ies) improved — re-snapshot with --update:`)
  fixed.forEach((f) => console.log(`  - ${f}`))
  console.log()
}

if (added.length) {
  console.error(`NEW TypeScript errors: ${added.length} not in the baseline.\n`)
  added.forEach((a) => console.error(`  + ${a}`))
  console.error('\nFix them, or if they are genuinely acceptable, justify and')
  console.error('re-snapshot with: node scripts/check-tsc-baseline.mjs --update')
  process.exit(1)
}

console.log(`No new TypeScript errors (${curTotal} known).`)
process.exit(0)
