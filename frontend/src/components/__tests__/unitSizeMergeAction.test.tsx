/**
 * The merge action: a per-polygon confirm, and nothing that can reshape a forest by
 * accident.
 *
 * The guardrails are the point of these tests, not the happy path:
 *   - no bulk action
 *   - a proposal the server could not fully describe is not offered
 *   - the dialog names BOTH polygons and the result before anything is written
 *   - the layer type comes from the server, never from the click
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { App } from 'antd';
import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import UnitSizeReviewPanel from '../sampling/UnitSizeReviewPanel';
import UnitSizeTable from '../sampling/UnitSizeTable';
import * as api from '../../services/api';

vi.mock('../../services/api', async () => {
  const actual = await vi.importActual<typeof import('../../services/api')>(
    '../../services/api'
  );
  return {
    ...actual,
    getUnitSizeReview: vi.fn(),
    mergeFeatures: vi.fn(),
  };
});

const getUnitSizeReview = api.getUnitSizeReview as unknown as ReturnType<typeof vi.fn>;
const mergeFeatures = api.mergeFeatures as unknown as ReturnType<typeof vi.fn>;

const MERGEABLE = {
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
};

const UNMERGEABLE = { ...MERGEABLE, block_name: 'ISLAND', neighbour: null, neighbour_id: null, unmergeable: true };
const NO_IDS = { ...MERGEABLE, id: null, neighbour_id: null };
const NO_LAYER = { ...MERGEABLE, layer_type: null };

const SUMMARY = {
  total: 2,
  sub_mmu: 2,
  review: 0,
  ok: 0,
  merge_offers: 1,
  unmergeable: 1,
};

const response = (candidates: unknown[]) => ({
  calculation_id: 'c1',
  boundary_area_ha: 366.03,
  mmu_ha: 1,
  review_pct: 5,
  read_only: true,
  summary: SUMMARY,
  candidates,
});

beforeEach(() => {
  vi.clearAllMocks();
});

// The panel uses App.useApp() for its toasts. Outside an <App> provider antd's
// message proxy throws, which aborted doMerge BEFORE it re-read the review - so
// the re-read assertion would fail for a reason that had nothing to do with
// merging, and the failure-path test would pass for the wrong reason.
const renderPanel = (ui: React.ReactElement) => render(<App>{ui}</App>);

describe('the merge button', () => {
  it('is offered for a complete proposal', () => {
    render(<UnitSizeTable candidates={[MERGEABLE]} onMergeRequest={() => {}} />);
    expect(screen.getByRole('button', { name: /merge/i })).toBeInTheDocument();
  });

  it('is NOT offered for an unmergeable unit', () => {
    render(<UnitSizeTable candidates={[UNMERGEABLE]} onMergeRequest={() => {}} />);
    expect(screen.queryByRole('button', { name: /merge/i })).not.toBeInTheDocument();
  });

  it('is NOT offered when the server could not supply both ids', () => {
    render(<UnitSizeTable candidates={[NO_IDS]} onMergeRequest={() => {}} />);
    expect(screen.queryByRole('button', { name: /merge/i })).not.toBeInTheDocument();
  });

  it('is NOT offered when the layer type is unknown - like-with-like is not optional', () => {
    render(<UnitSizeTable candidates={[NO_LAYER]} onMergeRequest={() => {}} />);
    expect(screen.queryByRole('button', { name: /merge/i })).not.toBeInTheDocument();
  });

  it('offers no button at all when no handler is wired', () => {
    render(<UnitSizeTable candidates={[MERGEABLE]} />);
    expect(screen.queryByRole('button', { name: /merge/i })).not.toBeInTheDocument();
  });

  it('is per row, never a bulk action', () => {
    const a = { ...MERGEABLE, block_name: 'A', id: 'a', neighbour: 'X', neighbour_id: 'x' };
    const b = { ...MERGEABLE, block_name: 'B', id: 'b', neighbour: 'X', neighbour_id: 'x' };
    render(<UnitSizeTable candidates={[a, b]} onMergeRequest={() => {}} />);
    const buttons = screen.getAllByRole('button', { name: /merge/i });
    expect(buttons).toHaveLength(2);
    expect(screen.queryByRole('button', { name: /merge all/i })).not.toBeInTheDocument();
  });
});

describe('confirming a merge', () => {
  it('names BOTH polygons and the resulting area before anything is sent', async () => {
    getUnitSizeReview.mockResolvedValue(response([MERGEABLE]));
    mergeFeatures.mockResolvedValue({ ok: true });
    renderPanel(<UnitSizeReviewPanel calculationId="c1" />);

    await screen.findByText('C35');
    fireEvent.click(screen.getByRole('button', { name: /merge/i }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('C35');
    expect(dialog).toHaveTextContent('C-6');
    // 0.0178 + 10.9165 = 10.9343
    expect(dialog).toHaveTextContent('10.9343');
    expect(mergeFeatures).not.toHaveBeenCalled();
  });

  it('states the consequence up front', async () => {
    getUnitSizeReview.mockResolvedValue(response([MERGEABLE]));
    mergeFeatures.mockResolvedValue({ ok: true });
    renderPanel(<UnitSizeReviewPanel calculationId="c1" />);
    await screen.findByText('C35');
    fireEvent.click(screen.getByRole('button', { name: /merge/i }));
    expect(await screen.findByRole('dialog')).toHaveTextContent(/structure/i);
  });

  it('calls the EXISTING merge endpoint with the server-supplied layer type and both ids', async () => {
    getUnitSizeReview.mockResolvedValue(response([MERGEABLE]));
    mergeFeatures.mockResolvedValue({ ok: true });
    renderPanel(<UnitSizeReviewPanel calculationId="c1" />);

    await screen.findByText('C35');
    fireEvent.click(screen.getByRole('button', { name: /merge/i }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(dialog.querySelector('.ant-btn-primary') as HTMLElement);

    await waitFor(() =>
      expect(mergeFeatures).toHaveBeenCalledWith('c1', 'blocks', ['id-c35', 'id-c6'])
    );
  });

  it('cancels without calling anything', async () => {
    getUnitSizeReview.mockResolvedValue(response([MERGEABLE]));
    renderPanel(<UnitSizeReviewPanel calculationId="c1" />);
    await screen.findByText('C35');
    fireEvent.click(screen.getByRole('button', { name: /merge/i }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(
      Array.from(dialog.querySelectorAll('button')).find(
        (b) => b.textContent?.trim() === 'Cancel'
      ) as HTMLElement
    );
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mergeFeatures).not.toHaveBeenCalled();
  });

  it('re-reads the review after a merge rather than patching it locally', async () => {
    getUnitSizeReview.mockResolvedValue(response([MERGEABLE]));
    mergeFeatures.mockResolvedValue({ ok: true });
    renderPanel(<UnitSizeReviewPanel calculationId="c1" />);

    await screen.findByText('C35');
    fireEvent.click(screen.getByRole('button', { name: /merge/i }));
    fireEvent.click((await screen.findByRole('dialog')).querySelector('.ant-btn-primary') as HTMLElement);

    await waitFor(() => expect(getUnitSizeReview).toHaveBeenCalledTimes(2));
  });

  it('reports a failure and does not pretend it worked', async () => {
    getUnitSizeReview.mockResolvedValue(response([MERGEABLE]));
    mergeFeatures.mockRejectedValue(new Error('locked'));
    renderPanel(<UnitSizeReviewPanel calculationId="c1" />);

    await screen.findByText('C35');
    fireEvent.click(screen.getByRole('button', { name: /merge/i }));
    fireEvent.click((await screen.findByRole('dialog')).querySelector('.ant-btn-primary') as HTMLElement);

    await waitFor(() => expect(mergeFeatures).toHaveBeenCalled());
    // Still asking for the review only once means no optimistic removal happened.
    expect(getUnitSizeReview).toHaveBeenCalledTimes(1);
  });
});
