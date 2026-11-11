/**
 * No consumer holds its own DBH class list.
 *
 * DBH_SSOT_PLAN P4, first half: "a new hardcoded class array fails the build".
 *
 * The scan is deliberately narrow, because the obvious version of this test is
 * useless. Searching production code for `label_en` or `labelNp` returns hundreds
 * of hits that have nothing to do with DBH: map variables, hazard profiles, point
 * symbols, geometry purposes, layer registries. A test that flagged those would
 * be turned off within a week, and a lock that gets turned off is worse than no
 * lock because it reads as protection.
 *
 * So it matches on the one thing that is genuinely distinctive: **a literal DBH
 * class key**. `0_4`, `60_plus` and their siblings appear nowhere else in an
 * unrelated context, so a string literal shaped like `\d+_\d+` is a class list
 * and nothing else. Legacy exported identifiers are matched too, but only as
 * identifiers -- see `stripCommentsAndStrings`.
 *
 * What this test found on its first run is the reason it exists. P3's survey
 * looked for *imports* of the deleted arrays and found four files; this one looks
 * for key literals and found two more that had never referenced the arrays at
 * all. `FieldInventoryTab.tsx` carried a hardcoded eight-key list **and** two
 * index assumptions built on it (`i < 2` for the classes with no harvestable
 * volume, `i === 7` for the last column). Both are fixed; the list now comes from
 * the API and the assumptions are derived.
 *
 * Test files are exempt, and that exemption is a real limitation worth stating
 * rather than hiding: a test may legitimately build a stand-in API response, and
 * such a fixture can drift from the database without this test noticing. It is
 * not harmless, so `dbhLabelJoin.test.ts` covers the part that matters -- every
 * key any fixture claims to be a real system must be a key the database has.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const SRC = join(__dirname, '..', '..');
const SCAN_EXT = /\.(ts|tsx)$/;

/** Files allowed to contain literal class keys, each with the reason it must. */
const ALLOWED: Record<string, string> = {
  // The key -> i18n-key lookup. It cannot disagree about ranges or order, and its
  // coverage is pinned from the other side: dbhLabelJoin asserts it maps exactly
  // the database's guideline_2061 keys, no more and no fewer.
  'constants/dbhClasses.ts':
    'the key -> i18n-key lookup; coverage pinned by dbhLabelJoin.test.ts',

  // A colour ramp for raster cells. Eight hex colours for eight classes is
  // presentation the API has no opinion about, and forcing it through a query
  // would be worse engineering, not better. The key list here is positional -- it
  // has to line up with DBH8 -- so it cannot be a lookup. Instead it is pinned to
  // the database by an explicit test in dbhLabelJoin.test.ts, which is a stronger
  // guarantee than "delete it" because it still passes if the ramp is correct.
  'lib/semanticPalettes.ts':
    'positional DBH colour ramp; key list pinned to the DB by dbhLabelJoin.test.ts',
};

/**
 * Replace comments and string/template literal contents with spaces, preserving
 * offsets so reported line numbers stay right.
 *
 * This is what lets the test say "no consumer *declares* a class list" while
 * `constants/dbhClasses.ts` can still document in a comment which arrays it used
 * to export, and while a file can legitimately pass the system name
 * `'guideline_2061'` to an API call. Matching inside strings is how a scan like
 * this acquires a hundred false positives and gets deleted.
 */
function stripCommentsAndStrings(src: string): string {
  const out = src.split('');
  let i = 0;
  const n = src.length;
  const blank = (from: number, to: number) => {
    for (let k = from; k < to && k < n; k++) {
      if (out[k] !== '\n') out[k] = ' ';
    }
  };
  while (i < n) {
    const two = src.slice(i, i + 2);
    if (two === '//') {
      const end = src.indexOf('\n', i);
      blank(i, end === -1 ? n : end);
      i = end === -1 ? n : end;
    } else if (two === '/*') {
      const end = src.indexOf('*/', i + 2);
      blank(i, end === -1 ? n : end + 2);
      i = end === -1 ? n : end + 2;
    } else if (src[i] === '"' || src[i] === "'" || src[i] === '`') {
      const quote = src[i];
      let j = i + 1;
      while (j < n) {
        if (src[j] === '\\') { j += 2; continue; }
        if (src[j] === quote) break;
        j++;
      }
      blank(i + 1, j);
      i = j + 1;
    } else {
      i++;
    }
  }
  return out.join('');
}

function walk(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'i18n') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, acc);
    else if (SCAN_EXT.test(entry)) acc.push(full);
  }
  return acc;
}

const isTestFile = (p: string) =>
  /__tests__|[.]test[.]|[.]spec[.]/.test(p) || p.includes(`${sep}e2e${sep}`);

const allFiles = walk(SRC);
const productionFiles = allFiles.filter((f) => !isTestFile(f));

/** The arrays P3 deleted, matched as identifiers only. */
const LEGACY_IDENTIFIERS =
  /\b(GUIDELINE_2061|GUIDELINE_SIMPLE|DFO_EXPORT|COMPARTMENT_LEGEND_COLORS|TREE_MARKER_CONFIG|classifyByDbh|formatDetailedLabel|shortLabels)\b/g;

/**
 * A **quoted** DBH class key: `'0_4'`, `"60_plus"`.
 *
 * Two details earn their place here.
 *
 * *It must be quoted.* A DBH class key is always a string, so requiring the
 * quotes is free precision -- and it is what separates a class key from
 * TypeScript's numeric separators. The first version of this pattern was
 * `/\d+_\d+/` applied to comment- and string-stripped source, and it reported 14
 * hits that were all `30_000` and `1_000`: `const TIMEOUT = 30_000`. A lock that
 * cries wolf on fourteen unrelated files is a lock that gets deleted.
 *
 * *`{1,2}` on the lower bound, and `plus` or `{1,2}` on the upper.* DBH bounds are
 * centimetres, so no class runs past 99 -- and the top class of every system is
 * open, spelled `60_plus`, so the second half is not always digits. Writing
 * `\d{1,2}_\d{1,2}` and forgetting the `plus` branch was a real miss: it made
 * `60_plus` invisible to the scan, and the decoy test below caught it. The bound
 * is also what rejects a quoted `'1_000'`: the pattern can take `1_00` but then
 * finds a `0` where the closing quote belongs.
 *
 * **Scope, stated plainly:** this finds numeric keys, which is every key of
 * `guideline_2061` -- the only system the UI renders a class list from. The other
 * four systems use ordinary words (`seedling`, `tree`, `mature_tree`) that cannot
 * be pattern-matched without matching half the codebase. Those are covered from
 * the other side by `dbhLabelJoin.test.ts`, which asserts the committed key
 * fixture is what the database actually holds.
 */
const QUOTED_CLASS_KEY = /['"`](\d{1,2}_(?:\d{1,2}|plus))['"`]/g;

const rel = (f: string) => relative(SRC, f).split(sep).join('/');

/** Scan comment- and string-stripped source: for declarations, not for values. */
function findInProduction(pattern: RegExp): Array<{ file: string; line: number; match: string }> {
  const hits: Array<{ file: string; line: number; match: string }> = [];
  for (const file of productionFiles) {
    const relPath = rel(file);
    if (ALLOWED[relPath]) continue;
    const code = stripCommentsAndStrings(readFileSync(file, 'utf8'));
    pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = pattern.exec(code)) !== null) {
      hits.push({
        file: relPath,
        line: code.slice(0, m.index).split('\n').length,
        match: m[0],
      });
    }
  }
  return hits;
}

/** Scan raw source, because a class key's whole purpose is to be a string value. */
function findQuotedInProduction(
  pattern: RegExp,
): Array<{ file: string; line: number; match: string }> {
  const hits: Array<{ file: string; line: number; match: string }> = [];
  for (const file of productionFiles) {
    const relPath = rel(file);
    if (ALLOWED[relPath]) continue;
    const raw = readFileSync(file, 'utf8');
    pattern.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = pattern.exec(raw)) !== null) {
      hits.push({
        file: relPath,
        line: raw.slice(0, m.index).split('\n').length,
        match: m[1],
      });
    }
  }
  return hits;
}

describe('no production consumer holds its own DBH class list', () => {
  it('has production files to scan (guard against a broken glob)', () => {
    expect(productionFiles.length).toBeGreaterThan(100);
  });

  it('finds no literal class key outside the allowlist', () => {
    const hits = findQuotedInProduction(QUOTED_CLASS_KEY);
    expect(
      hits,
      `A literal DBH class key is hardcoded in production code.\n` +
        hits.map((h) => `  ${h.file}:${h.line}  ${h.match}`).join('\n') +
        `\n\nThe class list comes from GET /api/dbh-classes/systems via ` +
        `useDbhClassConfig. If a colour ramp or a semantic marker genuinely ` +
        `cannot come from the API, add the file to ALLOWED in this test with a ` +
        `reason and a test that pins it to the database -- do not delete the lock.`,
    ).toEqual([]);
  });

  it('is not fooled by TypeScript numeric separators', () => {
    // The false positive that made the first version of this pattern useless:
    // `30_000` and `1_000` are thirty thousand, not a class called "30_000".
    // Requiring the quotes kills the bare numeric literals, and the two-digit
    // bound on each half plus the closing-quote anchor kills even a quoted
    // `'1_000'`, because `1_00` is followed by a `0` and not a quote.
    const decoys = `
      const TIMEOUT = 30_000;
      const LIMIT = 1_000;
      const BIG = 120_000;
      const pair = '1_000';
      const real = ['0_4', '60_plus'];
    `;
    const found = [...decoys.matchAll(QUOTED_CLASS_KEY)].map((m) => m[1]);
    expect(found).toEqual(['0_4', '60_plus']);
  });

  it('finds no re-introduced legacy class array', () => {
    const hits = findInProduction(LEGACY_IDENTIFIERS);
    expect(
      hits,
      `A class list deleted in P3 is back.\n` +
        hits.map((h) => `  ${h.file}:${h.line}  ${h.match}`).join('\n'),
    ).toEqual([]);
  });

  it('cannot be satisfied by moving the list into a comment', () => {
    // The reason `stripCommentsAndStrings` exists, asserted rather than assumed.
    const sample = `
      // const GUIDELINE_2061 = [{ key: '0_4', lower: 0, upper: 4 }];
      const name = 'guideline_2061';
      const real = [{ key: '0_4', lower: 0 }];
    `;
    const code = stripCommentsAndStrings(sample);
    expect(code).not.toMatch(/GUIDELINE_2061/);
    expect(code).not.toMatch(/0_4/);
    // ...and the legitimate use of a system name survives as a value, though the
    // scan ignores it, so the assertion that matters is the real one below.
    expect(sample).toMatch(/guideline_2061/);
  });

  it('still allows a system name passed as a string', () => {
    // `api.ts`, `useDbhClassify.ts` and `SamplingTab.tsx` all name the system.
    // They re-type no range, so they are correct as they are; the scan must not
    // make an argument with them.
    const hits = findInProduction(/guideline_2061/g);
    expect(hits).toEqual([]);
  });

  it('documents every allowlist entry', () => {
    // An allowlist entry without a reason is how a lock rots.
    for (const [file, reason] of Object.entries(ALLOWED)) {
      expect(reason.length, `${file} has no reason`).toBeGreaterThan(20);
    }
  });

  it('allowlists only files that exist', () => {
    for (const file of Object.keys(ALLOWED)) {
      expect(allFiles.map(rel), `${file} is allowlisted but gone`).toContain(file);
    }
  });
});
