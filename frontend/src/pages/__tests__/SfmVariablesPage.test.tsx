import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SfmVariablesPage from '../SfmVariablesPage';
import * as api from '../../services/api';

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    sfmVariablesApi: { get: vi.fn() },
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      listMapVariableForests: vi.fn(),
      getVariableCatalog: vi.fn(),
      mapVariablePreviewObjectUrl: vi.fn(),
    },
  };
});

const mockVars = api.sfmVariablesApi.get as unknown as ReturnType<typeof vi.fn>;
const mockForests = api.operationalPlanApi
  .listMapVariableForests as unknown as ReturnType<typeof vi.fn>;
const mockCatalog = api.operationalPlanApi
  .getVariableCatalog as unknown as ReturnType<typeof vi.fn>;
const mockPreview = api.operationalPlanApi
  .mapVariablePreviewObjectUrl as unknown as ReturnType<typeof vi.fn>;

const GROUPS = {
  calculation_id: 'c1',
  groups: [
    {
      id: 'numbers',
      label_ne: 'अङ्क',
      label_en: 'Headline numbers',
      variables: [
        { key: 'sfm_total_annual_harvest_m3', label_ne: 'x', label_en: 'Allowable harvest', registered: true },
      ],
    },
    {
      id: 'maps',
      label_ne: 'नक्सा',
      label_en: 'Maps',
      variables: [
        { key: 'thememap:sfm__forest_type', label_ne: 'x', label_en: 'Forest type', registered: true },
      ],
    },
    {
      id: 'tables',
      label_ne: 'तालिका',
      label_en: 'Tables',
      variables: [
        { key: 'sfm_yield_table', label_ne: 'x', label_en: 'Yield table', registered: true },
      ],
    },
  ],
};

beforeEach(() => {
  mockVars.mockReset();
  mockForests.mockReset();
  mockCatalog.mockReset();
  mockPreview.mockReset();
  mockForests.mockResolvedValue({
    forests: [{ calc_id: 'c1', forest_name: 'बृन्दाबन', has_field_inventory: true }],
  });
  mockVars.mockResolvedValue(GROUPS);
  mockCatalog.mockResolvedValue({
    variables: [
      { key: 'sfm_total_annual_harvest_m3', var_type: 'number', resolved: 252 },
      { key: 'sfm_yield_table', var_type: 'list', resolved: [{ 'सि.नं.': 1, 'वार्षिक कटान (घन.मी.)': 252 }] },
    ],
  });
  mockPreview.mockResolvedValue('blob:fake');
});

describe('SfmVariablesPage', () => {
  it('auto-picks a forest, fetches the manifest and renders a preview per key', async () => {
    render(
      <MemoryRouter initialEntries={['/templates/sfm-variables']}>
        <SfmVariablesPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mockForests).toHaveBeenCalled());
    await waitFor(() => expect(mockVars).toHaveBeenCalledWith('c1'));

    // a scalar preview (also appears in the yield-table row)
    expect((await screen.findAllByText('252')).length).toBeGreaterThan(0);
    // the copy-token affordance for each variable
    expect(screen.getByText('{{sfm_total_annual_harvest_m3}}')).toBeInTheDocument();
    expect(screen.getByText('{{thememap:sfm__forest_type}}')).toBeInTheDocument();
    // the maps group asks for a thumbnail, not a catalog row
    await waitFor(() =>
      expect(mockPreview).toHaveBeenCalledWith('thememap:sfm__forest_type', 'c1'),
    );
    // the catalog is fetched only for the non-map keys
    const askedKeys = mockCatalog.mock.calls[0][1].keys;
    expect(askedKeys).not.toContain('thememap:');
  });
});
