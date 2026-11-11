import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import HazardTables from '../HazardTables';
import * as api from '../../../services/api';
import type { HazardErosionTables } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    hazardErosionApi: { ...actual.hazardErosionApi, tables: vi.fn() },
  };
});

const mockTables = api.hazardErosionApi.tables as unknown as ReturnType<typeof vi.fn>;

const DATA: HazardErosionTables = {
  calculation_id: 'c1',
  fs_enabled: true,
  hh_available: true,
  has_user_group: false,
  soil_loss_by_unit: [
    { एकाइ: 'ब्लक १', औसत_क्षय_टन_हे_वर्ष: 12.4, क्षेत्रफल_हे: 30 },
    { एकाइ: 'ब्लक २', औसत_क्षय_टन_हे_वर्ष: 4.1, क्षेत्रफल_हे: 22 },
  ],
  soil_loss_aoi_comparison: [],
  lsi_area_by_class: [{ वर्ग: 'उच्च', क्षेत्रफल_हे: 8.2, 'क्षेत्रफल_%': 20 }],
  lsi_by_unit: [],
  fs_by_unit: [],
  hazard_aoi_comparison: [],
  hh_priority_table: [
    { घर_नं: 'H-1', टोल: 'माथिल्लो', जोखिम_अंक: 0.81, प्रमुख_कारक: 'Economic' },
    { घर_नं: 'H-2', टोल: 'तल्लो', जोखिम_अंक: 0.42, प्रमुख_कारक: 'Social' },
    { घर_नं: 'H-3', टोल: 'माथिल्लो', जोखिम_अंक: 0.67, प्रमुख_कारक: 'Economic' },
  ],
  hh_settlement_rollup_table: [],
  hh_driver_counts: [],
};

beforeEach(() => {
  mockTables.mockReset();
  mockTables.mockResolvedValue(DATA);
});

describe('HazardTables', () => {
  it('shows only the non-empty tables as tabs', async () => {
    render(<HazardTables calculationId="c1" />);
    await waitFor(() => screen.getByText('Soil loss by unit'));
    expect(screen.getByText('Landslide susceptibility by class')).toBeTruthy();
    expect(screen.getByText('Priority households')).toBeTruthy();
    // an empty table gets no tab
    expect(screen.queryByText('Settlement roll-up')).toBeNull();
  });

  it('renders Devanagari column headers from the dict keys', async () => {
    render(<HazardTables calculationId="c1" />);
    await waitFor(() => screen.getByText('Soil loss by unit'));
    expect(screen.getAllByText('एकाइ').length).toBeGreaterThan(0);
    expect(screen.getAllByText('औसत क्षय टन हे वर्ष').length).toBeGreaterThan(0);
  });

  it('the priority tab defaults to score-descending order', async () => {
    render(<HazardTables calculationId="c1" />);
    await waitFor(() => screen.getByText('Priority households'));
    fireEvent.click(screen.getByText('Priority households'));
    await waitFor(() => screen.getByText('Export CSV'));
    // rows render in descending जोखिम_अंक order (0.81, 0.67, 0.42)
    const bodyRows = document.querySelectorAll('.ant-tabs-tabpane-active tbody tr.ant-table-row');
    const houseCol = Array.from(bodyRows).map(
      (r) => r.querySelector('td')?.textContent,
    );
    expect(houseCol).toEqual(['H-1', 'H-3', 'H-2']);
  });

  it('exports the priority table to CSV with Devanagari headers', async () => {
    const created: Blob[] = [];
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    // jsdom implements neither — stub both for this test
    (URL as unknown as { createObjectURL: (b: Blob) => string }).createObjectURL = (b) => {
      created.push(b);
      return 'blob:stub';
    };
    (URL as unknown as { revokeObjectURL: (u: string) => void }).revokeObjectURL = () => {};
    try {
      render(<HazardTables calculationId="c1" />);
      await waitFor(() => screen.getByText('Priority households'));
      fireEvent.click(screen.getByText('Priority households'));
      await waitFor(() => screen.getByText('Export CSV'));
      fireEvent.click(screen.getByText('Export CSV'));
      await waitFor(() => expect(created.length).toBe(1));
      const csv = await created[0].text();
      expect(csv).toContain('जोखिम_अंक');
      expect(csv).toContain('घर_नं');
      expect(csv).toContain('H-1');
    } finally {
      (URL as unknown as { createObjectURL?: unknown }).createObjectURL = origCreate;
      (URL as unknown as { revokeObjectURL?: unknown }).revokeObjectURL = origRevoke;
    }
  });

  it('renders an error alert when the fetch fails', async () => {
    mockTables.mockReset();
    mockTables.mockRejectedValue(new Error('boom'));
    render(<HazardTables calculationId="c1" />);
    await waitFor(() => expect(screen.getByText('Could not load the tables.')).toBeTruthy());
  });

  it('shows an empty state when every table is empty', async () => {
    mockTables.mockReset();
    mockTables.mockResolvedValue({
      ...DATA,
      soil_loss_by_unit: [],
      lsi_area_by_class: [],
      hh_priority_table: [],
    });
    render(<HazardTables calculationId="c1" />);
    await waitFor(() =>
      expect(screen.getByText('No tables yet — run the analysis first.')).toBeTruthy(),
    );
  });
});
