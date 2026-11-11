import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import * as L from 'leaflet';
import { NtfpPlotsGroup } from '../NtfpPlotsGroup';
import * as api from '../../services/api';
import { NTFP_PLOTS_PANE } from '../../lib/ntfp';

vi.mock('../ntfp/NtfpPlotEntry', () => ({ default: ({ open, plotNumber }: any) => (open ? <div data-testid="sheet">{`sheet for plot ${plotNumber}`}</div> : null) }));
vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, getDesign: vi.fn(), records: vi.fn(), allExtras: vi.fn() } };
});
const m = api.ntfpApi as unknown as { getDesign: ReturnType<typeof vi.fn>; records: ReturnType<typeof vi.fn>; allExtras: ReturnType<typeof vi.fn> };

const design: any = {
  plot_shape: 'square', seed: 1, min_plots: 3, species: [{ species_key: 'x', label: 'टिमुर', growth_class: 'shrub', plot_sqm: 25, intensity_pct: 1, plots: 3, intensity_achieved_pct: 1, plots_by_stratum: {} }],
  strata: [], warnings: [], transects: { type: 'FeatureCollection', features: [] }, layout: {},
  plots: [1, 2, 3].map((n) => ({ plot_number: n, stratum: 'a', transect: 1, longitude: 83.4 + n * 0.001, latitude: 27.4, species_keys: ['x'] })),
};
const records: any = {
  pairs_assigned: 3, pairs_recorded: 1, weights: 0, mode: 'manual',
  observations: [{ plot_number: 1, species_key: 'x', visit_date: null, count_total: 6, count_mature: null, count_small: null, clumps: null, tillers: null, notes: null, source: 'manual', weights: [] }],
};

let map: L.Map;
const markers = () => { const out: L.CircleMarker[] = []; map.eachLayer((l) => { if (l instanceof L.CircleMarker) out.push(l); }); return out; };

beforeEach(() => {
  localStorage.clear();
  m.getDesign.mockReset(); m.records.mockReset(); m.allExtras.mockReset();
  m.getDesign.mockResolvedValue({ design });
  m.records.mockResolvedValue(records);
  m.allExtras.mockResolvedValue({ plots: { '2': { verdict: 'far', photos: 0 } } });
  const div = document.createElement('div');
  document.body.appendChild(div);
  map = L.map(div).setView([27.4, 83.4], 14);
});

describe('NtfpPlotsGroup', () => {
  it('reads nothing and draws nothing until it is switched on', () => {
    render(<NtfpPlotsGroup calculationId="c1" map={map} />);
    expect(m.getDesign).not.toHaveBeenCalled();
    expect(markers()).toHaveLength(0);
  });

  it('draws every plot coloured by its status, with the position check as a ring, and counts the statuses', async () => {
    render(<NtfpPlotsGroup calculationId="c1" map={map} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'NTFP sample plots' }));
    await waitFor(() => expect(markers()).toHaveLength(3));
    const byNumber = markers().map((mk) => mk.options);
    expect(byNumber.map((o) => o.fillColor)).toEqual(['#2e7d32', '#9e9e9e', '#9e9e9e']);   // 1 recorded, 2 and 3 not visited
    expect(byNumber[1].color).toBe('#c62828');                                              // plot 2 was checked from far away
    expect(markers()[0].options.pane).toBe(NTFP_PLOTS_PANE);
    expect(screen.getByTestId('ntfp-plots-legend-done')).toHaveTextContent('Recorded · 1');
    expect(screen.getByTestId('ntfp-plots-legend-none')).toHaveTextContent('Not visited · 2');
  });

  it('opens the same entry sheet as the NTFP page when a plot is clicked', async () => {
    render(<NtfpPlotsGroup calculationId="c1" map={map} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'NTFP sample plots' }));
    await waitFor(() => expect(markers()).toHaveLength(3));
    markers()[2].fire('click');
    expect(await screen.findByTestId('sheet')).toHaveTextContent('sheet for plot 3');
  });

  it('says where to make the plots when the forest has none, and draws nothing', async () => {
    m.getDesign.mockResolvedValue({ design: null });
    render(<NtfpPlotsGroup calculationId="c1" map={map} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'NTFP sample plots' }));
    expect(await screen.findByText(/lay them out on the NTFP inventory page/)).toBeInTheDocument();
    expect(markers()).toHaveLength(0);
  });

  it('removes the plots when switched off, and remembers the choice for the forest', async () => {
    const { unmount } = render(<NtfpPlotsGroup calculationId="c1" map={map} />);
    fireEvent.click(screen.getByRole('checkbox', { name: 'NTFP sample plots' }));
    await waitFor(() => expect(markers()).toHaveLength(3));
    fireEvent.click(screen.getByRole('checkbox', { name: 'NTFP sample plots' }));
    await waitFor(() => expect(markers()).toHaveLength(0));
    fireEvent.click(screen.getByRole('checkbox', { name: 'NTFP sample plots' }));
    await waitFor(() => expect(markers()).toHaveLength(3));
    unmount();
    expect(markers()).toHaveLength(0);                                     // leaving the page takes everything off the map
    render(<NtfpPlotsGroup calculationId="c1" map={map} />);
    await waitFor(() => expect(markers()).toHaveLength(3));                // it was left on
  });
});
