import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { SamplingTab } from '../SamplingTab';

// English translation map for test mock
const enTranslations: Record<string, string> = {
  'sampling.createNewDesign': '+ Create New Sampling Design',
  'sampling.guidelineConfig': 'Guideline-2061 Configuration',
  'sampling.typeLabel': 'Sampling Type',
  'sampling.intensityProductiveForest': 'Sampling Intensity for Productive Forest',
  'sampling.areaFiltersTitle': 'Sampling Area Filters',
  'sampling.createDesign': 'Create Design',
  'sampling.createDesignConfirm': 'Create sampling design with current settings?',
  'common.cancel': 'Cancel',
  'sampling.stratumLabelProduction': 'Production',
  'sampling.stratumLabelConservation': 'Conservation',
  'sampling.stratumLabelProtection': 'Protection',
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

const t = (key: string): string => {
  const result = enTranslations[key] || key;
  if (!enTranslations[key]) console.log(`MISSING KEY: ${key}`);
  return result;
};

vi.mock('../SamplingMapView', () => ({
  SamplingMapView: () => <div data-testid="sampling-map-view" />,
}));

vi.mock('../AccessibleForestPreview', () => ({
  AccessibleForestPreview: () => <div data-testid="accessible-preview" />,
}));

import { samplingApi, forestApi, compartmentApi } from '../../services/api';

const mockFn = (impl?: () => Promise<unknown>) =>
  impl ? vi.fn(impl) : vi.fn();

describe('SamplingTab — removed per-block design (Phase B)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (samplingApi.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (samplingApi.getProtectedZones as ReturnType<typeof vi.fn>).mockResolvedValue({
      has_protected: false,
      protected_zone_count: 0,
      protected_area_hectares: 0,
    });
    (forestApi.getCalculation as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'calc-1',
      name: 'Test Forest',
      result_data: {
        blocks: [
          { block_name: 'Block 1', area_hectares: 10 },
          { block_name: 'Block 2', area_hectares: 5 },
        ],
      },
    });
    (compartmentApi.getAvailableBlocks as ReturnType<typeof vi.fn>).mockResolvedValue([
      { block_name: 'Block 1', has_compartments: false },
      { block_name: 'Block 2', has_compartments: false },
    ]);
  });

  it('renders the Guideline-2061 create form without Manual (Advanced) method (B.1)', async () => {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText(t('sampling.createNewDesign'));
    fireEvent.click(createBtn);

    await screen.findByText(t('sampling.guidelineConfig'));
    // Sampling Type selector IS shown in both modes, but Manual option should not exist
    expect(screen.queryByText('Manual Sampling Configuration')).toBeNull();
    expect(screen.getByText(t('sampling.intensityProductiveForest'))).toBeTruthy();
  });

  it('hides per-block customization / block overrides for multi-block forests (B.2)', async () => {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText(t('sampling.createNewDesign'));
    fireEvent.click(createBtn);

    await screen.findByText(t('sampling.guidelineConfig'));
    expect(screen.queryByText(/Per-Blocks? Customization/i)).toBeNull();
    expect(screen.queryByText('Enable')).toBeNull();
    expect(screen.queryByText('Customize')).toBeNull();
    expect(screen.queryByText('Block 1')).toBeNull();
    expect(screen.queryByText('Block 2')).toBeNull();
    // Only the read-only global summary remains (kept for B.3)
    expect(screen.getByText(t('sampling.areaFiltersTitle'))).toBeTruthy();
  });

  it('create payload no longer sends manual-only fields or block_overrides (B.2/B.3)', async () => {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText(t('sampling.createNewDesign'));
    fireEvent.click(createBtn);
    await screen.findByText(t('sampling.guidelineConfig'));

    // Debug: log the container HTML
    console.log('Container HTML:', document.body.innerHTML);

    const submit = await screen.findByText(t('sampling.createDesignConfirm'), undefined, { timeout: 5000 });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(samplingApi.create).toHaveBeenCalledTimes(1);
    });
    const [[, params]] = (samplingApi.create as ReturnType<typeof vi.fn>).mock.calls;
    expect(params.sampling_method).toBe('guideline_2061');
    expect(params.block_overrides).toBeUndefined();
    expect(params.sampling_type).toBeUndefined();
    expect(params.plot_shape).toBeUndefined();
    expect(params.min_samples_per_block).toBeUndefined();
  });

  it('enforce_min_samples_{production,conservation,protection} all default to checked/true in the create payload', async () => {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText(t('sampling.createNewDesign'));
    fireEvent.click(createBtn);
    await screen.findByText(t('sampling.guidelineConfig'));

    const prodCheckbox = screen.getByText('Production').closest('label')!.querySelector('input') as HTMLInputElement;
    const consCheckbox = screen.getByText('Conservation').closest('label')!.querySelector('input') as HTMLInputElement;
    const protCheckbox = screen.getByText('Protection').closest('label')!.querySelector('input') as HTMLInputElement;
    expect(prodCheckbox.checked).toBe(true);
    expect(consCheckbox.checked).toBe(true);
    expect(protCheckbox.checked).toBe(true);

    const submit = await screen.findByText(t('sampling.createDesignConfirm'), undefined, { timeout: 5000 });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(samplingApi.create).toHaveBeenCalledTimes(1);
    });
    const [[, params]] = (samplingApi.create as ReturnType<typeof vi.fn>).mock.calls;
    expect(params.enforce_min_samples_production).toBe(true);
    expect(params.enforce_min_samples_conservation).toBe(true);
    expect(params.enforce_min_samples_protection).toBe(true);
  });

  it('unchecking only the Conservation toggle sends enforce_min_samples_conservation=false while the other two stay true', async () => {
    render(<SamplingTab calculationId="calc-1" />);
    const createBtn = await screen.findByText(t('sampling.createNewDesign'));
    fireEvent.click(createBtn);
    await screen.findByText(t('sampling.guidelineConfig'));

    const consCheckbox = screen.getByText('Conservation').closest('label')!.querySelector('input') as HTMLInputElement;
    fireEvent.click(consCheckbox);

    const submit = await screen.findByText(t('sampling.createDesignConfirm'), undefined, { timeout: 5000 });
    fireEvent.click(submit);

    await waitFor(() => {
      expect(samplingApi.create).toHaveBeenCalledTimes(1);
    });
    const [[, params]] = (samplingApi.create as ReturnType<typeof vi.fn>).mock.calls;
    expect(params.enforce_min_samples_production).toBe(true);
    expect(params.enforce_min_samples_conservation).toBe(false);
    expect(params.enforce_min_samples_protection).toBe(true);
  });
});