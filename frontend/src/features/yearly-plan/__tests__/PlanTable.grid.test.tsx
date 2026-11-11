/**
 * The spreadsheet grid of the Yearly Activities step (owner, 2026-10-15): one number per year cell, typed into directly;
 * Enter saves and goes down, a block copied from Excel fills cells from where it is pasted, and the budget of each year is
 * added up at the foot.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  parseLocaleNumber: (s: string) => (String(s).trim() === '' ? NaN : Number(String(s).replace(/,/g, ''))),
}));
vi.mock('../../../services/api', () => ({
  yearlyPlanApi: { getPlan: vi.fn(), updateLine: vi.fn(), confirmLine: vi.fn(), addLine: vi.fn() },
  yearlyActivitiesApi: { deleteProposedActivity: vi.fn() },
}));

import { yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { PlanTable } from '../PlanTable';

const api = yearlyPlanApi as unknown as Record<'getPlan' | 'updateLine', ReturnType<typeof vi.fn>>;

const years = (q: number, b: number) =>
  Array.from({ length: 10 }, (_, i) => ({ year: i + 1, quantity: q, budget: b, planned: q > 0 || b > 0, has_row: true }));
const line = (id: string, name: string, q: number, b: number, over: Partial<YearlyPlanLine> = {}): YearlyPlanLine => ({
  id,
  potential_activity_id: id === 'A' ? 1 : 2,
  activity: name,
  program: 'Programme',
  unit: 'ha',
  requires_map: false,
  default_quantity: q || 1,
  default_yearly_budget: b,
  years: years(q, b),
  planned_years: q > 0 || b > 0 ? [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] : [],
  total_budget: b * 10,
  version: 4,
  reviewed_at: '2026-10-01T00:00:00Z',
  placeholder_fields: [],
  feature_count: 0,
  location_mode: 'not_applicable',
  assign_to_all_blocks: false,
  status: 'planned',
  notes: null,
  ...over,
});

const A = line('A', 'Alpha plantation', 2, 100);
const B = line('B', 'Beta fire line', 1, 50);

beforeEach(() => {
  vi.clearAllMocks();
  api.getPlan.mockResolvedValue({ total_budget: 0, lines: [A, B] });
  api.updateLine.mockImplementation(async (_c: string, id: string, edit: { years?: { year: number; quantity?: number }[] }) => ({
    plan_line: id === 'A' ? A : B,
    filled_years: [],
    edit,
  }));
});

async function loaded(props: Record<string, unknown> = {}) {
  render(<PlanTable calculationId="c1" gridMode {...props} />);
  await screen.findByText('Alpha plantation');
}

describe('the year cells', () => {
  it('are inputs showing the quantity, or the budget once the switch says so', async () => {
    await loaded();
    expect((screen.getByTestId('year-input-A-1') as HTMLInputElement).value).toBe('2');
    fireEvent.click(screen.getByText('Budget'));
    await waitFor(() => expect((screen.getByTestId('year-input-A-1') as HTMLInputElement).value).toBe('100'));
  });

  it('are not inputs outside the grid (the map keeps its panel)', async () => {
    await loaded({ gridMode: false });
    expect(screen.queryByTestId('year-input-A-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('year-edit-A-1')).toBeInTheDocument();
  });
});

describe('typing', () => {
  it('Enter saves the number and moves down to the next row', async () => {
    await loaded();
    const cell = screen.getByTestId('year-input-A-3') as HTMLInputElement;
    fireEvent.focus(cell);
    fireEvent.change(cell, { target: { value: '7' } });
    fireEvent.keyDown(cell, { key: 'Enter' });
    await waitFor(() =>
      expect(api.updateLine).toHaveBeenCalledWith('c1', 'A', { years: [{ year: 3, quantity: 7 }], expected_version: 4 }),
    );
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('year-input-B-3')));
  });

  it('on the budget view it saves the budget', async () => {
    await loaded();
    fireEvent.click(screen.getByText('Budget'));
    const cell = (await screen.findByTestId('year-input-A-2')) as HTMLInputElement;
    fireEvent.focus(cell);
    fireEvent.change(cell, { target: { value: '250' } });
    fireEvent.keyDown(cell, { key: 'Enter' });
    await waitFor(() =>
      expect(api.updateLine).toHaveBeenCalledWith('c1', 'A', { years: [{ year: 2, budget: 250 }], expected_version: 4 }),
    );
  });

  it('something that is not a number is refused and nothing is saved', async () => {
    await loaded();
    const cell = screen.getByTestId('year-input-A-1') as HTMLInputElement;
    fireEvent.focus(cell);
    fireEvent.change(cell, { target: { value: 'abc' } });
    fireEvent.keyDown(cell, { key: 'Enter' });
    await waitFor(() => expect(cell).toHaveAttribute('aria-invalid', 'true'));
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('leaving a cell unchanged saves nothing', async () => {
    await loaded();
    const cell = screen.getByTestId('year-input-A-1') as HTMLInputElement;
    fireEvent.focus(cell);
    fireEvent.blur(cell);
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('Esc puts the old number back', async () => {
    await loaded();
    const cell = screen.getByTestId('year-input-A-1') as HTMLInputElement;
    fireEvent.focus(cell);
    fireEvent.change(cell, { target: { value: '99' } });
    fireEvent.keyDown(cell, { key: 'Escape' });
    expect(cell.value).toBe('2');
    expect(api.updateLine).not.toHaveBeenCalled();
  });
});

describe('pasting from Excel', () => {
  const paste = (cell: HTMLElement, text: string) =>
    fireEvent.paste(cell, { clipboardData: { getData: () => text } });

  it('fills rows down the plan and columns along the years, one save per line', async () => {
    await loaded();
    paste(screen.getByTestId('year-input-A-1'), '5\t6\n7\t8\n');
    await waitFor(() => expect(api.updateLine).toHaveBeenCalledTimes(2));
    expect(api.updateLine).toHaveBeenCalledWith('c1', 'A', {
      years: [{ year: 1, quantity: 5 }, { year: 2, quantity: 6 }],
      expected_version: 4,
    });
    expect(api.updateLine).toHaveBeenCalledWith('c1', 'B', {
      years: [{ year: 1, quantity: 7 }, { year: 2, quantity: 8 }],
      expected_version: 4,
    });
  });

  it('applies nothing when one pasted cell is not a number', async () => {
    await loaded();
    paste(screen.getByTestId('year-input-A-1'), '5\tx\n7\t8');
    await new Promise((r) => setTimeout(r, 30));
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('a single value is an ordinary paste', async () => {
    await loaded();
    paste(screen.getByTestId('year-input-A-1'), '5');
    await new Promise((r) => setTimeout(r, 30));
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('cells past the tenth year are ignored', async () => {
    await loaded();
    paste(screen.getByTestId('year-input-A-10'), '5\t6');
    await waitFor(() => expect(api.updateLine).toHaveBeenCalledTimes(1));
    expect(api.updateLine).toHaveBeenCalledWith('c1', 'A', { years: [{ year: 10, quantity: 5 }], expected_version: 4 });
  });
});

describe('the sub-area column', () => {
  it('names the sub-areas of a line, the category of its kind in bold', async () => {
    api.getPlan.mockResolvedValue({
      total_budget: 0,
      lines: [
        { ...A, sub_areas: [{ id: 's1', name: 'Plantation 1', category: 'plantation', matches: true }, { id: 's2', name: 'Pro-poor 3', category: 'pro-poor', matches: false }] },
        B,
      ],
    });
    await loaded();
    const cell = screen.getByTestId('sub-areas-A');
    expect(cell.textContent).toContain('Plantation 1');
    expect(cell.querySelector('[data-matches="true"]')?.textContent).toBe('Plantation 1');
    expect(screen.queryByTestId('sub-areas-B')).not.toBeInTheDocument();
  });
});

describe('the Draw button', () => {
  it('is on the rows that need a place and takes the user to the map for that line', async () => {
    const onDrawOnMap = vi.fn();
    api.getPlan.mockResolvedValue({ total_budget: 0, lines: [{ ...A, requires_map: true }, B] });
    await loaded({ onDrawOnMap });
    expect(screen.queryByTestId('draw-B')).not.toBeInTheDocument(); // needs no map
    fireEvent.click(screen.getByTestId('draw-A'));
    expect(onDrawOnMap).toHaveBeenCalledWith(expect.objectContaining({ id: 'A' }));
  });

  it('is absent when the host gives no map to go to', async () => {
    api.getPlan.mockResolvedValue({ total_budget: 0, lines: [{ ...A, requires_map: true }, B] });
    await loaded();
    expect(screen.queryByTestId('draw-A')).not.toBeInTheDocument();
  });
});

describe('the foot', () => {
  it('adds up the budget of each year', async () => {
    await loaded();
    expect(screen.getByTestId('year-total-1').textContent).toBe('150'); // 100 + 50
  });
});
