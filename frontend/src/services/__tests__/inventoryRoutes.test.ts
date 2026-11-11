/**
 * Tree-mapping route pinning.
 *
 * `inventoryApi.getTreeMappingByCalculation` called `/api/inventory/tree-mapping/{id}`,
 * a route the backend does not have. The real one is
 * `/api/inventory/by-calculation/{calculation_id}` (backend/app/api/inventory.py:1414),
 * declared alongside `/by-calculation/{calculation_id}/check` and
 * `/by-calculation/{calculation_id}/force`.
 *
 * Because nothing asserted the URL, the 404 was invisible: the Data pane's
 * "fetch the existing mapping" path simply never worked, and nothing failed
 * loudly. These assertions exist so a renamed or invented path fails here
 * instead of in the browser.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('axios', () => {
  // api.ts installs request/response interceptors on the instance at import
  // time, so the stub has to carry them.
  const interceptors = { request: { use: vi.fn() }, response: { use: vi.fn() } };
  const create = vi.fn(() => ({
    get,
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    interceptors,
  }));
  return { default: { create }, create };
});

vi.mock('../utils/download', () => ({ downloadFromApi: vi.fn() }));

import { inventoryApi } from '../api';

const CALC_ID = '25c4e349-0f38-473c-a1ec-12a6ea51ecf5';

describe('inventoryApi tree-mapping routes', () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: {} });
  });

  it('fetches the mapping by calculation from the route the backend declares', async () => {
    await inventoryApi.getTreeMappingByCalculation(CALC_ID);
    expect(get).toHaveBeenCalledWith(`/api/inventory/by-calculation/${CALC_ID}`);
  });

  it('never calls the invented /tree-mapping/ path', async () => {
    await inventoryApi.getTreeMappingByCalculation(CALC_ID);
    const paths = get.mock.calls.map((c) => String(c[0]));
    expect(paths.some((p) => p.includes('/api/inventory/tree-mapping/'))).toBe(false);
  });

  it('keeps the existence check on its own /check route', async () => {
    await inventoryApi.checkTreeMappingExists(CALC_ID);
    expect(get).toHaveBeenCalledWith(`/api/inventory/by-calculation/${CALC_ID}/check`);
  });
});
