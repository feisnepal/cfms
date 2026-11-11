/**
 * The DBH class list comes from the API, and the words come from the i18n bundle.
 *
 * DBH_SSOT_PLAN P3, on the owner's decision: structure from the database, words
 * from the translations. The two halves have different owners -- an editor in the
 * translations page cannot write to `dbh_class_systems`, and a boundary that
 * disagrees between the two produces wrong per-hectare figures -- so they are
 * sourced separately on purpose.
 *
 * These tests also cover a live defect found while doing this work: the bundled
 * `GUIDELINE_2061` pointed at `dbhClass.*` i18n keys that **did not exist in
 * either bundle**, and eight Results tables rendered `t('dbhClass.seedling')`.
 * i18next returns the key string for a missing key, so those tables showed the
 * literal text `dbhClass.seedling`. The unit tests missed it because they mock
 * `useT` as the identity function, so a missing key and a present one look
 * identical in the output. `test_every_mapped_label_key_exists` is the assertion
 * that would have caught it, and it reads the real bundles rather than a mock.
 */
import { describe, it, expect } from 'vitest';
import en from '../../i18n/locales/en.json';
import ne from '../../i18n/locales/ne.json';
import {
  DBH_CLASS_LABEL_KEYS,
  DEFAULT_SYSTEM,
  type DbhClassDef,
} from '../../constants/dbhClasses';
import { resolveClassLabel, toDbhClassDef, type ApiDbhClass } from '../useDbhClasses';

/** The eight `guideline_2061` classes as the API sends them. */
const API_CLASSES: ApiDbhClass[] = [
  { key: '0_4', lower: 0, upper: 4, label_en: 'Seedling', label_np: 'बिरुवा', stand_type: 'Regeneration' },
  { key: '4_10', lower: 4, upper: 10, label_en: 'Sapling', label_np: 'लाथ्रा', stand_type: 'Sapling' },
  { key: '10_20', lower: 10, upper: 20, label_en: 'Small Pole', label_np: 'सानो खाँवा', stand_type: 'Pole' },
  { key: '20_30', lower: 20, upper: 30, label_en: 'Large Pole', label_np: 'ठुलो खाँवा', stand_type: 'Pole' },
  { key: '30_40', lower: 30, upper: 40, label_en: 'Small Tree', label_np: 'सानो रुख', stand_type: 'Tree' },
  { key: '40_50', lower: 40, upper: 50, label_en: 'Medium Tree', label_np: 'मझौला रुख', stand_type: 'Tree' },
  { key: '50_60', lower: 50, upper: 60, label_en: 'Large Tree', label_np: 'ठुलो रुख', stand_type: 'Tree' },
  { key: '60_plus', lower: 60, upper: null, label_en: 'Very Large Tree', label_np: 'अति ठुलो रुख', stand_type: 'Tree' },
];

/** Reads a dotted path out of a bundle, so a missing key is a value, not a crash. */
function lookup(bundle: any, path: string): string | undefined {
  return path.split('.').reduce<any>((acc, k) => (acc == null ? undefined : acc[k]), bundle);
}

describe('the class list is not bundled any more', () => {
  it('the constants module exports no class array', async () => {
    const mod = await import('../../constants/dbhClasses');
    const classArrays = Object.keys(mod).filter((k) =>
      /^(GUIDELINE_|DFO_|CLASSES$)/.test(k),
    );
    expect(classArrays).toEqual([]);
  });

  it('and no colour map that embeds one either', async () => {
    const mod = await import('../../constants/dbhClasses');
    // A colour map that also carries key/lower/upper/label is a class list
    // wearing a disguise, and it is exactly what P3 removes.
    for (const name of ['COMPARTMENT_LEGEND_COLORS', 'TREE_MARKER_CONFIG']) {
      expect(Object.keys(mod)).not.toContain(name);
    }
  });
});

describe('toDbhClassDef', () => {
  it('maps every field the components consume', () => {
    const cls = toDbhClassDef(API_CLASSES[2]);
    expect(cls).toMatchObject({
      key: '10_20',
      lower: 10,
      upper: 20,
      labelEn: 'Small Pole',
      labelNp: 'सानो खाँवा',
      standType: 'Pole',
    });
  });

  it('preserves an open upper bound as null, not Infinity', () => {
    // `Infinity` would render inside a range label as a number; `undefined` would
    // read as "the data was incomplete". Neither is what the database said.
    const top = toDbhClassDef(API_CLASSES[7]);
    expect(top.upper).toBeNull();
    expect(Number.isFinite(top.upper as unknown as number)).toBe(false);
  });

  it('coerces numeric bounds, so a string from the API cannot break sorting', () => {
    const cls = toDbhClassDef({ ...API_CLASSES[0], lower: '0' as unknown as number });
    expect(cls.lower).toBe(0);
    expect(typeof cls.lower).toBe('number');
  });

  it('leaves labelKey undefined for a class with no curated translation', () => {
    const cls = toDbhClassDef({
      key: 'mature_tree', lower: 40, upper: null,
      label_en: 'Mature Tree', label_np: 'परिपक्व रुख', stand_type: 'Tree',
    });
    expect(cls.labelKey).toBeUndefined();
  });
});

describe('every mapped label key exists in both bundles', () => {
  // The assertion the old test could not make, because it mocked `useT` and a
  // missing key then looked exactly like a present one.
  for (const [classKey, i18nKey] of Object.entries(DBH_CLASS_LABEL_KEYS)) {
    it(`${classKey} -> ${i18nKey}`, () => {
      expect(lookup(en, i18nKey), `${i18nKey} missing from en.json`).toBeTruthy();
      expect(lookup(ne, i18nKey), `${i18nKey} missing from ne.json`).toBeTruthy();
    });
  }

  it('covers exactly the eight guideline_2061 classes', () => {
    // A map that grows entries for other systems would be re-introducing class
    // knowledge in the frontend, which is what this phase removed.
    expect(Object.keys(DBH_CLASS_LABEL_KEYS).sort()).toEqual(
      API_CLASSES.map((c) => c.key).sort(),
    );
  });
});

describe('resolveClassLabel', () => {
  const t = (k: string) => `t:${k}`;

  it('uses the curated i18n key when there is one', () => {
    const cls = toDbhClassDef(API_CLASSES[0]);
    expect(resolveClassLabel(cls, t, false)).toBe('t:dbhClass.seedling');
    expect(resolveClassLabel(cls, t, true)).toBe('t:dbhClass.seedling');
  });

  it('falls back to the API label, not to a guess', () => {
    // The old default was `t(c.labelKey ?? 'dbhClass.seedling')`, and that key
    // exists in no bundle -- so a class without a curated key rendered the
    // literal text "dbhClass.seedling".
    const cls: DbhClassDef = {
      key: 'mature_tree', lower: 40, upper: null,
      labelEn: 'Mature Tree', labelNp: 'परिपक्व रुख',
    };
    expect(resolveClassLabel(cls, t, false)).toBe('Mature Tree');
    expect(resolveClassLabel(cls, t, true)).toBe('परिपक्व रुख');
  });

  it('never returns a raw i18n key', () => {
    // A guard, in the spirit of P0: whatever happens, the reader must not see
    // "dbhClass.something" in a table cell.
    const realT = (k: string) => lookup(en, k) ?? k;
    for (const api of API_CLASSES) {
      for (const nepali of [false, true]) {
        const label = resolveClassLabel(toDbhClassDef(api), realT, nepali);
        expect(label).not.toMatch(/^[a-zA-Z]+\.[a-zA-Z]+$/);
      }
    }
  });
});

describe('the default system', () => {
  it('is guideline_2061, the system the Results tables are written in', () => {
    expect(DEFAULT_SYSTEM).toBe('guideline_2061');
  });
});
