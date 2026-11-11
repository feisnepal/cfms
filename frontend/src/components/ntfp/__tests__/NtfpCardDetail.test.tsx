import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import NtfpCardDetail from '../NtfpCardDetail';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, card: vi.fn() } };
});

const m = api.ntfpApi as unknown as { card: ReturnType<typeof vi.fn> };

const val = (over: Record<string, unknown>) => ({
  id: String(Math.random()), value_num: null, value_num2: null, value_text: null, unit: null, calendar: null, source_key: 'DOF2069', source_title: 'NTFP Resource Survey Guideline 2069',
  source_year: '2012', source_url: null, source_tier: 1, locator: 'Annex 2', status: 'documented', chosen: true, note: null, reviewed_by: null, reviewed_at: null, ...over,
});

const CARD = {
  species_key: 'nardostachys jatamansi', nepali_name: 'जटामसी', scientific_name: 'Nardostachys jatamansi', aliases: ['Nardostachys grandiflora'], card_status: 'documented', has_method_card: true,
  growth_class: 'herb', part_groups: ['क'], sources: {},
  facts: [
    { field: 'growth_class', part_group: null, chosen: val({ value_text: 'herb' }), others: [], conflict: false },
    { field: 'plot_area_sqm', part_group: null, chosen: val({ value_num: 25, value_num2: 25, unit: 'm2' }), others: [], conflict: false },
    { field: 'aah_pct', part_group: 'क', chosen: val({ source_key: 'ANSAB2022', source_year: '2022', source_url: 'https://ansab.org.np/x.pdf', locator: 'Annex 3, AAH table', value_num: 80, unit: '%' }),
      others: [val({ source_key: 'ANSAB2010', source_year: '2010', locator: 'Table 18', value_num: 75, unit: '%', chosen: false })], conflict: true },
    { field: 'season', part_group: 'क', chosen: val({ source_key: 'ANSAB2022', source_year: '2022', calendar: 'AD', value_num: 9, value_num2: 12, value_text: 'September-December', locator: 'Annex 3' }),
      others: [val({ calendar: 'BS', value_num: 5, value_num2: 6, value_text: 'भदौ - असोज', status: 'provisional', chosen: false, locator: 'Table 5' })], conflict: true },
  ],
};

beforeEach(() => m.card.mockReset());

describe('NtfpCardDetail', () => {
  it('shows every value with its source, the table or page and a status', async () => {
    m.card.mockResolvedValue(CARD);
    render(<NtfpCardDetail calculationId="c1" speciesKey="nardostachys jatamansi" />);
    expect(await screen.findByText('Annual allowable harvest')).toBeInTheDocument();
    expect(m.card).toHaveBeenCalledWith('c1', 'nardostachys jatamansi');
    expect(screen.getByText('25 m2')).toBeInTheDocument();
    expect(screen.getAllByText('DOF2069, Annex 2').length).toBeGreaterThan(0);
    const link = screen.getByRole('link', { name: 'ANSAB2022, Annex 3, AAH table' });
    expect(link).toHaveAttribute('href', 'https://ansab.org.np/x.pdf');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('lists the other sources beside the chosen value and says where they differ', async () => {
    m.card.mockResolvedValue(CARD);
    render(<NtfpCardDetail calculationId="c1" speciesKey="x" />);
    await screen.findByText('Annual allowable harvest');
    expect(screen.getAllByText('Sources differ')).toHaveLength(2);
    expect(screen.getByText(/ANSAB2010, Table 18/)).toBeInTheDocument();
    expect(screen.getByText(/^75 %/)).toBeInTheDocument();
  });

  it('names a season by month and calendar, never as bare numbers', async () => {
    m.card.mockResolvedValue(CARD);
    render(<NtfpCardDetail calculationId="c1" speciesKey="x" />);
    expect(await screen.findByText('September – December (AD)')).toBeInTheDocument();
    expect(screen.getByText(/^Bhadra – Ashwin \(BS\)/)).toBeInTheDocument();             // the guideline's unreviewed reading, in its own calendar
    expect(screen.getAllByText('Provisional').length).toBeGreaterThan(0);
  });

  it('warns that a provisional card was made by rules', async () => {
    m.card.mockResolvedValue({ ...CARD, card_status: 'provisional' });
    render(<NtfpCardDetail calculationId="c1" speciesKey="x" />);
    expect(await screen.findByText(/Made by rules from the growth form/)).toBeInTheDocument();
  });

  it('says so when there is nothing sourced, and shows a failure plainly', async () => {
    m.card.mockResolvedValueOnce({ ...CARD, facts: [] });
    const first = render(<NtfpCardDetail calculationId="c1" speciesKey="x" />);
    expect(await screen.findByText('No sourced values for this species yet.')).toBeInTheDocument();
    first.unmount();
    m.card.mockRejectedValueOnce({ response: { data: { detail: 'boom' } } });
    render(<NtfpCardDetail calculationId="c1" speciesKey="y" />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });
});
