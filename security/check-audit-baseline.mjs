#!/usr/bin/env node
/**
 * H2.12 / S2-23 — the ratchet that turns dependency scanning into a gate.
 *
 * A hard "no high or critical, ever" gate was not available on day one: the
 * frontend arrived with 13 high and 2 critical advisories, and the backend
 * lock with four vulnerable packages. A gate that is red on the day it lands
 * teaches everyone to ignore it, which is worse than no gate — that is the
 * lesson of the `|| true` steps this repository already carries (S2-23).
 *
 * So the rule is comparative, not absolute: **a finding that is already in the
 * baseline passes; anything new fails.** The existing debt stays visible in
 * `npm-audit-baseline.json` and `pip-audit-baseline.json`, both of which are
 * meant to shrink and must never grow. Removing the last entry is what turns
 * this into the absolute gate G-SEC-2 describes.
 *
 * This covers npm only. `pip-audit` has a native `--ignore-vuln` flag, so the
 * backend baseline is fed straight to the tool in CI rather than post-processed
 * here — one mechanism per ecosystem, each the idiomatic one.
 *
 * Usage:
 *   npm audit --json | node security/check-audit-baseline.mjs npm
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const mode = process.argv[2];

if (mode !== 'npm') {
  console.error('usage: check-audit-baseline.mjs npm   (npm audit --json on stdin)');
  process.exit(2);
}

function readStdin() {
  try {
    return readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

const raw = readStdin().trim();
if (!raw) {
  // An empty report is not a pass. A scanner that failed to run must not read
  // as "nothing found" — that is how a gate silently stops gating.
  console.error(`✗ ${mode}: no report on stdin. The scanner did not produce output.`);
  process.exit(1);
}

const baselineFile = join(HERE, `${mode}-audit-baseline.json`);
const baseline = JSON.parse(readFileSync(baselineFile, 'utf8')).packages ?? {};

/** Current findings as `{ package: [advisory ids] }`, whatever the scanner. */
function currentFindings(report) {
  const found = {};
  for (const [name, v] of Object.entries(report.vulnerabilities ?? {})) {
    if (v.severity !== 'high' && v.severity !== 'critical') continue;
    found[name] = {
      severity: v.severity,
      ids: [...new Set((v.via ?? []).filter((x) => typeof x === 'object').map((x) => String(x.source)))].sort(),
    };
  }
  return found;
}

const current = currentFindings(JSON.parse(raw));

const newPackages = [];
const newAdvisories = [];
for (const [name, info] of Object.entries(current)) {
  const known = baseline[name];
  if (!known) {
    newPackages.push({ name, ...info });
    continue;
  }
  const knownIds = new Set(known.advisories ?? []);
  const unseen = info.ids.filter((id) => !knownIds.has(id));
  if (unseen.length) newAdvisories.push({ name, ids: unseen });
}

// Entries that no longer appear are the good news, and worth printing: they are
// the prompt to shrink the baseline, which is the only way this ends.
const resolved = Object.keys(baseline).filter((name) => !current[name]);

console.log(`${mode}: ${Object.keys(current).length} finding(s) now, ${Object.keys(baseline).length} in the baseline.`);

if (resolved.length) {
  console.log(`\n✓ No longer reported (remove from ${mode}-audit-baseline.json):`);
  for (const name of resolved) console.log(`    ${name}`);
}

if (!newPackages.length && !newAdvisories.length) {
  console.log('\n✓ Nothing new since the baseline.');
  process.exit(0);
}

console.error('\n✗ NEW vulnerabilities, not present when the baseline was taken:');
for (const p of newPackages) {
  console.error(`    ${p.name}  [${p.severity}]  ${p.ids.join(', ')}`);
}
for (const a of newAdvisories) {
  console.error(`    ${a.name}  new advisories: ${a.ids.join(', ')}`);
}
console.error(
  '\nFix the dependency, or — only if the finding genuinely does not apply — add it to ' +
    `security/${mode}-audit-baseline.json with a reason in the entry.`,
);
process.exit(1);
