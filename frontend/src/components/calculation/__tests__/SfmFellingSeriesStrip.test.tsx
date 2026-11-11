import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import SfmFellingSeriesStrip from '../SfmFellingSeriesStrip';
import type { SfmFellingSeries } from '../../../services/api';

const s = (over: Partial<SfmFellingSeries> = {}): SfmFellingSeries => ({
  id: 1,
  type_no: 1,
  branch: 'adequate',
  method: 'selection_felling_cycle',
  C: 10,
  R: null,
  N: 10,
  area_ha: 20,
  annual_felling_area_ha: 2,
  gs_ge40_m3_per_ha: 200,
  gs_ge40_m3: 4000,
  pct: 2,
  annual_harvest_m3: 80,
  note_ne: '',
  note_en: '',
  ...over,
});

describe('SfmFellingSeriesStrip', () => {
  it('renders one row per series with the annual harvest', () => {
    render(
      <SfmFellingSeriesStrip
        series={[s(), s({ id: 2, type_no: 2, annual_harvest_m3: 60 })]}
        lang="en"
      />,
    );
    expect(screen.getByText('80.0')).toBeInTheDocument();
    expect(screen.getByText('60.0')).toBeInTheDocument();
  });

  it('shows a dash for a stem-count series (no harvest number)', () => {
    render(
      <SfmFellingSeriesStrip
        series={[
          s({
            method: 'stem_count',
            C: null,
            N: null,
            pct: null,
            gs_ge40_m3: null,
            annual_harvest_m3: null,
            note_en: 'target residual stems',
          }),
        ]}
        lang="en"
      />,
    );
    // the harvest cell renders "—" rather than a number
    expect(screen.queryByText('80.0')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  it('renders a salvage-only tag for a zero-harvest protection series', () => {
    render(
      <SfmFellingSeriesStrip
        series={[s({ type_no: 3, method: 'area_coupe', C: null, N: null, pct: null, annual_harvest_m3: 0 })]}
        lang="en"
      />,
    );
    expect(screen.getByText('Salvage only')).toBeInTheDocument();
  });
});
