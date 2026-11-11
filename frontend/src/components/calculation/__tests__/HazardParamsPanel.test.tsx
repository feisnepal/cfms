import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import HazardParamsPanel from '../HazardParamsPanel';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    soilErosionApi: { get: vi.fn(), patch: vi.fn(), reset: vi.fn() },
    hazardVulnApi: { get: vi.fn(), patch: vi.fn(), reset: vi.fn() },
  };
});

const soil = api.soilErosionApi as unknown as Record<string, ReturnType<typeof vi.fn>>;
const haz = api.hazardVulnApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const soilResp = (over = {}) => ({
  params: {},
  provenance: { r_method: 'default' },
  customised: false,
  ...over,
});
const hazResp = (over = {}) => ({
  params: {},
  provenance: { landslide: 'default', factor_of_safety: 'default', household: 'default' },
  customised: false,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  soil.get.mockResolvedValue(soilResp());
  haz.get.mockResolvedValue(hazResp());
});

describe('HazardParamsPanel', () => {
  it('renders both collapse groups and "all defaults" when nothing is overridden', async () => {
    render(<HazardParamsPanel calculationId="c1" />);
    await waitFor(() => expect(soil.get).toHaveBeenCalledWith('c1'));
    expect(screen.getByText('RUSLE soil loss')).toBeTruthy();
    expect(
      screen.getByText('Landslide hazard & household vulnerability'),
    ).toBeTruthy();
    expect(screen.getAllByText('all defaults').length).toBe(2);
  });

  it('shows provenance tags for a customised group', async () => {
    haz.get.mockResolvedValue(
      hazResp({ customised: true, provenance: { landslide: 'forest', factor_of_safety: 'default', household: 'profile' } }),
    );
    render(<HazardParamsPanel calculationId="c1" />);
    await waitFor(() => screen.getByText(/landslide: forest/));
    expect(screen.getByText(/household: profile/)).toBeTruthy();
  });

  it('Save is disabled until a field is dirty; Reset disabled unless customised', async () => {
    render(<HazardParamsPanel calculationId="c1" />);
    await waitFor(() => screen.getByText('Save'));
    expect(screen.getByText('Save').closest('button')).toBeDisabled();
    expect(screen.getByText('Reset to default').closest('button')).toBeDisabled();
  });

  it('Reset calls both reset endpoints and onSaved', async () => {
    soil.get.mockResolvedValue(soilResp({ customised: true, provenance: { r_method: 'forest' } }));
    soil.reset.mockResolvedValue(soilResp());
    haz.reset.mockResolvedValue(hazResp());
    const onSaved = vi.fn();
    render(<HazardParamsPanel calculationId="c1" onSaved={onSaved} />);
    await waitFor(() => expect(screen.getByText('Reset to default').closest('button')).not.toBeDisabled());
    fireEvent.click(screen.getByText('Reset to default'));
    await waitFor(() => expect(soil.reset).toHaveBeenCalledWith('c1'));
    expect(haz.reset).toHaveBeenCalledWith('c1');
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
