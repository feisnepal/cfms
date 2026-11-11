import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttributeTable } from '../AttributeTable';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

const bigFeats = (n: number) =>
  Array.from({ length: n }, (_, i) => ({
    type: 'Feature' as const,
    geometry: { type: 'Polygon' as const, coordinates: [] },
    // `index` is the table's default order (real blocks always carry one). Without it the
    // rows fall back to a string sort of the id (b0, b1, b10, b100 ...) and "Block 400"
    // is nowhere near row 400.
    properties: { id: `b${i}`, index: i, name: `Block ${i}`, area_hectares: i },
  }));

function seedStore() {
  useWorkspaceStore.setState({
    activeLayerId: 'blocks',
    activeImportedLayerId: null,
    calculationId: 'c1',
    customLayerStyles: {},
    layerRenderers: {},
    tableFilter: null,
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

const rowNodes = () =>
  screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));

describe('AttributeTable P2b — row virtualization (WORKSPACE_LAYER_STYLING_PLAN.md P2.4)', () => {
  beforeEach(seedStore);

  it('a 1,000-feature layer keeps far fewer than 60 row nodes in the DOM', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={bigFeats(1000)} onZoomToFeature={() => {}} />);
    expect(rowNodes().length).toBeGreaterThan(0);
    expect(rowNodes().length).toBeLessThan(60);
  });

  it('scrolling down mounts later rows and unmounts the first ones', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={bigFeats(1000)} onZoomToFeature={() => {}} />);
    expect(within(rowNodes()[0]).queryByText('Block 0')).toBeTruthy();
    expect(screen.queryByText('Block 400')).toBeNull();

    const grid = document.querySelector('.table-grid') as HTMLElement;
    Object.defineProperty(grid, 'scrollTop', { value: 400 * 40, writable: true, configurable: true });
    fireEvent.scroll(grid);

    expect(screen.getByText('Block 400')).toBeTruthy();
    expect(screen.queryByText('Block 0')).toBeNull();
  });

  it('a small layer is NOT virtualized — every row is present', () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={bigFeats(10)} onZoomToFeature={() => {}} />);
    expect(rowNodes()).toHaveLength(10);
  });

  it('sort + filter still work over a virtualized set', async () => {
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={bigFeats(1000)} onZoomToFeature={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.filterButton' })); // the filter is a pop-up
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterField'), 'name');
    await userEvent.selectOptions(screen.getByLabelText('attributeTable.filterOp'), 'eq');
    await userEvent.type(screen.getByLabelText('attributeTable.filterValue'), 'Block 777');
    expect(rowNodes()).toHaveLength(1);
    expect(rowNodes()[0]).toHaveTextContent('Block 777');
  });
});
