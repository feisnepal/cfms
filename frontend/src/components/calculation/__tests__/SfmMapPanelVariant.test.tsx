import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
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
  };
});

const mockPreview = api.operationalPlanApi
  .mapVariablePreviewObjectUrl as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockPreview.mockReset();
  mockPreview.mockResolvedValue('blob:fake');
});

describe('SfmMapPanel variants (SV-1.10)', () => {
  it('defaults to the baseline (no variant param) and labels it Guideline', async () => {
    render(<SfmMapPanel calculationId="c1" />);
    await waitFor(() => expect(mockPreview).toHaveBeenCalled());
    // default forest-type map, calcId only — no variant param
    expect(mockPreview.mock.calls[0][0]).toBe('thememap:sfm__forest_type');
    expect(mockPreview.mock.calls[0][1]).toBe('c1');
    expect(mockPreview.mock.calls[0][2]).toBeUndefined();
    expect(screen.getByText('Guideline (raster)')).toBeInTheDocument();
  });

  it('sends variant=user on the preview URL and labels it My adjustments', async () => {
    render(<SfmMapPanel calculationId="c1" variant="user" />);
    await waitFor(() => expect(mockPreview).toHaveBeenCalled());
    expect(mockPreview.mock.calls[0][0]).toBe('thememap:sfm__forest_type');
    expect(mockPreview.mock.calls[0][1]).toBe('c1');
    expect(mockPreview.mock.calls[0][2]).toBe('user');
    expect(screen.getByText('My adjustments (workspace)')).toBeInTheDocument();
  });

  it('re-fetches when the variant prop changes', async () => {
    const { rerender } = render(<SfmMapPanel calculationId="c1" variant="baseline" />);
    await waitFor(() => expect(mockPreview.mock.calls.length).toBe(1));
    rerender(<SfmMapPanel calculationId="c1" variant="user" />);
    await waitFor(() => expect(mockPreview.mock.calls.length).toBe(2));
    expect(mockPreview.mock.calls[1][2]).toBe('user');
  });
});