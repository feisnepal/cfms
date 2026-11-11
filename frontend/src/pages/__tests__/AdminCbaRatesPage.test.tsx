import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AdminCbaRatesPage from '../AdminCbaRatesPage';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return { ...actual, cbaRateApi: { get: vi.fn(), put: vi.fn() } };
});

const rate = api.cbaRateApi as unknown as Record<string, ReturnType<typeof vi.fn>>;

const DEFAULTS = {
  timber_sal: 12000,
  timber_mixed: 8000,
  timber_softwood: 5000,
  fuelwood: 1500,
  poles: 300,
  carbon: 3000,
  grass: 500,
  bedding: 300,
};

beforeEach(() => {
  vi.clearAllMocks();
  rate.get.mockResolvedValue({ rates: { timber_mixed: 9500 }, defaults: DEFAULTS });
});

describe('AdminCbaRatesPage', () => {
  it('loads the org rates and shows an override next to the default placeholder', async () => {
    render(<AdminCbaRatesPage />);
    await waitFor(() => expect(rate.get).toHaveBeenCalled());
    expect(screen.getByText('CBA — organisation default rates')).toBeTruthy();
    expect(screen.getByDisplayValue('9500')).toBeTruthy(); // the one override
  });

  it('saves the edited rates', async () => {
    rate.put.mockResolvedValue({ rates: { timber_mixed: 9500, carbon: 3200 }, defaults: DEFAULTS });
    render(<AdminCbaRatesPage />);
    await waitFor(() => screen.getByDisplayValue('9500'));
    fireEvent.click(screen.getByText('Save'));
    await waitFor(() => expect(rate.put).toHaveBeenCalledWith({ timber_mixed: 9500 }));
  });

  it('shows a retry on load failure', async () => {
    rate.get.mockReset();
    rate.get.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({
      rates: {},
      defaults: DEFAULTS,
    });
    render(<AdminCbaRatesPage />);
    await waitFor(() => screen.getByText('Could not load the organisation rates.'));
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.getByText('CBA — organisation default rates')).toBeTruthy());
  });
});
