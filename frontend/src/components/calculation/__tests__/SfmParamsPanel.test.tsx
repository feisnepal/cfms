import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import SfmParamsPanel from '../SfmParamsPanel';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    sfmParamsApi: { get: vi.fn(), patch: vi.fn(), reset: vi.fn() },
  };
});

const mockGet = api.sfmParamsApi.get as unknown as ReturnType<typeof vi.fn>;
const mockPatch = api.sfmParamsApi.patch as unknown as ReturnType<typeof vi.fn>;
const mockReset = api.sfmParamsApi.reset as unknown as ReturnType<typeof vi.fn>;

const RESP = {
  params: { seedling_threshold: 5000, harvestable_dbh_min_cm: 40 },
  provenance: { seedling_threshold: 'profile', harvestable_dbh_min_cm: 'default' } as Record<
    string,
    'default' | 'profile' | 'forest'
  >,
  customised: false,
};

beforeEach(() => {
  mockGet.mockReset();
  mockPatch.mockReset();
  mockReset.mockReset();
  mockGet.mockResolvedValue(RESP);
  mockPatch.mockImplementation(async (_id, patch) => ({ ...RESP, params: { ...RESP.params, ...patch }, customised: true }));
  mockReset.mockResolvedValue(RESP);
});

describe('SfmParamsPanel', () => {
  it('renders the provenance tags for non-default keys', async () => {
    render(<SfmParamsPanel calculationId="c1" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalledWith('c1'));
    // open the collapse
    fireEvent.click(screen.getByText('SFM parameters'));
    expect(await screen.findByText('seedling_threshold: profile')).toBeInTheDocument();
  });

  it('Save PATCHes only the changed keys (sparse patch)', async () => {
    render(<SfmParamsPanel calculationId="c1" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    fireEvent.click(screen.getByText('SFM parameters'));

    // change the crown-density field
    const crown = await screen.findByRole('spinbutton', { name: '' }).catch(() => null);
    void crown;
    const inputs = screen.getAllByRole('spinbutton');
    // "Crown density default (%)" is the 3rd numeric field
    fireEvent.change(inputs[2], { target: { value: '35' } });

    const saveBtn = screen.getByRole('button', { name: 'Save' });
    await waitFor(() => expect(saveBtn).not.toBeDisabled());
    fireEvent.click(saveBtn);

    await waitFor(() => expect(mockPatch).toHaveBeenCalled());
    const sent = mockPatch.mock.calls[0][1];
    expect(sent).toEqual({ crown_density_default: 35 });
  });

  it('Reset calls the DELETE adapter', async () => {
    mockGet.mockResolvedValue({ ...RESP, customised: true });
    render(<SfmParamsPanel calculationId="c1" />);
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    const resetBtn = screen.getByRole('button', { name: 'Reset to default' });
    await waitFor(() => expect(resetBtn).not.toBeDisabled());
    fireEvent.click(resetBtn);
    await waitFor(() => expect(mockReset).toHaveBeenCalledWith('c1'));
  });
});
