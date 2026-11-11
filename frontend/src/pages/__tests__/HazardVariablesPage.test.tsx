import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import HazardVariablesPage from '../HazardVariablesPage';
import * as api from '../../services/api';

vi.mock('react-chartjs-2', () => ({ Bar: () => <div data-testid="bar-chart" /> }));

vi.mock('../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../services/api')>();
  return {
    ...actual,
    hazardErosionApi: { ...actual.hazardErosionApi, variables: vi.fn() },
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      listMapVariableForests: vi.fn(),
      getVariableCatalog: vi.fn(),
      mapVariablePreviewObjectUrl: vi.fn(),
    },
  };
});

const mockHz = api.hazardErosionApi as unknown as { variables: ReturnType<typeof vi.fn> };
const mockOp = api.operationalPlanApi as unknown as {
  listMapVariableForests: ReturnType<typeof vi.fn>;
  getVariableCatalog: ReturnType<typeof vi.fn>;
  mapVariablePreviewObjectUrl: ReturnType<typeof vi.fn>;
};

const GROUPS = {
  calculation_id: 'c1',
  groups: [
    {
      id: 'numbers', label_ne: 'अङ्क', label_en: 'Headline numbers',
      variables: [{ key: 'hazard_landslide_prone_area_pct', label_ne: 'x', label_en: 'Prone %', var_type: 'number', registered: true }],
    },
    {
      id: 'maps', label_ne: 'नक्सा', label_en: 'Maps',
      variables: [{ key: 'thememap:hazard__landslide_susceptibility', label_ne: 'x', label_en: 'LSI', is_user_group: false }],
    },
    {
      id: 'tables', label_ne: 'तालिका', label_en: 'Tables',
      variables: [{ key: 'hazard_household_priority_table', label_ne: 'x', label_en: 'Priority HH', var_type: 'list', registered: true }],
    },
    {
      id: 'charts', label_ne: 'चार्ट', label_en: 'Charts',
      variables: [{ key: 'chart:hazard_slope_class_split', label_ne: 'x', label_en: 'Slope split', var_type: 'dict', registered: true }],
    },
  ],
};

beforeEach(() => {
  mockHz.variables.mockReset().mockResolvedValue(GROUPS);
  mockOp.listMapVariableForests.mockReset().mockResolvedValue({
    forests: [{ calc_id: 'c1', forest_name: 'बृन्दाबन', has_field_inventory: true }],
  });
  mockOp.getVariableCatalog.mockReset().mockResolvedValue({
    variables: [
      { key: 'hazard_landslide_prone_area_pct', var_type: 'number', resolved: 42 },
      { key: 'hazard_household_priority_table', var_type: 'list', resolved: [{ 'घर_नं': 1, 'अंक': 0.8 }] },
      { key: 'chart:hazard_slope_class_split', var_type: 'dict', resolved: { type: 'bar', labels: ['a'], datasets: [{ data: [1] }] } },
    ],
  });
  mockOp.mapVariablePreviewObjectUrl.mockReset().mockResolvedValue('blob:preview');
});

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={['/templates/hazard-variables?calc_id=c1']}>
      <HazardVariablesPage />
    </MemoryRouter>,
  );

describe('HazardVariablesPage', () => {
  it('renders the 5 groups with copyable tokens', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Headline numbers')).toBeTruthy());
    expect(screen.getByText('Maps')).toBeTruthy();
    expect(screen.getByText('Tables')).toBeTruthy();
    expect(screen.getByText('Charts')).toBeTruthy();
    expect(screen.getByText('{{hazard_landslide_prone_area_pct}}')).toBeTruthy();
  });

  it('shows the resolved scalar value', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('42')).toBeTruthy());
  });

  it('renders a real table for a list variable', async () => {
    renderPage();
    // column titles have underscores swapped for spaces; assert on a cell value
    await waitFor(() => expect(screen.getByText('0.8')).toBeTruthy());
    expect(screen.getAllByText('घर नं').length).toBeGreaterThan(0);
  });

  it('renders a chart component for a chart: variable', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByTestId('bar-chart')).toBeTruthy());
  });

  it('requests the catalog with the non-map keys only', async () => {
    renderPage();
    await waitFor(() => expect(mockOp.getVariableCatalog).toHaveBeenCalled());
    const [, params] = mockOp.getVariableCatalog.mock.calls[0];
    expect(params.keys).toContain('hazard_landslide_prone_area_pct');
    expect(params.keys).not.toContain('thememap:');
  });
});
