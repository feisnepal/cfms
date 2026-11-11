/**
 * The D4 join: a DBH class key, and a word for it in each language.
 *
 * DBH_SSOT_PLAN P4, second half, and D4 itself: the registry owns which classes
 * exist, their order and their ranges; the bundle owns how a class is worded. The
 * class **key** is the join between them, and this test is the join.
 *
 * **It reads the database, via a committed fixture.** `dbh_class_keys.json` at the
 * repo root holds each system's keys and bounds and no labels. That is the one
 * artefact neither side can check alone: the backend holds the truth, the i18n
 * bundle holds the words, and a test in one language cannot see the other. The
 * fixture is only trustworthy because `backend/tests/test_dbh_class_keys_fixture.py`
 * asserts it against the live table -- so it cannot go stale without a backend
 * test failing first. Labels are deliberately absent from it, because a fixture
 * that carried them would be a second copy of the words, and the whole point is
 * that the bundle is the only place they live.
 *
 * **Why the join covers `guideline_2061` and not all five systems.** The obvious
 * reading of "every class key has a `dbhClass.*` label" is unimplementable, and
 * finding that out is why this file is worded the way it is. The five systems
 * reuse key *names* for different bands: `regeneration` is 0-10 cm in
 * `harvesting_cfmg` but 1-4 cm in `validation`; `tree` is 30 cm-and-above in
 * `guideline_simple` but 30-200 cm in `validation`; `0_4` is "Seedling" in
 * `guideline_2061` while `seedling` is the same band in `guideline_simple`. One
 * `dbhClass.<name>` key cannot serve two bands, so a test demanding 25 i18n keys
 * would be demanding the wrong thing -- and someone would satisfy it by giving
 * two different bands the same word.
 *
 * So the join is over the keys the UI actually renders, which is
 * `guideline_2061` and only that. Everything else is rendered from the label the
 * API sends, and `test_dbh_class_keys_fixture.py` asserts those are non-empty in
 * both languages for every class of every system -- which is the guarantee that
 * actually matters for a Nepali user opening a picker.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import en from '../../i18n/locales/en.json';
import ne from '../../i18n/locales/ne.json';
import { DBH_CLASS_LABEL_KEYS, DEFAULT_SYSTEM } from '../dbhClasses';

// The fixture lives under backend/tests/fixtures: the database is the authority,
// so the artefact stays on the backend's side of the contract, and .gitignore
// already excepts that directory from its blanket *.json rule -- so this needed
// no new ignore exception.
const FIXTURE = join(
  __dirname, '..', '..', '..', '..', 'backend', 'tests', 'fixtures', 'dbh_class_keys.json',
);

interface FixtureClass {
  key: string;
  lower: number;
  upper: number | null;
}
interface FixtureSystem {
  is_active: boolean;
  is_system_default: boolean;
  classes: FixtureClass[];
}
const fixture: Record<string, FixtureSystem> = JSON.parse(readFileSync(FIXTURE, 'utf8'));

/** The system whose classes the UI renders, per D4. */
const RENDERED = DEFAULT_SYSTEM;

function lookup(bundle: any, path: string): string | undefined {
  return path.split('.').reduce<any>((acc, k) => (acc == null ? undefined : acc[k]), bundle);
}

const renderedKeys = fixture[RENDERED].classes.map((c) => c.key);

describe('the key fixture is shaped as a contract, not a copy', () => {
  it('holds every system the API serves', () => {
    // P2 established five; this pins the fixture to that number so a system
    // cannot be added to the table and quietly missed here.
    expect(Object.keys(fixture).sort()).toEqual([
      'dfo_export',
      'guideline_2061',
      'guideline_simple',
      'harvesting_cfmg',
      'validation',
    ]);
  });

  it('carries no labels, so it cannot become a second copy of the words', () => {
    for (const [name, system] of Object.entries(fixture)) {
      for (const cls of system.classes) {
        expect(Object.keys(cls).sort(), `${name}.${cls.key}`).toEqual(['key', 'lower', 'upper']);
      }
    }
  });

  it('has an open upper bound only where the database has one', () => {
    // `60_plus` is open; `validation.tree` stops at 200. Both are real, and
    // conflating them would make the top class of one system mean something
    // different from the top class of another.
    const top2061 = fixture[RENDERED].classes.filter((c) => c.upper === null);
    expect(top2061.map((c) => c.key)).toEqual(['60_plus']);
    expect(fixture.validation.classes.filter((c) => c.upper === null)).toEqual([]);
  });
});

describe('D4: every rendered class key has a word in both languages', () => {
  it('the rendered system is the one the UI uses', () => {
    expect(RENDERED).toBe('guideline_2061');
  });

  for (const key of renderedKeys) {
    it(`${key} -> dbhClass.* present in en and ne`, () => {
      const i18nKey = DBH_CLASS_LABEL_KEYS[key];
      expect(i18nKey, `${key} has no entry in DBH_CLASS_LABEL_KEYS`).toBeTruthy();
      expect(i18nKey!.startsWith('dbhClass.'), `${key} maps outside the namespace`).toBe(true);
      expect(lookup(en, i18nKey!), `${i18nKey} missing from en.json`).toBeTruthy();
      expect(lookup(ne, i18nKey!), `${i18nKey} missing from ne.json`).toBeTruthy();
    });
  }

  it('and the values are words, not placeholders echoed back', () => {
    // The failure this whole file exists to prevent is a key that resolves to
    // itself, which renders as the literal string "dbhClass.seedling" in a table.
    // P3 found exactly that in eight live tables.
    for (const key of renderedKeys) {
      const i18nKey = DBH_CLASS_LABEL_KEYS[key]!;
      for (const [lang, bundle] of [['en', en], ['ne', ne]] as const) {
        const value = lookup(bundle, i18nKey);
        expect(value, `${lang}:${i18nKey} is empty`).toBeTruthy();
        expect(value, `${lang}:${i18nKey} echoes its own key`).not.toBe(i18nKey);
        // `toBeTruthy` above already failed if this were undefined; the join
        // keeps the type narrow without an `!` that would hide a real absence.
        expect(String(value ?? '').trim(), `${lang}:${i18nKey} is blank`).not.toBe('');
      }
    }
  });

  it('the two languages actually differ, so ne is not a copy of en', () => {
    // `keySync` proves the key *sets* match. This proves the Nepali is translated
    // rather than an English string pasted into the second bundle -- a failure
    // keySync cannot see, and one a Nepali-first application cannot afford.
    const identical = renderedKeys.filter(
      (key) => lookup(en, DBH_CLASS_LABEL_KEYS[key]!) === lookup(ne, DBH_CLASS_LABEL_KEYS[key]!),
    );
    expect(identical).toEqual([]);
  });
});

describe('D4: the lookup covers the system exactly', () => {
  it('no more keys than the database has', () => {
    // A map entry for a class the system does not contain is class knowledge
    // creeping back into the frontend, which is what P3 removed.
    const extra = Object.keys(DBH_CLASS_LABEL_KEYS).filter((k) => !renderedKeys.includes(k));
    expect(extra, `DBH_CLASS_LABEL_KEYS has keys the system lacks: ${extra.join(', ')}`).toEqual([]);
  });

  it('no fewer keys than the database has', () => {
    const missing = renderedKeys.filter((k) => !(k in DBH_CLASS_LABEL_KEYS));
    expect(missing, `classes with no word: ${missing.join(', ')}`).toEqual([]);
  });
});

describe('the colour ramp is pinned to the database', () => {
  // `lib/semanticPalettes.ts` holds a positional eight-colour ramp, which the API
  // has no opinion about -- so it is allowed to keep a local key list. This is the
  // test that makes that allowance safe: the list is asserted to be the system's
  // keys, in order, and the ramp to be the same length.
  it('DBH8_KEYS is guideline_2061, in order', async () => {
    const src = readFileSync(join(__dirname, '..', '..', 'lib', 'semanticPalettes.ts'), 'utf8');
    const keysMatch = src.match(/DBH8_KEYS\s*=\s*\[([^\]]*)\]/);
    expect(keysMatch, 'DBH8_KEYS not found in semanticPalettes.ts').toBeTruthy();
    const keys = [...keysMatch![1].matchAll(/'([^']+)'/g)].map((m) => m[1]);
    expect(keys).toEqual(renderedKeys);
  });

  it('the ramp has one colour per class', async () => {
    const src = readFileSync(join(__dirname, '..', '..', 'lib', 'semanticPalettes.ts'), 'utf8');
    const colours = src.match(/DBH8\s*=\s*\[([^\]]*)\]/);
    expect(colours, 'DBH8 not found in semanticPalettes.ts').toBeTruthy();
    expect([...colours![1].matchAll(/#[0-9a-fA-F]{3,8}/g)]).toHaveLength(renderedKeys.length);
  });
});

describe('the no-timber rule is derived, and pinned to CFMG', () => {
  // `FieldInventoryTab` greys the classes that carry no harvestable volume. That
  // used to be `i < 2`; it is now a set derived from each class's upper bound
  // against CFMG's regeneration bound. The point of pinning it here is that the
  // derivation and the database cannot disagree about where regeneration ends.
  const regenerationUpper = fixture.harvesting_cfmg.classes[0].upper;
  const expectedNoTimber = renderedKeys.filter((key) => {
    const cls = fixture[RENDERED].classes.find((c) => c.key === key)!;
    return cls.upper !== null && cls.upper <= regenerationUpper!;
  });

  it('the derived set is seedling and sapling', () => {
    expect(expectedNoTimber).toEqual(['0_4', '4_10']);
  });

  it('and it is exactly the set the component computes', async () => {
    const src = readFileSync(join(__dirname, '..', '..', 'components', 'FieldInventoryTab.tsx'), 'utf8');
    const bound = src.match(/CFMG_REGENERATION_UPPER_CM\s*=\s*(\d+)/);
    expect(bound, 'CFMG_REGENERATION_UPPER_CM not found').toBeTruthy();
    expect(Number(bound![1])).toBe(regenerationUpper);

    // Re-derive from the constant the component actually uses.
    const derived = fixture[RENDERED].classes
      .filter((c) => c.upper !== null && c.upper <= Number(bound![1]))
      .map((c) => c.key);
    expect(derived).toEqual(expectedNoTimber);
  });
});
