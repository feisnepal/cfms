import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import NtfpCollectPanel from '../NtfpCollectPanel';
import * as api from '../../../services/api';

// Leaflet needs a real layout: the map is a stub that lists its plots as buttons carrying the value written on each icon
vi.mock('../NtfpPlotMap', async () => {
  const lib = await vi.importActual<typeof import('../../../lib/ntfp')>('../../../lib/ntfp');
  return {
    default: ({ plots, summaries, layer, onSelect }: any) => (
      <div data-testid="map-stub">
        {plots.map((p: any) => (
          <button key={p.plot_number} onClick={() => onSelect?.(p.plot_number)}>{`plot ${p.plot_number}: ${lib.layerLabel(layer, summaries?.[p.plot_number])}`}</button>
        ))}
      </div>
    ),
  };
});
vi.mock('../NtfpPlotEntry', () => ({ default: ({ open, plotNumber }: any) => (open ? <div data-testid="sheet">{`sheet for plot ${plotNumber}`}</div> : null) }));
vi.mock('../../../utils/download', () => ({ downloadFromApi: vi.fn() }));
vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return { ...actual, ntfpApi: { ...actual.ntfpApi, allExtras: vi.fn() } };
});
const extras = api.ntfpApi as unknown as { allExtras: ReturnType<typeof vi.fn> };

const design: any = {
  plot_shape: 'square', seed: 1, min_plots: 3, species: [{ species_key: 'x', label: 'टिमुर', growth_class: 'shrub', plot_sqm: 25, intensity_pct: 1, plots: 2, intensity_achieved_pct: 1, plots_by_stratum: {} }],
  strata: [], plots: [
    { plot_number: 1, stratum: 'a', transect: 1, longitude: 84, latitude: 28, species_keys: ['x'] },
    { plot_number: 2, stratum: 'a', transect: 1, longitude: 84, latitude: 28, species_keys: ['x'] },
  ], warnings: [], transects: { type: 'FeatureCollection', features: [] }, layout: {},
};
const rec = (mode: 'upload' | 'manual' | null, n = 0): any => ({
  pairs_assigned: 2, pairs_recorded: n, weights: 0, mode,
  observations: n ? [{ plot_number: 1, species_key: 'x', visit_date: null, count_total: 6, count_mature: null, count_small: null, clumps: null, tillers: null, notes: null, source: mode, weights: [] }] : [],
});
const renderPanel = (records: any) => render(<NtfpCollectPanel calculationId="c1" hasDesign records={records} onChanged={() => {}} design={design} boundary={null} />);

describe('NtfpCollectPanel: one way of recording per forest', () => {
  beforeEach(() => { extras.allExtras.mockReset(); extras.allExtras.mockResolvedValue({ plots: { '1': { verdict: 'at', photos: 2 } } }); });

  it('lets the user choose when there are no records, starting with the upload', () => {
    renderPanel(rec(null));
    expect(screen.getByRole('button', { name: /Download the form/ })).toBeInTheDocument();
    expect(screen.queryByTestId('map-stub')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Enter on the map'));
    expect(screen.getByTestId('map-stub')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Download the form/ })).not.toBeInTheDocument();
  });

  it('shows the recording status on each plot icon and opens the sheet for the clicked plot', () => {
    renderPanel(rec('manual', 1));
    expect(screen.getByText('plot 1: 1/1')).toBeInTheDocument();     // recorded of assigned
    expect(screen.getByText('plot 2: 0/1')).toBeInTheDocument();
    fireEvent.click(screen.getByText('plot 2: 0/1'));
    expect(screen.getByTestId('sheet')).toHaveTextContent('sheet for plot 2');
  });

  it('keeps to the way the records came: uploaded records close the map way, with the reason', () => {
    renderPanel(rec('upload', 1));
    expect(screen.getByText(/Delete all records to enter them on the map instead/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Download the form/ })).toBeInTheDocument();
    fireEvent.click(screen.getByText('Enter on the map'));
    expect(screen.queryByTestId('map-stub')).not.toBeInTheDocument();   // the disabled option does not switch
  });

  it('keeps to the map way once records were entered there', () => {
    renderPanel(rec('manual', 1));
    expect(screen.getByText(/Delete all records to upload the form instead/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Upload the Excel form'));
    expect(screen.getByTestId('map-stub')).toBeInTheDocument();
  });

  it('asks for the position checks and photo counts of the plots when entering on the map, not when uploading', async () => {
    renderPanel(rec('manual', 1));
    await waitFor(() => expect(extras.allExtras).toHaveBeenCalledWith('c1'));
    extras.allExtras.mockClear();
    renderPanel(rec('upload', 1));
    expect(extras.allExtras).not.toHaveBeenCalled();
  });

  it('colours by a species count when that layer is chosen', () => {
    renderPanel(rec('manual', 1));
    fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Show on the map' }));
    fireEvent.click(screen.getByText('Count of टिमुर'));
    expect(screen.getByText('plot 1: 6')).toBeInTheDocument();
    expect(screen.getByText(/^plot 2:\s*$/)).toBeInTheDocument();         // not surveyed: no value
  });
});
