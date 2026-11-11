import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AdminSfmPrescriptionsPage, { RowEditor } from '../AdminSfmPrescriptionsPage';
import * as api from '../../services/api';
import type { SfmPrescription } from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    sfmPrescriptionApi: { list: vi.fn(), get: vi.fn(), put: vi.fn() },
  };
});

const mockList = api.sfmPrescriptionApi.list as unknown as ReturnType<typeof vi.fn>;
const mockPut = api.sfmPrescriptionApi.put as unknown as ReturnType<typeof vi.fn>;

const row = (n: number): SfmPrescription => ({
  type_no: n,
  name_ne: `प्रकार ${n}`,
  name_en: `Type ${n}`,
  species_groups: ['SAL'],
  zone_triggers: ['LOWLAND_SAL'],
  slope_band: 1,
  origin: null,
  orientation: 'Production',
  branches: {
    adequate: {
      method: 'selection_felling_cycle',
      system_ne: 'छनौट',
      system_en: 'Selection',
      felling_cycle_years: 10,
      regeneration_period_years: null,
      rotation_years: null,
      regen_method_ne: '',
      regen_method_en: '',
      mother_trees_per_ha: null,
      yield_rules: {
        basis: 'growing_stock_pct_ge40',
        steps: [{ gs_per_ha_min: 200, gs_per_ha_max: null, pct: 2.0 }],
        target_stems_per_ha: null,
        note_ne: '',
        note_en: '',
      },
      note_ne: '',
      note_en: '',
    },
  },
  notes_ne: null,
  notes_en: null,
  is_active: true,
  sort_order: n * 10,
});

const ROWS = Array.from({ length: 14 }, (_, i) => row(i + 1));

beforeEach(() => {
  mockList.mockReset();
  mockPut.mockReset();
  mockList.mockResolvedValue(ROWS);
  mockPut.mockImplementation(async (_n, body) => ({ ..._n, ...body, type_no: _n }));
});

describe('AdminSfmPrescriptionsPage', () => {
  it('renders the 14 seeded rows', async () => {
    render(<AdminSfmPrescriptionsPage />);
    await waitFor(() => expect(mockList).toHaveBeenCalled());
    expect(await screen.findByText('प्रकार 1')).toBeInTheDocument();
    expect(screen.getByText('प्रकार 14')).toBeInTheDocument();
    // one <tr> per type
    expect(document.querySelectorAll('tbody.ant-table-tbody tr.ant-table-row').length).toBe(14);
  });

  it('the row editor saves a retuned yield step without a type_no in the body', async () => {
    render(<RowEditor row={row(1)} onSaved={vi.fn()} />);

    // spinbuttons in order = felling cycle, regen period, step min, step max, step %
    const spin = screen.getAllByRole('spinbutton');
    const pctInput = spin[spin.length - 1];
    fireEvent.change(pctInput, { target: { value: '2.5' } });
    fireEvent.blur(pctInput);

    fireEvent.click(screen.getByRole('button', { name: /Save this forest type/ }));
    await waitFor(() => expect(mockPut).toHaveBeenCalled());
    const [typeNo, body] = mockPut.mock.calls[0];
    expect(typeNo).toBe(1);
    expect(body.branches.adequate.yield_rules.steps[0].pct).toBe(2.5);
    expect('type_no' in body).toBe(false);
  });
});
