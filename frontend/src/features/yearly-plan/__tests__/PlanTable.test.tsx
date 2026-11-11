/**
 * Table B — the Yearly Plan on the map (P4, YA-4.1): one row per plan line, whether or not the activity has a
 * place on the map, in the words of the catalogue, with a Features | Plan switch above it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import en from '../../../i18n/locales/en.json';

vi.mock('react-i18next', () => {
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
  const t = (key: string, values: Record<string, unknown> = {}): string => {
    const node = lookup(key);
    if (typeof node !== 'string') return key;
    return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, name) => String(values[name] ?? ''));
  };
  return { useTranslation: () => ({ t, i18n: { language: 'en' } }) };
});
vi.mock('../../../i18n/numberFormat', () => ({
  formatNumber: (n: number) => String(n),
  formatDecimal: (n: number) => String(n),
}));
vi.mock('../../../services/api', () => ({ yearlyPlanApi: { getPlan: vi.fn(), confirmLine: vi.fn() } }));

import { yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { PlanTable, TableViewSwitch } from '../PlanTable';

const getPlan = (yearlyPlanApi as unknown as { getPlan: ReturnType<typeof vi.fn> }).getPlan;
const confirmLine = (yearlyPlanApi as unknown as { confirmLine: ReturnType<typeof vi.fn> }).confirmLine;

/** ten year cells; `f(year)` gives [quantity, budget] */
const matrix = (f: (year: number) => [number, number]) =>
  Array.from({ length: 10 }, (_, i) => {
    const [quantity, budget] = f(i + 1);
    return { year: i + 1, quantity, budget, planned: quantity > 0 || budget > 0, has_row: true };
  });

const line = (over: Partial<YearlyPlanLine>): YearlyPlanLine => ({
  id: 'L1',
  potential_activity_id: 1,
  activity: 'Main nursery',
  program: 'Forest development',
  unit: 'no.',
  requires_map: true,
  default_quantity: 1,
  default_yearly_budget: 5000,
  years: matrix((y) => (y === 4 ? [0, 0] : [1, 5000])),
  planned_years: [1, 2, 3, 5, 6, 7, 8, 9, 10],
  total_budget: 20000,
  version: 1,
  reviewed_at: null,
  placeholder_fields: [],
  feature_count: 2,
  location_mode: 'places',
  assign_to_all_blocks: false,
  status: 'planned',
  notes: null,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe('PlanTable', () => {
  it('shows one row per plan line, including an activity that needs no map', async () => {
    getPlan.mockResolvedValue({
      total_budget: 45000,
      lines: [
        line({ id: 'L1' }),
        line({ id: 'L2', activity: 'Scholarship', program: 'Community', requires_map: false, feature_count: 0, planned_years: [1, 2, 3, 4, 5], total_budget: 25000 }),
      ],
    });
    render(<PlanTable calculationId="c1" />);
    expect(await screen.findByText('Main nursery')).toBeInTheDocument();
    expect(screen.getByText('Scholarship')).toBeInTheDocument();
    const rows = screen.getAllByRole('row').filter((r) => r.hasAttribute('data-row-key'));
    expect(rows).toHaveLength(2);
    // one column per plan year
    for (const y of ['Y1', 'Y5', 'Y10']) expect(screen.getAllByText(y).length).toBeGreaterThan(0); // (the sticky header repeats titles)
  });

  it('the Location cell says what applies: places with their units, the whole forest, or not shown yet', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        line({ id: 'P', activity: 'Aaa', feature_count: 3, location_mode: 'places', location_units: ['C-1', 'C-3'] }),
        line({ id: 'W', activity: 'Bbb', feature_count: 0, location_mode: 'whole_forest' }),
        line({ id: 'U', activity: 'Ccc', feature_count: 0, location_mode: 'needs_location' }),
      ],
    });
    render(<PlanTable calculationId="c1" onSelectPlaces={vi.fn()} onShowOnMap={vi.fn()} />);
    await screen.findByText('Aaa');
    expect(screen.getByTestId('select-places-P').textContent).toBe('Places: 3');
    expect(screen.getByTestId('location-units-P').textContent).toBe('In C-1, C-3');
    expect(screen.getByTestId('whole-forest-W').textContent).toBe('Whole forest');
    const cellU = within(document.querySelector('[data-row-key="U"]') as HTMLElement).getAllByRole('cell')[15];
    expect(cellU.textContent).toContain('Not shown on the map yet');
    expect(screen.getByTestId('show-on-map-U')).toBeInTheDocument();
  });

  it('blocks chosen for an activity, with no place drawn, are named (and the row does not say "not shown yet")', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ id: 'U', feature_count: 0, location_mode: 'units', location_units: ['C-1', 'C-3'] })],
    });
    render(<PlanTable calculationId="c1" onShowOnMap={vi.fn()} />);
    await screen.findByText('Main nursery');
    expect(screen.getByTestId('assigned-units-U').textContent).toBe('In C-1, C-3');
    expect(screen.queryByTestId('show-on-map-U')).toBeNull();
    expect(screen.queryByText('Not shown on the map yet')).toBeNull();
  });

  it('an activity that needs no map has an empty Location cell — no words, no button', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ id: 'M', activity: 'Bbb', requires_map: false, feature_count: 0, location_mode: 'not_applicable' })],
    });
    render(<PlanTable calculationId="c1" onSelectPlaces={vi.fn()} onShowOnMap={vi.fn()} />);
    await screen.findByText('Bbb');
    const cell = within(document.querySelector('[data-row-key="M"]') as HTMLElement).getAllByRole('cell')[15]; // Location
    expect(cell.textContent).toBe('');
    expect(screen.queryByTestId('select-places-M')).toBeNull();
    expect(screen.queryByTestId('show-on-map-M')).toBeNull();
  });

  it('"Show on the map" opens the questions for that activity', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'U', feature_count: 0, location_mode: 'needs_location' })] });
    const onShow = vi.fn();
    render(<PlanTable calculationId="c1" onShowOnMap={onShow} />);
    await screen.findByText('Main nursery');
    fireEvent.click(screen.getByTestId('show-on-map-U'));
    expect(onShow).toHaveBeenCalledTimes(1);
    expect(onShow.mock.calls[0][0].id).toBe('U');
  });

  it('never rounds a quantity to a whole number and shows a zero budget as 0', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ default_quantity: 0.5, default_yearly_budget: 0, total_budget: 0, unit: 'ha' })],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    const cells = within(document.querySelector('[data-row-key="L1"]') as HTMLElement).getAllByRole('cell');
    expect(cells[3].textContent).toBe('0.5');
    expect(cells[4].textContent).toBe('0');
    expect(cells[16].textContent).toBe('0');
  });

  it('says how many activities and the whole budget, and lists them by programme then name', async () => {
    getPlan.mockResolvedValue({
      total_budget: 30000,
      lines: [
        line({ id: 'Z', activity: 'Zeta', program: 'B', total_budget: 10000 }),
        line({ id: 'A', activity: 'Alpha', program: 'A', total_budget: 20000 }),
      ],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Alpha');
    expect(screen.getByTestId('plan-table-summary').textContent).toBe('Activities in the plan: 2 · Total NPR 30000');
    const order = screen.getAllByRole('row').filter((r) => r.hasAttribute('data-row-key')).map((r) => r.getAttribute('data-row-key'));
    expect(order).toEqual(['A', 'Z']);
  });

  it('shows quantity above budget in a planned year and a dimmed dash where nothing is planned', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ id: 'G', years: matrix((y) => (y <= 2 ? [3, 7000] : [0, 0])) })],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    const y1 = screen.getByTestId('year-G-1');
    expect(y1).toHaveAttribute('data-planned', 'true');
    expect(y1.textContent).toBe('37000');
    expect(y1).toHaveAttribute('title', 'Year 1: quantity 3, budget NPR 7000');
    const y3 = screen.getByTestId('year-G-3');
    expect(y3).toHaveAttribute('data-planned', 'false');
    expect(y3.textContent).toBe('—');
    expect(y3).toHaveAttribute('title', 'Year 3: nothing planned');
  });

  it('shows a real zero when only one of the two is zero (voluntary work / money with no countable output)', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ id: 'Z', years: matrix((y) => (y === 1 ? [5, 0] : y === 2 ? [0, 5000] : [0, 0])) })],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    expect(screen.getByTestId('year-Z-1')).toHaveAttribute('data-planned', 'true');
    expect(screen.getByTestId('year-Z-1').textContent).toBe('50'); // quantity 5, budget 0
    expect(screen.getByTestId('year-Z-2')).toHaveAttribute('data-planned', 'true');
    expect(screen.getByTestId('year-Z-2').textContent).toBe('05000'); // quantity 0, budget 5000
    expect(screen.getByTestId('year-Z-3')).toHaveAttribute('data-planned', 'false');
  });

  it('explains the grid in one line', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({})] });
    render(<PlanTable calculationId="c1" />);
    expect((await screen.findByTestId('plan-table-grid-hint')).textContent).toContain('A dimmed “—” means nothing is planned');
  });

  it('the place count of a plan line selects its places on the map', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'S', feature_count: 3, location_mode: 'places' })] });
    const onSelect = vi.fn();
    render(<PlanTable calculationId="c1" onSelectPlaces={onSelect} />);
    await screen.findByText('Main nursery');
    fireEvent.click(screen.getByTestId('select-places-S'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].id).toBe('S');
  });

  it('never hides places that exist, even on an activity that needs no map', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'X', requires_map: false, feature_count: 2, location_mode: 'places' })] });
    render(<PlanTable calculationId="c1" onSelectPlaces={vi.fn()} />);
    await screen.findByText('Main nursery');
    expect(screen.getByTestId('select-places-X').textContent).toBe('Places: 2');
  });

  it('a line still at the starting numbers is tagged, says which, and can be confirmed', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        line({ id: 'Q', activity: 'Qqq', placeholder_fields: ['quantity'] }),
        line({ id: 'B', activity: 'Bbb', placeholder_fields: ['budget'] }),
        line({ id: 'A', activity: 'Aaa', placeholder_fields: ['budget', 'quantity'] }),
      ],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Qqq');
    expect(screen.getByTestId('review-badge-Q')).toHaveAttribute('title', expect.stringContaining('quantity is still the starting value (1)'));
    expect(screen.getByTestId('review-badge-B')).toHaveAttribute('title', expect.stringContaining('budget is still the starting value'));
    expect(screen.getByTestId('review-badge-A')).toHaveAttribute('title', expect.stringContaining('quantity and the budget are still'));
    expect(screen.getByTestId('review-badge-Q').textContent).toBe('Starting numbers');
    expect(screen.getByTestId('review-confirm-Q').textContent).toBe('These numbers are right');
  });

  it('confirming sends the line and its version, re-reads the plan and tells the host', async () => {
    getPlan
      .mockResolvedValueOnce({ total_budget: 0, lines: [line({ id: 'C', version: 7, placeholder_fields: ['quantity', 'budget'] })] })
      .mockResolvedValueOnce({ total_budget: 0, lines: [line({ id: 'C', version: 8, placeholder_fields: [], reviewed_at: '2026-09-21T00:00:00Z' })] });
    confirmLine.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<PlanTable calculationId="c1" onPlanChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId('review-confirm-C'));
    await waitFor(() => expect(confirmLine).toHaveBeenCalledWith('c1', 'C', 7));
    expect(await screen.findByTestId('review-confirmed-C')).toBeInTheDocument();
    expect(screen.queryByTestId('review-badge-C')).toBeNull();
    expect(getPlan).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('a failed confirm changes nothing: the tag stays, the plan is not re-read, the host is not told', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'F', placeholder_fields: ['quantity'] })] });
    confirmLine.mockRejectedValue(new Error('boom'));
    const onChanged = vi.fn();
    render(<PlanTable calculationId="c1" onPlanChanged={onChanged} />);
    fireEvent.click(await screen.findByTestId('review-confirm-F'));
    await waitFor(() => expect(confirmLine).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('review-confirm-F')).not.toBeDisabled());
    expect(screen.getByTestId('review-badge-F')).toBeInTheDocument();
    expect(getPlan).toHaveBeenCalledTimes(1);
    expect(onChanged).not.toHaveBeenCalled();
  });

  it('a confirmed line says so, and a line with real numbers that was never confirmed is quiet', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        line({ id: 'K', activity: 'Kkk', reviewed_at: '2026-09-21T00:00:00Z', placeholder_fields: [] }),
        line({ id: 'R', activity: 'Rrr', reviewed_at: null, placeholder_fields: [] }),
      ],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Kkk');
    expect(screen.getByTestId('review-confirmed-K').textContent).toBe('Confirmed');
    expect(screen.queryByTestId('review-badge-K')).toBeNull();
    const cellR = within(document.querySelector('[data-row-key="R"]') as HTMLElement).getAllByRole('cell')[17]; // Review
    expect(cellR.textContent).toBe('');
  });

  describe('width', () => {
    const observers: Array<{ el: Element | null; cb: (e: unknown[]) => void }> = [];
    class FakeResizeObserver {
      el: Element | null = null;
      cb: (e: unknown[]) => void;
      constructor(cb: (e: unknown[]) => void) {
        this.cb = cb;
        observers.push(this);
      }
      observe(el: Element) {
        this.el = el;
      }
      unobserve() {}
      disconnect() {}
    }
    const original = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    beforeEach(() => {
      observers.length = 0;
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = FakeResizeObserver;
    });
    afterEach(() => {
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = original;
    });
    const resizeTo = (width: number) => {
      const mine = observers.find((o) => (o.el as HTMLElement | null)?.getAttribute('data-testid') === 'plan-table');
      expect(mine).toBeTruthy();
      act(() => mine!.cb([{ contentRect: { width } }]));
    };

    it('pins the Activity column only when the table has room — in a narrow panel it would cover everything', async () => {
      getPlan.mockResolvedValue({ total_budget: 0, lines: [line({})] });
      render(<PlanTable calculationId="c1" />);
      await screen.findByText('Main nursery');
      const pinned = () => document.querySelectorAll('.ant-table-cell-fix-start').length;
      expect(pinned()).toBeGreaterThan(0); // no width known yet: assume there is room
      resizeTo(300); // the 20 % dock
      await waitFor(() => expect(pinned()).toBe(0));
      resizeTo(1200); // the wide view
      await waitFor(() => expect(pinned()).toBeGreaterThan(0));
    });
  });

  it('"Wider view" opens the same table in a large panel, which has no wider-view button of its own', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'W' })] });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    expect(screen.getAllByTestId('plan-table')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('plan-table-expand'));
    await waitFor(() => expect(screen.getAllByTestId('plan-table')).toHaveLength(2));
    expect(screen.getAllByTestId('plan-table-expand')).toHaveLength(1); // only the side panel's
    expect(getPlan).toHaveBeenCalledTimes(2); // the wide copy read the plan itself
  });

  it('acting on the map from the wide view closes it so the map is free', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'M', feature_count: 2, location_mode: 'places' })] });
    const onSelect = vi.fn();
    render(<PlanTable calculationId="c1" onSelectPlaces={onSelect} />);
    await screen.findByText('Main nursery');
    fireEvent.click(screen.getByTestId('plan-table-expand'));
    await waitFor(() => expect(screen.getAllByTestId('select-places-M')).toHaveLength(2));
    fireEvent.click(screen.getAllByTestId('select-places-M')[1]); // the copy in the panel
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0][0].id).toBe('M');
    await waitFor(() => expect(screen.getAllByTestId('select-places-M')).toHaveLength(1));
  });

  it('for someone who is not the owner (the plan routes answer 404) it says so plainly and offers nothing to press', async () => {
    getPlan.mockRejectedValue({ response: { status: 404 } });
    render(<PlanTable calculationId="c1" onAddActivity={vi.fn()} />);
    const message = await screen.findByTestId('plan-table-not-owner');
    expect(message.textContent).toBe('Only the owner of this forest can see and change its yearly plan.');
    expect(screen.queryByTestId('plan-table-failed')).toBeNull(); // not "could not be loaded"
    expect(screen.queryByTestId('plan-table-add')).not.toBeVisible();
    expect(screen.queryByTestId('plan-table-loading')).toBeNull();
  });

  it('"Open full plan" is offered only where the host gives it, and calls the host', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({})] });
    const open = vi.fn();
    const { unmount } = render(<PlanTable calculationId="c1" onOpenFullPlan={open} />);
    fireEvent.click(await screen.findByTestId('plan-table-full-plan'));
    expect(open).toHaveBeenCalledTimes(1);
    unmount();
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    expect(screen.queryByTestId('plan-table-full-plan')).toBeNull();
  });

  it('offers what the drawn places measure when it differs from the quantity — and applies nothing by itself', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [line({ id: 'M', default_quantity: 1, unit: 'km', measured_quantity: 2.35 })],
    });
    render(<PlanTable calculationId="c1" />);
    await screen.findByText('Main nursery');
    expect(screen.getByTestId('measured-hint-M').textContent).toContain('Drawn on the map: 2.35 km');
    expect(screen.getByTestId('default-quantity-M').textContent).toBe('1'); // the number is untouched
  });

  it('shows no hint when the drawing agrees, when nothing can be measured, or when the table is read-only', async () => {
    getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        line({ id: 'A', activity: 'Aaa', default_quantity: 2.35, measured_quantity: 2.35 }),
        line({ id: 'B', activity: 'Bbb', measured_quantity: null }),
        line({ id: 'C', activity: 'Ccc' }), // the field is absent (an older server)
      ],
    });
    const { unmount } = render(<PlanTable calculationId="c1" />);
    await screen.findByText('Aaa');
    for (const id of ['A', 'B', 'C']) expect(screen.queryByTestId(`measured-hint-${id}`)).toBeNull();
    unmount();
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ id: 'R', measured_quantity: 9 })] });
    render(<PlanTable calculationId="c1" readOnly />);
    await screen.findByText('Main nursery');
    expect(screen.queryByTestId('measured-hint-R')).toBeNull();
  });

  it('an empty plan points at the Add activity button', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [] });
    const onAdd = vi.fn();
    render(<PlanTable calculationId="c1" onAddActivity={onAdd} />);
    expect(await screen.findByTestId('plan-table-empty')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('plan-table-add'));
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it('a failed read says nothing was changed and can be retried', async () => {
    getPlan.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({ total_budget: 0, lines: [line({})] });
    render(<PlanTable calculationId="c1" />);
    const failed = await screen.findByTestId('plan-table-failed');
    expect(failed.textContent).toContain('Nothing was changed');
    expect(failed.textContent).not.toContain('boom');
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText('Main nursery')).toBeInTheDocument();
  });

  it('reads the plan again when the map or the wizard changes it', async () => {
    getPlan.mockResolvedValue({ total_budget: 0, lines: [line({})] });
    const { rerender } = render(<PlanTable calculationId="c1" refreshKey="1:0" />);
    await screen.findByText('Main nursery');
    expect(getPlan).toHaveBeenCalledTimes(1);
    rerender(<PlanTable calculationId="c1" refreshKey="1:1" />);
    await waitFor(() => expect(getPlan).toHaveBeenCalledTimes(2));
  });
});

describe('TableViewSwitch', () => {
  it('offers the two views and reports the one chosen', () => {
    const onChange = vi.fn();
    render(<TableViewSwitch value="features" onChange={onChange} />);
    expect(screen.getByText('Places on the map')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Yearly plan'));
    expect(onChange).toHaveBeenCalledWith('plan');
  });
});
