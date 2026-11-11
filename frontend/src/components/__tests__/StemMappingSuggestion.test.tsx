import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import StemMappingSuggestion from '../StemMappingSuggestion';

const getSuggestion = vi.fn();
vi.mock('../../services/api', () => ({
  sfmApi: { getStemMappingSuggestion: (...a: unknown[]) => getSuggestion(...a) },
}));

const range = (n: number, v: number) => ({ count_per_ha: n, volume_m3_per_ha: v });
const ROWS = [
  { block_name: 'C2', area_ha: 12, plot_count: 3, has_inventory: true, stem_mapped: false, suggested: true,
    ranges: { from10_to40: range(70, 34), from10: range(82, 104), from40: range(12, 70) } },
  { block_name: 'C1', area_ha: 10, plot_count: 2, has_inventory: true, stem_mapped: true, suggested: false,
    ranges: { from10_to40: range(280, 110), from10: range(281, 115), from40: range(1, 5) } },
  { block_name: 'C9', area_ha: 5, plot_count: 0, has_inventory: false, stem_mapped: false, suggested: false, ranges: null },
];

describe('StemMappingSuggestion', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders nothing when no series is managed by shelterwood', async () => {
    getSuggestion.mockResolvedValue({ applies: false, series: [], rows: [], suggested: null });
    const { container } = render(<StemMappingSuggestion calculationId="c1" />);
    await new Promise((r) => setTimeout(r, 30));
    expect(container.innerHTML).toBe('');
    expect(getSuggestion).toHaveBeenCalledWith('c1');
  });

  it('renders nothing (no error) when the suggestion cannot be read', async () => {
    getSuggestion.mockRejectedValue(new Error('boom'));
    const { container } = render(<StemMappingSuggestion calculationId="c1" />);
    await new Promise((r) => setTimeout(r, 30));
    expect(container.innerHTML).toBe('');
  });

  it('names the suggested unit and marks only that row', async () => {
    getSuggestion.mockResolvedValue({ applies: true, series: ['5'], rows: ROWS, suggested: 'C2' });
    render(<StemMappingSuggestion calculationId="c1" />);
    expect(await screen.findByTestId('stem-suggestion-best')).toHaveTextContent('Suggested for stem mapping: C2');
    expect(screen.getByTestId('stem-suggestion-row-C2').getAttribute('data-suggested')).toBe('true');
    expect(screen.getByTestId('stem-suggestion-row-C1').getAttribute('data-suggested')).toBe('false');
    expect(screen.getByTestId('stem-suggestion-row-C9').getAttribute('data-suggested')).toBe('false');
  });

  it('shows trees and volume separately for the three DBH ranges', async () => {
    getSuggestion.mockResolvedValue({ applies: true, series: ['5'], rows: ROWS, suggested: 'C2' });
    render(<StemMappingSuggestion calculationId="c1" />);
    const row = await screen.findByTestId('stem-suggestion-row-C2');
    const cells = Array.from(row.querySelectorAll('td')).map((td) => td.textContent?.trim());
    // unit, area, plots, then (trees, volume) for 10-40, 10+, 40+, then status
    expect(cells.slice(3, 9)).toEqual(['70', '34.0', '82', '104.0', '12', '70.0']);
    expect(screen.getByText('10 to 40 cm')).toBeTruthy();
    expect(screen.getByText('10 cm and above')).toBeTruthy();
    expect(screen.getByText('40 cm and above')).toBeTruthy();
  });

  it('says so for a unit without a field inventory and for one already stem mapped', async () => {
    getSuggestion.mockResolvedValue({ applies: true, series: ['5'], rows: ROWS, suggested: 'C2' });
    render(<StemMappingSuggestion calculationId="c1" />);
    await screen.findByTestId('stem-mapping-suggestion');
    expect(screen.getByText('no field inventory')).toBeTruthy();
    expect(screen.getByText('stem mapping done')).toBeTruthy();
  });

  it('says nothing can be suggested when no unit has trees of 40 cm and above', async () => {
    getSuggestion.mockResolvedValue({ applies: true, series: ['5'], rows: [ROWS[2]], suggested: null });
    render(<StemMappingSuggestion calculationId="c1" />);
    expect(await screen.findByText(/nothing can be suggested/)).toBeTruthy();
    expect(screen.queryByTestId('stem-suggestion-best')).toBeNull();
  });
});
