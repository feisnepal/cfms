import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import HazardNarration from '../HazardNarration';
import * as api from '../../../services/api';
import type { HazardErosionNarration } from '../../../services/api';

vi.mock('../../../services/api', async (orig) => {
  const actual = await orig<typeof import('../../../services/api')>();
  return {
    ...actual,
    hazardErosionApi: {
      ...actual.hazardErosionApi,
      narration: vi.fn(),
      insertOpSubsections: vi.fn(),
    },
  };
});

const mockNarr = api.hazardErosionApi.narration as unknown as ReturnType<typeof vi.fn>;
const mockInsert = api.hazardErosionApi.insertOpSubsections as unknown as ReturnType<typeof vi.fn>;

const DATA: HazardErosionNarration = {
  calculation_id: 'c1',
  soil_available: true,
  hazard_available: true,
  soil: {
    methodology_ne: 'माटो विधि', methodology_en: 'Soil method text',
    findings_ne: 'माटो नतिजा', findings_en: 'Soil findings text',
    prescription_ne: 'माटो उपाय', prescription_en: 'Soil prescription text',
    assumptions_ne: ['माटो चेतावनी'], assumptions_en: ['Soil caveat one'],
  },
  hazard: {
    methodology_ne: 'पहिरो विधि', methodology_en: 'Hazard method text',
    findings_ne: 'पहिरो नतिजा', findings_en: 'Hazard findings text',
    prescription_ne: 'पहिरो उपाय', prescription_en: 'Hazard prescription text',
    assumptions_ne: ['पहिरो चेतावनी'], assumptions_en: ['Hazard caveat two'],
  },
};

const renderIt = () =>
  render(
    <MemoryRouter initialEntries={['/calculations/c1?tab=data-maps&context=hazarderosion']}>
      <HazardNarration calculationId="c1" lang="en" />
    </MemoryRouter>,
  );

beforeEach(() => {
  mockNarr.mockReset();
  mockInsert.mockReset();
  mockNarr.mockResolvedValue(DATA);
});

describe('HazardNarration', () => {
  it('renders the findings panel with the caveat box by default', async () => {
    renderIt();
    await waitFor(() => screen.getByText('Soil findings text'));
    expect(screen.getByText('Hazard findings text')).toBeTruthy();
    expect(screen.getByText('Soil caveat one')).toBeTruthy();
    expect(screen.getByText('Hazard caveat two')).toBeTruthy();
  });

  it('the language toggle switches to Nepali prose', async () => {
    renderIt();
    await waitFor(() => screen.getByText('Soil findings text'));
    fireEvent.click(screen.getByText('नेपाली'));
    await waitFor(() => expect(screen.getByText('माटो नतिजा')).toBeTruthy());
    expect(screen.getByText('पहिरो नतिजा')).toBeTruthy();
  });

  it('inserts the subsections and then offers to open the plan', async () => {
    mockInsert.mockResolvedValue({
      status: 'inserted',
      inserted: ['Soil Loss & Erosion Risk', 'Slope Instability, Landslide Hazard & Household Vulnerability'],
      plan_id: 'p1',
    });
    renderIt();
    await waitFor(() => screen.getByText('Insert ३.८ / ३.९ into the Operational Plan'));
    fireEvent.click(screen.getByText('Insert ३.८ / ३.९ into the Operational Plan'));
    await waitFor(() => expect(mockInsert).toHaveBeenCalledWith('c1'));
    await waitFor(() => expect(screen.getByText('Open the plan')).toBeTruthy());
  });

  it('warns when there is no Operational Plan yet', async () => {
    mockInsert.mockRejectedValue({ response: { data: { detail: { code: 'NO_OP' } } } });
    renderIt();
    await waitFor(() => screen.getByText('Insert ३.८ / ३.९ into the Operational Plan'));
    fireEvent.click(screen.getByText('Insert ३.८ / ३.९ into the Operational Plan'));
    await waitFor(() => expect(mockInsert).toHaveBeenCalled());
    // no "open the plan" button on the failure path
    expect(screen.queryByText('Open the plan')).toBeNull();
  });

  it('shows an error alert when the narration fetch fails', async () => {
    mockNarr.mockReset();
    mockNarr.mockRejectedValue(new Error('boom'));
    renderIt();
    await waitFor(() =>
      expect(screen.getByText('Could not load the interpretation.')).toBeTruthy(),
    );
  });
});
