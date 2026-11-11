// scripts/check-any-count.mjs
// Run: node scripts/check-any-count.mjs        (or: npm run lint:any)
//      node scripts/check-any-count.mjs --update
//
// `any`-count ratchet — task 4.5 / S2-24. The industry report cites 1,635
// `: any` / `as any` occurrences across src/. strict:true is now on; the
// escaping-hatch count may only shrink, never grow.
//
// Definition: the report's own — textual `: any` and `as any` occurrences in
// src/**/*.{ts,tsx}, comments excluded. Keyed on file so a PR can see where
// the growth would come from. Same philosophy as the tsc/lint baselines:
// record what is known, fail on anything new.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '..')
const SRC = path.join(ROOT, 'src')
const BASELINE = path.join(ROOT, 'any-count-baseline.json')

function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, out)
    else if (e.name.endsWith('.ts') || e.name.endsWith('.tsx')) out.push(p)
  }
  return out
}

// Strip line comments, block comments and strings so `: any` inside docs or
// error-message templates doesn't count. (A pragmatic lexical scan — good
// enough for a count; the ESLint rule remains the authority.)
function stripCode(src) {
  let s = ''
  let i = 0
  const n = src.length
  while (i < n) {
    const c = src[i]
    const d = src[i + 1]
    if (c === '/' && d === '/') {
      while (i < n && src[i] !== '\n') i++
    } else if (c === '/' && d === '*') {
      i += 2
      while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++
      i += 2
    } else if (c === '"' || c === "'") {
      const q = c
      s += c
      i++
      while (i < n && src[i] !== q) {
        if (src[i] === '\\') {
          s += src[i] + (src[i + 1] || '')
          i += 2
          continue
        }
        s += src[i]
        i++
      }
      s += q
      i++
    } else if (c === '`') {
      s += c
      i++
      while (i < n && src[i] !== '`') {
        if (src[i] === '\\') {
          s += src[i] + (src[i + 1] || '')
          i += 2
          continue
        }
        s += src[i]
        i++
      }
      s += '`'
      i++
    } else {
      s += c
      i++
    }
  }
  return s
}

function tally(files) {
  const counts = {}
  for (const f of files) {
    const src = stripCode(fs.readFileSync(f, 'utf8'))
    const m = src.match(/(:\s*any\b|\bas\s+any\b)/g)
    if (m) {
      const rel = path.relative(ROOT, f).replace(/\\/g, '/')
      counts[rel] = (counts[rel] || 0) + m.length
    }
  }
  return counts
}

function readBaseline() {
  if (!fs.existsSync(BASELINE)) return null
  return JSON.parse(fs.readFileSync(BASELINE, 'utf8')).files ?? {}
}

function writeBaseline(counts) {
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  fs.writeFileSync(
    BASELINE,
    JSON.stringify(
      {
        _comment:
          'Known `: any` / `as any` counts, keyed file. Expected to SHRINK. ' +
          'Regenerate with: node scripts/check-any-count.mjs --update',
        total,
        files: Object.fromEntries(Object.entries(counts).sort()),
      },
      null,
      2,
    ) + '\n',
  )
  return total
}

const update = process.argv.includes('--update')
const files = walk(SRC)
const current = tally(files)
const baseline = readBaseline()
const curTotal = Object.values(current).reduce((a, b) => a + b, 0)

if (baseline === null) {
  const total = writeBaseline(current)
  console.log(`Any-count baseline created: ${total}.`)
  process.exit(0)
}

const added = Object.entries(current).filter(([f, n]) => (baseline[f] || 0) < n)
const fixed = Object.entries(baseline).filter(([f, was]) => (current[f] || 0) < was)

if (update) {
  if (added.length) {
    console.error('Refusing to update: the any-count would GROW.')
    added.forEach(([f, n]) => console.error(`  + ${f} (${baseline[f] || 0} -> ${n})`))
    process.exit(1)
  }
  const total = writeBaseline(current)
  console.log(`Any-count baseline updated: ${total} (${fixed.length} improved).`)
  process.exit(0)
}

if (fixed.length) {
  console.log(`${fixed.length} file(s) improved — re-snapshot with --update:`)
  fixed.forEach(([f, was]) => console.log(`  - ${f}: ${was} -> ${current[f] || 0}`))
  console.log()
}

if (added.length) {
  console.error(`NEW \`any\` occurrences: ${added.length} file(s) above baseline.\n`)
  added.forEach(([f, n]) => console.error(`  + ${f}: ${baseline[f] || 0} -> ${n}`))
  console.error('\nFix them, or if genuinely acceptable, justify and re-snapshot:')
  console.error('node scripts/check-any-count.mjs --update')
  process.exit(1)
}

console.log(`No new \`any\` occurrences (${curTotal} known, was ${Object.values(baseline).reduce((a, b) => a + b, 0)}).`)
process.exit(0)