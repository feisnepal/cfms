import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HazardMapLegend, SfmMapLegend, hazardLegendTarget } from '../MapLegend';

const getSfm = vi.fn();
const getHazard = vi.fn();
const getDots = vi.fn();
vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    sfmApi: { ...actual.sfmApi, getMapLegend: (...a: unknown[]) => getSfm(...a) },
    hazardErosionApi: {
      ...actual.hazardErosionApi,
      getMapLegend: (...a: unknown[]) => getHazard(...a),
      getDotsSummary: (...a: unknown[]) => getDots(...a),
    },
  };
});

const sfmReady = (specKey: string, classes: unknown[]) => ({ state: 'ready', key: specKey, total_ha: 30, classes });
const cls = (key: string, color: string, count: number, area: number, share: number) => ({ key, color, label_ne: key, label_en: key, count, area_ha: area, share_pct: share });

beforeEach(() => {
  vi.clearAllMocks();
});

describe('hazardLegendTarget', () => {
  it('maps every raster hazard map to its legend layer, with the user-group view', () => {
    expect(hazardLegendTarget('thememap:soil__annual_loss')).toEqual({ kind: 'raster', layer: 'soil', area: 'forest' });
    expect(hazardLegendTarget('thememap:hazard__landslide_susceptibility__user_group')).toEqual({ kind: 'raster', layer: 'lsi', area: 'user_group' });
    expect(hazardLegendTarget('thememap:hazard__factor_of_safety')?.layer).toBe('fs');
    expect(hazardLegendTarget('thememap:hazard__landslide_prone_area')?.layer).toBe('prone');
  });

  it('maps the factor bands and the household dots', () => {
    expect(hazardLegendTarget('thememap:soil__factor_ls')?.layer).toBe('f_soil_ls');
    expect(hazardLegendTarget('thememap:hazard__lsi_factor_dist_road')?.layer).toBe('f_lsi_dist_road');
    expect(hazardLegendTarget('thememap:hh__vulnerability')).toEqual({ kind: 'dots', layer: 'households', area: 'forest' });
    expect(hazardLegendTarget('thememap:hh__priority_settlements__user_group')).toEqual({ kind: 'dots', layer: 'settlements', area: 'user_group' });
  });

  it('has nothing for a map it does not know', () => {
    expect(hazardLegendTarget('thememap:something__else')).toBeNull();
    expect(hazardLegendTarget('thememap:hazard__lsi_factor_nope')).toBeNull();
  });
});

describe('SfmMapLegend', () => {
  it('lists only the classes returned, each with units, hectares and share', async () => {
    getSfm.mockResolvedValue(sfmReady('sfm__forest_type', [cls('3', '#009E73', 2, 20, 66.7), cls('7', '#0072B2', 1, 10, 33.3)]));
    render(<SfmMapLegend calculationId="c1" specKey="sfm__forest_type" />);
    expect(await screen.findByText('Type 3')).toBeInTheDocument();
    expect(screen.getByText('Type 7')).toBeInTheDocument();
    expect(screen.queryByText('Type 1')).toBeNull();
    expect(screen.getByTestId('legend-row-3')).toHaveTextContent('2 units · 20.0 ha · 66.7%');
    expect(getSfm).toHaveBeenCalledWith('c1', 'sfm__forest_type', undefined);
  });

  it('names the stock classes with their thresholds and leaves out the ones nobody falls in', async () => {
    getSfm.mockResolvedValue(sfmReady('sfm__gs_vs_threshold', [cls('1', '#ffffbf', 2, 20, 66.7), cls('2', '#2b83ba', 1, 10, 33.3)]));
    render(<SfmMapLegend calculationId="c1" specKey="sfm__gs_vs_threshold" variant="user" />);
    expect(await screen.findByText(/150 – 200/)).toBeInTheDocument();
    expect(screen.getByText(/> 200/)).toBeInTheDocument();
    expect(screen.queryByText(/< 150/)).toBeNull();
    expect(getSfm).toHaveBeenCalledWith('c1', 'sfm__gs_vs_threshold', 'user');
  });

  it('says it is not available until the classification is built', async () => {
    getSfm.mockResolvedValue({ state: 'not_computed', key: 'sfm__forest_type' });
    render(<SfmMapLegend calculationId="c1" specKey="sfm__forest_type" />);
    expect(await screen.findByText('Not available until the classification is built.')).toBeInTheDocument();
  });

  it('says so when the legend cannot be loaded', async () => {
    getSfm.mockRejectedValue(new Error('boom'));
    render(<SfmMapLegend calculationId="c1" specKey="sfm__forest_type" />);
    expect(await screen.findByText('The legend could not be loaded.')).toBeInTheDocument();
  });
});

describe('HazardMapLegend', () => {
  const raster = (relative: boolean) => ({
    state: 'ready',
    key: 'lsi',
    relative,
    total_ha: 100,
    classes: [
      { index: 0, color: '#1a9641', label_ne: 'न', label_en: 'Relatively low', from: 0, to: 1.8, area_ha: 60, share_pct: 60 },
      { index: 3, color: '#d7191c', label_ne: 'उ', label_en: 'Relatively high', from: 3.4, to: null, area_ha: 40, share_pct: 40 },
    ],
  });

  it('shows the classes this forest has with hectares and share, and the relative note for the landslide map', async () => {
    getHazard.mockResolvedValue(raster(true));
    render(<HazardMapLegend calculationId="c1" mapKey="thememap:hazard__landslide_susceptibility" />);
    expect(await screen.findByText('Relatively low')).toBeInTheDocument();
    expect(screen.getByTestId('legend-row-3')).toHaveTextContent('Relatively high');
    expect(screen.getByTestId('legend-row-3')).toHaveTextContent('40.0 ha · 40.0%');
    expect(screen.getByText('Classes are relative to this forest.')).toBeInTheDocument();
    expect(getHazard).toHaveBeenCalledWith('c1', 'lsi', 'forest');
  });

  it('asks for the user-group view when the map is the user-group one, and has no relative note for an absolute map', async () => {
    getHazard.mockResolvedValue(raster(false));
    render(<HazardMapLegend calculationId="c1" mapKey="thememap:soil__annual_loss__user_group" />);
    await screen.findByText('Relatively low');
    expect(getHazard).toHaveBeenCalledWith('c1', 'soil', 'user_group');
    expect(screen.queryByText('Classes are relative to this forest.')).toBeNull();
  });

  it('says when the map has not been computed or there is no user group', async () => {
    getHazard.mockResolvedValue({ state: 'not_computed', key: 'soil' });
    const { unmount } = render(<HazardMapLegend calculationId="c1" mapKey="thememap:soil__annual_loss" />);
    expect(await screen.findByText('Not computed yet — open the Hazard & Erosion tab.')).toBeInTheDocument();
    unmount();
    getHazard.mockResolvedValue({ state: 'no_user_group', key: 'soil' });
    render(<HazardMapLegend calculationId="c1" mapKey="thememap:soil__annual_loss__user_group" />);
    expect(await screen.findByText(/No user group boundary yet/)).toBeInTheDocument();
  });

  it('draws a gradient with the range of scores for the household dots', async () => {
    getDots.mockResolvedValue({ state: 'ready', kind: 'households', count: 118, n_priority: 12, min: 0.2, max: 0.9 });
    render(<HazardMapLegend calculationId="c1" mapKey="thememap:hh__vulnerability" />);
    expect(await screen.findByTestId('legend-gradient')).toBeInTheDocument();
    expect(screen.getByText(/118 households/)).toBeInTheDocument();
    expect(getDots).toHaveBeenCalledWith('c1', 'households', 'forest');
    expect(getHazard).not.toHaveBeenCalled();
  });

  it('renders nothing for a map with no legend source (its image carries its own)', () => {
    const { container } = render(<HazardMapLegend calculationId="c1" mapKey="thememap:something__else" />);
    expect(container.innerHTML).toBe('');
  });
});
