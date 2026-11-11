import { describe, it, expect } from 'vitest';
import {
  aahQuantity, cardStatusColour, cardStatusKey, harvestDirty, harvestKey, harvestPayload, harvestProblem, initialEdit, matchesCardFilter, quantityFromShare, rangeText, shareFromQuantity,
  sourceLine, stockOf, valueOf, errorKey, reviewRow, plotSummaries, layerLabel, layerColour, PLOT_STATUS_COLOUR, draftsFor, draftIsEmpty, draftToEntry, draftProblem, overlayPending, ntfpStages,
  type HarvestEdit,
} from '../ntfp';
import type { NtfpHarvestRow } from '../../services/api';

const row = (over: Partial<NtfpHarvestRow> = {}): NtfpHarvestRow => ({
  species_key: 'zanthoxylum armatum', nepali_name: 'टिमुर', scientific_name: 'Zanthoxylum armatum', part_group: 'ङ',
  stock_fresh_kg: 1000, stock_dry_kg: 400, yield_precision_pct: 20, price: { npr_per_unit: 5, unit: 'kg', basis: 'schedule7', estimated: false, note: '' },
  plan: null, value_npr_per_year: null, ...over,
});

describe('the share-of-stock helper', () => {
  it('turns a share into a quantity and back', () => {
    expect(quantityFromShare(400, 10)).toBe(40);
    expect(quantityFromShare(333, 7)).toBe(23.31);
    expect(shareFromQuantity(400, 40)).toBe(10);
  });
  it('says nothing when the stock or the share is unknown', () => {
    expect(quantityFromShare(null, 10)).toBeNull();
    expect(quantityFromShare(400, null)).toBeNull();
    expect(shareFromQuantity(0, 5)).toBeNull();
    expect(shareFromQuantity(400, null)).toBeNull();
  });
});

describe('harvestProblem', () => {
  it('refuses a quantity above the whole stock, in kilograms only', () => {
    expect(harvestProblem(400, 401, 'kg')).toBe('exceedsStock');
    expect(harvestProblem(400, 400, 'kg')).toBeNull();
    expect(harvestProblem(400, 5000, 'piece')).toBeNull();
    expect(harvestProblem(null, 5000, 'kg')).toBeNull();     // no stock figure: the server decides
  });
  it('refuses a negative quantity and ignores an empty one', () => {
    expect(harvestProblem(400, -1, 'kg')).toBe('negative');
    expect(harvestProblem(400, null, 'kg')).toBeNull();
  });
});

describe('basis, value and the starting edit', () => {
  it('measures a quantity against the stock of its own basis', () => {
    expect(stockOf(row(), 'dry')).toBe(400);
    expect(stockOf(row(), 'fresh')).toBe(1000);
  });
  it('values a quantity at the price and rounds to paise', () => {
    expect(valueOf(40, 5)).toBe(200);
    expect(valueOf(3, 4.333)).toBe(13);
    expect(valueOf(null, 5)).toBeNull();
    expect(valueOf(40, null)).toBeNull();
  });
  it('starts a row with nothing planned, dry when dry weights exist and fresh when they do not', () => {
    expect(initialEdit(row())).toEqual({ quantity: null, basis: 'dry', price: null, unit: 'kg' });
    expect(initialEdit(row({ stock_dry_kg: null }))).toMatchObject({ basis: 'fresh' });
  });
  it('starts a planned row from the saved plan', () => {
    const planned = row({ plan: { annual_quantity: 40, unit: 'kg', weight_basis: 'fresh', price_override: 9, notes: null } });
    expect(initialEdit(planned)).toEqual({ quantity: 40, basis: 'fresh', price: 9, unit: 'kg' });
  });
  it('counts a piece-priced species in pieces', () => {
    expect(initialEdit(row({ price: { npr_per_unit: 500, unit: 'piece', basis: 'schedule7', estimated: false, note: '' } })).unit).toBe('piece');
  });
});

describe('payload and dirty state', () => {
  const rows = [row(), row({ species_key: 'bombax ceiba', part_group: 'घ' })];
  const edits = (a: Partial<HarvestEdit>): Record<string, HarvestEdit> => ({
    [harvestKey(rows[0])]: { ...initialEdit(rows[0]), ...a }, [harvestKey(rows[1])]: initialEdit(rows[1]),
  });
  it('sends only the rows with a quantity above zero', () => {
    expect(harvestPayload(rows, edits({ quantity: 40 }))).toEqual([
      { species_key: 'zanthoxylum armatum', part_group: 'ङ', annual_quantity: 40, unit: 'kg', weight_basis: 'dry', price_override: null },
    ]);
    expect(harvestPayload(rows, edits({ quantity: 0 }))).toEqual([]);
    expect(harvestPayload(rows, edits({ quantity: null }))).toEqual([]);
  });
  it('is not dirty until something differs from what is saved', () => {
    expect(harvestDirty(rows, edits({}))).toBe(false);
    expect(harvestDirty(rows, edits({ quantity: 5 }))).toBe(true);
    expect(harvestDirty(rows, edits({ quantity: null, basis: 'fresh' }))).toBe(false);   // a basis on a row with nothing planned is not a change
  });
  it('is dirty when a saved plan is cleared or its basis changes', () => {
    const saved = [row({ plan: { annual_quantity: 40, unit: 'kg', weight_basis: 'dry', price_override: null, notes: null } })];
    const k = harvestKey(saved[0]);
    expect(harvestDirty(saved, { [k]: { ...initialEdit(saved[0]), quantity: null } })).toBe(true);
    expect(harvestDirty(saved, { [k]: { ...initialEdit(saved[0]), basis: 'fresh' } })).toBe(true);
    expect(harvestDirty(saved, { [k]: initialEdit(saved[0]) })).toBe(false);
  });
});

describe('error codes', () => {
  it('maps the harvest codes to message keys', () => {
    expect(errorKey('harvest.exceeds_stock')).toBe('ntfp.harvest.errExceeds');
    expect(errorKey('harvest.nothing_planned')).toBe('ntfp.harvest.errNothingPlanned');
  });
});

describe('method-card sources', () => {
  it('shows a number, a range or nothing, with a unit', () => {
    expect(rangeText(25, null, 'm2')).toBe('25 m2');
    expect(rangeText(4, 25, 'm2')).toBe('4-25 m2');
    expect(rangeText(10, 10)).toBe('10');
    expect(rangeText(0.2891, null)).toBe('0.2891');
    expect(rangeText(null, 5)).toBe('');
  });
  it('writes the source line as key and locator (the year and title are in the tooltip)', () => {
    expect(sourceLine({ source_key: 'ANSAB2022', source_year: '2022', locator: 'Annex 3, AAH table' })).toBe('ANSAB2022, Annex 3, AAH table');
    expect(sourceLine({ source_key: 'RULE', source_year: null, locator: null })).toBe('RULE');
  });
  it('never shows a provisional or derived value as documented', () => {
    expect(cardStatusKey('provisional')).toBe('ntfp.card.statusProvisional');
    expect(cardStatusKey('derived')).toBe('ntfp.card.statusDerived');
    expect(cardStatusKey(null)).toBe('ntfp.card.statusNone');
    expect(new Set(['documented', 'derived', 'provisional', 'expert_confirmed'].map((x) => cardStatusColour(x as any))).size).toBe(4);
  });
  it('filters the species list by card status', () => {
    const rows = [{ card_status: 'documented', has_method_card: true }, { card_status: 'provisional', has_method_card: true }, { card_status: null, has_method_card: false }] as any[];
    expect(rows.filter((r) => matchesCardFilter(r, 'all')).length).toBe(3);
    expect(rows.filter((r) => matchesCardFilter(r, 'provisional')).length).toBe(1);
    expect(rows.filter((r) => matchesCardFilter(r, 'none')).length).toBe(1);
    expect(rows.filter((r) => matchesCardFilter(r, 'expert_confirmed')).length).toBe(0);
  });
  it('turns the annual allowable harvest into a quantity range of the stock', () => {
    expect(aahQuantity(400, { pct_min: 50, pct_max: 60 })).toEqual({ low: 200, high: 240 });
    expect(aahQuantity(400, { pct_min: 80, pct_max: 80 })).toEqual({ low: 320, high: 320 });
    expect(aahQuantity(null, { pct_min: 80, pct_max: 80 })).toBeNull();
    expect(aahQuantity(400, null)).toBeNull();
  });
});

describe('reviewRow', () => {
  const card = { species_key: 'a', plot_min_sqm: 4, plot_max_sqm: 25, growth_class: 'herb' } as unknown as Parameters<typeof reviewRow>[0];
  it('confirms a card when nothing differs', () => {
    expect(reviewRow(card, {})).toEqual({ species_key: 'a', confirmed: true });
    expect(reviewRow(card, { plot_min_sqm: 4, growth_class: 'herb' })).toEqual({ species_key: 'a', confirmed: true });   // typed back to the same value: no change
  });
  it('sends only the changed columns and does not confirm as it stands', () => {
    expect(reviewRow(card, { plot_min_sqm: 9, plot_max_sqm: 25 })).toEqual({ species_key: 'a', confirmed: false, plot_min_sqm: 9 });
  });
});


describe('plots on the map', () => {
  const plots = [
    { plot_number: 1, stratum: 'a', transect: 1, longitude: 0, latitude: 0, species_keys: ['x', 'y'] },
    { plot_number: 2, stratum: 'a', transect: 1, longitude: 0, latitude: 0, species_keys: ['x'] },
    { plot_number: 3, stratum: 'a', transect: 1, longitude: 0, latitude: 0, species_keys: ['x'] },
  ];
  const obs = (plot: number, key: string, n: number) => ({ plot_number: plot, species_key: key, count_total: n, weights: [] }) as unknown as Parameters<typeof plotSummaries>[1][number];
  const s = plotSummaries(plots, [obs(1, 'x', 4), obs(2, 'x', 0)]);

  it('says none, partly or all recorded, and counts the plants', () => {
    expect([s[1].status, s[2].status, s[3].status]).toEqual(['partial', 'done', 'none']);
    expect([s[1].recorded, s[1].assigned, s[1].plants, s[2].plants]).toEqual([1, 2, 4, 0]);
  });
  it('writes the value on the icon for the chosen layer', () => {
    expect(layerLabel('status', s[1])).toBe('1/2');
    expect(layerLabel('count', s[1])).toBe('4');
    expect(layerLabel('count', s[3])).toBe('');
    expect(layerLabel('species:x', s[2])).toBe('0');                 // looked for and found none is a value
    expect(layerLabel('species:y', s[1])).toBe('');                  // not surveyed is empty
  });
  it('colours by status, and a count layer by the share of the largest count; not surveyed is grey', () => {
    expect(layerColour('status', s[3], 0)).toBe(PLOT_STATUS_COLOUR.none);
    expect(layerColour('status', s[2], 0)).toBe(PLOT_STATUS_COLOUR.done);
    expect(layerColour('count', s[3], 4)).toBe(PLOT_STATUS_COLOUR.none);
    expect(layerColour('count', s[2], 4)).toBe('#eeeeee');           // zero plants
    expect(layerColour('count', s[1], 4)).toBe('rgb(27,94,32)');     // the largest count: the darkest green
  });
});

describe('entering a plot', () => {
  const stored = [{ plot_number: 1, species_key: 'x', visit_date: '2026-10-20', count_total: 5, count_mature: 2, count_small: null, clumps: null, tillers: null, notes: null, source: 'manual',
    weights: [{ sample_no: 1, part_group: null, fresh_weight_g: 800, dry_weight_g: 300, notes: null }] }] as unknown as Parameters<typeof draftsFor>[1];

  it('starts from what is stored and leaves other species empty', () => {
    const [x, y] = draftsFor(['x', 'y'], stored);
    expect([x.count_total, x.visit_date, x.weights]).toEqual([5, '2026-10-20', [{ fresh: 800, dry: 300 }]]);
    expect(draftIsEmpty(y)).toBe(true);
  });
  it('sends an empty draft as just its key (the server clears the record) and numbers the weights', () => {
    const [x, y] = draftsFor(['x', 'y'], stored);
    expect(draftToEntry(y)).toEqual({ species_key: 'y', weights: [] });
    expect(draftToEntry({ ...x, weights: [{ fresh: 10, dry: null }, { fresh: null, dry: null }, { fresh: 20, dry: 5 }] }).weights).toEqual([
      { sample_no: 1, fresh_weight_g: 10, dry_weight_g: null }, { sample_no: 2, fresh_weight_g: 20, dry_weight_g: 5 }]);
  });
  it('hints at the obvious mistakes before saving', () => {
    const [x] = draftsFor(['x'], stored);
    expect(draftProblem(x)).toBeNull();
    expect(draftProblem({ ...x, count_total: null })).toBe('ntfp.entry.needTotal');
    expect(draftProblem({ ...x, count_mature: 4, count_small: 3 })).toBe('ntfp.entry.partsExceed');
    expect(draftProblem({ ...x, weights: [{ fresh: 5, dry: 9 }] })).toBe('ntfp.entry.dryExceeds');
    expect(draftProblem({ ...x, count_total: 0, count_mature: null, weights: [{ fresh: 5, dry: null }] })).toBe('ntfp.entry.weighNothing');
  });
});

describe('overlayPending', () => {
  const rec = (plot: number, key: string, n: number) => ({ plot_number: plot, species_key: key, visit_date: null, count_total: n, count_mature: null, count_small: null, clumps: null, tillers: null, notes: null, source: 'manual', weights: [] }) as unknown as Parameters<typeof overlayPending>[0][number];
  it('lays a plot saved offline over what is stored: its species replace the stored ones, an empty species is gone', () => {
    const stored = [rec(1, 'x', 4), rec(1, 'y', 2), rec(2, 'x', 9)];
    const out = overlayPending(stored, [{ plotNumber: 1, entries: [{ species_key: 'x', count_total: 7, weights: [{ fresh_weight_g: 800, dry_weight_g: 300 }] }, { species_key: 'y', weights: [] }] }]);
    expect(out.map((o) => [o.plot_number, o.species_key, o.count_total])).toEqual([[2, 'x', 9], [1, 'x', 7]]);   // y was cleared; plot 2 untouched
    expect(out.find((o) => o.species_key === 'x' && o.plot_number === 1)!.weights).toEqual([{ sample_no: 1, part_group: null, fresh_weight_g: 800, dry_weight_g: 300, notes: null }]);
  });
  it('leaves the records alone when nothing is waiting', () => {
    const stored = [rec(1, 'x', 4)];
    expect(overlayPending(stored, [])).toBe(stored);
  });
});

describe('ntfpStages: where the survey stands', () => {
  const base = { picked: 0, designSpecies: 0, plots: 0, hasDesign: false, recorded: 0, assigned: 0, plannedRows: null as number | null };
  const by = (i: Partial<typeof base>) => Object.fromEntries(ntfpStages({ ...base, ...i }).map((s) => [s.key, s.status]));

  it('starts at choosing species, with everything after it waiting', () => {
    expect(by({})).toEqual({ species: 'current', design: 'locked', collect: 'locked', results: 'locked', harvest: 'locked' });
  });
  it('moves on to the plots once species are picked', () => {
    expect(by({ picked: 3 })).toEqual({ species: 'current', design: 'todo', collect: 'locked', results: 'locked', harvest: 'locked' });
  });
  it('has the species and the design done once the design is saved, and asks for findings next', () => {
    const s = ntfpStages({ ...base, hasDesign: true, designSpecies: 3, plots: 36, assigned: 108 });
    expect(s.map((x) => x.status)).toEqual(['done', 'done', 'current', 'locked', 'locked']);
    expect(s[0].params).toEqual({ n: 3 });
    expect(s[1].params).toEqual({ n: 36 });
    expect(s[2].detailKey).toBe('ntfp.stage.collectNone');
  });
  it('shows partial progress while findings are coming in, and unlocks the results and the harvest', () => {
    const s = ntfpStages({ ...base, hasDesign: true, designSpecies: 3, plots: 36, assigned: 108, recorded: 40 });
    expect(s.map((x) => x.status)).toEqual(['done', 'done', 'current', 'done', 'todo']);
    expect(s[2]).toMatchObject({ detailKey: 'ntfp.stage.collectPartly', params: { done: 40, all: 108 } });
  });
  it('marks the findings done when every pair is recorded, and the harvest current until one is planned', () => {
    const s = ntfpStages({ ...base, hasDesign: true, designSpecies: 3, plots: 36, assigned: 108, recorded: 108 });
    expect(s.map((x) => x.status)).toEqual(['done', 'done', 'done', 'done', 'current']);
    expect(s[4].detailKey).toBe('ntfp.stage.harvestNone');
  });
  it('is all done when a harvest is planned', () => {
    const s = ntfpStages({ ...base, hasDesign: true, designSpecies: 3, plots: 36, assigned: 108, recorded: 108, plannedRows: 2 });
    expect(s.map((x) => x.status)).toEqual(['done', 'done', 'done', 'done', 'done']);
    expect(s[4]).toMatchObject({ detailKey: 'ntfp.stage.harvestDone', params: { n: 2 } });
  });
  it('never claims a plan it has not read', () => {
    const s = ntfpStages({ ...base, hasDesign: true, designSpecies: 1, plots: 3, assigned: 3, recorded: 3, plannedRows: null });
    expect(s[4].status).toBe('current');
  });
  it('has exactly one current stage, or none when everything is done', () => {
    for (const i of [{}, { picked: 2 }, { hasDesign: true, assigned: 4, recorded: 1 }, { hasDesign: true, assigned: 4, recorded: 4 }]) {
      expect(ntfpStages({ ...base, ...i }).filter((s) => s.status === 'current').length).toBe(1);
    }
    expect(ntfpStages({ ...base, hasDesign: true, assigned: 4, recorded: 4, plannedRows: 1 }).some((s) => s.status === 'current')).toBe(false);
  });
});
