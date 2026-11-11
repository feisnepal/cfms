/**
 * The picker's non-text logic (§4.11): programme / unit wording keys, the map phrase, the filter chips and how
 * they combine, grouping, the browse tree, and the recently-used list — on the real master list.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildActivityIndex, searchActivities, toCatalogueActivity } from '../../../lib/activitySearch';
import {
  buildBrowseTree,
  countBy,
  filterHits,
  groupByProgramme,
  hasActiveFilters,
  mapPhrase,
  NO_FILTERS,
  programmeSlug,
  readRecent,
  rememberRecent,
  unitSlug,
  type PickerFilters,
} from '../activityCatalogue';
import { MASTER_LIST } from './masterList.fixture';

const CATALOGUE = MASTER_LIST.map(toCatalogueActivity);
const INDEX = buildActivityIndex(CATALOGUE);
const ALL = searchActivities(INDEX, '');
const CTX = { inPlan: (id: number) => id === 1 || id === 4, recent: [30, 31] };
const f = (over: Partial<PickerFilters>): PickerFilters => ({ ...NO_FILTERS, ...over });
const idsOf = (hits: { activity: { id: number } }[]) => hits.map((h) => h.activity.id);

describe('programme and unit wording keys', () => {
  it('every programme of the real master list has a plain-language note', () => {
    const programmes = [...new Set(CATALOGUE.map((a) => a.programme))];
    expect(programmes).toHaveLength(13);
    for (const p of programmes) expect(programmeSlug(p), p).not.toBeNull();
    // and no two programmes share a note
    expect(new Set(programmes.map((p) => programmeSlug(p))).size).toBe(programmes.length);
  });

  it('every unit of the real master list has a wording', () => {
    const units = [...new Set(CATALOGUE.map((a) => a.unit))];
    expect(units).toHaveLength(13);
    for (const u of units) expect(unitSlug(u), u).not.toBeNull();
  });

  it('an unknown programme or unit has no key (the picker then shows the raw text)', () => {
    expect(programmeSlug('कुनै नयाँ समूह')).toBeNull();
    expect(programmeSlug('')).toBeNull();
    expect(unitSlug('मुठा')).toBeNull();
  });
});

describe('mapPhrase', () => {
  const a = (requiresMap: boolean, mapKind: string | null) => ({ requiresMap, mapKind });

  it("follows the geometry of the activity's map symbol", () => {
    expect(mapPhrase(a(true, 'plantation'))).toBe('area');
    expect(mapPhrase(a(true, 'fire_line'))).toBe('line');
    expect(mapPhrase(a(true, 'nursery'))).toBe('point');
  });

  it('a mappable activity without a symbol is generic; the others need no map', () => {
    expect(mapPhrase(a(true, null))).toBe('generic');
    expect(mapPhrase(a(true, 'not_a_kind'))).toBe('generic');
    expect(mapPhrase(a(false, null))).toBe('none');
    expect(mapPhrase(a(false, 'nursery'))).toBe('none');
  });

  it('agrees with the master list: 60 of the 135 real activities can be mapped', () => {
    expect(CATALOGUE.filter((x) => mapPhrase(x) !== 'none')).toHaveLength(60);
  });
});

describe('filter chips', () => {
  it('no filters returns the very same list', () => {
    expect(hasActiveFilters(NO_FILTERS)).toBe(false);
    expect(filterHits(ALL, NO_FILTERS, CTX)).toBe(ALL);
  });

  it('can be shown on the map / needs no map split the list exactly', () => {
    const map = filterHits(ALL, f({ map: 'map' }), CTX);
    const none = filterHits(ALL, f({ map: 'nomap' }), CTX);
    expect(map.length + none.length).toBe(ALL.length);
    expect(map.every((h) => h.activity.requiresMap)).toBe(true);
  });

  it('several units are alternatives; a unit and a map chip combine', () => {
    const ha = filterHits(ALL, f({ units: ['हेक्टर'] }), CTX);
    const haOrKm = filterHits(ALL, f({ units: ['हेक्टर', 'कि.मि.'] }), CTX);
    expect(haOrKm.length).toBeGreaterThan(ha.length);
    const haNoMap = filterHits(ALL, f({ units: ['हेक्टर'], map: 'nomap' }), CTX);
    expect(haNoMap.every((h) => h.activity.unit === 'हेक्टर' && !h.activity.requiresMap)).toBe(true);
  });

  it('map-symbol chips select by map_kind', () => {
    const nurseries = filterHits(ALL, f({ kinds: ['nursery'] }), CTX);
    expect(idsOf(nurseries)).toEqual(expect.arrayContaining([1, 2, 62]));
    expect(nurseries.every((h) => h.activity.mapKind === 'nursery')).toBe(true);
  });

  it('in my plan / not yet in my plan', () => {
    expect(idsOf(filterHits(ALL, f({ plan: 'in' }), CTX))).toEqual([1, 4]);
    const not = filterHits(ALL, f({ plan: 'not' }), CTX);
    expect(not).toHaveLength(ALL.length - 2);
    expect(idsOf(not)).not.toContain(1);
  });

  it('recently used', () => {
    expect(idsOf(filterHits(ALL, f({ recentOnly: true }), CTX))).toEqual([30, 31]);
  });

  it('filters combine with a search', () => {
    const nursery = searchActivities(INDEX, 'nursery');
    const notInPlan = filterHits(nursery, f({ plan: 'not' }), CTX);
    expect(idsOf(notInPlan)).not.toContain(1);
    expect(idsOf(notInPlan)).toContain(2);
  });
});

describe('counts for the chips', () => {
  it('counts activities per unit, biggest first', () => {
    const units = countBy(ALL, (a) => a.unit);
    expect(units.reduce((n, u) => n + u.count, 0)).toBe(ALL.length);
    expect(units[0].count).toBeGreaterThanOrEqual(units[units.length - 1].count);
  });

  it('map-symbol counts skip activities without a symbol', () => {
    const kinds = countBy(ALL, (a) => a.mapKind);
    expect(kinds.reduce((n, k) => n + k.count, 0)).toBe(CATALOGUE.filter((a) => a.mapKind).length);
  });
});

describe('grouping and the browse tree', () => {
  it('groups results by programme without losing or repeating an activity', () => {
    const groups = groupByProgramme(ALL);
    expect(groups.flatMap((g) => idsOf(g.hits)).sort((a, b) => a - b)).toEqual(idsOf(ALL).sort((a, b) => a - b));
    expect(groups[0].programme).toBe(CATALOGUE[0].programme); // master-list order when not searching
  });

  it('puts the programme with the best hit first when searching', () => {
    const groups = groupByProgramme(searchActivities(INDEX, 'fence'));
    expect(groups[0].hits[0].score).toBeGreaterThanOrEqual(groups[groups.length - 1].hits[0].score);
  });

  it('the tree is project → programme → activity in master-list order, and totals add up', () => {
    const tree = buildBrowseTree(ALL);
    expect(tree).toHaveLength(10); // the 11th project of cf_db held only the removed test row
    expect(tree.reduce((n, p) => n + p.total, 0)).toBe(ALL.length);
    expect(tree[0].programmes).toHaveLength(4);
    expect(idsOf(tree[0].programmes[0].hits)[0]).toBe(1);
  });
});

describe('recently used (kept in this browser only)', () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('remembers newest first, without repeats, at most eight', () => {
    for (const id of [1, 2, 3, 4, 5, 6, 7, 8, 9, 2]) rememberRecent(id);
    expect(readRecent()).toEqual([2, 9, 8, 7, 6, 5, 4, 3]);
  });

  it('never throws when storage is blocked and simply keeps nothing', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readRecent()).toEqual([]);
    expect(rememberRecent(7)).toEqual([7]);
  });

  it('ignores a corrupt stored value', () => {
    window.localStorage.setItem('cfms.yearlyPlan.recentActivities', '{oops');
    expect(readRecent()).toEqual([]);
    window.localStorage.setItem('cfms.yearlyPlan.recentActivities', '"not a list"');
    expect(readRecent()).toEqual([]);
  });
});
