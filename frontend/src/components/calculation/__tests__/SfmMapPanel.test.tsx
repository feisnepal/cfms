import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import SfmMapPanel from '../SfmMapPanel';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    operationalPlanApi: {
      ...actual.operationalPlanApi,
      mapVariablePreviewObjectUrl: vi.fn(),
    },
    sfmApi: { ...actual.sfmApi, getMapLegend: vi.fn() },
  };
});

const mockPreview = api.operationalPlanApi
  .mapVariablePreviewObjectUrl as unknown as ReturnType<typeof vi.fn>;

const mockLegend = api.sfmApi.getMapLegend as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockLegend.mockReset();
  mockLegend.mockImplementation(async (_id: string, spec: string) =>
    spec === 'sfm__orientation'
      ? { state: 'ready', key: spec, total_ha: 30, classes: [{ key: 'Production', color: '#3182bd', label_ne: 'उ', label_en: 'Production', count: 2, area_ha: 20, share_pct: 66.7 }, { key: 'Protection', color: '#15803d', label_ne: 'प्र', label_en: 'Protection', count: 1, area_ha: 10, share_pct: 33.3 }] }
      : { state: 'ready', key: spec, total_ha: 30, classes: [{ key: '3', color: '#009E73', label_ne: '३', label_en: '3', count: 2, area_ha: 20, share_pct: 66.7 }, { key: '7', color: '#0072B2', label_ne: '७', label_en: '7', count: 1, area_ha: 10, share_pct: 33.3 }] },
  );
  mockPreview.mockReset();
  mockPreview.mockResolvedValue('blob:fake');
});

describe('SfmMapPanel', () => {
  it('renders the forest-type map by default with a legend of only the types this forest has', async () => {
    render(<SfmMapPanel calculationId="c1" />);
    await waitFor(() => expect(mockPreview).toHaveBeenCalled());
    expect(mockPreview.mock.calls[0][0]).toBe('thememap:sfm__forest_type');
    expect(mockPreview.mock.calls[0][1]).toBe('c1');
    await waitFor(() => expect(document.querySelector('img')).toBeTruthy());
    // only the types the forest has, each with its units, hectares and share - never all 14
    expect(await screen.findByText('Type 3')).toBeInTheDocument();
    expect(screen.getByText('Type 7')).toBeInTheDocument();
    expect(screen.queryByText('Type 1')).not.toBeInTheDocument();
    expect(screen.queryByText('Type 14')).not.toBeInTheDocument();
    expect(screen.getByTestId('legend-row-3')).toHaveTextContent('2 units · 20.0 ha · 66.7%');
    expect(mockLegend).toHaveBeenCalledWith('c1', 'sfm__forest_type', undefined);
  });

  it('switching the Segmented re-fetches the chosen spec', async () => {
    render(<SfmMapPanel calculationId="c1" />);
    await waitFor(() => screen.getByText('Orientation'));
    fireEvent.click(screen.getByText('Orientation'));
    await waitFor(() =>
      expect(mockPreview).toHaveBeenCalledWith(
        'thememap:sfm__orientation',
        'c1',
        undefined,
      ),
    );
    // orientation legend — labels match अनुसूची-१'s own wording
    // ("Production oriented" / "Conservation oriented" / bare "Protection")
    expect(await screen.findByText('Production oriented')).toBeInTheDocument();
    expect(screen.getByText('Protection')).toBeInTheDocument();
    expect(screen.queryByText('Conservation oriented')).not.toBeInTheDocument(); // not in this forest
    expect(mockLegend).toHaveBeenCalledWith('c1', 'sfm__orientation', undefined);
  });

  it('shows a retry on a failed render', async () => {
    mockPreview.mockReset();
    mockPreview.mockRejectedValueOnce(new Error('boom')).mockResolvedValue('blob:ok');
    render(<SfmMapPanel calculationId="c1" />);
    await waitFor(() => screen.getByText('Retry'));
    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(mockPreview.mock.calls.length).toBeGreaterThan(1));
  });
});
