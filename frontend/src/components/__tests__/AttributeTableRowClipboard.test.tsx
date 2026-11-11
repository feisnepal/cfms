import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AttributeTable } from '../AttributeTable';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

const FEATS = [
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b1', name: 'Block A' } },
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b2', name: 'Block B' } },
];

function seedStore(selected: string[] = []) {
  useWorkspaceStore.setState({
    activeLayerId: 'sub_areas',
    activeImportedLayerId: null,
    calculationId: 'c1',
    customLayerStyles: {},
    columnVisibility: {},
    columnOrder: {},
    columnWidths: {},
    columnLabels: {},
    importedLayers: [],
    selection: { layerId: 'sub_areas', featureIds: selected },
    editHistory: [],
    editFuture: [],
  } as never);
}

async function openRowMenu(row = 0) {
  const rows = screen.getAllByRole('row').filter((r) => r.className.includes('table-row'));
  await userEvent.click(within(rows[row]).getByRole('button', { name: 'attributeTable.rowActions' }));
}

const table = (props: Record<string, unknown> = {}) =>
  render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} {...props} />);

describe('AttributeTable row menu — Copy / Paste / Paste as new layer', () => {
  beforeEach(() => seedStore());

  it('Copy copies that row', async () => {
    const onCopyFeature = vi.fn();
    table({ onCopyFeature });
    await openRowMenu(1);
    await userEvent.click(screen.getByRole('menuitem', { name: /attributeTable\.copyFeature/ }));
    expect(onCopyFeature).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b2' }) }), 1);
  });

  it('the action column exists when Copy is the only handler', () => {
    table({ onCopyFeature: vi.fn() });
    expect(screen.getAllByRole('button', { name: 'attributeTable.rowActions' }).length).toBeGreaterThan(0);
  });

  it('a row inside a multi-selection says it will copy the selection', async () => {
    seedStore(['b1', 'b2']);
    table({ onCopyFeature: vi.fn() });
    await openRowMenu(0);
    expect(screen.getByRole('menuitem', { name: /layerPanel\.copySelected/ })).toBeTruthy();
  });

  it('Paste here runs when a paste can land in this layer', async () => {
    const onPasteFeatures = vi.fn();
    table({ onCopyFeature: vi.fn(), onPasteFeatures, pasteState: null, clipboardCount: 3 });
    await openRowMenu();
    const paste = screen.getByRole('menuitem', { name: /layerPanel\.pasteHere/ });
    expect((paste as HTMLButtonElement).disabled).toBe(false);
    await userEvent.click(paste);
    expect(onPasteFeatures).toHaveBeenCalledTimes(1);
  });

  it('Paste here is disabled, with the reason as its tooltip, when it cannot land right now', async () => {
    const onPasteFeatures = vi.fn();
    table({
      onCopyFeature: vi.fn(), onPasteFeatures, clipboardCount: 3,
      pasteState: { reasonKey: 'editing.paste.reason.geometry_mismatch', params: { have: 'Point', need: 'Polygon' } },
    });
    await openRowMenu();
    const paste = screen.getByRole('menuitem', { name: /layerPanel\.pasteHere/ }) as HTMLButtonElement;
    expect(paste.disabled).toBe(true);
    expect(paste.title).toBe('editing.paste.reason.geometry_mismatch');
    await userEvent.click(paste);
    expect(onPasteFeatures).not.toHaveBeenCalled();
  });

  it("Paste here is left out on a layer that can never take one — or when the layer's state is unknown", async () => {
    table({ onCopyFeature: vi.fn(), onPasteFeatures: vi.fn(), pasteState: 'never', clipboardCount: 3 });
    await openRowMenu();
    expect(screen.queryByRole('menuitem', { name: /layerPanel\.pasteHere/ })).toBeNull();
  });

  it('Paste as new layer is disabled while nothing is copied, then runs', async () => {
    const onPasteAsLayer = vi.fn();
    const { unmount } = table({ onCopyFeature: vi.fn(), onPasteAsLayer, clipboardCount: 0 });
    await openRowMenu();
    const empty = screen.getByRole('menuitem', { name: /layerPanel\.pasteAsLayer/ }) as HTMLButtonElement;
    expect(empty.disabled).toBe(true);
    expect(empty.title).toBe('editing.paste.reason.empty_clipboard');
    unmount();

    table({ onCopyFeature: vi.fn(), onPasteAsLayer, clipboardCount: 2 });
    await openRowMenu();
    await userEvent.click(screen.getByRole('menuitem', { name: /layerPanel\.pasteAsLayer/ }));
    expect(onPasteAsLayer).toHaveBeenCalledTimes(1);
  });

  it('leaves the existing Zoom and Delete commands alone', async () => {
    const onDelete = vi.fn();
    table({ onCopyFeature: vi.fn(), onZoomToFeature: vi.fn(), onDeleteFeature: onDelete });
    await openRowMenu();
    expect(screen.getByRole('menuitem', { name: /zoomToFeature/ })).toBeTruthy();
    await userEvent.click(screen.getByRole('menuitem', { name: /deleteFeature/ }));
    expect(onDelete).toHaveBeenCalledWith(expect.objectContaining({ properties: expect.objectContaining({ id: 'b1' }) }), 0);
  });
});
