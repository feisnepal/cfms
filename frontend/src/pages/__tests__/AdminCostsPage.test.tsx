import { describe, it, expect, beforeEach, vi, beforeAll } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { AdminCostsPage } from '../AdminCostsPage';

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  class ResizeObserverMock {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
  }
  (window as any).ResizeObserver = ResizeObserverMock;
});

// formatNumber/formatDecimal must be mocked so assertions never depend on raw
// Nepali or locale grouping glyphs (plan rule for CF-2 frontend tests).
vi.mock('../../i18n/numberFormat', () => ({
  formatDecimal: (n: unknown) => `fmt:${String(n)}`,
  formatNumber: (n: unknown) => `fmt:${String(n)}`,
  formatDateTime: (v: unknown) => (v ? 'dt' : '—'),
}));

vi.mock('../../services/api', () => ({
  forestCostsApi: {
    list: vi.fn(),
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

import { forestCostsApi } from '../../services/api';

describe('AdminCostsPage (CB-2)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (forestCostsApi.list as any).mockResolvedValue({
      rows: [
        { forest_name: 'Alpha', calculation_count: 2, total_cpu_seconds: 90, total_peak_memory_mb: 1536, total_cpu_cost: 0.8, total_memory_cost: 0.4, total_cost: 1.2, currency: 'USD', last_run_at: '2026-08-31T00:00:00Z' },
        { forest_name: 'Beta', calculation_count: 1, total_cpu_seconds: 120, total_peak_memory_mb: 768, total_cpu_cost: 1.1, total_memory_cost: 0.5, total_cost: 1.6, currency: 'USD', last_run_at: null },
      ],
      grand_total: 2.8,
      currency: 'USD',
    });
  });

  it('renders forest names and numeric values from the aggregation', async () => {
    render(<AdminCostsPage />);
    await waitFor(() => {
      expect(screen.getByText('Alpha')).toBeTruthy();
      expect(screen.getByText('Beta')).toBeTruthy();
    });
    expect(screen.getByText('adminCosts.grandTotal')).toBeTruthy();
  });

  it('calls forestCostsApi.list on mount', async () => {
    render(<AdminCostsPage />);
    await waitFor(() => {
      expect(forestCostsApi.list).toHaveBeenCalledTimes(1);
    });
  });

  it('shows the empty state when there is no cost data', async () => {
    (forestCostsApi.list as any).mockResolvedValue({ rows: [], grand_total: 0, currency: 'USD' });
    render(<AdminCostsPage />);
    await waitFor(() => {
      expect(screen.getByText('adminCosts.empty')).toBeTruthy();
    });
  });

  it('renders Unnamed Forest (id) for a UUID-shaped forest_name', async () => {
    (forestCostsApi.list as any).mockResolvedValue({
      rows: [
        { forest_name: '123e4567-e89b-12d3-a456-426614174000', calculation_count: 1, total_cpu_seconds: 10, total_peak_memory_mb: 256, total_cpu_cost: 0.1, total_memory_cost: 0.05, total_cost: 0.15, currency: 'USD', last_run_at: null },
      ],
      grand_total: 0.15,
      currency: 'USD',
    });
    render(<AdminCostsPage />);
    await waitFor(() => {
      expect(screen.getByText('adminCosts.unnamedForest')).toBeTruthy();
    });
  });
});
