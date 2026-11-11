import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { SamplingTab } from '../SamplingTab';

// English translation map for test mock
const enTranslations: Record<string, string> = {
  'sampling.createNewDesign': '+ Create New Sampling Design',
  'sampling.createDesign': 'Create Design',
  'sampling.createDesignConfirm': 'Create sampling design with current settings?',
  'sampling.previewSamplePlots': 'Preview Sample Plots',
  'sampling.samplePlotPreview': 'Sample Plot Preview',
  'sampling.areaBasisFull': 'Full Block Area',
  'common.cancel': 'Cancel',
};

vi.mock('../../services/api', () => ({
  samplingApi: {
    list: vi.fn(),
    getPoints: vi.fn(),
    previewAccessibleForest: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    getProtectedZones: vi.fn(),
    preview: vi.fn(),
  },
  forestApi: {
    getCalculation: vi.fn(),
  },
  compartmentApi: {
    getAvailableBlocks: vi.fn(),
  },
  sfmApi: {
    getSummary: vi.fn().mockResolvedValue({ forest_summary: { sampling_plan: [] } }),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => enTranslations[k] || k }),
}));

const t = (key: string): string => enTranslations[key] || key;

const mapPreviewProps = vi.fn();
vi.mock('../SamplingMapView', () => ({
  SamplingMapView: (props: any) => {
    mapPreviewProps(props);
    return <div data-testid="sampling-map-view" />;
  },
}));

vi.mock('../AccessibleForestPreview', () => ({
  AccessibleForestPreview: () => <div data-testid="accessible-preview" />,
}));

import { samplingApi, forestApi, compartmentApi } from '../../services/api';

const PREVIEW_FEATURE = {
  type: 'Feature' as const,
  geometry: { type: 'Point' as const, coordinates: [83.5, 27.5] },
  properties: { plot_number: 1, plot_id: 'P1', block_name: 'Block 1', zone_type: 'productive' },
};

function previewResponse() {
  return {
    calculation_id: 'calc-1',
    total_points: 3,
    total_units: 1,
    total_blocks: 1,
    area_basis: 'tree_cover',
    requested_intensity_percent: 0.5,
    forest_area_hectares: 30,
    actual_intensity_per_hectare: 0.5,
    plot_area_sqm: 500,
    total_sampled_area_hectares: 0.15,
    sampling_percentage: 0.5,
    sampling_type: 'systematic',
    preview_token: 'tok-1',
    boundary_layer: { type: 'Feature', geometry: null, properties: {} },
    forest_blocks_layer: null,
    filter_settings: { filter_tree_cover: true, filter_slope: false, max_slope_degrees: 45 },
    sampling_points_geojson: {
      type: 'FeatureCollection',
      features: [PREVIEW_FEATURE],
    },
  };
}

describe('SamplingTab — pre-create sample-plot preview (Phase F)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (samplingApi.list as any).mockResolvedValue([]);
    (samplingApi.getPoints as any).mockResolvedValue({ points: [] });
    (samplingApi.getProtectedZones as any).mockResolvedValue({ has_protected: false });
    (forestApi.getCalculation as any).mockResolvedValue({
      id: 'calc-1',
      name: 'Test Forest',
      result_data: {},
    });
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
    ]);
  });

  async function openForm() {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText('+ Create New Sampling Design');
    fireEvent.click(createBtn);
    await screen.findByText('Create Design');
  }

  it('preview button calls the preview endpoint with the current method params', async () => {
    (samplingApi.preview as any).mockResolvedValue(previewResponse());
    await openForm();

    fireEvent.click(screen.getByText('📍 Preview Sample Plots'));

    await waitFor(() => expect(samplingApi.preview).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.preview as any).mock.calls;
    expect(params.sampling_method).toBe('guideline_2061');
    expect(params.filter_tree_cover).toBe(true);
    // SS-1.5: the production-stratum floor (कार्यविधि §16) is 2.0%, so that
    // is now the dropdown's default, not the old pre-enforcement 0.5%.
    expect(params.productive_intensity).toBe('2.0');
  });

  it('preview result renders the map with boundary/points GeoJSON (F.2)', async () => {
    (samplingApi.preview as any).mockResolvedValue(previewResponse());
    await openForm();

    fireEvent.click(screen.getByText('📍 Preview Sample Plots'));
    await screen.findByText(/Sample Plot Preview/);

    const lastProps = mapPreviewProps.mock.calls[mapPreviewProps.mock.calls.length - 1][0];
    expect(lastProps.preview.calculation_id).toBe('calc-1');
    expect(lastProps.preview.sampling_points_geojson.features).toHaveLength(1);
    expect(screen.getByText('3')).toBeTruthy();
  });

  it('create after preview sends the exact captured preview payload (F.3)', async () => {
    (samplingApi.preview as any).mockResolvedValue(previewResponse());
    await openForm();

    fireEvent.click(screen.getByText('📍 Preview Sample Plots'));
    await screen.findByText(/Sample Plot Preview/);

    fireEvent.click(screen.getByText(t('sampling.createDesignConfirm')));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.preview).toBeDefined();
    expect(params.preview.preview_token).toBe('tok-1');
    expect(params.preview.sampling_points_geojson.features).toHaveLength(1);
    expect(params.preview.sampling_points_geojson.features[0].geometry.coordinates).toEqual([83.5, 27.5]);
  });

  it('changing sampling settings clears the captured preview (no stale replay)', async () => {
    (samplingApi.preview as any).mockResolvedValue(previewResponse());
    await openForm();

    fireEvent.click(screen.getByText('📍 Preview Sample Plots'));
    await screen.findByText(/Sample Plot Preview/);

    // Switch to Full Block Area basis → preview must be invalidated
    fireEvent.click(screen.getByText(/Full Block Area/));
    await waitFor(() => expect(screen.queryByText(/Sample Plot Preview/)).toBeNull());

    fireEvent.click(screen.getByText(t('sampling.createDesignConfirm')));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [[, params]] = (samplingApi.create as any).mock.calls;
    expect(params.preview).toBeUndefined();
    expect(params.filter_tree_cover).toBe(false);
  });
});
