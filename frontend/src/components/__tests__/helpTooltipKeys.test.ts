/**
 * Help tooltips say what their field is, not what some other field is.
 *
 * `tooltips.gpsPoints` ("GPS points are optional…") had been pasted onto ~35 unrelated
 * help icons: province, district, altitude, growing stock, sampling intensity, upload
 * projection… so "?" next to any of them told the user about GPS points. This pins the
 * one place that text belongs, and that every other tooltip key in use really exists.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url)); // frontend/src/components/__tests__
const SRC = path.resolve(here, '..', '..'); // frontend/src
const en = JSON.parse(fs.readFileSync(path.join(SRC, 'i18n', 'locales', 'en.json'), 'utf8'));
const ne = JSON.parse(fs.readFileSync(path.join(SRC, 'i18n', 'locales', 'ne.json'), 'utf8'));

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === '__tests__' || entry.name === 'node_modules') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) sourceFiles(full, out);
    else if (/\.(tsx|ts)$/.test(entry.name)) out.push(full);
  }
  return out;
}

/** Every `tKey="tooltips.x"` in the app, with the file it is in. */
function tooltipUses(): Array<{ key: string; file: string }> {
  const uses: Array<{ key: string; file: string }> = [];
  for (const file of sourceFiles(SRC)) {
    const text = fs.readFileSync(file, 'utf8');
    for (const m of text.matchAll(/tKey=["']tooltips\.([A-Za-z0-9_]+)["']/g)) {
      uses.push({ key: m[1], file: path.relative(SRC, file).replace(/\\/g, '/') });
    }
  }
  return uses;
}

describe('HelpTooltip keys', () => {
  const uses = tooltipUses();

  it('finds the tooltips in use (guards against the scan silently matching nothing)', () => {
    expect(uses.length).toBeGreaterThan(20);
  });

  it('tooltips.gpsPoints is used by the GPS point input only', () => {
    const files = uses.filter((u) => u.key === 'gpsPoints').map((u) => u.file);
    expect(files).toEqual(['components/MapCreation/GPSPointInput.tsx']);
  });

  it('every tooltip key in use exists, with text, in English and Nepali', () => {
    const missing = uses
      .filter((u) => !String(en.tooltips?.[u.key] ?? '').trim() || !String(ne.tooltips?.[u.key] ?? '').trim())
      .map((u) => `${u.file}: tooltips.${u.key}`);
    expect(missing).toEqual([]);
  });

  it('no two different sampling / upload / plan-metadata fields share one tooltip text', () => {
    // A key reused within a file is fine when the label is the same (the sampling form shows
    // the intensity and distance fields in two modes); this catches a text pasted across the
    // wider set of fields, which is how the GPS text spread.
    const perKeyFiles = new Map<string, Set<string>>();
    for (const u of uses) {
      if (!perKeyFiles.has(u.key)) perKeyFiles.set(u.key, new Set());
      perKeyFiles.get(u.key)!.add(u.file);
    }
    const spread = [...perKeyFiles].filter(([, files]) => files.size > 2).map(([k]) => k);
    expect(spread).toEqual([]);
  });
});
