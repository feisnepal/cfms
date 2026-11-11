/**
 * The add-activity wizard card (P3, YA-3.1–3.9) on the real master list and the real English catalogue:
 * one question at a time, the path each kind of activity takes, the numbers, and what is saved.
 */
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { message } from 'antd';
import en from '../../../i18n/locales/en.json';
import { MASTER_LIST } from './masterList.fixture';

const lookup = (key: string): unknown =>
  key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
const t = (key: string, values: Record<string, unknown> = {}): string => {
  const node = lookup(key);
  if (typeof node !== 'string') return (values.defaultValue as string) ?? key;
  return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
};
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t, i18n: { language: 'en' } }) }));
vi.mock('../../../i18n/hooks', () => ({ useT: () => t }));
vi.mock('../../../i18n/numberFormat', () => ({
  formatNumber: (n: number) => n.toLocaleString('en'),
  formatDecimal: (n: number) => String(n),
  parseLocaleNumber: (s: string) => (s.trim() === '' ? NaN : Number(s.replace(/,/g, ''))),
}));
vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { addLine: vi.fn(), createFeature: vi.fn(), updateLine: vi.fn() },
}));

import { yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { ActivityWizard } from '../wizard/ActivityWizard';
import { useActivityWizard, type WizardController } from '../wizard/useActivityWizard';

const api = yearlyPlanApi as unknown as Record<'addLine' | 'createFeature' | 'updateLine', ReturnType<typeof vi.fn>>;

const line = (over: Partial<YearlyPlanLine> = {}): YearlyPlanLine => ({
  id: 'L1',
  potential_activity_id: 1,
  activity: 'नर्सरी निर्माण',
  program: 'P',
  unit: 'वटा',
  requires_map: true,
  default_quantity: 2,
  default_yearly_budget: 20000,
  years: [1, 2, 3].map((year) => ({ year, quantity: 2, budget: 20000, planned: true, has_row: true })),
  planned_years: [1, 2, 3],
  total_budget: 60000,
  version: 4,
  reviewed_at: '2026-09-21T00:00:00Z',
  placeholder_fields: [],
  feature_count: 1,
  location_mode: 'places',
  assign_to_all_blocks: false,
  status: 'proposed',
  notes: null,
  ...over,
});

let controller: WizardController;
const onSaved = vi.fn();
const onOpenPlan = vi.fn();

const Harness: React.FC<{ lines?: YearlyPlanLine[] }> = ({ lines = [] }) => {
  controller = useActivityWizard();
  return (
    <>
      <button data-testid="open" onClick={() => controller.openWizard()} />
      <ActivityWizard
        controller={controller}
        calculationId="c1"
        activities={MASTER_LIST}
        lines={lines}
        onSaved={onSaved}
        onOpenPlan={onOpenPlan}
      />
    </>
  );
};

function start(lines: YearlyPlanLine[] = []) {
  render(<Harness lines={lines} />);
  fireEvent.click(screen.getByTestId('open'));
  return screen.getByTestId('activity-wizard');
}

/** Find an activity in the picker by a word and press its Choose (or Open) button. */
function pickActivity(id: number, word: string) {
  fireEvent.change(screen.getByTestId('activity-search'), { target: { value: word } });
  fireEvent.click(screen.getByTestId(`activity-row-${id}`));
}

const type = (testId: string, value: string) => fireEvent.change(screen.getByTestId(testId), { target: { value } });
const next = () => fireEvent.click(screen.getByTestId('wizard-next'));
const step = () => screen.getByTestId('activity-wizard').getAttribute('data-step');
const draw = (geometry: GeoJSON.Geometry) => act(() => controller.addPlace({ geometry }));
const POINT: GeoJSON.Geometry = { type: 'Point', coordinates: [85.05, 27.44] };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  api.addLine.mockResolvedValue({ plan_line: { id: 'L9', version: 1 }, created_plan_line: true, unit: 'पटक' });
  api.createFeature.mockResolvedValue({ plan_line: { id: 'L9', version: 1 } });
  api.updateLine.mockResolvedValue({ plan_line: { id: 'L9', version: 2 } });
  vi.spyOn(message, 'success').mockImplementation((() => undefined) as never);
  vi.spyOn(message, 'error').mockImplementation((() => undefined) as never);
});

describe('opening and the first question', () => {
  it('is closed until opened, then asks WHAT with the finder', () => {
    render(<Harness />);
    expect(screen.queryByTestId('activity-wizard')).toBeNull();
    fireEvent.click(screen.getByTestId('open'));
    expect(step()).toBe('what');
    expect(screen.getByText('What do you want to do?')).toBeInTheDocument();
    expect(screen.getByTestId('activity-picker')).toBeInTheDocument();
    expect(screen.queryByTestId('wizard-next')).toBeNull(); // choosing an activity is what moves on
  });

  it('can be closed', () => {
    start();
    fireEvent.click(screen.getByTestId('wizard-close'));
    expect(screen.queryByTestId('activity-wizard')).toBeNull();
  });
});

describe('an activity that needs no map (training)', () => {
  it('goes WHEN → HOW MUCH → CONFIRM with no place question, and saves one plan line', async () => {
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    expect(step()).toBe('when');
    expect(screen.getByTestId('wizard-progress').textContent).toBe('Step 2 of 4');
    expect(screen.queryByTestId('wizard-where')).toBeNull();

    fireEvent.click(screen.getByTestId('preset-first5'));
    for (const y of [1, 2, 3, 4, 5]) expect(screen.getByTestId(`when-year-${y}`)).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('when-year-6')).toHaveAttribute('aria-pressed', 'false');
    next();

    expect(step()).toBe('howMuch');
    expect(screen.getByText('Quantity (पटक)')).toBeInTheDocument(); // the unit is always shown
    expect(screen.getByTestId('wizard-next')).toBeDisabled();
    type('numbers-quantity', '3');
    type('numbers-budget', '15000');
    expect(screen.getByTestId('numbers-total').textContent).toBe('Total for 1–5 — NPR 75,000');
    next();

    expect(step()).toBe('confirm');
    expect(screen.getByTestId('confirm-sentence').textContent).toBe(
      'नर्सरी व्यवस्थापन तालिम · Years 1–5 · NPR 15,000 a year — NPR 75,000 in total',
    );
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.addLine).toHaveBeenCalledTimes(1));
    expect(api.addLine).toHaveBeenCalledWith('c1', { potential_activity_id: 41, years: [1, 2, 3, 4, 5], quantity: 3, budget: 15000 });
    expect(api.createFeature).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByTestId('activity-wizard')).toBeNull());
    expect(onSaved).toHaveBeenCalled();
  });

  it('a budget of 0 is accepted and explained', () => {
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    next();
    type('numbers-quantity', '1');
    type('numbers-budget', '0');
    expect(screen.getByTestId('numbers-zero').textContent).toContain('nothing is spent');
    expect(screen.getByTestId('wizard-next')).not.toBeDisabled();
  });

  it('numbers are checked: quantity above 0, budget 0 or more', () => {
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    next();
    type('numbers-quantity', '0');
    type('numbers-budget', '100');
    expect(screen.getByTestId('numbers-invalid')).toBeInTheDocument();
    expect(screen.getByTestId('wizard-next')).toBeDisabled();
  });

  it('warns before saving a very large amount (the plan check will not, for a line the person typed)', () => {
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    next();
    type('numbers-quantity', '1');
    type('numbers-budget', '2500000');
    expect(screen.getByTestId('numbers-unusual').textContent).toContain('NPR 2,500,000');
    type('numbers-budget', '900000');
    expect(screen.queryByTestId('numbers-unusual')).toBeNull();
  });

  it('warns when the amount is far above the other activities', () => {
    const others = [10000, 20000, 30000].map((budget, i) =>
      line({ id: `O${i}`, potential_activity_id: 100 + i, years: [{ year: 1, quantity: 1, budget, planned: true, has_row: true }] }),
    );
    start(others);
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    next();
    type('numbers-quantity', '1');
    type('numbers-budget', '500000'); // 25 x the median of 20,000
    expect(screen.getByTestId('numbers-unusual')).toBeInTheDocument();
  });

  it('different numbers each year: a row per chosen year, and they are sent in the same request', async () => {
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    fireEvent.click(screen.getByTestId('when-year-2')); // years 1 and 2
    next();
    fireEvent.click(screen.getByTestId('numbers-different'));
    type('grid-quantity-1', '1');
    type('grid-budget-1', '1000');
    type('grid-quantity-2', '3');
    type('grid-budget-2', '9000');
    expect(screen.getByTestId('numbers-total').textContent).toBe('Total for 1, 2 — NPR 10,000');
    next();
    expect(screen.getByTestId('confirm-sentence').textContent).toContain('NPR 10,000 in total (differs by year)');
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.addLine).toHaveBeenCalled());
    const body = api.addLine.mock.calls[0][1];
    expect(body.year_values).toEqual([
      { year: 1, quantity: 1, budget: 1000 },
      { year: 2, quantity: 3, budget: 9000 },
    ]);
  });
});

describe('a mappable activity (nursery)', () => {
  it('asks WHERE, offers the three answers, and tells how to draw', () => {
    start();
    pickActivity(1, 'nursery');
    expect(step()).toBe('where');
    expect(screen.getByTestId('where-map')).toBeInTheDocument();
    expect(screen.getByTestId('where-whole')).toBeInTheDocument();
    expect(screen.getByTestId('where-later')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('where-map'));
    expect(screen.getByText('Click the map to place it. You can add more places.')).toBeInTheDocument();
    expect(screen.queryByTestId('shape-point')).toBeNull(); // a nursery is always a point: no shape to choose
    expect(controller.armedGeom).toBe('point'); // the map is told which tool to arm
    expect(screen.getByTestId('wizard-next')).toBeDisabled(); // nothing drawn yet
  });

  it('a drawn place is counted, can be removed, and unlocks Next; the quantity is pre-filled from the drawing', async () => {
    start();
    pickActivity(1, 'nursery');
    fireEvent.click(screen.getByTestId('where-map'));
    draw(POINT);
    draw({ type: 'Point', coordinates: [85.06, 27.44] });
    expect(screen.getByText('Places drawn: 2')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('remove-place-1'));
    expect(screen.getByText('Places drawn: 1')).toBeInTheDocument();
    next(); // WHEN
    expect(step()).toBe('when');
    next(); // HOW MUCH
    expect((screen.getByTestId('numbers-quantity') as HTMLInputElement).value).toBe('1');
    expect(screen.getByTestId('numbers-measured').textContent).toContain('Drawn: 1');
    type('numbers-budget', '30000');
    next(); // NAME
    expect(step()).toBe('name');
    type('name-input', 'Main nursery');
    next(); // CONFIRM
    expect(screen.getByTestId('confirm-sentence').textContent).toBe(
      'Main nursery · Years 1 · Places: 1 · NPR 30,000 a year — NPR 30,000 in total',
    );
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.createFeature).toHaveBeenCalledTimes(1));
    const body = api.createFeature.mock.calls[0][1];
    expect(body).toMatchObject({ potential_activity_id: 1, feature_type: 'point', years: [1], name: 'Main nursery', quantity: 1, budget: 30000 });
    expect(JSON.parse(body.geometry)).toEqual(POINT);
    expect(api.addLine).not.toHaveBeenCalled();
  });

  it('several places: each is saved, the first carrying the numbers', async () => {
    start();
    pickActivity(1, 'nursery');
    fireEvent.click(screen.getByTestId('where-map'));
    draw(POINT);
    draw({ type: 'Point', coordinates: [85.06, 27.44] });
    next();
    next();
    type('numbers-budget', '1000');
    next();
    next(); // skip through NAME
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.createFeature).toHaveBeenCalledTimes(2));
    expect(api.createFeature.mock.calls[0][1].feature_type).toBe('point');
  });

  it('"It applies to the whole forest" needs nothing drawn and is sent as such', async () => {
    start();
    pickActivity(1, 'nursery');
    fireEvent.click(screen.getByTestId('where-whole'));
    next();
    next();
    type('numbers-quantity', '1');
    type('numbers-budget', '4000');
    next();
    expect(screen.getByTestId('confirm-sentence').textContent).toContain('Applies to the whole forest');
    expect(screen.queryByTestId('wizard-name')).toBeNull();
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.addLine).toHaveBeenCalled());
    expect(api.addLine.mock.calls[0][1]).toMatchObject({ potential_activity_id: 1, whole_forest: true });
  });

  it('"Decide later" skips the drawing and saves the activity without a place', async () => {
    start();
    pickActivity(1, 'nursery');
    fireEvent.click(screen.getByTestId('wizard-skip'));
    expect(step()).toBe('when');
    next();
    type('numbers-quantity', '2');
    type('numbers-budget', '500');
    next();
    expect(screen.getByTestId('confirm-sentence').textContent).toContain('Place to be decided later');
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.addLine).toHaveBeenCalled());
    expect(api.addLine.mock.calls[0][1].whole_forest).toBeUndefined();
  });

  it('an activity with no fixed shape lets the person choose the shape to draw', () => {
    start();
    pickActivity(8, 'operational plan'); // a mappable activity with no map symbol
    fireEvent.click(screen.getByTestId('where-map'));
    expect(controller.armedGeom).toBe('polygon');
    fireEvent.click(screen.getByTestId('shape-line'));
    expect(controller.armedGeom).toBe('line');
  });

  it('"Back" keeps what was answered', () => {
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    fireEvent.click(screen.getByTestId('preset-every'));
    next();
    type('numbers-quantity', '2');
    fireEvent.click(screen.getByTestId('wizard-back'));
    expect(step()).toBe('when');
    expect(screen.getByTestId('when-year-10')).toHaveAttribute('aria-pressed', 'true');
    next();
    expect((screen.getByTestId('numbers-quantity') as HTMLInputElement).value).toBe('2');
  });
});

describe('an activity already in the plan', () => {
  it('a mappable one skips the numbers and goes straight to "show where" (no "decide later")', async () => {
    start([line()]);
    pickActivity(1, 'nursery');
    expect(step()).toBe('where');
    expect(screen.queryByTestId('where-later')).toBeNull();
    fireEvent.click(screen.getByTestId('where-map'));
    draw(POINT);
    next(); // NAME
    expect(step()).toBe('name');
    next();
    expect(screen.getByTestId('confirm-sentence').textContent).toBe('नर्सरी निर्माण · One more place for an activity already in your plan · Places: 1');
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.createFeature).toHaveBeenCalledTimes(1));
    const body = api.createFeature.mock.calls[0][1];
    expect(body.years).toEqual([1, 2, 3]); // the line's own planned years
    expect(body).not.toHaveProperty('quantity');
    expect(message.success).toHaveBeenCalledWith('Saved. Places added: 1.');
  });

  it('one that needs no map says so and points to the yearly plan instead of adding it twice', () => {
    start([line({ id: 'L41', potential_activity_id: 41, requires_map: false, location_mode: 'not_applicable' })]);
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    expect(step()).toBe('what');
    const note = screen.getByTestId('wizard-in-plan');
    expect(note.textContent).toContain('already in your plan');
    fireEvent.click(within(note).getByRole('button', { name: 'Open the yearly plan' }));
    expect(onOpenPlan).toHaveBeenCalled();
    expect(api.addLine).not.toHaveBeenCalled();
  });

  it('"Save and add another" comes back to WHERE for the same activity without asking the numbers again', async () => {
    start();
    pickActivity(1, 'nursery');
    fireEvent.click(screen.getByTestId('where-map'));
    draw(POINT);
    next();
    next();
    type('numbers-budget', '1000');
    next();
    next();
    fireEvent.click(screen.getByTestId('wizard-save-add'));
    await waitFor(() => expect(api.createFeature).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(step()).toBe('where'));
    expect(screen.getByTestId('where-map')).toBeInTheDocument();
    expect(screen.queryByTestId('where-later')).toBeNull(); // the line exists now
    expect(screen.getByText('Nothing drawn yet.')).toBeInTheDocument();
  });
});

describe('when saving goes wrong', () => {
  it('a failed save keeps every answer and says nothing was lost', async () => {
    api.addLine.mockRejectedValue(new Error('offline'));
    start();
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    next();
    type('numbers-quantity', '2');
    type('numbers-budget', '700');
    next();
    fireEvent.click(screen.getByTestId('wizard-save'));
    const failed = await screen.findByTestId('confirm-failed');
    expect(failed.textContent).toContain('Could not save');
    expect(failed.textContent).not.toContain('offline');
    expect(screen.getByTestId('activity-wizard')).toBeInTheDocument();
    // the answers are still there: go back and see them
    fireEvent.click(screen.getByTestId('wizard-back'));
    expect((screen.getByTestId('numbers-budget') as HTMLInputElement).value).toBe('700');
    // and saving again works
    api.addLine.mockResolvedValue({ plan_line: { id: 'L9', version: 1 }, created_plan_line: true, unit: 'पटक' });
    next();
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(screen.queryByTestId('activity-wizard')).toBeNull());
  });

  it('when only some places fail, the rest are saved and a retry sends only the failed ones', async () => {
    api.createFeature
      .mockResolvedValueOnce({ plan_line: { id: 'L9', version: 1 } })
      .mockRejectedValueOnce(new Error('x'))
      .mockResolvedValueOnce({ plan_line: { id: 'L9', version: 1 } });
    start();
    pickActivity(1, 'nursery');
    fireEvent.click(screen.getByTestId('where-map'));
    draw(POINT);
    draw({ type: 'Point', coordinates: [85.06, 27.44] });
    next();
    next();
    type('numbers-budget', '1000');
    next();
    next();
    fireEvent.click(screen.getByTestId('wizard-save'));
    const failed = await screen.findByTestId('confirm-failed');
    expect(failed.textContent).toContain('Some places could not be saved (1)');
    expect(api.createFeature).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByTestId('wizard-save'));
    await waitFor(() => expect(api.createFeature).toHaveBeenCalledTimes(3)); // only the failed one again
    await waitFor(() => expect(screen.queryByTestId('activity-wizard')).toBeNull());
  });
});

describe('draw first, then say what it is', () => {
  it('a place drawn while the card is closed opens it, keeps the place, and asks WHAT', () => {
    render(<Harness />);
    act(() => controller.addPlace({ geometry: POINT }));
    expect(screen.getByTestId('activity-wizard')).toBeInTheDocument();
    expect(step()).toBe('what');
    pickActivity(1, 'nursery');
    expect(step()).toBe('where'); // a nursery is mappable: the drawn place is kept
    expect(screen.getByText('Places drawn: 1')).toBeInTheDocument();
  });

  it('but a place is dropped when the chosen activity needs no map', () => {
    render(<Harness />);
    act(() => controller.addPlace({ geometry: POINT }));
    pickActivity(41, 'नर्सरी व्यवस्थापन तालिम');
    expect(step()).toBe('when');
    expect(controller.state.places).toEqual([]);
  });
});
