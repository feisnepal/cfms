/**
 * What a host (the map workspace's "Create sample plots" modal) needs from SamplingTab:
 * open on the create form, and be told when a design is created or deleted.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, fireEvent, screen, waitFor } from '@testing-library/react';
import { SamplingTab } from '../SamplingTab';

const enTranslations: Record<string, string> = {
  'sampling.createNewDesign': '+ Create New Sampling Design',
  'sampling.createDesign': 'Create Design',
  'sampling.createDesignConfirm': 'Create sampling design with current settings?',
  'sampling.oneDesignPerForestTitle': 'One design per forest',
  'common.delete': 'Delete',
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
  forestApi: { getCalculation: vi.fn() },
  compartmentApi: { getAvailableBlocks: vi.fn() },
  sfmApi: { getSummary: vi.fn().mockResolvedValue({ forest_summary: { sampling_plan: [] } }) },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => enTranslations[k] || k }),
}));
vi.mock('../SamplingMapView', () => ({ SamplingMapView: () => <div data-testid="sampling-map-view" /> }));
vi.mock('../AccessibleForestPreview', () => ({ AccessibleForestPreview: () => <div /> }));

import { samplingApi, forestApi, compartmentApi } from '../../services/api';

const DESIGN = { id: 'd1', result_data: { blocks_info: [] }, default_parameters: {} };

describe('SamplingTab — as hosted by the map workspace', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    vi.spyOn(window, 'alert').mockImplementation(() => {});
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    (samplingApi.list as any).mockResolvedValue([]);
    (samplingApi.getPoints as any).mockResolvedValue({ points: [] });
    (samplingApi.getProtectedZones as any).mockResolvedValue({ has_protected: false });
    (samplingApi.create as any).mockResolvedValue({ blocks_info: [] });
    (samplingApi.delete as any).mockResolvedValue(undefined);
    (compartmentApi.getAvailableBlocks as any).mockResolvedValue([]);
    (forestApi.getCalculation as any).mockResolvedValue({ id: 'calc-1', name: 'Forest', result_data: {} });
  });

  it('startInCreateForm opens on the form when there is no design yet', async () => {
    render(<SamplingTab calculationId="calc-1" startInCreateForm />);
    expect(await screen.findByText('Create Design')).toBeTruthy();
    // The stand-alone page's "Create New Design" gate is skipped.
    expect(screen.queryByText('+ Create New Sampling Design')).toBeNull();
  });

  it('by default (the Sampling page) it still waits for the user to ask for the form', async () => {
    render(<SamplingTab calculationId="calc-1" />);
    expect(await screen.findByText('+ Create New Sampling Design')).toBeTruthy();
    expect(screen.queryByText('Create Design')).toBeNull();
  });

  it('startInCreateForm does not override the one-design-per-forest notice when a design exists', async () => {
    (samplingApi.list as any).mockResolvedValue([DESIGN]);
    render(<SamplingTab calculationId="calc-1" startInCreateForm />);
    expect(await screen.findByText('One design per forest')).toBeTruthy();
    expect(screen.queryByText('Create Design')).toBeNull();
  });

  it('reports "created" after the design is created, once the tab has reloaded', async () => {
    const onDesignChanged = vi.fn();
    render(<SamplingTab calculationId="calc-1" startInCreateForm onDesignChanged={onDesignChanged} />);
    await screen.findByText('Create Design');

    fireEvent.click(screen.getByText('Create sampling design with current settings?'));

    await waitFor(() => expect(onDesignChanged).toHaveBeenCalledWith('created'));
    expect(samplingApi.create).toHaveBeenCalledTimes(1);
    // The tab reloaded its own designs before telling the host.
    expect((samplingApi.list as any).mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it('does not report "created" when the server refuses', async () => {
    (samplingApi.create as any).mockRejectedValue({ response: { data: { detail: 'sampling.design_already_exists' } } });
    const onDesignChanged = vi.fn();
    render(<SamplingTab calculationId="calc-1" startInCreateForm onDesignChanged={onDesignChanged} />);
    await screen.findByText('Create Design');

    fireEvent.click(screen.getByText('Create sampling design with current settings?'));

    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(window.alert).toHaveBeenCalled());
    expect(onDesignChanged).not.toHaveBeenCalled();
  });

  it('has no slope filter: the server never applies it, so the form must not offer it', async () => {
    render(<SamplingTab calculationId="calc-1" startInCreateForm />);
    await screen.findByText('Create Design');

    // No checkbox or selector for it, and nothing in the form is about slope.
    expect(screen.queryByText('sampling.slopeFilterTitle')).toBeNull();
    expect(screen.queryByText('sampling.maxSlopeThreshold')).toBeNull();
    expect(screen.queryByRole('checkbox', { name: /slope/i })).toBeNull();

    fireEvent.click(screen.getByText('Create sampling design with current settings?'));
    await waitFor(() => expect(samplingApi.create).toHaveBeenCalledTimes(1));
    const [, params] = (samplingApi.create as any).mock.calls[0];
    expect(params).not.toHaveProperty('filter_slope');
    expect(params).not.toHaveProperty('max_slope_degrees');
  });

  it('reports "deleted" after a design is deleted', async () => {
    (samplingApi.list as any).mockResolvedValueOnce([DESIGN]).mockResolvedValue([]);
    const onDesignChanged = vi.fn();
    render(<SamplingTab calculationId="calc-1" onDesignChanged={onDesignChanged} />);

    fireEvent.click(await screen.findByText('Delete'));

    await waitFor(() => expect(onDesignChanged).toHaveBeenCalledWith('deleted'));
    expect(samplingApi.delete).toHaveBeenCalledWith('d1');
  });
});
