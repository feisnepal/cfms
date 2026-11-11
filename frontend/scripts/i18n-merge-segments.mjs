/**
 * i18n-merge-segments — merge dotted-key segment reports into en.json / ne.json.
 *
 * Usage:
 *   node scripts/i18n-merge-segments.mjs <segmentsDir> [--write]
 *
 * Segment file format (JSON array):
 *   [ { "key": "workspace.layerPanel.foo", "en": "...", "ne": "..." }, ... ]
 *
 * Without --write it prints the diff summary only. With --write it mutates
 * frontend/src/i18n/locales/{en,ne}.json (preserving indentation set below).
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOCALES = path.resolve(__dirname, '..', 'src', 'i18n', 'locales');
const NEWLINE = '\n';
const INDENT = 2;

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function setNested(root, dotted, value) {
  const parts = dotted.split('.');
  let node = root;
  for (let i = 0; i < parts.length - 1; i++) {
    const part = parts[i];
    if (typeof node[part] !== 'object' || node[part] === null) node[part] = {};
    node = node[part];
  }
  const last = parts[parts.length - 1];
  if (node[last] !== undefined && node[last] !== value) {
    // keep explicit conflict visible
    process.exitCode = 2;
    console.error(`CONFLICT ${dotted}: existing=${JSON.stringify(node[last])} new=${JSON.stringify(value)}`);
  }
  node[last] = value;
}

function main() {
  const segmentsDir = path.resolve(process.cwd(), process.argv[2] || '.i18n-4b');
  const write = process.argv.includes('--write');
  if (!fs.existsSync(segmentsDir)) {
    console.error(`Segments dir not found: ${segmentsDir}`);
    process.exit(1);
  }
  const en = readJson(path.join(LOCALES, 'en.json'));
  const ne = readJson(path.join(LOCALES, 'ne.json'));
  let keys = 0;
  const files = fs.readdirSync(segmentsDir).filter((f) => f.endsWith('.json'));
  for (const f of files) {
    const rows = JSON.parse(fs.readFileSync(path.join(segmentsDir, f), 'utf8'));
    for (const row of rows) {
      if (!row.key || typeof row.en !== 'string' || typeof row.ne !== 'string') {
        console.error(`Skipping malformed row in ${f}: ${JSON.stringify(row)}`);
        continue;
      }
      setNested(en, row.key, row.en);
      setNested(ne, row.key, row.ne);
      keys += 1;
    }
  }
  if (!write) {
    console.log(`Parsed ${keys} keys across ${files.length} segment file(s). Re-run with --write to apply.`);
    return;
  }
  fs.writeFileSync(path.join(LOCALES, 'en.json'), JSON.stringify(en, null, INDENT) + NEWLINE);
  fs.writeFileSync(path.join(LOCALES, 'ne.json'), JSON.stringify(ne, null, INDENT) + NEWLINE);
  console.log(`Merged ${keys} keys into en.json / ne.json`);
}

main();