import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import HazardMapPanel from '../HazardMapPanel';
import * as api from '../../../services/api';
import type { HazardErosionMap } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    // the legend under the map is covered in MapLegend.test.tsx; keep it off the network here
    hazardErosionApi: {
      ...actual.hazardErosionApi,
      getMapLegend: vi.fn().mockResolvedValue({ state: 'not_computed', key: 'x' }),
      getDotsSummary: vi.fn().mockResolvedValue({ state: 'not_computed', kind: 'households' }),
    },
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      mapVariablePreviewObjectUrl: vi.fn(),
    },
  };
});

const mockPreview = api.operationalPlanApi
  .mapVariablePreviewObjectUrl as unknown as ReturnType<typeof vi.fn>;

const mk = (over: Partial<HazardErosionMap>): HazardErosionMap => ({
  key: 'thememap:hazard__landslide_susceptibility',
  label_ne: 'LSI ने',
  label_en: 'LSI',
  section: 'S9',
  is_factor_band: false,
  is_user_group: false,
  available: true,
  reason_ne: '',
  ...over,
});

const MAPS: HazardErosionMap[] = [
  mk({}),
  mk({
    key: 'thememap:hazard__landslide_susceptibility__user_group',
    label_en: 'LSI — UG',
    is_user_group: true,
  }),
  mk({ key: 'thememap:soil__annual_loss', label_en: 'Soil loss' }),
  mk({
    key: 'thememap:hazard__lsi_factor_slope',
    label_en: 'LSI factor — slope',
    is_factor_band: true,
  }),
  mk({ key: 'thememap:hh__vulnerability', label_en: 'Household vulnerability' }),
];

beforeEach(() => {
  mockPreview.mockReset();
  mockPreview.mockResolvedValue('blob:fake');
});

describe('HazardMapPanel', () => {
  it('renders an image for the default map and a caveat', async () => {
    render(<HazardMapPanel calculationId="c1" maps={MAPS} hasUserGroup />);
    await waitFor(() => expect(mockPreview).toHaveBeenCalled());
    // default = first available primary (the LSI spec)
    expect(mockPreview.mock.calls[0][0]).toBe('thememap:hazard__landslide_susceptibility');
    expect(mockPreview.mock.calls[0][1]).toBe('c1');
    await waitFor(() => expect(document.querySelector('img')).toBeTruthy());
    // LSI caveat mentions "not a probability"
    expect(screen.getByText(/not a probability/i)).toBeTruthy();
  });

  it('swaps to the __user_group key when the toggle is set', async () => {
    render(<HazardMapPanel calculationId="c1" maps={MAPS} hasUserGroup />);
    await waitFor(() => screen.getByText('User group'));
    fireEvent.click(screen.getByText('User group'));
    await waitFor(() =>
      expect(mockPreview).toHaveBeenCalledWith(
        'thememap:hazard__landslide_susceptibility__user_group',
        'c1',
      ),
    );
  });

  it('hides the CF/UG toggle when there is no user-group extent', async () => {
    render(<HazardMapPanel calculationId="c1" maps={MAPS} hasUserGroup={false} />);
    await waitFor(() => expect(mockPreview).toHaveBeenCalled());
    expect(screen.queryByText('User group')).toBeNull();
  });

  it('shows a retry on a failed render', async () => {
    mockPreview.mockReset();
    mockPreview.mockRejectedValueOnce(new Error('boom')).mockResolvedValue('blob:ok');
    render(<HazardMapPanel calculationId="c1" maps={MAPS} hasUserGroup />);
    await waitFor(() => screen.getByText('Retry'));
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(mockPreview.mock.calls.length).toBeGreaterThan(1));
  });

  it('the household map switches the caveat text', async () => {
    render(<HazardMapPanel calculationId="c1" maps={MAPS} hasUserGroup />);
    await waitFor(() => screen.getByRole('combobox'));
    fireEvent.mouseDown(screen.getByRole('combobox'));
    await waitFor(() => screen.getByText('Household vulnerability'));
    fireEvent.click(screen.getByText('Household vulnerability'));
    await waitFor(() =>
      expect(screen.getByText(/No names, caste or coordinates/i)).toBeTruthy(),
    );
  });
});
