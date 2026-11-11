/**
 * Two failures reported from the Field Inventory tab.
 *
 * 1. **A React crash.** `Objects are not valid as a React child (found: object
 *    with keys {code, message, message_np, reference})`. The backend's error
 *    bodies are bilingual objects, and `api.ts`'s response interceptor injects
 *    `detail.reference` from the top-level `correlation_id`. Five sites in the
 *    provider read `err.response?.data?.detail` and assigned it straight into
 *    `error` / `componentError`, which are typed `string | null` and rendered as
 *    `<p>{error}</p>`. An object child is exactly the reported crash.
 *
 * 2. **Results stayed disabled after an upload.** Readiness is fetched once when
 *    the page mounts and a `needsStepData` pane is locked from it, and
 *    `readiness.refresh()` was never called from anywhere in production code —
 *    so a step completed in the current session kept its own Results tab locked
 *    until a manual reload. Processing a field inventory now refreshes it, and
 *    deleting one refreshes it the other way so Results locks again.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

const processInventory = vi.fn();
const deleteInventory = vi.fn();
const getByCalculation = vi.fn();

vi.mock('../../services/api', () => ({
  fieldInventoryApi: {
    getByCalculation: (...a: any[]) => getByCalculation(...a),
    getSummary: vi.fn().mockResolvedValue({ blocks: [] }),
    getSpeciesBreakdown: vi.fn().mockResolvedValue({}),
    getSpeciesDbhBreakdown: vi.fn().mockResolvedValue({}),
    getMaiAah: vi.fn().mockResolvedValue(null),
    getTotalInventory: vi.fn().mockResolvedValue({ blocks: [] }),
    process: (...a: any[]) => processInventory(...a),
    delete: (...a: any[]) => deleteInventory(...a),
  },
  forestApi: {
    // The load effect calls this first; without it the effect throws and the
    // record never loads, which looks exactly like "the fix did nothing".
    getCalculation: vi.fn().mockResolvedValue({ result_data: {} }),
    calculateTreeCoverAreas: vi.fn().mockResolvedValue({ tree_cover_areas: [] }),
    getBlockAreaDetail: vi.fn().mockResolvedValue({ block_details: [] }),
  },
  samplingApi: { getSamplingDesignByCalculation: vi.fn().mockResolvedValue({ exists: false }) },
}));

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../../i18n/numberFormat', () => ({
  formatNumber: (v: any) => String(v ?? ''),
  formatDecimal: (v: any, d = 2) => Number(v || 0).toFixed(d),
}));

import { useFieldInventoryDataState } from '../fieldInventory/useFieldInventoryData';

// The exact body a 500 produces: bilingual detail + the correlation id the
// axios interceptor folds into `detail.reference`.
const I18N_ERROR = {
  code: 'general.unexpected_error',
  message: 'Something went wrong at our end. Your work has not been saved.',
  message_np: 'हामीसँग केही गडबड भयो। तपाईंको काम सुरक्षित छैन।',
  reference: 'abc123-def456',
};

function bilingualError() {
  return { response: { data: { detail: { ...I18N_ERROR }, correlation_id: 'abc123-def456' } } };
}

function mount(onStepDataChanged?: () => void) {
  return renderHook(() => useFieldInventoryDataState('calc-1', [], 'Forest', onStepDataChanged));
}

/**
 * The provider deliberately does not self-load: the Data pane calls
 * `ensureLoaded()` so that opening Results first does not pay for a load the
 * user may not need. A test of the hook therefore has to start it by hand.
 */
async function mountAndLoad(onStepDataChanged?: () => void) {
  const view = mount(onStepDataChanged);
  await act(async () => {
    view.result.current.ensureLoaded();
  });
  await waitFor(() => expect(view.result.current.initialized).toBe(true));
  return view;
}

describe('Field Inventory: bilingual error objects are never rendered raw', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getByCalculation.mockResolvedValue({
      id: 'fi-1',
      status: 'completed',
      field_inventory_id: 'fi-1',
    });
  });

  it('stores a STRING for componentError when the load fails with an i18n object', async () => {
    getByCalculation.mockRejectedValue(bilingualError());

    const { result } = await mountAndLoad();

    // The crash was an object reaching JSX; the type says string.
    expect(result.current.componentError).toBeTruthy();
    expect(typeof result.current.componentError).toBe('string');
    expect(result.current.componentError).not.toMatch(/\[object Object\]/);
    // And it is the message, not the object dumped into a string.
    expect(result.current.componentError).toContain('Something went wrong at our end');
  });

  it('keeps the Nepali message when the app is in Nepali', async () => {
    // The point of the bilingual envelope: `readDetail` is language-aware, so a
    // raw `.detail` would have shown the English half in a Nepali-first app.
    const i18n = (await import('../../i18n/index')).default;
    const prev = i18n.language;
    await i18n.changeLanguage('ne');
    try {
      getByCalculation.mockRejectedValue(bilingualError());
      const { result } = await mountAndLoad();
      expect(result.current.componentError).toContain('गडबड');
    } finally {
      await i18n.changeLanguage(prev);
    }
  });

  it('stores a STRING for the delete failure', async () => {
    deleteInventory.mockRejectedValue(bilingualError());
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { result } = await mountAndLoad();
    await act(async () => {
      await result.current.handleDelete();
    });
    expect(typeof result.current.error).toBe('string');
    expect(result.current.error).toBeTruthy();
  });

  it('stores a STRING for the processing failure', async () => {
    processInventory.mockRejectedValue(bilingualError());
    const { result } = await mountAndLoad();
    await act(async () => {
      await result.current.handleProcess('fi-1', new File(['x'], 'x.csv'));
    });
    expect(typeof result.current.error).toBe('string');
    expect(result.current.error).toBeTruthy();
  });
});

describe('Field Inventory: a write re-reads the step readiness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getByCalculation.mockResolvedValue({
      id: 'fi-1',
      status: 'completed',
      field_inventory_id: 'fi-1',
    });
  });

  it('refreshes readiness after a successful process', async () => {
    const onStepDataChanged = vi.fn();
    processInventory.mockResolvedValue({ status: 'completed' });

    const { result } = await mountAndLoad(onStepDataChanged);
    await act(async () => {
      await result.current.handleProcess('fi-1', new File(['x'], 'x.csv'));
    });

    // Without this the Results tab stays locked until a manual reload.
    expect(onStepDataChanged).toHaveBeenCalled();
  });

  it('does NOT refresh when the process failed', async () => {
    const onStepDataChanged = vi.fn();
    processInventory.mockRejectedValue(bilingualError());

    const { result } = await mountAndLoad(onStepDataChanged);
    await act(async () => {
      await result.current.handleProcess('fi-1', new File(['x'], 'x.csv'));
    });

    expect(onStepDataChanged).not.toHaveBeenCalled();
  });

  it('refreshes after a delete, so Results locks again', async () => {
    const onStepDataChanged = vi.fn();
    deleteInventory.mockResolvedValue(undefined);
    // confirm() must accept the delete to reach the refresh.
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    const { result } = await mountAndLoad(onStepDataChanged);
    await act(async () => {
      await result.current.handleDelete();
    });

    expect(onStepDataChanged).toHaveBeenCalled();
  });

  it('works without the callback, so a provider mounted without one does not crash', async () => {
    processInventory.mockResolvedValue({ status: 'completed' });
    const { result } = await mountAndLoad(undefined);
    await act(async () => {
      await result.current.handleProcess('fi-1', new File(['x'], 'x.csv'));
    });
    expect(result.current.error).toBeNull();
  });
});
