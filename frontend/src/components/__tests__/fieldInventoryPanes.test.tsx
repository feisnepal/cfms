/**
 * P5d — Field Inventory's shared data hook and its group wiring.
 * WORKSPACE_FLOW_NAV_PLAN §8.4 (D4/D5).
 *
 * `ContextTabHost` mounts one pane at a time, so Field Inventory's 20 useState
 * hooks had to move above the host or the two panes would each hold a copy and
 * the second one to mount would win. `contextTabs.test.tsx` already proves the
 * generic mechanism with a toy counter; this file proves the *real* thing, which
 * is what actually regresses:
 *
 * - a multiplier edit survives a pane switch (symptom: the AAH figures silently
 *   revert to defaults),
 * - the record is fetched once across the whole step, not once per pane,
 * - the entering pane is never locked, only the Results pane is,
 * - the Results pane shows a message rather than a second file input when there
 *   is nothing behind it — the shape of a duplicate write.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import React from 'react';
import ContextTabHost from '../calculation/ContextTabHost';
import { CONTEXT_TABS, renderContext } from '../calculation/contextComponents';
import { findContext } from '../calculation/calcContexts';
import { FieldInventoryDataProvider, useFieldInventoryData } from '../fieldInventory/useFieldInventoryData';
import { FieldInventoryTab } from '../FieldInventoryTab';
import en from '../../i18n/locales/en.json';
import { renderWithProviders } from '../../test/renderWithProviders';
import ne from '../../i18n/locales/ne.json';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

vi.mock('../../services/api', () => {
  // Inside the factory: vi.mock is hoisted above module scope, so a helper
  // declared out here would not be initialised yet. The 404 is the real
  // "no inventory yet" path, so the provider settles with no record — which is
  // exactly the state Upload Data opens in.
  const notFound = () => {
    const err: any = new Error('not found');
    err.response = { status: 404 };
    return Promise.reject(err);
  };
  return {
    fieldInventoryApi: {
      getByCalculation: vi.fn(notFound),
      getSummary: vi.fn(notFound),
      getSpeciesBreakdown: vi.fn(notFound),
      getMaiAah: vi.fn(notFound),
      getSpeciesDbhBreakdown: vi.fn(notFound),
      getTotalInventory: vi.fn(notFound),
      previewMapping: vi.fn(notFound),
      upload: vi.fn(),
      process: vi.fn(),
      delete: vi.fn(),
      exportDfoSummary: vi.fn(),
      exportExcel: vi.fn(),
    },
    forestApi: {
      getCalculation: vi.fn(async () => ({ result_data: {} })),
      calculateTreeCoverAreas: vi.fn(notFound),
      getBlockAreaDetail: vi.fn(notFound),
    },
    // P4: `FieldInventoryTab` fetches its DBH class list from here. This factory
    // replaces the whole api module, so an omitted export is `undefined` rather
    // than a partially-stubbed object -- and `useDbhClassConfig` then throws
    // during render. Nothing surfaced it, because `renderContext` swallows a
    // render-time throw into `null` (its own comment says so), so the subtree
    // simply failed to mount and a later assertion read "0 calls" instead of a
    // stack trace. Served as the eight `guideline_2061` classes, which is the
    // system this tab renders.
    dbhClassApi: {
      getSystem: vi.fn(async () => ({
        system_name: 'guideline_2061',
        class_count: 8,
        classes: [
          { key: '0_4', lower: 0, upper: 4, label_en: 'Seedling', label_np: 'बिरुवा', stand_type: 'Regeneration' },
          { key: '4_10', lower: 4, upper: 10, label_en: 'Sapling', label_np: 'लाथ्रा', stand_type: 'Sapling' },
          { key: '10_20', lower: 10, upper: 20, label_en: 'Small Pole', label_np: 'सानो खाँवा', stand_type: 'Pole' },
          { key: '20_30', lower: 20, upper: 30, label_en: 'Large Pole', label_np: 'ठुलो खाँवा', stand_type: 'Pole' },
          { key: '30_40', lower: 30, upper: 40, label_en: 'Small Tree', label_np: 'सानो रुख', stand_type: 'Tree' },
          { key: '40_50', lower: 40, upper: 50, label_en: 'Medium Tree', label_np: 'मझौला रुख', stand_type: 'Tree' },
          { key: '50_60', lower: 50, upper: 60, label_en: 'Large Tree', label_np: 'ठुलो रुख', stand_type: 'Tree' },
          { key: '60_plus', lower: 60, upper: null, label_en: 'Very Large Tree', label_np: 'अति ठुलो रुख', stand_type: 'Tree' },
        ],
      })),
      listSystems: vi.fn(async () => []),
    },
  };
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const PANEL_PROPS = {
  calculationId: 'calc-1',
  calculation: null,
  permissions: {},
  structureLocked: false,
  mapLifecycleStatus: 'idle',
} as any;

// Taken from the registry rather than restated, so adding a pane to the group
// cannot quietly leave this file testing a two-tab version of it.
const TABS = findContext('fieldinventory')!.item.tabs!;

const group = () => CONTEXT_TABS.fieldinventory;

/**
 * Reads the shared value the way a real pane does, and asks for the record the
 * way a real pane does — `ensureLoaded`, not a fetch of its own.
 *
 * `loads` is how the Metadata pane is modelled: it is a pane of this group but
 * it reads the forest metadata record, not the field inventory, so it must not
 * drag the shared state along behind it.
 */
const Probe: React.FC<{ name: string; loads?: boolean }> = ({ name, loads = true }) => {
  const { customMultipliers, setCustomMultipliers, file, ensureLoaded } = useFieldInventoryData();
  React.useEffect(() => {
    if (loads) ensureLoaded();
  }, [ensureLoaded, loads]);
  return (
    <div>
      <span data-testid={`pane-${name}`}>{name}</span>
      <span data-testid="multipliers">{JSON.stringify(customMultipliers)}</span>
      <span data-testid="file">{file ? 'chosen' : 'none'}</span>
      <button type="button" onClick={() => setCustomMultipliers({ BlockA: 42 })}>
        bump
      </button>
    </div>
  );
};

const PROBE_PANES = {
  data: { id: 'data', labelKey: 'workflow.tab.uploadData', render: () => <Probe name="data" /> },
  results: { id: 'results', labelKey: 'workflow.tab.results', render: () => <Probe name="results" /> },
};

/**
 * The Results pane's own entry point, which is `ensureResultsLoaded` rather than
 * `ensureLoaded`: it resolves the effective areas and then the totals.
 */
const ResultsProbe: React.FC = () => {
  const { ensureResultsLoaded } = useFieldInventoryData();
  React.useEffect(() => {
    ensureResultsLoaded();
  }, [ensureResultsLoaded]);
  return <div data-testid="pane-results-first">results</div>;
};

const RESULTS_FIRST_PANES = {
  ...PROBE_PANES,
  results: { id: 'results', labelKey: 'workflow.tab.results', render: () => <ResultsProbe /> },
};

/**
 * The shape renderContext builds: the group's own provider above the real host.
 *
 * `firstTab` opens the host on a chosen pane, which is how a test can observe
 * what visiting *one* pane costs. The host defaults to the first unlocked tab, so
 * reordering the list is how a test arrives at Metadata without first mounting
 * Upload Data and its fetch.
 */
function Harness({
  stepDone = true,
  panes = PROBE_PANES,
  firstTab = null,
}: {
  stepDone?: boolean;
  panes?: any;
  firstTab?: string | null;
}) {
  const Provider = group().provider!;
  const tabs = firstTab ? [...TABS].sort((a: any, b: any) => (a.id === firstTab ? -1 : 0)) : TABS;
  return (
    <Provider calculationId="calc-1">
      <ContextTabHost {...PANEL_PROPS} tabs={tabs} panes={panes} stepDone={stepDone} />
    </Provider>
  );
}

describe('Field Inventory group wiring', () => {
  it('declares a provider, because its panes share one record', () => {
    // Without this the two panes mount independently: two fetches, and the
    // multiplier edits live in whichever copy was mounted last.
    expect(group().provider).toBeTypeOf('function');
    expect(Object.keys(group().panes).sort()).toEqual(['data', 'results']);
  });

  it('locks Results and leaves Upload Data alone; Forest Metadata is no longer a pane of this step', () => {
    const byId = Object.fromEntries(TABS.map((tab: any) => [tab.id, tab]));
    expect(byId.data.needsStepData).toBeUndefined();
    expect(byId.results.needsStepData).toBe(true);
    // Forest Metadata became its own step (owner, 2026-10-11): not a third pane here.
    expect(byId.metadata).toBeUndefined();
    expect(findContext('forestmetadata')!.item.step).toBe(6);
  });

  it('the new guard message is translated, not an English leftover', () => {
    expect(en.fieldInventory.noDataForResults).toBeTruthy();
    expect(ne.fieldInventory.noDataForResults).not.toBe(en.fieldInventory.noDataForResults);
  });

  it('the real renderContext path hands the provider a calculationId', async () => {
    // Regression, and a quiet one: `TabbedContext` once rendered
    // `<Provider>{host}</Provider>`, so the provider's `calculationId` was
    // `undefined`, the load bailed on `noCalcId`, and the step opened empty
    // with no error. `renderContext` also swallows a render-time throw into
    // `null`, so nothing would have surfaced it.
    const { fieldInventoryApi } = await import('../../services/api');
    (fieldInventoryApi.getByCalculation as any).mockClear();

    renderWithProviders(
      <React.Suspense fallback={<div>loading</div>}>
        {renderContext('fieldinventory', PANEL_PROPS, true)}
      </React.Suspense>,
    );

    // A real timeout, not `waitFor`'s 1s default. This asserts *wiring* -- that
    // the provider was handed a calculationId and so fetched -- and not how fast
    // it happens. Under a loaded worker the lazy pane module plus the fetch can
    // take longer than a second, and the failure that produces is `0 calls`,
    // which reads like a wiring regression and is nothing of the kind.
    await waitFor(
      () => expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledWith('calc-1'),
      { timeout: 5000 },
    );
  });
});

describe('Field Inventory state survives a pane switch', () => {
  it('keeps a multiplier edit made on Upload Data', async () => {
    renderWithProviders(<Harness />);
    await waitFor(() => expect(screen.getByTestId('pane-data')).toBeTruthy());

    fireEvent.click(screen.getByText('bump'));
    expect(screen.getByTestId('multipliers').textContent).toContain('42');

    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.results' }));
    await waitFor(() => expect(screen.getByTestId('pane-results')).toBeTruthy());
    expect(screen.getByTestId('multipliers').textContent).toContain('42');

    fireEvent.click(screen.getByRole('tab', { name: 'workflow.tab.uploadData' }));
    await waitFor(() => expect(screen.getByTestId('pane-data')).toBeTruthy());
    // The failure this guards against is silent: the edit just disappears.
    expect(screen.getByTestId('multipliers').textContent, 'the edit was lost').toContain('42');
  });

  it('reads the record once across the step, not once per pane', async () => {
    const { fieldInventoryApi } = await import('../../services/api');
    (fieldInventoryApi.getByCalculation as any).mockClear();

    renderWithProviders(<Harness />);
    await waitFor(() => expect(screen.getByTestId('pane-data')).toBeTruthy());

    for (const name of ['workflow.tab.results', 'workflow.tab.uploadData']) {
      fireEvent.click(screen.getByRole('tab', { name }));
      await waitFor(() => expect(screen.queryByRole('tab', { selected: true })).toBeTruthy());
    }

    expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledTimes(1);
  });

  it('reloads for a different calculation rather than reusing the first', async () => {
    // The other half of keying the guard on the id: "loaded once" must mean once
    // per forest, not once per provider instance.
    const { fieldInventoryApi } = await import('../../services/api');
    const Provider = group().provider!;
    (fieldInventoryApi.getByCalculation as any).mockClear();

    const { rerender } = render(
      <Provider calculationId="calc-1">
        <ContextTabHost {...PANEL_PROPS} tabs={TABS} panes={PROBE_PANES} stepDone />
      </Provider>,
    );
    await waitFor(() => expect(screen.getByTestId('pane-data')).toBeTruthy());
    expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledTimes(1);

    rerender(
      <Provider calculationId="calc-2">
        <ContextTabHost {...PANEL_PROPS} tabs={TABS} panes={PROBE_PANES} stepDone />
      </Provider>,
    );
    await waitFor(() =>
      expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledWith('calc-2'),
    );
  });

  it('locks the Results pane without gating the step', async () => {
    renderWithProviders(<Harness stepDone={false} />);
    await waitFor(() => expect(screen.getByTestId('pane-data')).toBeTruthy());

    const results = screen.getByRole('tab', { name: 'workflow.tab.results' }) as HTMLButtonElement;
    expect(results.disabled).toBe(true);
    // Sequence, never enforce: the pane that does the entering still works.
    expect(screen.getByText('bump')).toBeTruthy();
  });
});

describe('Results opened without visiting Upload Data first', () => {
  it('waits for the inventory record instead of skipping the totals', async () => {
    // Results is a pane of the same group, so the host can open straight onto it
    // and nothing has fetched the record yet. The totals request is keyed on the
    // *inventory* id, so firing it before the record lands means it never fires:
    // a calculation that does have an inventory then sits on the manual-calculate
    // fallback, with nothing in the console to say why.
    const { fieldInventoryApi, forestApi } = await import('../../services/api');

    let releaseRecord: (v: any) => void = () => {};
    (fieldInventoryApi.getByCalculation as any).mockImplementationOnce(
      () => new Promise((resolve) => { releaseRecord = resolve; }),
    );
    (fieldInventoryApi.getSummary as any).mockResolvedValueOnce({});
    (fieldInventoryApi.getSpeciesBreakdown as any).mockResolvedValueOnce([]);
    (fieldInventoryApi.getMaiAah as any).mockResolvedValueOnce({});
    (fieldInventoryApi.getSpeciesDbhBreakdown as any).mockResolvedValueOnce({ blocks: [] });
    (forestApi.calculateTreeCoverAreas as any).mockResolvedValueOnce({
      tree_cover_areas: [
        { block_name: 'Block A', total_area_ha: 10, effective_area_ha: 8, tree_cover_percentage: 80 },
      ],
    });
    (forestApi.getBlockAreaDetail as any).mockResolvedValueOnce({
      block_details: [{ block_name: 'Block A', effective_area_ha: 8 }],
    });
    (fieldInventoryApi.getTotalInventory as any).mockResolvedValueOnce({
      forest_totals: { total_area_ha: 8 },
      blocks: [{ block_name: 'Block A' }],
    });

    renderWithProviders(<Harness panes={RESULTS_FIRST_PANES} firstTab="results" />);
    await waitFor(() => expect(screen.getByTestId('pane-results-first')).toBeTruthy());

    // The record is still in flight, so the totals must not have been attempted.
    expect(fieldInventoryApi.getTotalInventory).not.toHaveBeenCalled();

    releaseRecord({ id: 'inv-1' });

    await waitFor(() => expect(fieldInventoryApi.getTotalInventory).toHaveBeenCalledTimes(1));
    expect((fieldInventoryApi.getTotalInventory as any).mock.calls[0][0]).toBe('inv-1');
  });

  it('does not calculate totals when the calculation has no effective areas', async () => {
    // Every per-hectare figure divides by the effective area. With none
    // resolved there is no denominator, and a total computed anyway would look
    // like a real answer.
    const { fieldInventoryApi, forestApi } = await import('../../services/api');

    (fieldInventoryApi.getByCalculation as any).mockResolvedValueOnce({ id: 'inv-1' });
    (fieldInventoryApi.getSummary as any).mockResolvedValueOnce({});
    (fieldInventoryApi.getSpeciesBreakdown as any).mockResolvedValueOnce([]);
    (fieldInventoryApi.getMaiAah as any).mockResolvedValueOnce({});
    (fieldInventoryApi.getSpeciesDbhBreakdown as any).mockResolvedValueOnce({ blocks: [] });
    (forestApi.calculateTreeCoverAreas as any).mockResolvedValueOnce({ tree_cover_areas: [] });

    renderWithProviders(<Harness panes={RESULTS_FIRST_PANES} firstTab="results" />);
    await waitFor(() => expect(screen.getByTestId('pane-results-first')).toBeTruthy());

    await waitFor(() => expect(forestApi.calculateTreeCoverAreas).toHaveBeenCalled());
    expect(fieldInventoryApi.getTotalInventory).not.toHaveBeenCalled();
  });
});

describe('the two panes never offer the same write', () => {
  const REAL_PANES = {
    data: group().panes.data,
    results: group().panes.results,
    metadata: group().panes.metadata,
  };

  it('Results offers no file input while there is no inventory', async () => {
    // This is the duplicate-write guard. The alternative is a Results tab that
    // lets the user replace a file the step just said it had no record of.
    renderWithProviders(
      <FieldInventoryDataProvider calculationId="calc-1">
        <ContextTabHost {...PANEL_PROPS} tabs={TABS} panes={REAL_PANES} stepDone={true} />
      </FieldInventoryDataProvider>,
    );

    fireEvent.click(await screen.findByRole('tab', { name: 'workflow.tab.results' }));
    await waitFor(() => expect(screen.getByTestId('fieldinventory-results-empty')).toBeTruthy());

    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it('Upload Data keeps the file input, and the host keeps one copy of each pane', async () => {
    renderWithProviders(
      <FieldInventoryDataProvider calculationId="calc-1">
        <ContextTabHost {...PANEL_PROPS} tabs={TABS} panes={REAL_PANES} stepDone={true} />
      </FieldInventoryDataProvider>,
    );

    await waitFor(() => expect(document.querySelector('input[type="file"]')).toBeTruthy());
    expect(screen.queryByTestId('fieldinventory-results-empty')).toBeNull();
  });

  it('reloads the record and tells the workflow when a field inventory is imported from Add data', async () => {
    const { fieldInventoryApi } = await import('../../services/api');
    const { emitDataImported } = await import('../../lib/uploadEvents');
    const changed = vi.fn();
    renderWithProviders(
      <FieldInventoryDataProvider calculationId="calc-1" onStepDataChanged={changed}>
        <Probe name="data" />
      </FieldInventoryDataProvider>,
    );
    await waitFor(() => expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledTimes(1));

    emitDataImported(['households']); // another kind of data: nothing to reload here
    await new Promise((r) => setTimeout(r, 50));
    expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledTimes(1);
    expect(changed).not.toHaveBeenCalled();

    emitDataImported(['field_inventory']);
    await waitFor(() => expect(fieldInventoryApi.getByCalculation).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1)); // Results unlocks without a reload
  });

  it('the Upload Data pane says the data IS in the system once an inventory exists', async () => {
    const { fieldInventoryApi } = await import('../../services/api');
    (fieldInventoryApi.getByCalculation as any).mockResolvedValueOnce({
      id: 'fi-1', calculation_id: 'calc-1', uploaded_filename: 'my_inventory.xlsx', status: 'completed',
    });
    renderWithProviders(
      <FieldInventoryDataProvider calculationId="calc-1">
        <ContextTabHost {...PANEL_PROPS} tabs={TABS} panes={REAL_PANES} stepDone={true} />
      </FieldInventoryDataProvider>,
    );
    const line = await screen.findByTestId('upload-state-line');
    await waitFor(() => expect(screen.getByTestId('upload-state-line').getAttribute('data-present')).toBe('true'));
    expect(line).toBeTruthy();
    expect(screen.getByTestId('upload-state-line').textContent).toContain('my_inventory.xlsx');
  });

  it('the Upload Data pane says the data is NOT in the system while there is no inventory', async () => {
    renderWithProviders(
      <FieldInventoryDataProvider calculationId="calc-1">
        <ContextTabHost {...PANEL_PROPS} tabs={TABS} panes={REAL_PANES} stepDone={true} />
      </FieldInventoryDataProvider>,
    );
    await waitFor(() => expect(document.querySelector('input[type="file"]')).toBeTruthy());
    expect(screen.getByTestId('upload-state-line').getAttribute('data-present')).toBe('false');
  });
});
