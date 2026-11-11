/**
 * keySync — the permanent i18n gate (Phase 0.2).
 *
 * Guarantees en/ne bundle symmetry for the single `translation` namespace:
 *   1. top-level namespace sets are identical across languages;
 *   2. every leaf key present in one language has a non-empty value in the other;
 *   3. no leaf value is the bare key itself (kills `t(key, key)` cope-backs);
 *   4. every static `t('...')` literal in the frontend source exists in the bundle
 *      (dynamic/template-literal keys are skipped).
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const testDir = path.dirname(fileURLToPath(import.meta.url)); // frontend/src/i18n/__tests__
const ROOT = path.resolve(testDir, '..', '..', '..'); // frontend/
const LOCALES_DIR = path.join(__dirname, '..', 'locales');
const SRC_DIR = path.join(ROOT, 'src');

const en: Record<string, any> = JSON.parse(fs.readFileSync(path.join(LOCALES_DIR, 'en.json'), 'utf8'));
const ne: Record<string, any> = JSON.parse(fs.readFileSync(path.join(LOCALES_DIR, 'ne.json'), 'utf8'));

interface Leaf {
  path: string;
  value: string;
}

function walkLeaves(obj: Record<string, any>, prefix = '', out: Leaf[] = []): Leaf[] {
  for (const [key, value] of Object.entries(obj)) {
    const p = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object') {
      walkLeaves(value, p, out);
    } else {
      out.push({ path: p, value: String(value) });
    }
  }
  return out;
}

function walkFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkFiles(full, out);
    } else if (/\.(tsx|ts)$/.test(entry.name) && !/\.(test|spec)\./.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

describe('i18n key-sync (en ↔ ne)', () => {
  const enLeaves = walkLeaves(en);
  const neLeaves = walkLeaves(ne);
  const enIdx = new Map(enLeaves.map((l) => [l.path, l]));
  const neIdx = new Map(neLeaves.map((l) => [l.path, l]));

  it('has identical top-level namespace sets', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ne).sort());
  });

  it('has identical leaf key sets across languages', () => {
    const enOnly = enLeaves.map((l) => l.path).filter((k) => !neIdx.has(k));
    const neOnly = neLeaves.map((l) => l.path).filter((k) => !enIdx.has(k));
    expect({ missingInNe: enOnly, missingInEn: neOnly }).toEqual({
      missingInNe: [],
      missingInEn: [],
    });
  });

  it('has no empty/whitespace-only leaf values in either language', () => {
    const emptyEn = enLeaves.filter((l) => !l.value.trim());
    const emptyNe = neLeaves.filter((l) => !l.value.trim());
    expect({ emptyInEn: emptyEn.map((l) => l.path), emptyInNe: emptyNe.map((l) => l.path) }).toEqual({
      emptyInEn: [],
      emptyInNe: [],
    });
  });

  it('has no leaf value equal to its own key (no t(key, key) cope-backs)', () => {
    const selfKeys = enLeaves.filter((l) => l.value === l.path);
    expect(selfKeys.map((l) => l.path)).toEqual([]);
  });

  it('has no malformed key segments (rejects pasted scan-report lines)', () => {
    const SAFE_SEGMENT = /^[A-Za-z0-9_-]+$/;
    const collectSegments = (obj: Record<string, any>, prefix = '', out: string[] = []): string[] => {
      for (const [key, value] of Object.entries(obj)) {
        const p = prefix ? `${prefix}.${key}` : key;
        if (!SAFE_SEGMENT.test(key)) out.push(p);
        if (value && typeof value === 'object') collectSegments(value, p, out);
      }
      return out;
    };
    expect({ malformedInEn: collectSegments(en), malformedInNe: collectSegments(ne) }).toEqual({
      malformedInEn: [],
      malformedInNe: [],
    });
  });

  const TOP_LEVEL_NAMESPACES = new Set(Object.keys(en));

  it('has every static t("...") literal in the bundle', () => {
    const bundleKeys = new Set(enLeaves.map((l) => l.path));
    const missing = new Set<string>();
    let literals = 0;

    const literalRe = /(?:^|[^\w.])t\(\s*['"]([^'"`]+)['"]/g;
    for (const file of walkFiles(SRC_DIR)) {
      const content = fs.readFileSync(file, 'utf8');
      let m: RegExpExecArray | null;
      while ((m = literalRe.exec(content)) !== null) {
        const key = m[1];
        if (!key.trim() || /^\$/.test(key)) continue; // skip odd/dynamic
        literals += 1;
        if (!bundleKeys.has(key)) missing.add(`${key}   (${path.relative(ROOT, file)})`);
      }
    }

    expect({ totalLiterals: literals, missing }).toEqual({ totalLiterals: literals, missing: new Set() });
  });
  /**
   * The assertion above only sees `t('literal')`. Phase 4 leaned heavily on the
   * labelKey pattern - the key is stored in a module-scope map and resolved as
   * `t(map[x].labelKey)` - which the literal scanner cannot follow. A key
   * missing there renders the raw key string on screen with no test failing,
   * and Phase 5 found 75 of them live in the UI (`analysis.presetQuick`,
   * `status.lifecycle.draft`, `sampling.catProtected`, …).
   *
   * This catches the same class by shape: any single-quoted literal that looks
   * like an i18n key must resolve in the bundle.
   */
  it('has every key-shaped literal in the bundle, including keys held in variables', () => {
    const bundleKeys = new Set(enLeaves.map((l) => l.path));
    const missing = new Set<string>();

    // `feature.subject` or deeper, lowercase-first, no slashes or extensions.
    const keyish = /'([a-z][A-Za-z0-9]*(?:\.[a-zA-Z0-9_]+){1,4})'/g;
    // Version strings and similar are not keys.
    const NOT_A_KEY = /^v?\d/;

    for (const file of walkFiles(SRC_DIR)) {
      const content = fs.readFileSync(file, 'utf8');
      const lines = content.split('\n');
      let m: RegExpExecArray | null;
      while ((m = keyish.exec(content)) !== null) {
        const key = m[1];
        if (NOT_A_KEY.test(key)) continue;
        if (/\.(ts|tsx|json|css|png|jpe?g|svg)$/.test(key)) continue;
        // `i18nPrefix` holds a namespace prefix, not a leaf key. The field is
        // currently dead (declared on 8 layers, read nowhere), so its values
        // are never resolved or rendered.
        const line = lines[content.slice(0, m.index).split('\n').length - 1] ?? '';
        if (line.includes('i18nPrefix')) continue;
        // Only judge literals whose first segment is a real namespace; anything
        // else is more likely a dotted identifier than a key.
        if (!TOP_LEVEL_NAMESPACES.has(key.split('.')[0])) continue;
        if (!bundleKeys.has(key)) missing.add(`${key}   (${path.relative(ROOT, file)})`);
      }
    }

    expect(missing).toEqual(new Set());
  });
});
