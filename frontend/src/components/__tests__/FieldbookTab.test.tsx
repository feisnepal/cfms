import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { FieldbookTab } from '../FieldbookTab';

const list = vi.fn();
vi.mock('../../services/api', () => ({
  fieldbookApi: {
    list: (...a: unknown[]) => list(...a),
    generate: vi.fn(),
    delete: vi.fn(),
  },
  compartmentApi: { getAvailableBlocks: vi.fn().mockResolvedValue([]) },
}));
vi.mock('../../utils/download', () => ({ downloadFromApi: vi.fn() }));

const pt = (over: Record<string, unknown>) => ({
  id: String(over.point_number),
  point_type: 'vertex',
  longitude: '83.5', latitude: '27.5',
  azimuth_to_next: '90', distance_to_next: '50',
  block_number: 1, block_name: 'A',
  ...over,
});

const CLASSIFIED = {
  total_count: 5,
  lines: [
    { id: 'O-1', kind: 'outer', closed: true, labels: ['O1', 'O2', 'O3'], length_m: 100 },
    { id: 'I-1', kind: 'internal', closed: false, labels: ['O2', 'I1', 'I2'], length_m: 40 },
  ],
  points: [
    pt({ point_number: 1, point_label: 'O1', boundary_class: 'outer', adjacent_units: ['A'], remarks: 'outer: A', is_junction: false, junction_degree: 1, next_point_label: 'O2', line_id: 'O-1', lines: { 'O-1': 1 } }),
    pt({ point_number: 2, point_label: 'O2', boundary_class: 'outer', adjacent_units: ['A', 'B'], remarks: 'outer: A, B', is_junction: true, junction_degree: 2, next_point_label: 'O3', line_id: 'O-1', lines: { 'O-1': 2, 'I-1': 1 } }),
    pt({ point_number: 3, point_label: 'O3', boundary_class: 'outer', adjacent_units: ['B'], remarks: 'outer: B', is_junction: false, junction_degree: 1, next_point_label: 'O1', line_id: 'O-1', lines: { 'O-1': 3 } }),
    pt({ point_number: 4, point_label: 'I1', boundary_class: 'internal', adjacent_units: ['A', 'B'], remarks: 'internal: A, B', is_junction: false, junction_degree: 2, next_point_label: 'I2', line_id: 'I-1', lines: { 'I-1': 2 } }),
    pt({ point_number: 5, point_label: 'I2', boundary_class: 'internal', adjacent_units: ['A', 'B', 'C'], remarks: 'internal (junction of 3): A, B, C', is_junction: true, junction_degree: 3, next_point_label: null, line_id: 'I-1', lines: { 'I-1': 3 } }),
  ],
};

const LEGACY = {
  total_count: 2,
  points: [pt({ point_number: 1 }), pt({ point_number: 2 })],
};

const labelsShown = () =>
  screen.getAllByRole('row').slice(1).map((r) => within(r).getAllByRole('cell')[0].textContent);

beforeEach(() => {
  list.mockReset();
  sessionStorage.clear();
});

describe('FieldbookTab — outer / internal / junction', () => {
  it('lists points by their O/I label, outer first, and one Remark column says which units each separates', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    expect(labelsShown()).toEqual(['O1', 'O2', 'O3', 'I1', 'I2']);
    expect(screen.getAllByTestId('fieldbook-remark').map((c) => c.textContent)).toEqual([
      'outer: A', 'outer: A, B', 'outer: B', 'internal: A, B', 'internal (junction of 3): A, B, C',
    ]);
  });

  it('has ONE column for what a point is and which units it separates -- no separate Block or Separates column', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent ?? '');
    expect(headers.filter((h) => /remark/i.test(h) || h === 'attributeTable.col.remark')).toHaveLength(1);
    expect(headers.some((h) => /block|separates|colSeparates/i.test(h))).toBe(false);
    expect(screen.queryByTestId('fieldbook-separates')).not.toBeInTheDocument();
  });

  it('a point with no remark shows a dash', async () => {
    list.mockResolvedValue({ total_count: 1, points: [pt({ point_number: 1, point_label: 'O1', boundary_class: 'outer', is_junction: false, remarks: null })] });
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    expect(screen.getByTestId('fieldbook-remark').textContent).toBe('-');
  });

  it('shows the outer / internal / junction split', async () => {
    list.mockResolvedValue({ ...CLASSIFIED, outer_points: 3, internal_points: 2, junction_points: 2 });
    render(<FieldbookTab calculationId="calc-1" />);
    const split = await screen.findByTestId('fieldbook-split');
    expect(split.textContent).toContain('3');
    expect(split.textContent).toContain('2');
  });

  it('filter chips carry counts and narrow the table', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');

    expect(screen.getByTestId('fieldbook-filter-all').textContent).toContain('(5)');
    expect(screen.getByTestId('fieldbook-filter-outer').textContent).toContain('(3)');
    expect(screen.getByTestId('fieldbook-filter-internal').textContent).toContain('(2)');
    expect(screen.getByTestId('fieldbook-filter-junction').textContent).toContain('(2)');

    fireEvent.click(screen.getByTestId('fieldbook-filter-outer'));
    expect(labelsShown()).toEqual(['O1', 'O2', 'O3']);

    fireEvent.click(screen.getByTestId('fieldbook-filter-internal'));
    expect(labelsShown()).toEqual(['I1', 'I2']);

    fireEvent.click(screen.getByTestId('fieldbook-filter-junction'));
    expect(labelsShown()).toEqual(['O2', 'I2']);   // an outer junction and an internal one

    fireEvent.click(screen.getByTestId('fieldbook-filter-all'));
    expect(labelsShown()).toHaveLength(5);
  });

  it('marks a junction with how many regions meet there', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    fireEvent.click(screen.getByTestId('fieldbook-filter-junction'));
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0].textContent).toContain('✦ 2');
    expect(rows[1].textContent).toContain('✦ 3');
  });

  it('shows the next point to walk to', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    const first = screen.getAllByRole('row')[1];
    const cells = within(first).getAllByRole('cell');
    // columns end ... Next, Line
    expect(cells[cells.length - 2].textContent).toBe('O2');
    expect(cells[cells.length - 1].textContent).toBe('O-1');
  });

  it('a field book made before outer/internal existed still renders, as P-numbers, with no filters', async () => {
    list.mockResolvedValue(LEGACY);
    render(<FieldbookTab calculationId="calc-1" />);
    await waitFor(() => expect(screen.getAllByRole('row').length).toBeGreaterThan(1));
    expect(labelsShown()).toEqual(['P1', 'P2']);
    expect(screen.queryByTestId('fieldbook-filters')).not.toBeInTheDocument();
    expect(screen.queryByTestId('fieldbook-split')).not.toBeInTheDocument();
  });

  it('a real zero distance is shown as 0.0, not as a dash', async () => {
    list.mockResolvedValue({ total_count: 1, points: [pt({ point_number: 1, azimuth_to_next: '0', distance_to_next: '0' })] });
    render(<FieldbookTab calculationId="calc-1" />);
    await waitFor(() => expect(screen.getAllByRole('row').length).toBeGreaterThan(1));
    const cells = within(screen.getAllByRole('row')[1]).getAllByRole('cell').map((c) => c.textContent);
    expect(cells.filter((c) => c === '0.0').length).toBe(2);   // azimuth and distance
  });

  it('says which line each point is on, and summarises the lines: outer outlines closed, internal lines open', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    expect(screen.getAllByTestId('fieldbook-line').map((c) => c.textContent)).toEqual(['O-1', 'O-1', 'O-1', 'I-1', 'I-1']);
    const summary = screen.getByTestId('fieldbook-lines-summary');
    expect(summary.textContent).toMatch(/1/);                      // one outer outline
    expect(summary.textContent).toMatch(/1/);                      // one internal line
  });

  it('a point on two lines (a junction) shows both in its tooltip', async () => {
    list.mockResolvedValue(CLASSIFIED);
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    const junctionCell = screen.getAllByTestId('fieldbook-line')[1];     // O2: the ring AND the internal edge that starts there
    expect(junctionCell.getAttribute('title')).toBe('O-1, I-1');
  });

  it('no lines summary for a book made before lines existed', async () => {
    list.mockResolvedValue({ ...CLASSIFIED, lines: undefined });
    render(<FieldbookTab calculationId="calc-1" />);
    await screen.findByTestId('fieldbook-filters');
    expect(screen.queryByTestId('fieldbook-lines-summary')).not.toBeInTheDocument();
  });
});
