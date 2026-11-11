import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SfmSlopeHelperPanel from '../SfmSlopeHelperPanel';
import * as api from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    sfmApi: {
      ...actual.sfmApi,
      slopeClassPolygons: vi.fn(),
      draftProtectionSubarea: vi.fn(),
    },
  };
});

const mockFC = api.sfmApi.slopeClassPolygons as unknown as ReturnType<typeof vi.fn>;
const mockDraft = api.sfmApi
  .draftProtectionSubarea as unknown as ReturnType<typeof vi.fn>;

const writeText = vi.fn().mockResolvedValue(undefined);

const FC_TWO_BANDS: api.SfmSlopeClassFC = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { band: 1, label_ne: '< १९°', label_en: '< 19°', area_ha: 3.1 },
      geometry: { type: 'Polygon', coordinates: [] },
    },
    {
      type: 'Feature',
      properties: { band: 3, label_ne: '३१–४५°', label_en: '31–45°', area_ha: 2.2 },
      geometry: { type: 'Polygon', coordinates: [] },
    },
  ],
};

beforeEach(() => {
  mockFC.mockReset();
  mockDraft.mockReset();
  writeText.mockClear();
  Object.assign(navigator, { clipboard: { writeText } });
});

describe('SfmSlopeHelperPanel', () => {
  it('lists a row per slope band from the FeatureCollection', async () => {
    mockFC.mockResolvedValue(FC_TWO_BANDS);
    render(<SfmSlopeHelperPanel calculationId="c1" />);
    await waitFor(() => expect(mockFC).toHaveBeenCalledWith('c1'));
    expect(await screen.findByText('31–45°')).toBeInTheDocument();
    expect(screen.getByText('< 19°')).toBeInTheDocument();
    expect(screen.getByText(/2\.20/)).toBeInTheDocument();
  });

  it('shows the no-raster notice when the FeatureCollection is empty', async () => {
    mockFC.mockResolvedValue({ type: 'FeatureCollection', features: [] });
    render(<SfmSlopeHelperPanel calculationId="c1" />);
    expect(
      await screen.findByText(/no slope raster covers this forest/i),
    ).toBeInTheDocument();
  });

  it('generates a draft (default class ≥ 31°), shows the §23.2 hint, copies the GeoJSON', async () => {
    mockFC.mockResolvedValue(FC_TWO_BANDS);
    mockDraft.mockResolvedValue({
      min_band: 3,
      category: 'protected',
      polygon: { type: 'Polygon', coordinates: [[[84, 27]]] },
      slope_profile: { dominant_band: 3, area_pct_by_band: { '3': 70, '4': 30 } },
      hint_ne: 'ने संकेत',
      hint_en: 'A starting draft only — hand-edit it against the §23.2 checklist.',
    } as api.SfmDraftProtectionResponse);

    render(<SfmSlopeHelperPanel calculationId="c1" />);
    await screen.findByText('31–45°');

    await userEvent.click(screen.getByRole('button', { name: /generate draft/i }));
    await waitFor(() => expect(mockDraft).toHaveBeenCalledWith('c1', 3));

    expect(
      await screen.findByText(/hand-edit it against the §23.2 checklist/i),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole('button', { name: /copy polygon geojson/i }),
    );
    expect(writeText).toHaveBeenCalledWith(
      JSON.stringify({ type: 'Polygon', coordinates: [[[84, 27]]] }),
    );
  });

  it('reports when nothing that steep is inside the forest (404)', async () => {
    mockFC.mockResolvedValue(FC_TWO_BANDS);
    mockDraft.mockRejectedValue({ response: { status: 404 } });
    render(<SfmSlopeHelperPanel calculationId="c1" />);
    await screen.findByText('31–45°');
    await userEvent.click(screen.getByRole('button', { name: /generate draft/i }));
    expect(
      await screen.findByText(/no slope band that steep/i),
    ).toBeInTheDocument();
  });
});
