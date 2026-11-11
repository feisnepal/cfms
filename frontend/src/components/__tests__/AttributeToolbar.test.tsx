/** The attribute table's one-row toolbar (owner request 2026-10-11: four bars took about 155px of the panel's height). */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('../../i18n/hooks', () => ({ useT: () => (key: string, values?: Record<string, unknown>) => (values?.count != null ? `${key}:${values.count}` : key) }));

import { AttributeToolbar, type AttributeToolbarProps } from '../AttributeToolbar';

const base = (over: Partial<AttributeToolbarProps> = {}): AttributeToolbarProps => ({
  toolsOpen: true,
  onToggleTools: () => undefined,
  searchQuery: '',
  onSearchChange: () => undefined,
  selectionCount: 0,
  showOnlySelected: false,
  onToggleShowOnlySelected: () => undefined,
  filter: {
    field: '', op: 'eq', value: '', active: false, onField: () => undefined, onOp: () => undefined, onValue: () => undefined,
    onClear: () => undefined, onMap: false, onOnMap: () => undefined,
    columns: [{ key: 'name', label: 'Name' }, { key: 'area', label: 'Area' }], suggestions: [],
  },
  columnsChooser: { rows: [{ key: 'name', label: 'Name', shown: true }], onToggle: () => undefined },
  downloads: { onCsv: () => undefined, onGeoJson: () => undefined, onCopy: () => undefined },
  ...over,
});

const VIEW = {
  themes: ['all', 'basic', 'raster', 'inventory'] as never,
  active: 'all' as never,
  onPick: () => undefined,
  groups: ['location', 'terrain'] as never,
  activeGroup: 'all' as never,
  onPickGroup: () => undefined,
};

describe('AttributeToolbar', () => {
  it('is a single toolbar row, however many tools are open', () => {
    const { container, rerender } = render(<AttributeToolbar {...base({ toolsOpen: false })} />);
    expect(container.querySelectorAll('.table-toolbar')).toHaveLength(1);
    rerender(<AttributeToolbar {...base({ toolsOpen: true, view: VIEW, onUpdateAttribute: () => undefined, onZoomToSelection: () => undefined, onSelectInView: () => undefined, onUndo: () => undefined, onRedo: () => undefined })} />);
    expect(container.querySelectorAll('.table-toolbar')).toHaveLength(1);
  });

  it('keeps the filter, the view and Update attribute available with the tools collapsed; the rest waits for the tools', () => {
    render(<AttributeToolbar {...base({ toolsOpen: false, view: VIEW, onUpdateAttribute: () => undefined })} />);
    expect(screen.getByTestId('tb-filter')).toBeTruthy();
    expect(screen.getByTestId('tb-view')).toBeTruthy();
    expect(screen.getByTestId('tb-update-attribute')).toBeTruthy();
    for (const hidden of ['attributeTable.search', 'attributeTable.columnsChooser', 'attributeTable.downloadMenu', 'attributeTable.showOnlySelectedShort']) {
      expect(screen.queryByLabelText(hidden)).toBeNull();
    }
  });

  it('opens the filter as a pop-up that Escape closes, and an outside press closes too', async () => {
    render(<AttributeToolbar {...base()} />);
    expect(screen.queryByLabelText('attributeTable.filterField')).toBeNull();
    await userEvent.click(screen.getByTestId('tb-filter'));
    expect(screen.getByLabelText('attributeTable.filterField')).toBeTruthy();
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByLabelText('attributeTable.filterField')).toBeNull();
    await userEvent.click(screen.getByTestId('tb-filter'));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByLabelText('attributeTable.filterField')).toBeNull();
  });

  it('shows an active filter as a chip with a clear button', async () => {
    const onClear = vi.fn();
    render(<AttributeToolbar {...base({ filter: { ...base().filter, field: 'name', value: 'Block A', active: true, onClear } })} />);
    expect(screen.getByTestId('tb-filter-chip').textContent).toContain('Name');
    expect(screen.getByTestId('tb-filter-chip').textContent).toContain('Block A');
    await userEvent.click(screen.getByLabelText('attributeTable.filterClear'));
    expect(onClear).toHaveBeenCalled();
  });

  it('the View menu lists the views with the Raster analysis subjects nested, and picking one closes it', async () => {
    const onPick = vi.fn();
    const onPickGroup = vi.fn();
    render(<AttributeToolbar {...base({ view: { ...VIEW, onPick, onPickGroup } })} />);
    await userEvent.click(screen.getByTestId('tb-view'));
    expect(screen.getByTestId('tb-view-basic')).toBeTruthy();
    expect(screen.getByTestId('analysis-group-terrain')).toBeTruthy();
    await userEvent.click(screen.getByTestId('analysis-group-terrain'));
    expect(onPick).toHaveBeenCalledWith('raster');
    expect(onPickGroup).toHaveBeenCalledWith('terrain');
    expect(screen.queryByTestId('tb-view-basic')).toBeNull(); // closed
    await userEvent.click(screen.getByTestId('tb-view'));
    await userEvent.click(screen.getByTestId('tb-view-inventory'));
    expect(onPick).toHaveBeenLastCalledWith('inventory');
  });

  it('names the current view on the button, with its Raster analysis subject', () => {
    render(<AttributeToolbar {...base({ view: { ...VIEW, active: 'raster' as never, activeGroup: 'terrain' as never } })} />);
    expect(screen.getByTestId('tb-view').textContent).toContain('attributeUpdate.theme.raster');
    expect(screen.getByTestId('tb-view').textContent).toContain('attributeUpdate.group.terrain');
  });

  it('puts the three downloads in one menu and closes it after a choice', async () => {
    const downloads = { onCsv: vi.fn(), onGeoJson: vi.fn(), onCopy: vi.fn() };
    render(<AttributeToolbar {...base({ downloads })} />);
    expect(screen.queryByLabelText('attributeTable.exportCsvTitle')).toBeNull();
    await userEvent.click(screen.getByTestId('tb-download'));
    await userEvent.click(screen.getByLabelText('attributeTable.exportGeoJsonTitle'));
    expect(downloads.onGeoJson).toHaveBeenCalled();
    expect(screen.queryByLabelText('attributeTable.exportCsvTitle')).toBeNull();
    await userEvent.click(screen.getByTestId('tb-download'));
    await userEvent.click(screen.getByLabelText('attributeTable.copyView'));
    expect(downloads.onCopy).toHaveBeenCalled();
  });

  it('Update attribute and Set colour call their handlers; the colour button carries the selection count', async () => {
    const onUpdateAttribute = vi.fn();
    const onClick = vi.fn();
    render(<AttributeToolbar {...base({ onUpdateAttribute, colour: { count: 3, open: false, onClick } })} />);
    await userEvent.click(screen.getByTestId('tb-update-attribute'));
    expect(onUpdateAttribute).toHaveBeenCalled();
    const colour = screen.getByLabelText('attributeTable.setColourBulk:3');
    expect(colour.textContent).toContain('3');
    await userEvent.click(colour);
    expect(onClick).toHaveBeenCalled();
  });

  it('flags a hidden search or "selected only" on the collapsed toggle, so missing rows always have a visible reason', () => {
    const { rerender } = render(<AttributeToolbar {...base({ toolsOpen: false })} />);
    expect(document.querySelector('.toolbar-dot')).toBeNull();
    rerender(<AttributeToolbar {...base({ toolsOpen: false, searchQuery: 'abc' })} />);
    expect(document.querySelector('.toolbar-dot')).not.toBeNull();
    rerender(<AttributeToolbar {...base({ toolsOpen: false, showOnlySelected: true })} />);
    expect(document.querySelector('.toolbar-dot')).not.toBeNull();
  });

  it('the selection actions are enabled only with a selection, and the count is shown', () => {
    const { rerender } = render(<AttributeToolbar {...base({ onZoomToSelection: () => undefined })} />);
    expect((screen.getByLabelText('attributeTable.zoomToSelection') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('attributeTable.showOnlySelectedShort') as HTMLButtonElement).disabled).toBe(true);
    rerender(<AttributeToolbar {...base({ selectionCount: 2, onZoomToSelection: () => undefined })} />);
    expect((screen.getByLabelText('attributeTable.zoomToSelection') as HTMLButtonElement).disabled).toBe(false);
    expect(document.querySelector('.selection-count')?.textContent).toContain('2');
  });
});
