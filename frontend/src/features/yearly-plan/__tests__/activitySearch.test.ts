/**
 * Finding an activity (§4.11): the spelling rules, the ranking and the never-a-dead-end promise, run on the
 * REAL master list (135 active activities, as seeded in cf_db) — not on invented sample names.
 */
import { describe, expect, it } from 'vitest';
import {
  buildActivityIndex,
  fuzzyPrefix,
  highlightSegments,
  normalizeActivityText,
  searchActivities,
  suggestActivities,
  toCatalogueActivity,
  withinOneEdit,
} from '../../../lib/activitySearch';
import { MASTER_LIST } from './masterList.fixture';

const CATALOGUE = MASTER_LIST.map(toCatalogueActivity);
const INDEX = buildActivityIndex(CATALOGUE);
const ids = (q: string) => searchActivities(INDEX, q).map((h) => h.activity.id);

describe('normalizeActivityText — the usual Nepali spelling variants are one spelling', () => {
  const same: Array<[string, string]> = [
    ['वन सिमांकन', 'बन सिमांकन'], // ब / व
    ['सिमांकन', 'सिमाङ्कन'], // ं / ङ्
    ['सम्बन्धी', 'संबंधी'], // म् / न् before a consonant
    ['पूनरावलोकन', 'पुनरावलोकन'], // ू / ु
    ['नर्सरी', 'नर्सरि'], // ी / ि
    ['शसक्तिकरण', 'सषक्तिकरण'], // श / ष / स
    ['कपडाः', 'कपडा'], // visarga
    [`न${String.fromCodePoint(0x200d)}र्सरी`, 'नर्सरी'], // zero-width joiner
    ['वन  कार्ययोजना,', 'वन कार्ययोजना'], // spaces and punctuation
    ['Fire Line', 'fire line'], // Latin case
    ['वर्ष १०', 'वर्ष 10'], // Devanagari digits
  ];
  it.each(same)('%s == %s', (a, b) => {
    expect(normalizeActivityText(a)).toBe(normalizeActivityText(b));
  });

  it('keeps different words different', () => {
    expect(normalizeActivityText('काठ')).not.toBe(normalizeActivityText('दाउरा'));
    expect(normalizeActivityText('नर्सरी निर्माण')).not.toBe(normalizeActivityText('नर्सरी मर्मत'));
  });

  it('is safe on empty input', () => {
    expect(normalizeActivityText('')).toBe('');
    expect(normalizeActivityText(null)).toBe('');
    expect(normalizeActivityText(undefined)).toBe('');
    expect(normalizeActivityText(' / , ')).toBe('');
  });
});

describe('typo tolerance', () => {
  it('allows exactly one edit', () => {
    expect(withinOneEdit('nursery', 'nursary')).toBe(true); // substitution
    expect(withinOneEdit('nursery', 'nurery')).toBe(true); // deletion
    expect(withinOneEdit('nursery', 'nurssery')).toBe(true); // insertion
    expect(withinOneEdit('nursery', 'nuresry')).toBe(true); // swap of neighbours
    expect(withinOneEdit('nursery', 'nurseryy2')).toBe(false);
    expect(withinOneEdit('nursery', 'nurxxry')).toBe(false);
  });

  it('only for words of four letters or more', () => {
    expect(fuzzyPrefix('van', 'vin')).toBe(false);
    expect(fuzzyPrefix('nursary', 'nursery')).toBe(true);
  });
});

describe('golden searches on the real master list', () => {
  it('finds nurseries by the Nepali start of the word', () => {
    const found = ids('नर्स');
    for (const id of [1, 2, 41, 62, 81]) expect(found).toContain(id);
    expect(found[0]).toBe(1);
  });

  it('a full Nepali name is the first result', () => {
    expect(ids('नर्सरी निर्माण')[0]).toBe(1);
    expect(ids('वन सिमांकन')[0]).toBe(10); // the list spells it बन
    expect(ids('बन सिमाङ्कन')[0]).toBe(10);
  });

  it('every typed word must match, in any order', () => {
    expect(ids('सिमांकन वन')[0]).toBe(10);
    expect(ids('nursery build')).toContain(1);
    expect(ids('nursery build')).not.toContain(2); // the repair row has no "build"
  });

  it('English and romanised words find the Nepali activity', () => {
    expect(ids('nursery')[0]).toBe(1);
    expect(ids('nursery')).toEqual(expect.arrayContaining([2, 41, 62, 81]));
    expect(ids('timber')[0]).toBe(30);
    expect(ids('firewood')[0]).toBe(31);
    expect(ids('trail')).toEqual(expect.arrayContaining([90, 126]));
    expect(ids('ban')).toContain(10);
    expect(ids('van')).toContain(10);
    expect(ids('nurseri')).toContain(1);
  });

  it('"fire line" puts both fire-line activities in the first few results', () => {
    const top = ids('fire line').slice(0, 5);
    expect(top).toEqual(expect.arrayContaining([12, 98]));
  });

  it('typo tolerance is for when typing found nothing clean: "trail" does not also list every "training"', () => {
    const found = ids('trail');
    expect(found).toEqual(expect.arrayContaining([82, 90, 126]));
    expect(found).not.toContain(38); // an orientation training, one edit away from "trail" only by accident
    expect(found).not.toContain(41);
  });

  it('a one-letter typo in a long word still finds it', () => {
    expect(ids('nursary')).toContain(1);
    expect(ids('plantaton')).toContain(4);
    expect(ids('fensing')).toContain(18);
  });

  it('matches programme and project words too (lowest tier)', () => {
    const found = ids('प्रशासनिक'); // the administration programme
    expect(found).toEqual(expect.arrayContaining([133, 134, 135]));
  });

  it('ranks a name match above a programme-only match', () => {
    const hits = searchActivities(INDEX, 'तालिम');
    const first = hits[0].activity;
    expect(first.name).toContain('तालिम');
    // an activity found only through its programme name comes after every name match
    const lastName = hits.map((h) => h.activity.name.includes('तालिम')).lastIndexOf(true);
    const firstGroupOnly = hits.findIndex((h) => !normalizeActivityText(h.activity.name).includes('तालिम'));
    if (firstGroupOnly >= 0) expect(firstGroupOnly).toBeGreaterThan(lastName);
  });

  it('an empty query returns the whole list in master-list order', () => {
    const all = searchActivities(INDEX, '');
    expect(all).toHaveLength(CATALOGUE.length);
    expect(all.map((h) => h.activity.id)).toEqual([...CATALOGUE].map((a) => a.id).sort((a, b) => a - b));
  });
});

describe('the order is deterministic', () => {
  it('the same typing always gives the same order', () => {
    for (const q of ['nursery', 'तालिम', 'fire', 'वन', 'अन्य']) {
      expect(ids(q)).toEqual(ids(q));
    }
  });

  it('does not depend on the order the API returned the rows in', () => {
    const shuffled = buildActivityIndex([...CATALOGUE].reverse());
    for (const q of ['nursery', 'तालिम', 'fire', 'वन']) {
      expect(searchActivities(shuffled, q).map((h) => h.activity.id)).toEqual(ids(q));
    }
  });
});

describe('completeness — every activity can be found', () => {
  const swapBV = (s: string) => s.replace(/[बव]/g, (c) => (c === 'ब' ? 'व' : 'ब'));
  const longVowels = (s: string) => s.replace(/ि/g, 'ी').replace(/ु/g, 'ू');

  it('has all 135 real activities', () => {
    expect(CATALOGUE).toHaveLength(135);
  });

  it.each(CATALOGUE.map((a) => [a.id, a] as const))('#%i is found by its own name, its ब/व-swapped name and its English name', (_id, a) => {
    expect(ids(a.name)).toContain(a.id);
    expect(ids(swapBV(a.name))).toContain(a.id);
    expect(ids(longVowels(a.name))).toContain(a.id);
    expect(a.nameEn).toBeTruthy();
    expect(ids(a.nameEn as string)).toContain(a.id);
  });

  it('every activity has English search words as well', () => {
    for (const a of CATALOGUE) expect((a.searchTerms ?? '').trim().length).toBeGreaterThan(0);
  });
});

describe('two activities with the same name can always be told apart', () => {
  it('"अन्य" is two activities in two programmes', () => {
    const others = searchActivities(INDEX, 'अन्य').map((h) => h.activity).filter((a) => a.name === 'अन्य');
    expect(others.map((a) => a.id).sort((a, b) => a - b)).toEqual([119, 132]);
    expect(new Set(others.map((a) => a.programme)).size).toBe(2);
  });

  it('the repeated constitution row differs by its unit', () => {
    const rows = CATALOGUE.filter((a) => a.name === 'समूहको विधान संशोधन');
    expect(rows.map((a) => a.id)).toEqual([108, 111]);
    expect(new Set(rows.map((a) => `${a.programme}|${a.unit}`)).size).toBe(2);
  });
});

describe('never a blank panel', () => {
  it.each(['xyzqq', 'zzzz', '###', 'qwertyuiop', 'ऊऊऊऊ'])('"%s" matches nothing but still offers three suggestions', (q) => {
    const suggestions = suggestActivities(INDEX, q);
    expect(suggestions).toHaveLength(3);
    expect(new Set(suggestions.map((s) => s.id)).size).toBe(3);
  });

  it('suggestions for a near miss include the nearby activity', () => {
    const s = suggestActivities(INDEX, 'nurseries plants shop', 3).map((a) => a.id);
    expect(s.length).toBe(3);
  });

  it('suggestions are deterministic', () => {
    expect(suggestActivities(INDEX, 'qwerty').map((a) => a.id)).toEqual(
      suggestActivities(INDEX, 'qwerty').map((a) => a.id),
    );
  });
});

describe('highlightSegments', () => {
  it('marks the words the typing matched, and only those', () => {
    const segs = highlightSegments('नर्सरी निर्माण', 'नर्स');
    expect(segs.filter((s) => s.hit).map((s) => s.text)).toEqual(['नर्सरी']);
    expect(segs.map((s) => s.text).join('')).toBe('नर्सरी निर्माण');
  });

  it('matches through a spelling variant (ब/व)', () => {
    const segs = highlightSegments('बन सिमांकन', 'वन');
    expect(segs[0]).toEqual({ text: 'बन', hit: true });
  });

  it('marks nothing for an empty query and keeps the text whole', () => {
    expect(highlightSegments('नर्सरी निर्माण', '')).toEqual([{ text: 'नर्सरी निर्माण', hit: false }]);
    expect(highlightSegments('', 'x')).toEqual([]);
  });

  it('works on English text', () => {
    const segs = highlightSegments('Build a nursery', 'nurs');
    expect(segs.filter((s) => s.hit).map((s) => s.text)).toEqual(['nursery']);
  });
});
