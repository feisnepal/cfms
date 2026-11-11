/**
 * i18n:scan — advisory coverage report (Phase 0.3).
 *
 * Runs i18next-parser into a throwaway output dir, then prints which keys
 * referenced by the code are missing from the committed bundles, plus the
 * keys present in the bundle but never referenced. READS only — the committed
 * en.json / ne.json are never written. The hard gate stays the keySync test.
 */
import { execSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const outDir = path.join(root, 'node_modules', '.cache', 'i18n-scan');
const localesDir = path.join(root, 'src', 'i18n', 'locales');

fs.rmSync(outDir, { recursive: true, force: true });

try {
  execSync('npx i18next --config i18next-parser.config.cjs', {
    cwd: root,
    stdio: 'inherit',
  });
} catch (err) {
  if (err.stdout) process.stdout.write(String(err.stdout));
  if (err.stderr) process.stderr.write(String(err.stderr));
  console.error('i18next-parser failed (report-only — not a gate):', err.message);
  process.exit(0);
}

function leaves(obj, prefix = '', out = []) {
  for (const [k, v] of Object.entries(obj)) {
    const p = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === 'object') leaves(v, p, out);
    else out.push(p);
  }
  return out;
}

const committed = JSON.parse(fs.readFileSync(path.join(localesDir, 'en.json'), 'utf8'));
const scanned = JSON.parse(fs.readFileSync(path.join(outDir, 'en.json'), 'utf8'));

const committedKeys = new Set(leaves(committed));
const scannedKeys = new Set(leaves(scanned));

const missingFromBundle = [...scannedKeys].filter((k) => !committedKeys.has(k)).sort();
const unusedInCode = [...committedKeys].filter((k) => !scannedKeys.has(k)).sort();

console.log('\n=== i18n:scan report (advisory) ===');
console.log(`keys referenced in code: ${scannedKeys.size}`);
console.log(`keys in committed bundle: ${committedKeys.size}`);
console.log(`\nMISSING from bundle (referenced in code, not in en.json/ne.json): ${missingFromBundle.length}`);
for (const k of missingFromBundle) console.log(`  ${k}`);
console.log(`\nIN bundle but not referenced anywhere: ${unusedInCode.length}`);
for (const k of unusedInCode) console.log(`  ${k}`);
console.log('\nNote: dynamic keys (template literals, backend keys) cannot be detected by the parser.');