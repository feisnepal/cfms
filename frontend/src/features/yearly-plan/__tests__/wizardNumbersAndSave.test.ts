/**
 * The wizard's numbers (measuring, per-year amounts, the unusual-amount hint — P3, YA-3.6 / 3.9) and how a
 * finished wizard becomes requests (YA-3.8).
 */
import { describe, expect, it, vi } from 'vitest';
import type { CatalogueActivity } from '../../../lib/activitySearch';
import { initialWizard, type WizardState } from '../wizard/wizardMachine';
import {
  isUnusualAmount,
  measureKind,
  measuredText,
  measurePlaces,
  peakBudgetOf,
  totalBudgetOf,
  yearAmounts,
} from '../wizard/wizardNumbers';
import { buildWizardPlan, runWizardPlan, type WizardApi } from '../wizard/wizardSave';

const parse = (t: string) => (t.trim() === '' ? NaN : Number(t.replace(/,/g, '')));

const activity = (over: Partial<CatalogueActivity> = {}): CatalogueActivity => ({
  id: 1,
  name: 'नर्सरी निर्माण',
  nameEn: 'Build a nursery',
  searchTerms: null,
  programme: 'P',
  project: 'P',
  unit: 'वटा',
  requiresMap: true,
  mapKind: 'nursery',
  description: null,
  ...over,
});

const state = (over: Partial<WizardState> = {}): WizardState => ({
  ...initialWizard(),
  activity: activity(),
  years: [1, 2, 3],
  quantity: '2',
  budget: '20000',
  where: 'map',
  places: [{ geometry: { type: 'Point', coordinates: [85, 27] } }],
  ...over,
});

// ~1.1 km x ~1.1 km square near Kathmandu (about 120 ha) and a ~1.1 km line
const SQUARE: GeoJSON.Geometry = {
  type: 'Polygon',
  coordinates: [[[85, 27], [85.01, 27], [85.01, 27.01], [85, 27.01], [85, 27]]],
};
const LINE: GeoJSON.Geometry = { type: 'LineString', coordinates: [[85, 27], [85.01, 27]] };

describe('measuring the drawn places', () => {
  it('knows which units a drawing can measure', () => {
    expect(measureKind('हेक्टर')).toBe('ha');
    expect(measureKind('कि.मि.')).toBe('km');
    expect(measureKind('वटा')).toBe('count');
    expect(measureKind('स्थान')).toBe('count');
    expect(measureKind('पटक')).toBeNull();
    expect(measureKind(null)).toBeNull();
  });

  it('polygons measure hectares, lines measure kilometres, and places are counted', () => {
    const ha = measurePlaces([{ geometry: SQUARE }], 'हेक्टर');
    expect(ha).toBeGreaterThan(90);
    expect(ha).toBeLessThan(130);
    const km = measurePlaces([{ geometry: LINE }], 'कि.मि.');
    expect(km).toBeGreaterThan(0.9);
    expect(km).toBeLessThan(1.1);
    expect(measurePlaces([{ geometry: LINE }, { geometry: LINE }, { geometry: LINE }], 'वटा')).toBe(3);
  });

  it('several places add up; a drawing that cannot be measured for the unit gives nothing', () => {
    const one = measurePlaces([{ geometry: SQUARE }], 'हेक्टर') as number;
    expect(measurePlaces([{ geometry: SQUARE }, { geometry: SQUARE }], 'हेक्टर')).toBeCloseTo(one * 2, 5);
    expect(measurePlaces([{ geometry: LINE }], 'हेक्टर')).toBeNull(); // a line has no area
    expect(measurePlaces([{ geometry: SQUARE }], 'पटक')).toBeNull();
    expect(measurePlaces([], 'हेक्टर')).toBeNull();
  });

  it('a measured amount is shown without trailing zeros and never rounded to a whole number', () => {
    expect(measuredText(2.4)).toBe('2.4');
    expect(measuredText(0.5)).toBe('0.5');
    expect(measuredText(3)).toBe('3');
    expect(measuredText(1.23456)).toBe('1.235');
  });
});

describe('per-year amounts and totals', () => {
  it('"same every year" uses the typed numbers for every chosen year', () => {
    const amounts = yearAmounts(state(), parse);
    expect(amounts).toEqual([
      { year: 1, quantity: 2, budget: 20000 },
      { year: 2, quantity: 2, budget: 20000 },
      { year: 3, quantity: 2, budget: 20000 },
    ]);
    expect(totalBudgetOf(amounts)).toBe(60000);
    expect(peakBudgetOf(amounts)).toBe(20000);
  });

  it('"different each year" uses each year\'s own numbers', () => {
    const amounts = yearAmounts(
      state({ same: false, years: [1, 2], yearValues: { 1: { quantity: '1', budget: '1000' }, 2: { quantity: '3', budget: '9000' } } }),
      parse,
    );
    expect(totalBudgetOf(amounts)).toBe(10000);
    expect(peakBudgetOf(amounts)).toBe(9000);
  });

  it('text that is not a number counts as 0, so the live total never shows NaN', () => {
    expect(totalBudgetOf(yearAmounts(state({ budget: 'abc' }), parse))).toBe(0);
  });
});

describe('the unusual-amount hint (same thresholds as the plan-health check)', () => {
  it('more than NPR 10,00,000 a year is unusual', () => {
    expect(isUnusualAmount(1_000_001, [])).toBe(true);
    expect(isUnusualAmount(1_000_000, [])).toBe(false);
  });

  it('more than 20 times the median of the other activities is unusual — once there are three others', () => {
    expect(isUnusualAmount(500_000, [10_000, 20_000, 30_000])).toBe(true); // 20 x 20,000 = 400,000
    expect(isUnusualAmount(300_000, [10_000, 20_000, 30_000])).toBe(false);
    expect(isUnusualAmount(500_000, [10_000, 20_000])).toBe(false); // too few to compare
  });

  it('uses the middle of an even-sized list', () => {
    expect(isUnusualAmount(410_000, [10_000, 10_000, 30_000, 30_000])).toBe(true); // median 20,000
  });
});

describe('what the wizard sends', () => {
  it('an activity that needs no map: one plan-line request with the numbers, never a place', () => {
    const plan = buildWizardPlan(state({ activity: activity({ id: 41, requiresMap: false, unit: 'पटक' }), where: null, places: [] }), parse);
    expect(plan.features).toEqual([]);
    expect(plan.line).toEqual({ potential_activity_id: 41, years: [1, 2, 3], quantity: 2, budget: 20000 });
  });

  it('"whole forest" is sent as such; "decide later" is just the line', () => {
    const whole = buildWizardPlan(state({ where: 'whole', places: [] }), parse);
    expect(whole.line).toMatchObject({ whole_forest: true });
    const later = buildWizardPlan(state({ where: 'later', places: [] }), parse);
    expect(later.line?.whole_forest).toBeUndefined();
  });

  it('places: one feature request each, carrying the years, the name and the numbers', () => {
    const plan = buildWizardPlan(
      state({ name: ' Nursery A ', places: [{ geometry: { type: 'Point', coordinates: [85, 27] } }, { geometry: { type: 'Point', coordinates: [85.1, 27] } }] }),
      parse,
    );
    expect(plan.line).toBeUndefined();
    expect(plan.features).toHaveLength(2);
    expect(plan.features[0]).toMatchObject({ potential_activity_id: 1, feature_type: 'point', years: [1, 2, 3], name: 'Nursery A', quantity: 2, budget: 20000 });
    expect(JSON.parse(plan.features[1].geometry).coordinates).toEqual([85.1, 27]);
  });

  it('an activity already in the plan sends no numbers and uses the line\'s own years', () => {
    const plan = buildWizardPlan(state({ existing: { id: 'L1', version: 2, years: [1, 2], wholeForest: false }, years: [1, 2] }), parse);
    expect(plan.features[0]).not.toHaveProperty('quantity');
    expect(plan.features[0].years).toEqual([1, 2]);
  });

  it('different each year: the individual years travel separately after the line exists', () => {
    const plan = buildWizardPlan(
      state({ same: false, years: [1, 2], yearValues: { 1: { quantity: '1', budget: '1000' }, 2: { quantity: '3', budget: '9000' } } }),
      parse,
    );
    expect(plan.yearValues).toEqual([
      { year: 1, quantity: 1, budget: 1000 },
      { year: 2, quantity: 3, budget: 9000 },
    ]);
    // the line is created with the first year's numbers
    expect(plan.features[0]).toMatchObject({ quantity: 1, budget: 1000 });
  });

  it('a no-place line with different numbers each year sends them in the same request', () => {
    const plan = buildWizardPlan(
      state({ activity: activity({ requiresMap: false }), where: null, places: [], same: false, years: [1, 2], yearValues: { 1: { quantity: '1', budget: '1' }, 2: { quantity: '2', budget: '2' } } }),
      parse,
    );
    expect(plan.line?.year_values).toHaveLength(2);
  });

  it('refuses an unfinished wizard', () => {
    expect(() => buildWizardPlan(initialWizard(), parse)).toThrow();
    expect(() => buildWizardPlan(state({ places: [{ geometry: { type: 'MultiPoint', coordinates: [[1, 1]] } }] }), parse)).toThrow(/unsupported/);
  });
});

describe('running a save', () => {
  const line = (id = 'L1', version = 1) => ({ plan_line: { id, version } });
  const api = (over: Partial<WizardApi> = {}): WizardApi & { addLine: ReturnType<typeof vi.fn>; createFeature: ReturnType<typeof vi.fn>; updateLine: ReturnType<typeof vi.fn> } =>
    ({
      addLine: vi.fn().mockResolvedValue(line()),
      createFeature: vi.fn().mockResolvedValue(line()),
      updateLine: vi.fn().mockResolvedValue(line('L1', 2)),
      ...over,
    }) as never;

  it('a plan without places is one request', async () => {
    const a = api();
    const out = await runWizardPlan(buildWizardPlan(state({ where: 'later', places: [] }), parse), a);
    expect(out).toMatchObject({ ok: true, lineId: 'L1', failedPlaces: [] });
    expect(a.addLine).toHaveBeenCalledTimes(1);
    expect(a.createFeature).not.toHaveBeenCalled();
  });

  it('places are sent in order, and a different-each-year plan then updates the line once', async () => {
    const a = api();
    const plan = buildWizardPlan(
      state({ same: false, years: [1, 2], yearValues: { 1: { quantity: '1', budget: '1' }, 2: { quantity: '2', budget: '2' } }, places: [{ geometry: { type: 'Point', coordinates: [1, 1] } }, { geometry: { type: 'Point', coordinates: [2, 2] } }] }),
      parse,
    );
    const out = await runWizardPlan(plan, a);
    expect(out.ok).toBe(true);
    expect(a.createFeature).toHaveBeenCalledTimes(2);
    expect(a.updateLine).toHaveBeenCalledTimes(1);
    expect(a.updateLine.mock.calls[0][0]).toBe('L1');
    expect(out.version).toBe(2);
  });

  it('a place that fails is reported, the others still save, and a retry sends only the failed one', async () => {
    const boom = new Error('offline');
    const a = api({ createFeature: vi.fn().mockResolvedValueOnce(line()).mockRejectedValueOnce(boom).mockResolvedValueOnce(line()).mockResolvedValueOnce(line()) } as never);
    const plan = buildWizardPlan(
      state({ places: [{ geometry: { type: 'Point', coordinates: [1, 1] } }, { geometry: { type: 'Point', coordinates: [2, 2] } }, { geometry: { type: 'Point', coordinates: [3, 3] } }] }),
      parse,
    );
    const first = await runWizardPlan(plan, a);
    expect(first).toMatchObject({ ok: false, failedPlaces: [1], error: boom });
    expect(a.createFeature).toHaveBeenCalledTimes(3);

    const retry = await runWizardPlan(plan, a, first.failedPlaces);
    expect(a.createFeature).toHaveBeenCalledTimes(4); // just the one that failed
    expect(retry.ok).toBe(true);
  });

  it('the individual years are not updated while a place is still missing', async () => {
    const a = api({ createFeature: vi.fn().mockRejectedValue(new Error('x')) } as never);
    const plan = buildWizardPlan(
      state({ same: false, years: [1], yearValues: { 1: { quantity: '1', budget: '1' } } }),
      parse,
    );
    const out = await runWizardPlan(plan, a);
    expect(out.ok).toBe(false);
    expect(a.updateLine).not.toHaveBeenCalled();
  });

  it('a failed plan-line request is reported, never thrown', async () => {
    const boom = new Error('409');
    const a = api({ addLine: vi.fn().mockRejectedValue(boom) } as never);
    const out = await runWizardPlan(buildWizardPlan(state({ where: 'later', places: [] }), parse), a);
    expect(out).toMatchObject({ ok: false, error: boom, lineId: null });
  });
});
