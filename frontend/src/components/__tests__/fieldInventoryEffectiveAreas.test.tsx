/**
 * Effective-area resolution when the tree-cover recompute comes back empty.
 *
 * The forest this was reported on (calculation 25c4e349…, forest "blocks-1" …
 * "blocks-5") has a `POST /tree-cover-areas` that returns an EMPTY list — no
 * raster overlap — while `GET /block-area-detail` returns all five blocks with
 * correct `effective_area_ha` (126.2144, 73.9117, 226.7519, 3.3970, 79.7335).
 *
 * `loadTreeCoverAreas` used to `return null` on the empty recompute, so the
 * block-area-detail call never ran. With no areas, every per-hectare figure has
 * no denominator, so the Results pane rendered no per-hectare tables at all.
 *
 * These tests use the real response shapes captured from that forest.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const calculateTreeCoverAreas = vi.fn();
const getBlockAreaDetail = vi.fn();

vi.mock('../../services/api', () => ({
  forestApi: {
    calculateTreeCoverAreas: (...a: any[]) => calculateTreeCoverAreas(...a),
    getBlockAreaDetail: (...a: any[]) => getBlockAreaDetail(...a),
  },
  fieldInventoryApi: {
    getFieldInventoryByCalculation: vi.fn().mockResolvedValue({ status: 'completed', id: 'fi-1' }),
    getFieldInventorySummary: vi.fn().mockResolvedValue({}),
    getSpeciesBreakdown: vi.fn().mockResolvedValue({}),
  },
  samplingApi: { getSamplingDesignByCalculation: vi.fn().mockResolvedValue({ exists: false }) },
  calculationApi: { getCalculation: vi.fn().mockResolvedValue({ result_data: {} }) },
}));

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../../i18n/numberFormat', () => ({
  formatNumber: (v: any) => String(v ?? ''),
  formatDecimal: (v: any, d = 2) => Number(v || 0).toFixed(d),
}));
vi.mock('../hooks/useErrorHandler', () => ({ useErrorHandler: () => ({ handleError: vi.fn() }) }));

import { useFieldInventoryDataState } from '../fieldInventory/useFieldInventoryData';

// Captured from GET /block-area-detail on the reported forest.
const BLOCK_AREA_DETAIL = {
  block_details: [
    { block_name: 'blocks-2', effective_area_ha: 73.9117 },
    { block_name: 'blocks-3', effective_area_ha: 226.7519 },
    { block_name: 'blocks-4', effective_area_ha: 3.397 },
    { block_name: 'blocks-5', effective_area_ha: 79.7335 },
    { block_name: 'blocks-1', effective_area_ha: 126.2144 },
  ],
};

function mount() {
  return renderHook(() => useFieldInventoryDataState('calc-1', [], 'Forest'));
}

describe('loadTreeCoverAreas: the tree-cover recompute is not the gate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('falls back to block-area-detail when the recompute returns an empty list', async () => {
    // The real failure: empty array, not an error.
    calculateTreeCoverAreas.mockResolvedValue({ tree_cover_areas: [] });
    getBlockAreaDetail.mockResolvedValue(BLOCK_AREA_DETAIL);

    const { result } = mount();

    let areas: Record<string, number> | null = null;
    await act(async () => {
      areas = await result.current.loadTreeCoverAreas();
    });

    expect(areas).not.toBeNull();
    expect(Object.keys(areas!).sort()).toEqual([
      'blocks-1', 'blocks-2', 'blocks-3', 'blocks-4', 'blocks-5',
    ]);
    expect(areas!['blocks-1']).toBeCloseTo(126.2144, 4);
    expect(areas!['blocks-3']).toBeCloseTo(226.7519, 4);
    // The authoritative source must actually have been consulted.
    expect(getBlockAreaDetail).toHaveBeenCalled();
    expect(result.current.treeCoverError).toBeNull();
  });

  it('falls back to block-area-detail when the recompute throws', async () => {
    calculateTreeCoverAreas.mockRejectedValue(new Error('raster unavailable'));
    getBlockAreaDetail.mockResolvedValue(BLOCK_AREA_DETAIL);

    const { result } = mount();

    let areas: Record<string, number> | null = null;
    await act(async () => {
      areas = await result.current.loadTreeCoverAreas();
    });

    expect(areas).not.toBeNull();
    expect(Object.keys(areas!)).toHaveLength(5);
    expect(result.current.treeCoverError).toBeNull();
  });

  it('still uses the recompute areas when block-area-detail is unavailable', async () => {
    calculateTreeCoverAreas.mockResolvedValue({
      tree_cover_areas: [{ block_name: 'blocks-1', effective_area_ha: 10 }],
    });
    getBlockAreaDetail.mockRejectedValue(new Error('no geometry'));

    const { result } = mount();

    let areas: Record<string, number> | null = null;
    await act(async () => {
      areas = await result.current.loadTreeCoverAreas();
    });

    expect(areas).toEqual({ 'blocks-1': 10 });
  });

  it('reports a problem only when BOTH sources come up empty', async () => {
    calculateTreeCoverAreas.mockResolvedValue({ tree_cover_areas: [] });
    getBlockAreaDetail.mockResolvedValue({ block_details: [] });

    const { result } = mount();

    let areas: Record<string, number> | null = {};
    await act(async () => {
      areas = await result.current.loadTreeCoverAreas();
    });

    expect(areas).toBeNull();
    await waitFor(() => {
      expect(result.current.treeCoverError).toBeTruthy();
    });
  });

  it('does not call the totals endpoint without areas — the guard stays honest', async () => {
    // The empty-areas guard in handleCalculateTotals is what made the missing
    // areas visible as blank tables. It must keep refusing to divide by nothing.
    calculateTreeCoverAreas.mockResolvedValue({ tree_cover_areas: [] });
    getBlockAreaDetail.mockResolvedValue({ block_details: [] });

    const { result } = mount();
    await act(async () => {
      await result.current.loadTreeCoverAreas();
    });

    expect(result.current.blockAreas).toEqual({});
  });
});
