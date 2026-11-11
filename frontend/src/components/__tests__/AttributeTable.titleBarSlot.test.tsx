/** The attribute table's toolbar moves into the dock panel's title bar when the panel reserved a slot (owner request 2026-10-11). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Group } from 'react-resizable-panels';
import { AttributeTable } from '../AttributeTable';
import { DockPanel } from '../DockPanel';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));
vi.mock('../SymbolPicker', () => ({ default: () => null }));

const FEATS = [
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b1', name: 'Block A' } },
  { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [] }, properties: { id: 'b2', name: 'Block B' } },
];

beforeEach(() => {
  useWorkspaceStore.setState({
    activeLayerId: 'blocks', activeImportedLayerId: null, calculationId: 'c1', customLayerStyles: {}, columnVisibility: {},
    columnOrder: {}, columnWidths: {}, columnLabels: {}, importedLayers: [], selection: { layerId: null, featureIds: [] },
    editHistory: [], editFuture: [],
  } as never);
});
afterEach(() => document.getElementById('dock-toolbar-attributeTable')?.remove());

describe('toolbar placement', () => {
  it('stays above the rows when there is no title-bar slot', () => {
    const { container } = render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(container.querySelector('[data-testid="attribute-toolbar"]')).not.toBeNull();
  });

  it('fills the title-bar slot when the dock panel reserved one, and leaves nothing above the rows', () => {
    const slot = document.createElement('div');
    slot.id = 'dock-toolbar-attributeTable';
    document.body.appendChild(slot);
    const { container } = render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(slot.querySelector('[data-testid="attribute-toolbar"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="attribute-toolbar"]')).toBeNull();
    // it is the same live toolbar: its controls work from there
    expect(slot.querySelector('[data-testid="tb-filter"]')).not.toBeNull();
  });

  it('keeps working in the slot: the tools toggle shows the search box and a second press hides it', async () => {
    const slot = document.createElement('div');
    slot.id = 'dock-toolbar-attributeTable';
    document.body.appendChild(slot);
    render(<AttributeTable isLoading={false} error={null} onRetry={() => {}} features={FEATS} />);
    expect(screen.queryByRole('searchbox', { name: 'attributeTable.search' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    expect(await screen.findByRole('searchbox', { name: 'attributeTable.search' })).toBeTruthy();
    expect(slot.querySelector('input[type="search"]')).not.toBeNull(); // it is in the title bar, not above the rows
    await userEvent.click(screen.getByRole('button', { name: 'attributeTable.moreTools' }));
    expect(screen.queryByRole('searchbox', { name: 'attributeTable.search' })).toBeNull();
  });
});

describe('DockPanel toolbar slot', () => {
  it('reserves a title-bar slot only when asked', () => {
    const { container, rerender } = render(
      <Group orientation="vertical">
        <DockPanel id="attributeTable" title="Attribute Table" toolbarSlot>
          <div />
        </DockPanel>
      </Group>,
    );
    expect(container.querySelector('#dock-toolbar-attributeTable.dock-panel-toolbar')).not.toBeNull();
    rerender(
      <Group orientation="vertical">
        <DockPanel id="attributeTable" title="Attribute Table">
          <div />
        </DockPanel>
      </Group>,
    );
    expect(container.querySelector('.dock-panel-toolbar')).toBeNull();
  });
});
