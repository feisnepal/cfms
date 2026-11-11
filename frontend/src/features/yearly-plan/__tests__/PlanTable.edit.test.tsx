/**
 * Editing numbers in the Yearly plan table (P4, YA-4.8): every change saves at once, the first value typed fills
 * the years still at the starting value (the server does that; the screen says so and offers Undo), and a failed
 * save keeps what was typed.
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
vi.mock('../../../services/api', () => ({ yearlyPlanApi: { getPlan: vi.fn(), updateLine: vi.fn(), confirmLine: vi.fn() } }));

import { yearlyPlanApi, type YearlyPlanLine } from '../../../services/api';
import { PlanTable } from '../PlanTable';

const api = yearlyPlanApi as unknown as Record<'getPlan' | 'updateLine', ReturnType<typeof vi.fn>>;

const matrix = (f: (year: number) => [number, number]) =>
  Array.from({ length: 10 }, (_, i) => {
    const [quantity, budget] = f(i + 1);
    return { year: i + 1, quantity, budget, planned: quantity > 0 || budget > 0, has_row: true };
  });

const line = (over: Partial<YearlyPlanLine> = {}): YearlyPlanLine => ({
  id: 'L',
  potential_activity_id: 1,
  activity: 'Main nursery',
  program: 'Forest development',
  unit: 'no.',
  requires_map: false,
  default_quantity: 1,
  default_yearly_budget: 5000,
  years: matrix(() => [1, 5000]),
  planned_years: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
  total_budget: 50000,
  version: 3,
  reviewed_at: null,
  placeholder_fields: ['quantity', 'budget'],
  feature_count: 0,
  location_mode: 'not_applicable',
  assign_to_all_blocks: false,
  status: 'planned',
  notes: null,
  ...over,
});

const result = (l: YearlyPlanLine, filled: number[] = []) => ({ plan_line: l, filled_years: filled });

beforeEach(() => {
  vi.clearAllMocks();
  api.getPlan.mockResolvedValue({ total_budget: 0, lines: [line()] });
});

async function loaded() {
  render(<PlanTable calculationId="c1" />);
  await screen.findByText('Main nursery');
}

describe('the usual quantity and budget', () => {
  it('press, type, leave the field: it saves at once with the version it was read at, and the row shows the answer', async () => {
    api.updateLine.mockResolvedValue(result(line({ default_quantity: 3, version: 4 })));
    await loaded();
    fireEvent.click(screen.getByTestId('default-quantity-L'));
    const input = screen.getByTestId('default-quantity-L-input');
    fireEvent.change(input, { target: { value: '3' } });
    fireEvent.blur(input);
    await waitFor(() => expect(api.updateLine).toHaveBeenCalledWith('c1', 'L', { default_quantity: 3, expected_version: 3 }));
    expect(await screen.findByTestId('plan-table-status')).toHaveAttribute('data-kind', 'saved');
    await waitFor(() => expect(screen.getByTestId('default-quantity-L').textContent).toBe('3'));
  });

  it('the usual quantity cannot be 0: it says so and sends nothing', async () => {
    await loaded();
    fireEvent.click(screen.getByTestId('default-quantity-L'));
    const input = screen.getByTestId('default-quantity-L-input');
    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.blur(input);
    expect(await screen.findByTestId('default-quantity-L-invalid')).toHaveTextContent('Please type a number above 0.');
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('a value that is not a number is refused, and Esc leaves the cell as it was', async () => {
    await loaded();
    fireEvent.click(screen.getByTestId('default-budget-L'));
    const input = screen.getByTestId('default-budget-L-input');
    fireEvent.change(input, { target: { value: 'abc' } });
    fireEvent.blur(input);
    expect(await screen.findByTestId('default-budget-L-invalid')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByTestId('default-budget-L-input'), { key: 'Escape' });
    expect(screen.queryByTestId('default-budget-L-input')).toBeNull();
    expect(screen.getByTestId('default-budget-L').textContent).toBe('5000');
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('typing the same value again saves nothing', async () => {
    await loaded();
    fireEvent.click(screen.getByTestId('default-budget-L'));
    fireEvent.blur(screen.getByTestId('default-budget-L-input'));
    await waitFor(() => expect(screen.queryByTestId('default-budget-L-input')).toBeNull());
    expect(api.updateLine).not.toHaveBeenCalled();
  });
});

describe('the measured quantity', () => {
  it('"Use this" saves what the drawn places measure as the usual quantity, at the version it was read at', async () => {
    api.getPlan.mockResolvedValue({ total_budget: 0, lines: [line({ measured_quantity: 2.35, unit: 'km' })] });
    api.updateLine.mockResolvedValue(result(line({ default_quantity: 2.35, version: 4, measured_quantity: 2.35, unit: 'km' })));
    await loaded();
    fireEvent.click(screen.getByTestId('use-measured-L'));
    await waitFor(() => expect(api.updateLine).toHaveBeenCalledWith('c1', 'L', { default_quantity: 2.35, expected_version: 3 }));
    await waitFor(() => expect(screen.queryByTestId('measured-hint-L')).toBeNull()); // it agrees now
  });
});

describe('one year', () => {
  it('sends only the field that changed', async () => {
    api.updateLine.mockResolvedValue(result(line({ version: 4, years: matrix((y) => (y === 2 ? [1, 7000] : [1, 5000])) })));
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-2'));
    fireEvent.change(await screen.findByTestId('year-edit-L-2-budget'), { target: { value: '7000' } });
    fireEvent.click(screen.getByTestId('year-edit-L-2-save'));
    await waitFor(() => expect(api.updateLine).toHaveBeenCalledWith('c1', 'L', { years: [{ year: 2, budget: 7000 }], expected_version: 3 }));
    // the panel closes once it has saved
    await waitFor(() => expect(screen.getByTestId('year-edit-L-2')).toHaveAttribute('aria-expanded', 'false'));
  });

  it('typing 0 in both is one deliberate action that leaves the year unplanned', async () => {
    api.updateLine.mockResolvedValue(result(line({ version: 4 })));
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-4'));
    fireEvent.change(await screen.findByTestId('year-edit-L-4-quantity'), { target: { value: '0' } });
    fireEvent.change(screen.getByTestId('year-edit-L-4-budget'), { target: { value: '0' } });
    fireEvent.click(screen.getByTestId('year-edit-L-4-save'));
    await waitFor(() =>
      expect(api.updateLine).toHaveBeenCalledWith('c1', 'L', { years: [{ year: 4, quantity: 0, budget: 0 }], expected_version: 3 }),
    );
  });

  it('a field that is not a number keeps the panel open and sends nothing', async () => {
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-1'));
    fireEvent.change(await screen.findByTestId('year-edit-L-1-quantity'), { target: { value: 'x' } });
    fireEvent.click(screen.getByTestId('year-edit-L-1-save'));
    expect(await screen.findByTestId('year-edit-L-1-invalid')).toBeInTheDocument();
    expect(api.updateLine).not.toHaveBeenCalled();
  });

  it('a failed save keeps the panel open with what was typed, and shows no "saved" message', async () => {
    api.updateLine.mockRejectedValue(Object.assign(new Error('x'), { code: 'ERR_NETWORK', request: {} }));
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-2'));
    fireEvent.change(await screen.findByTestId('year-edit-L-2-budget'), { target: { value: '7000' } });
    fireEvent.click(screen.getByTestId('year-edit-L-2-save'));
    await waitFor(() => expect(api.updateLine).toHaveBeenCalled());
    expect((screen.getByTestId('year-edit-L-2-budget') as HTMLInputElement).value).toBe('7000');
    expect(screen.getByTestId('year-edit-L-2')).toHaveAttribute('aria-expanded', 'true'); // still open
    expect(screen.queryByTestId('plan-table-status')).toBeNull();
  });

  it('a conflict (someone else changed the line) shows what is there now', async () => {
    api.updateLine.mockRejectedValue(Object.assign(new Error('conflict'), { response: { status: 409 } }));
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-2'));
    fireEvent.change(await screen.findByTestId('year-edit-L-2-budget'), { target: { value: '7000' } });
    fireEvent.click(screen.getByTestId('year-edit-L-2-save'));
    await waitFor(() => expect(api.getPlan).toHaveBeenCalledTimes(2));
  });
});

describe('the first value fills the rest, and Undo puts it back', () => {
  const filledYears = [2, 3, 4, 5, 6, 7, 8, 9, 10];
  const afterFill = () =>
    line({ version: 4, default_yearly_budget: 80000, years: matrix(() => [1, 80000]), placeholder_fields: ['quantity'], total_budget: 800000 });

  it('says the number was used for all years, shades those years, and offers Undo', async () => {
    api.updateLine.mockResolvedValue(result(afterFill(), filledYears));
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-1'));
    fireEvent.change(await screen.findByTestId('year-edit-L-1-budget'), { target: { value: '80000' } });
    fireEvent.click(screen.getByTestId('year-edit-L-1-save'));

    const status = await screen.findByTestId('plan-table-status');
    expect(status).toHaveAttribute('data-kind', 'filled');
    expect(status.textContent).toContain('Used for all years — change any year if it differs.');
    expect(screen.getByTestId('plan-table-undo')).toBeInTheDocument();
    expect(screen.getByTestId('year-edit-L-5').style.background).toContain('rgb(255, 251, 230)'); // a filled year is shaded
    expect(screen.getByTestId('year-edit-L-1').style.background).not.toContain('rgb(255, 251, 230)'); // the year that was typed is not
  });

  it('Undo sends the earlier numbers (all ten years, the usual numbers, the current version, unreview) and says so', async () => {
    api.updateLine.mockResolvedValueOnce(result(afterFill(), filledYears)).mockResolvedValueOnce(result(line({ version: 5 })));
    await loaded();
    fireEvent.click(screen.getByTestId('year-edit-L-1'));
    fireEvent.change(await screen.findByTestId('year-edit-L-1-budget'), { target: { value: '80000' } });
    fireEvent.click(screen.getByTestId('year-edit-L-1-save'));
    fireEvent.click(await screen.findByTestId('plan-table-undo'));

    await waitFor(() => expect(api.updateLine).toHaveBeenCalledTimes(2));
    const sent = api.updateLine.mock.calls[1][2];
    expect(sent.years).toHaveLength(10);
    expect(sent.years.every((y: { quantity: number; budget: number }) => y.quantity === 1 && y.budget === 5000)).toBe(true);
    expect(sent).toMatchObject({ default_quantity: 1, default_yearly_budget: 5000, expected_version: 4, unreview: true });
    expect(await screen.findByText('Undone.')).toBeInTheDocument();
    expect(screen.queryByTestId('plan-table-undo')).toBeNull();
    expect(screen.getByTestId('default-budget-L').textContent).toBe('5000');
  });

  it('tells the host after each change so the Next-step bar can re-read', async () => {
    api.updateLine.mockResolvedValue(result(line({ version: 4 })));
    const onChanged = vi.fn();
    render(<PlanTable calculationId="c1" onPlanChanged={onChanged} />);
    await screen.findByText('Main nursery');
    fireEvent.click(screen.getByTestId('default-budget-L'));
    const input = screen.getByTestId('default-budget-L-input');
    fireEvent.change(input, { target: { value: '6000' } });
    fireEvent.blur(input);
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });
});

describe('read only', () => {
  it('shows the numbers with nothing to press', async () => {
    render(<PlanTable calculationId="c1" readOnly />);
    await screen.findByText('Main nursery');
    expect(screen.queryByTestId('default-quantity-L')).toBeNull();
    expect(screen.queryByTestId('default-budget-L')).toBeNull();
    expect(screen.queryByTestId('year-edit-L-1')).toBeNull();
    expect(screen.getByTestId('year-L-1')).toBeInTheDocument(); // the year is still shown
  });
});
