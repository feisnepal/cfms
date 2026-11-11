/**
 * placeholderStrings — no explanatory text may ship as its own key reworded.
 *
 * ~190 strings of the Sampling form (hints, descriptions, banners, error messages) were
 * bundled as the key run through a "humaniser", in BOTH locales: users saw "Plot Size Intro",
 * "Slope Filter Subtitle", "Delete Success" beside the fields, and Nepali users saw the same
 * English. keySync could not catch it: the value is non-empty, differs from the bare key, and
 * exists in both languages.
 *
 * A key is an offender when
 *   - its last segment is an explanatory kind (Hint, Desc, Intro, Subtitle, Body, Note, Title,
 *     Explanation, Tooltip, or a numbered variant), and it is at least two words, and
 *   - BOTH the English and the Nepali value equal the humanised key ("Area Basis Tree Cover Desc").
 * Requiring both keeps genuine short labels ("Map Title") out of it.
 *
 * This is a ratchet: the offenders that exist today are listed in the baseline and may only
 * go away. A new one fails the build — write the real text — and fixing one obliges you to
 * remove it from the baseline, so the list can never quietly grow back.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const LOCALES = path.join(here, '..', 'locales');
const en: Record<string, unknown> = JSON.parse(fs.readFileSync(path.join(LOCALES, 'en.json'), 'utf8'));
const ne: Record<string, unknown> = JSON.parse(fs.readFileSync(path.join(LOCALES, 'ne.json'), 'utf8'));
const baseline: string[] = JSON.parse(
  fs.readFileSync(path.join(here, 'placeholderStringsBaseline.json'), 'utf8'),
);

const EXPLANATORY = /(Hint|Desc\d*|Description|Intro|Subtitle|Body\d*|Note|Explanation|Title|Tooltip)$/;

function leaves(obj: Record<string, unknown>, prefix = '', out: Record<string, string> = {}) {
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === 'object') leaves(v as Record<string, unknown>, `${prefix}${k}.`, out);
    else if (typeof v === 'string') out[`${prefix}${k}`] = v;
  }
  return out;
}

/** The reworded key the placeholder generator produced: `areaBasisTreeCoverDesc` -> "Area Basis Tree Cover Desc". */
function humanise(segment: string): string {
  return segment
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function offenders(): string[] {
  const E = leaves(en);
  const N = leaves(ne);
  const found: string[] = [];
  for (const [key, value] of Object.entries(E)) {
    const human = humanise(key.split('.').pop() as string);
    if (human.split(' ').length < 2 || !EXPLANATORY.test(human)) continue;
    if (value.trim() === human && (N[key] ?? '').trim() === human) found.push(key);
  }
  return found.sort();
}

describe('placeholder strings', () => {
  const current = offenders();

  it('the detector recognises the shape it is meant to catch', () => {
    expect(humanise('areaBasisTreeCoverDesc')).toBe('Area Basis Tree Cover Desc');
    expect(EXPLANATORY.test('Area Basis Tree Cover Desc')).toBe(true);
    expect(EXPLANATORY.test('Total Area')).toBe(false); // an ordinary label is not flagged
  });

  it('no new explanatory string is a reworded key — write the real text in both languages', () => {
    const fresh = current.filter((k) => !baseline.includes(k));
    expect(fresh).toEqual([]);
  });

  it('a fixed string is removed from the baseline, so the baseline only ever shrinks', () => {
    const fixed = baseline.filter((k) => !current.includes(k));
    expect(fixed).toEqual([]);
  });

  it('the Sampling form has none left', () => {
    expect(current.filter((k) => k.startsWith('sampling.'))).toEqual([]);
  });
});
