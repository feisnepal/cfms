import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import NtfpDesignPanel from '../NtfpDesignPanel';

vi.mock('../NtfpPlotMap', () => ({ default: () => <div data-testid="map-stub" /> }));

const sp = (key: string, pct: number, below: boolean): any => ({ species_key: key, label: key, growth_class: 'shrub', plot_sqm: 25, intensity_pct: pct, plots: 10, intensity_achieved_pct: pct, plots_by_stratum: {}, below_guideline: below });
const stored = (species: any[]): any => ({
  plot_shape: 'square', seed: 1, min_plots: 3, species, strata: [], plots: [{ plot_number: 1, stratum: 'a', transect: 1, longitude: 84, latitude: 28, species_keys: [species[0].species_key] }],
  warnings: [], transects: { type: 'FeatureCollection', features: [] }, layout: {},
});
const renderPanel = (design: any) => render(<NtfpDesignPanel calculationId="c1" boundary={null} species={[]} picks={{}} stored={design} hasRecords={false} onStored={() => {}} />);

describe('NtfpDesignPanel: intensity under the guideline', () => {
  it('marks the species set below the guideline and explains it once', () => {
    renderPanel(stored([sp('a', 0.25, true), sp('b', 0.5, false)]));
    expect(screen.getAllByText('below the guideline')).toHaveLength(1);
    expect(screen.getByText(/lowest sampling intensity \(Table 4\)/)).toBeInTheDocument();
  });

  it('says nothing when every species is at or above the guideline', () => {
    renderPanel(stored([sp('a', 0.5, false)]));
    expect(screen.queryByText('below the guideline')).not.toBeInTheDocument();
    expect(screen.queryByText(/lowest sampling intensity/)).not.toBeInTheDocument();
  });
});
