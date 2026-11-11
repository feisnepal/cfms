import { describe, it, expect, beforeEach, beforeAll, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

beforeAll(() => {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false, media: query, onchange: null,
      addListener: vi.fn(), removeListener: vi.fn(),
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  });
  class ResizeObserverMock { observe = vi.fn(); unobserve = vi.fn(); disconnect = vi.fn(); }
  (window as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverMock;
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:x';
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
});

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
const setSearchParams = vi.fn();
vi.mock('react-router-dom', () => ({
  useSearchParams: () => [new URLSearchParams(''), setSearchParams],
}));
vi.mock('../../services/api', () => ({
  operationalPlanApi: {
    listMapVariables: vi.fn(),
    mapVariablePreviewObjectUrl: vi.fn().mockResolvedValue('blob:x'),
    listMapVariableForests: vi.fn().mockResolvedValue({ forests: [] }),
  },
}));

import { operationalPlanApi } from '../../services/api';
import MapVariablesPage from '../MapVariablesPage';

const ROWS = [
  {
    key: 'thememap:unit__growing_stock', family: 'thememap', section: 'S3',
    section_ne: 'वन मौज्दात', section_en: 'Growing stock',
    label_ne: 'वन मौज्दात नक्सा', label_en: 'Growing Stock Map',
    description_ne: 'क', description_en: 'Growing stock per hectare by unit.',
    viz: 'choropleth', palette: 'growing_stock', palette_swatch: ['#edf8e9', '#006d2c'],
    basemap: 'canvas_light',
    preview_url: '/x.png',
    availability: {
      status: 'partial', copyable: true, requires: ['field_inventory'],
      reason_ne: 'x', reason_en: 'No field inventory has been processed.',
      hint_ne: 'x', hint_en: 'Upload and process a field inventory.',
    },
  },
  {
    key: 'thememap:zone__slope_mean', family: 'thememap', section: 'S9',
    section_ne: 'भू-बनोट', section_en: 'Physiography',
    label_ne: 'x', label_en: 'Zonal slope',
    description_ne: 'x', description_en: 'Per-unit mean slope from a raster.',
    viz: 'choropleth', palette: 'oranges', palette_swatch: ['#feedde'],
    basemap: 'hillshade', preview_url: '/y.png',
    availability: {
      status: 'unavailable', copyable: false, requires: ['raster_zonal'],
      reason_ne: 'x', reason_en: 'Not available yet.', hint_ne: 'x', hint_en: 'x',
    },
  },
];

describe('MapVariablesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (operationalPlanApi.listMapVariables as ReturnType<typeof vi.fn>).mockResolvedValue({
      total: ROWS.length, sections: {}, variables: ROWS,
    });
  });

  it('renders a card per map variable with its copyable token', async () => {
    render(<MapVariablesPage />);
    await waitFor(() => {
      expect(screen.getByText('{{thememap:unit__growing_stock}}')).toBeTruthy();
      expect(screen.getByText('{{thememap:zone__slope_mean}}')).toBeTruthy();
    });
  });

  it('shows the amber / red status pills', async () => {
    render(<MapVariablesPage />);
    await waitFor(() => {
      expect(screen.getByText(/mapVars\.status\.partial/)).toBeTruthy();
      expect(screen.getByText(/mapVars\.status\.unavailable/)).toBeTruthy();
    });
  });

  it('disables the copy button for a 🔴 (not-copyable) variable', async () => {
    render(<MapVariablesPage />);
    await waitFor(() => screen.getByText('{{thememap:zone__slope_mean}}'));
    const buttons = screen.getAllByTitle('mapVars.copy');
    // one enabled (growing_stock), one disabled (zone__slope_mean)
    expect(buttons.some((b) => (b as HTMLButtonElement).disabled)).toBe(true);
    expect(buttons.some((b) => !(b as HTMLButtonElement).disabled)).toBe(true);
  });

  it('loads the forest picker and puts the chosen forest in the URL', async () => {
    (operationalPlanApi.listMapVariableForests as ReturnType<typeof vi.fn>).mockResolvedValue({
      forests: [
        { calc_id: 'c-1', forest_name: 'बृन्दाबन', status: 'completed', has_field_inventory: true, created_at: null },
      ],
    });
    const { default: userEvent } = await import('@testing-library/user-event');
    const user = userEvent.setup();
    render(<MapVariablesPage />);
    const combo = await screen.findByRole('combobox');
    await user.click(combo);
    await user.click(await screen.findByText('बृन्दाबन'));
    expect(setSearchParams).toHaveBeenCalled();
    const calls = setSearchParams.mock.calls;
    const updater = calls[calls.length - 1]![0] as (p: URLSearchParams) => URLSearchParams;
    expect(updater(new URLSearchParams('')).get('calc_id')).toBe('c-1');
  });
});
