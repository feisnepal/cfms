import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttributeTable } from '../AttributeTable';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

const FEATS = [
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b1', name: 'Block A', block_name: 'B-1' } },
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b2', name: 'Block B', block_name: 'B-2' } },
];

// Partial setState — merges over the real store, so real actions
// (setColumnVisibility, selectFeatures, …) keep working. Do NOT spread
// createInitialState() here: it replaces the actions with no-op stubs.
function seedStore() {
  useWorkspaceStore.setState({
    activeLayerId: 'blocks',
    activeImportedLayerId: null,
    calculationId: 'c1',
    customLayerStyles: {},
    columnVisibility: {},
    columnOrder: {},
    columnWidths: {},
    columnLabels: {},
    importedLayers: [],
    selection: { layerId: null, featureIds: [] },
    editHistory: [],
    editFuture: [],
  } as never);
}

describe('AttributeTable P2 — row-action menu (WORKSPACE_LAYER_STYLING_PLAN.md P2.1)', () => {
  beforeEach(seedStore);

  it('the leading ⋮ menu invokes zoom and delete for that row', async () => {
    const onZoom = vi.fn();
    const onDelete = vi.fn();
    render(
      <AttributeTable
        isLoading={false} error={null} onRetry={() => {}} features={FEATS}
        onZoomToFeature={onZoom} onDeleteFeature={onDelete}
      />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    const menuBtn = within(rows[0]).getByRole('button', { name: 'attributeTable.rowActions' });
    await userEvent.click(menuBtn);

    await userEvent.click(screen.getByRole('menuitem', { name: /zoomToFeature/ }));
    expect(onZoom).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }));

    await userEvent.click(menuBtn);
    await userEvent.click(screen.getByRole('menuitem', { name: /deleteFeature/ }));
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }), 0);
  });

  it('the ⋮ menu is portaled to <body> (never clipped by the table overflow)', async () => {
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={() => {}} />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'attributeTable.rowActions' }));
    const menu = screen.getByRole('menu');
    expect(menu.closest('.attribute-table')).toBeNull();       // not inside the table subtree
    expect(document.body.contains(menu)).toBe(true);
  });

  it('no leading action column when neither zoom nor delete handler is supplied', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(screen.queryByRole('button', { name: 'attributeTable.rowActions' })).toBeNull();
  });
});

describe('AttributeTable P3 — per-feature style cells (WORKSPACE_LAYER_STYLING_PLAN.md P3.4)', () => {
  beforeEach(seedStore);

  it('the colour cell writes style_fill; its clear button writes style_clear', async () => {
    const onSave = vi.fn();
    render(
      <AttributeTable
        isLoading={false} error={null} onRetry={() => {}}
        features={[{ ...FEATS[0], properties: { ...FEATS[0].properties, style: { fill: '#123456' } } }]}
        onSaveProperty={onSave}
      />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    const colorInput = within(rows[0]).getByLabelText('attributeTable.styleFillAria') as HTMLInputElement;
    fireEvent.input(colorInput, { target: { value: '#00ff00' } });
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }), 'style_fill', '#00ff00');

    await userEvent.click(within(rows[0]).getByRole('button', { name: 'attributeTable.clearStyle' }));
    expect(onSave).toHaveBeenCalledWith(expect.anything(), 'style_clear', '');
  });

  it('the opacity cell writes style_opacity as a 0..1 string', async () => {
    const onSave = vi.fn();
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    const sel = within(rows[0]).getByLabelText('attributeTable.styleOpacityAria');
    await userEvent.selectOptions(sel, '0.5');
    expect(onSave).toHaveBeenCalledWith(expect.anything(), 'style_opacity', '0.5');
  });
});

describe('AttributeTable P3.6 — Set colour (row menu + bulk)', () => {
  beforeEach(seedStore);

  it('the row ⋮ "Set colour…" opens a swatch grid; a swatch writes style_fill', async () => {
    const onSave = vi.fn();
    render(
      <AttributeTable
        isLoading={false} error={null} onRetry={() => {}} features={FEATS}
        onZoomToFeature={() => {}} onSaveProperty={onSave}
      />,
    );
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'attributeTable.rowActions' }));
    await userEvent.click(screen.getByRole('menuitem', { name: /setColour/ }));

    const grid = screen.getByRole('group', { name: 'attributeTable.setColour' });
    await userEvent.click(within(grid).getByLabelText('#3cb44b'));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }),
      'style_fill', '#3cb44b',
    );
  });

  it('the bulk "Set colour" button applies one style_fill per selected feature', async () => {
    useWorkspaceStore.setState({ selection: { layerId: 'blocks', featureIds: ['b1', 'b2'] } } as never);
    const onSave = vi.fn();
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={onSave} />,
    );
    await userEvent.click(screen.getByRole('button', { name: /setColourBulk/ }));
    const grid = screen.getByRole('group', { name: 'attributeTable.setColour' });
    await userEvent.click(within(grid).getByLabelText('#000000'));
    expect(onSave).toHaveBeenCalledTimes(2);
    expect(onSave.mock.calls.map((c) => c[0].properties.id).sort()).toEqual(['b1', 'b2']);
    expect(onSave.mock.calls.every((c) => c[1] === 'style_fill' && c[2] === '#000000')).toBe(true);
  });

  it('no bulk button when nothing is selected', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onSaveProperty={() => {}} />);
    expect(screen.queryByRole('button', { name: /setColourBulk/ })).toBeNull();
  });
});

// The filter is a pop-up behind the Filter button (one-row toolbar, owner request 2026-10-11).
const openFilter = () => userEvent.click(screen.getByRole('button', { name: 'attributeTable.filterButton' }));

describe('AttributeTable P4.6 — filter row + selection helpers', () => {
  beforeEach(seedStore);

  it('a field · op · value filter narrows the visible rows', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={() => {}} />);
    let rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    expect(rows).toHaveLength(2);

    await openFilter();
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterField'), 'name');
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterOp'), 'contains');
    await userEvent.type(screen.getByLabelText('attributeTable.filterValue'), 'Block A');

    rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('Block A');
  });

  it('an active filter stays visible as a chip after the pop-up closes, and the chip clears it', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={() => {}} />);
    expect(screen.queryByTestId('tb-filter-chip')).toBeNull();
    await openFilter();
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterField'), 'name');
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterOp'), 'contains');
    await userEvent.type(screen.getByLabelText('attributeTable.filterValue'), 'Block A');
    await userEvent.keyboard('{Escape}'); // the pop-up closes; the filter keeps working and shows as a chip
    expect(screen.queryByLabelText('attributeTable.filterValue')).toBeNull();
    expect(screen.getByTestId('tb-filter-chip')).toHaveTextContent('Block A');
    expect(screen.getAllByRole('row').filter((r) => r.className.includes('table-row'))).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.filterClear' }));
    expect(screen.queryByTestId('tb-filter-chip')).toBeNull();
    expect(screen.getAllByRole('row').filter((r) => r.className.includes('table-row'))).toHaveLength(2);
  });

  it('"Select in view" calls the prop; "Zoom to selection" is disabled with an empty selection', async () => {
    const onSelectInView = vi.fn();
    const onZoomToSelection = vi.fn();
    render(
      <AttributeTable
        isLoading={false} error={null} onRetry={() => {}} features={FEATS}
        onSelectInView={onSelectInView} onZoomToSelection={onZoomToSelection}
      />,
    );
    // Owner request, 2026-09-24: these tools now live behind the "more
    // tools" toggle, collapsed by default.
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.selectInView' }));
    expect(onSelectInView).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'attributeTable.zoomToSelection' })).toBeDisabled();
  });

  it('"show only matches on map" publishes / clears store.tableFilter', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    await openFilter();
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterField'), 'name');
    await userEvent.type(screen.getByLabelText('attributeTable.filterValue'), 'Block A');
    expect(useWorkspaceStore.getState().tableFilter).toBeNull();

    await userEvent.click(screen.getByLabelText('attributeTable.filterOnMapShort'));
    expect(useWorkspaceStore.getState().tableFilter).toEqual(
      expect.objectContaining({ layerId: 'blocks', field: 'name', value: 'Block A' }),
    );

    await userEvent.click(screen.getByLabelText('attributeTable.filterOnMapShort'));
    expect(useWorkspaceStore.getState().tableFilter).toBeNull();
  });

  it('"show only selected" narrows the visible rows to store.selection (owner request, 2026-09-15)', async () => {
    useWorkspaceStore.setState({ selection: { layerId: 'blocks', featureIds: ['b2'] } } as never);
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    let rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    expect(rows).toHaveLength(2);

    // Owner request, 2026-09-24: hidden behind "more tools" by default.
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    await userEvent.click(screen.getByLabelText('attributeTable.showOnlySelectedShort'));
    rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent('Block B');

    await userEvent.click(screen.getByLabelText('attributeTable.showOnlySelectedShort'));
    rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    expect(rows).toHaveLength(2);
  });

  it('"show only selected" checkbox is disabled while nothing is selected', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    expect(screen.getByLabelText('attributeTable.showOnlySelectedShort')).toBeDisabled();
  });

  it('sorting freezes row order -- an edit to the sorted column does not reshuffle rows until the header is clicked again (owner request, 2026-09-15)', async () => {
    // Deliberately out of alphabetical order to begin with, so an actual
    // reorder is observable. Uses the 'name' column (its sortable comparator
    // reads properties.name directly, matching the column key) rather than
    // 'area' (a PRE-EXISTING, separate bug: that column's key is 'area' but
    // its data lives at properties.area_hectares, so properties['area'] is
    // always undefined and sorting by it has never worked -- out of scope
    // here, flagged separately).
    const feats = [
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'a', name: 'Zebra' } },
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b', name: 'Alpha' } },
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'c', name: 'Mango' } },
    ];
    // Column order (no zoom/delete handlers passed, so no leading actions
    // column): '#' (row number), then 'name' -- gridcell index 1.
    const rowNames = () =>
      screen.getAllByRole('row').filter((r) => r.className.includes('table-row'))
        .map((r) => within(r).getAllByRole('gridcell')[1].textContent);

    const { rerender } = render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={feats} />);
    await userEvent.click(screen.getByRole('columnheader', { name: /attributeTable\.col\.name\b/ }));
    expect(rowNames()).toEqual(['Alpha', 'Mango', 'Zebra']); // ascending

    // Simulate a post-edit refetch: 'Alpha' is renamed past 'Zebra'. An
    // unfrozen live re-sort would move it to last place -- the frozen
    // snapshot must keep it in its original (first) row position, just
    // showing the new text there.
    const edited = [
      feats[0],
      { ...feats[1], properties: { ...feats[1].properties, name: 'Zzzz' } },
      feats[2],
    ];
    rerender(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={edited} />);
    expect(rowNames()).toEqual(['Zzzz', 'Mango', 'Zebra']); // same row positions, new text in row 1

    // An explicit re-click (toggles to descending) re-derives from the
    // CURRENT values -- proving this isn't simply stuck forever.
    await userEvent.click(screen.getByRole('columnheader', { name: /attributeTable\.col\.name\b/ }));
    expect(rowNames()).toEqual(['Zzzz', 'Zebra', 'Mango']); // descending: Zzzz, Zebra, Mango
  });

  it('sorting by "Area (ha)" orders by the real numeric area_hectares, not the string key "area" (bug found 2026-09-15)', async () => {
    // The 'area' column's key has never matched its data (properties.area
    // doesn't exist -- the real value is properties.area_hectares), and its
    // getValue formats a display STRING via toFixed, which sorts
    // lexicographically ("10.00" < "2.00"). Both are fixed by ColumnDef's
    // new `sortValue`. 10 > 2 numerically but "10" < "2" as strings, so this
    // distinguishes a correct fix from either bug.
    const feats = [
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'a', name: 'A', area_hectares: 10 } },
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b', name: 'B', area_hectares: 2 } },
    ];
    const rowNames = () =>
      screen.getAllByRole('row').filter((r) => r.className.includes('table-row'))
        .map((r) => within(r).getAllByRole('gridcell')[1].textContent);

    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={feats} />);
    await userEvent.click(screen.getByRole('columnheader', { name: /attributeTable\.col\.area\b/ }));
    expect(rowNames()).toEqual(['B', 'A']); // ascending by real value: 2, then 10
  });
});

describe('AttributeTable P5 — hide on map + grid keyboard nav', () => {
  beforeEach(seedStore);

  it('the ⋮ "Hide on map" item toggles store.hiddenFeatureIds', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={() => {}} />);
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    await userEvent.click(within(rows[0]).getByRole('button', { name: 'attributeTable.rowActions' }));
    await userEvent.click(screen.getByRole('menuitem', { name: /hideOnMap/ }));
    // keyed per calculation so hiding a feature on one forest never affects another
    expect(useWorkspaceStore.getState().hiddenFeatureIds['c1::blocks']).toEqual(['b1']);

    await userEvent.click(within(rows[0]).getByRole('button', { name: 'attributeTable.rowActions' }));
    expect(screen.getByRole('menuitem', { name: /showOnMap/ })).toBeTruthy();
  });

  it('clicking a cell focuses it; ArrowDown moves focus to the next row', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={() => {}} />);
    const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
    const cellR0 = within(rows[0]).getByText('B-1'); // block_name cell, row 0
    await userEvent.click(cellR0);
    expect(cellR0.closest('.table-cell')).toHaveClass('cell-focused');

    await userEvent.keyboard('{ArrowDown}');
    expect(within(rows[1]).getByText('B-2').closest('.table-cell')).toHaveClass('cell-focused');
    expect(cellR0.closest('.table-cell')).not.toHaveClass('cell-focused');
  });
});

describe('AttributeTable — imported inline rename routes through the host (undo follow-up)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      activeLayerId: null,
      activeImportedLayerId: 7,
      calculationId: 'c1',
      customLayerStyles: {},
      columnVisibility: {}, columnOrder: {}, columnWidths: {}, columnLabels: {},
      importedLayers: [{ id: 7, name: 'plots', geometryTypes: ['Polygon'], purpose: undefined }],
      importedLayerFeatures: { 7: [] },
      selection: { layerId: null, featureIds: [] },
      editHistory: [], editFuture: [],
    } as never);
  });

  it('a committed inline edit calls onSaveProperty(feature, colKey, value) instead of fetching directly', async () => {
    const onSave = vi.fn();
    const feats = [
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'f1', label: 'old' } },
    ];
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={feats} onSaveProperty={onSave} />);
    await userEvent.dblClick(screen.getByText('old'));
    const input = screen.getByLabelText('attributeTable.editValue');
    await userEvent.clear(input);
    await userEvent.type(input, 'new{Enter}');
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ properties: expect.objectContaining({ id: 'f1' }) }),
      'label', 'new',
    );
  });
});

describe('AttributeTable P2 — column chooser (WORKSPACE_LAYER_STYLING_PLAN.md P2.2)', () => {
  beforeEach(seedStore);

  it('geometry columns show by default; the chooser can turn any column off', async () => {
    render(
      <AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} onZoomToFeature={() => {}} />,
    );
    // GEO_* metadata is visible in the header by default now
    const header = screen.getAllByRole('row').find((r) => r.className.includes('table-header'))!;
    expect(within(header).getByText('attributeTable.col.geo_area_ha')).toBeTruthy();
    expect(within(header).getByText('attributeTable.col.block_name')).toBeTruthy();

    // Owner request, 2026-09-24: hidden behind "more tools" by default.
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.columnsChooser' }));
    const chooser = screen.getByRole('dialog', { name: 'attributeTable.columnsChooser' });

    // turn OFF a GEO_* column
    const geoRow = within(chooser).getByText('attributeTable.col.geo_area_ha').closest('label')!;
    await userEvent.click(within(geoRow).getByRole('checkbox'));
    expect(useWorkspaceStore.getState().columnVisibility['blocks'].geo_area_ha).toBe(false);
    const header2 = screen.getAllByRole('row').find((r) => r.className.includes('table-header'))!;
    expect(within(header2).queryByText('attributeTable.col.geo_area_ha')).toBeNull();

    // turn OFF a plain column too
    const bnRow = within(chooser).getByText('attributeTable.col.block_name').closest('label')!;
    await userEvent.click(within(bnRow).getByRole('checkbox'));
    expect(useWorkspaceStore.getState().columnVisibility['blocks'].block_name).toBe(false);
    const header3 = screen.getAllByRole('row').find((r) => r.className.includes('table-header'))!;
    expect(within(header3).queryByText('attributeTable.col.block_name')).toBeNull();
  });
});

describe('AttributeTable — "more tools" toggle (owner request, 2026-09-24)', () => {
  beforeEach(seedStore);

  it('search, undo/redo, columns, exports and copy are hidden by default', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(screen.queryByRole('searchbox', { name: 'attributeTable.search' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.undo' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.redo' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.columnsChooser' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.exportCsvTitle' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.exportGeoJsonTitle' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.copyView' })).toBeNull();
    // The toggle itself is always visible.
    expect(screen.getByRole('button', { name: 'attributeTable.moreTools' })).toBeInTheDocument();
  });

  it('zoom-to-selection, select-in-view and "selected only" are hidden by default', () => {
    render(
      <AttributeTable
        isLoading={false} error={null} onRetry={() => {}} features={FEATS}
        onZoomToSelection={() => {}} onSelectInView={() => {}}
      />,
    );
    expect(screen.queryByRole('button', { name: 'attributeTable.zoomToSelection' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'attributeTable.selectInView' })).toBeNull();
    expect(screen.queryByLabelText('attributeTable.showOnlySelectedShort')).toBeNull();
  });

  it('clicking the toggle reveals every hidden tool at once', async () => {
    render(
      <AttributeTable
        isLoading={false} error={null} onRetry={() => {}} features={FEATS}
        onZoomToSelection={() => {}} onSelectInView={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    expect(screen.getByRole('searchbox', { name: 'attributeTable.search' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'attributeTable.columnsChooser' })).toBeInTheDocument();
    // the three downloads are one menu now
    expect(screen.queryByRole('button', { name: 'attributeTable.exportCsvTitle' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.downloadMenu' }));
    expect(screen.getByRole('button', { name: 'attributeTable.exportCsvTitle' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'attributeTable.exportGeoJsonTitle' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'attributeTable.copyView' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'attributeTable.zoomToSelection' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'attributeTable.selectInView' })).toBeInTheDocument();
    expect(screen.getByLabelText('attributeTable.showOnlySelectedShort')).toBeInTheDocument();

    // Clicking again collapses it back.
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    expect(screen.queryByRole('searchbox', { name: 'attributeTable.search' })).toBeNull();
  });

  it('the open/closed choice persists across a remount (localStorage)', async () => {
    const { unmount } = render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    expect(screen.getByRole('searchbox', { name: 'attributeTable.search' })).toBeInTheDocument();
    unmount();

    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(screen.getByRole('searchbox', { name: 'attributeTable.search' })).toBeInTheDocument();
  });

  it('a hidden active search still shows a dot on the toggle', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    await userEvent.type(screen.getByRole('searchbox', { name: 'attributeTable.search' }), 'Block A');
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' })); // collapse again
    expect(document.querySelector('.tools-toggle-btn .toolbar-dot')).toBeTruthy();
  });
});
