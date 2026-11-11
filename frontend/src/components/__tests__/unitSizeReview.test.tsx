/**
 * P8 - the unit size table and the two surfaces that render it.
 *
 * The assertions that matter are the guardrails from the plan, not the pixels:
 * a proposal is never applied, an unmergeable unit says so instead of naming a
 * neighbour, and the note renders nothing at all when nothing is missing.
 */

import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UnitSizeReviewPanel from '../sampling/UnitSizeReviewPanel';
import { UnsampledUnitsNote } from '../fieldInventory/UnsampledUnitsNote';
import UnitSizeTable from '../sampling/UnitSizeTable';
import * as api from '../../services/api';

vi.mock('../../services/api', async () => {
  const actual = await vi.importActual<typeof import('../../services/api')>(
    '../../services/api'
  );
  return {
    ...actual,
    getUnitSizeReview: vi.fn(),
    getUnsampledUnits: vi.fn(),
  };
});

const getUnitSizeReview = api.getUnitSizeReview as unknown as ReturnType<typeof vi.fn>;
const getUnsampledUnits = api.getUnsampledUnits as unknown as ReturnType<typeof vi.fn>;

const REVIEW = {
  calculation_id: 'c1',
  boundary_area_ha: 366.03,
  mmu_ha: 1,
  review_pct: 5,
  read_only: true,
  summary: { total: 3, sub_mmu: 1, review: 1, ok: 1, merge_offers: 1, unmergeable: 0 },
  candidates: [
    {
      block_name: 'C35',
      id: 'id-c35',
      layer_type: 'blocks',
      area_ha: 0.0178,
      band: 'sub_mmu' as const,
      action: 'merge_offer' as const,
      neighbour: 'C-6',
      neighbour_id: 'id-c6',
      neighbour_area_ha: 10.9165,
      unmergeable: false,
      reason: 'below the 1 ha MMU: too small to hold 5 x 500 m2 plots',
    },
    {
      block_name: 'ISLAND',
      id: 'id-island',
      layer_type: 'blocks',
      area_ha: 0.05,
      band: 'sub_mmu' as const,
      action: 'merge_offer' as const,
      neighbour: null,
      neighbour_id: null,
      neighbour_area_ha: null,
      unmergeable: true,
      reason: 'below the 1 ha MMU and no unit touches it',
    },
    {
      block_name: 'C-9',
      id: 'id-c9',
      layer_type: 'blocks',
      area_ha: 6.2105,
      band: 'review' as const,
      action: 'flag_only' as const,
      neighbour: null,
      neighbour_id: null,
      unmergeable: false,
      reason: 'C-9: 6.21 ha, under the review threshold',
    },
  ],
};

const NOTE = {
  field_inventory_id: 'f1',
  calculation_id: 'c1',
  total_units: 24,
  summarised_units: 21,
  review_pct: 5,
  read_only: true,
  summary: { total: 3, sub_mmu: 2, review: 1, ok: 0, merge_offers: 2, unmergeable: 1 },
  // All three, deliberately including a unit that is NOT a sliver (C-9): an
  // unsampled unit is not automatically a sliver, and the note must be able to
  // report that case too rather than implying everything missing is tiny.
  unsampled_units: REVIEW.candidates,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('UnitSizeTable', () => {
  it('names the unit and the proposed neighbour for a merge', () => {
    render(<UnitSizeTable candidates={[REVIEW.candidates[0]]} />);
    expect(screen.getByText('C35')).toBeInTheDocument();
    expect(screen.getByText('C-6')).toBeInTheDocument();
  });

  it('says an unmergeable unit cannot be merged, and names nobody', () => {
    render(<UnitSizeTable candidates={[REVIEW.candidates[1]]} />);
    expect(screen.getByText(/cannot be merged/i)).toBeInTheDocument();
    // It must not invent a neighbour for a unit that has none.
    expect(screen.queryByText('C-6')).not.toBeInTheDocument();
  });

  it('offers no merge proposal for a flagged-but-valid unit', () => {
    render(<UnitSizeTable candidates={[REVIEW.candidates[2]]} />);
    expect(screen.getByText('C-9')).toBeInTheDocument();
    // The proposal column exists (another row needs it) but stays empty for C-9.
    expect(screen.queryByText('C-6')).not.toBeInTheDocument();
  });

  it('shows the server reason verbatim rather than re-deriving it', () => {
    render(<UnitSizeTable candidates={[REVIEW.candidates[0]]} />);
    expect(
      screen.getByText(/too small to hold 5 x 500 m2 plots/)
    ).toBeInTheDocument();
  });

  it('states that merging happens elsewhere - it never applies one', () => {
    render(<UnitSizeTable candidates={[REVIEW.candidates[0]]} />);
    expect(screen.getByText(/only proposes/i)).toBeInTheDocument();
  });

  it('renders an empty state rather than an empty table', () => {
    render(<UnitSizeTable candidates={[]} />);
    expect(screen.getByText(/No units to review/i)).toBeInTheDocument();
  });

  it('shows the summary counts and both thresholds', () => {
    // i18next splits an interpolated string across text nodes, so assert on the
    // rendered text rather than on one element's textContent.
    const { container } = render(
      <UnitSizeTable
        candidates={REVIEW.candidates}
        summary={REVIEW.summary}
        mmuHa={1}
        reviewPct={5}
      />
    );
    const text = container.textContent || '';
    expect(text).toMatch(/3\s*units/);
    expect(text).toMatch(/1\s*below the MMU/);
    expect(text).toMatch(/1\s*flagged/);
    expect(text).toMatch(/Minimum management unit:\s*1\s*ha/);
    expect(text).toMatch(/Review screen:\s*5%/);
  });
});

describe('UnitSizeReviewPanel', () => {
  it('loads the review and renders the bands', async () => {
    getUnitSizeReview.mockResolvedValue(REVIEW);
    render(<UnitSizeReviewPanel calculationId="c1" />);
    await waitFor(() => expect(getUnitSizeReview).toHaveBeenCalledWith('c1', undefined));
    expect(await screen.findByText('C35')).toBeInTheDocument();
    expect(screen.getByText('C-9')).toBeInTheDocument();
  });

  it('forwards an explicit review percentage', async () => {
    getUnitSizeReview.mockResolvedValue(REVIEW);
    render(<UnitSizeReviewPanel calculationId="c1" reviewPct={10} />);
    await waitFor(() => expect(getUnitSizeReview).toHaveBeenCalledWith('c1', 10));
  });

  it('surfaces a failure instead of rendering a clean bill of health', async () => {
    getUnitSizeReview.mockRejectedValue(new Error('boom'));
    render(<UnitSizeReviewPanel calculationId="c1" />);
    expect(await screen.findByText(/Could not review unit sizes/i)).toBeInTheDocument();
  });
});

describe('UnsampledUnitsNote', () => {
  it('names every unit missing a summary', async () => {
    getUnsampledUnits.mockResolvedValue(NOTE);
    const { container } = render(<UnsampledUnitsNote fieldInventoryId="f1" />);
    await waitFor(() =>
      expect(getUnsampledUnits).toHaveBeenCalledWith('f1', undefined)
    );
    expect(await screen.findByText('C35')).toBeInTheDocument();
    expect(screen.getByText('ISLAND')).toBeInTheDocument();
    // The count line is interpolated, so read the rendered text rather than an element.
    expect(container.textContent || '').toMatch(/3\s*of\s*24\s*units/);
  });

  it('explains that they were never sampled, rather than implying data loss', async () => {
    getUnsampledUnits.mockResolvedValue(NOTE);
    render(<UnsampledUnitsNote fieldInventoryId="f1" />);
    expect(await screen.findByText(/never sampled/i)).toBeInTheDocument();
  });

  it('renders nothing at all when every unit has data', async () => {
    getUnsampledUnits.mockResolvedValue({ ...NOTE, unsampled_units: [] });
    const { container } = render(<UnsampledUnitsNote fieldInventoryId="f1" />);
    await waitFor(() => expect(getUnsampledUnits).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing without a field inventory', () => {
    const { container } = render(<UnsampledUnitsNote fieldInventoryId={null} />);
    expect(container).toBeEmptyDOMElement();
    expect(getUnsampledUnits).not.toHaveBeenCalled();
  });
});
