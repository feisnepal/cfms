/**
 * The layer menu's child lists (Style presets, Label-by-field, Export formats)
 * are shown in a fly-out, not flattened into the vertical column.
 *
 * Before this, every submenu child was appended straight after its parent row.
 * An imported layer with a dozen attribute columns therefore added a dozen
 * "label by <field>" rows, and the bottom of the menu ran off the viewport —
 * users had to zoom the whole page out to reach "Remove layer". These tests pin
 * the fly-out: children are absent from the column until the parent is opened,
 * and the parent opens on hover and on ArrowRight.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { LayerPanel } from '../LayerPanel';
import { createInitialState, useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('jszip', () => ({
  default: class { file = vi.fn(); generateAsync = vi.fn().mockResolvedValue(new Blob()); },
}));
vi.mock('../../contexts/BoundaryPreviewContext', () => ({
  useBoundaryPreview: () => ({ reviewBoundary: vi.fn() }),
}));
vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({
    canUndo: false, canRedo: false, undo: vi.fn(), redo: vi.fn(),
    pushOp: vi.fn(), pushAndExecute: vi.fn(),
  }),
}));

const HANDLERS = {
  onAddSubArea: vi.fn(),
  onPolygonFromPoints: vi.fn(),
  onAutoCreate: vi.fn(),
  onNewDraw: vi.fn(),
  onDivide: vi.fn(),
};

function makeStore(over: Record<string, unknown> = {}) {
  const state = {
    ...createInitialState(),
    calculationId: 'calc-1',
    featureCounts: { boundary: 1, blocks: 3, sub_areas: 1 },
    importedLayers: [
      { id: 7, name: 'Roads Import', visible: true, featureCount: 4, purpose: 'blocks', isDraft: false },
    ],
    // Two attribute columns → the "Show labels" row gets a 2-child fly-out.
    importedLayerFeatures: { 7: [{ properties: { name: 'a', width: 3 } }] },
    ...over,
  } as never;
  useWorkspaceStore.setState(state, true);
  vi.spyOn(useWorkspaceStore, 'getState').mockReturnValue(state);
  return state;
}

function renderPanel(mode: 'layers' | 'imported' = 'imported') {
  return render(
    <LayerPanel map={null} isLoading={false} error={null} mode={mode} hasGeometry {...HANDLERS} />,
  );
}

const openMenu = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
// menuitem + menuitemradio labels in a given menu, in order.
const labelsIn = (menu: HTMLElement) =>
  within(menu).queryAllByRole('menuitem').concat(within(menu).queryAllByRole('menuitemradio'))
    .map((el) => el.getAttribute('aria-label') ?? '');

beforeEach(() => vi.clearAllMocks());

describe('the label-by-field choices live in a fly-out, not the column', () => {
  it('are absent from the top-level menu until it is opened', () => {
    makeStore();
    renderPanel();
    openMenu('Actions for Roads Import');
    const menu = screen.getByRole('menu');
    // The two field choices are NOT flattened into the column.
    expect(within(menu).queryByRole('menuitemradio')).toBeNull();
    // The parent row advertises a submenu.
    const labelsRow = within(menu).getAllByRole('menuitem')
      .find((el) => (el.getAttribute('aria-label') ?? '').toLowerCase().includes('label'))!;
    expect(labelsRow).toBeTruthy();
    expect(labelsRow.getAttribute('aria-haspopup')).toBe('menu');
    expect(labelsRow.getAttribute('aria-expanded')).toBe('false');
  });

  it('opens on hover, as a second menu carrying the field choices', () => {
    makeStore();
    renderPanel();
    openMenu('Actions for Roads Import');
    const column = screen.getByRole('menu');
    const labelsRow = within(column).getAllByRole('menuitem')
      .find((el) => (el.getAttribute('aria-label') ?? '').toLowerCase().includes('label'))!;

    fireEvent.mouseEnter(labelsRow);

    const menus = screen.getAllByRole('menu');
    expect(menus.length).toBe(2);
    const flyout = menus.find((m) => m !== column)!;
    const radios = within(flyout).getAllByRole('menuitemradio');
    expect(radios.length).toBe(2);
    expect(labelsRow.getAttribute('aria-expanded')).toBe('true');
  });

  it('opens with ArrowRight and closes back to the parent with ArrowLeft', () => {
    makeStore();
    renderPanel();
    openMenu('Actions for Roads Import');
    const column = screen.getByRole('menu');
    const labelsRow = within(column).getAllByRole('menuitem')
      .find((el) => (el.getAttribute('aria-label') ?? '').toLowerCase().includes('label'))! as HTMLButtonElement;

    labelsRow.focus();
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(screen.getAllByRole('menu').length).toBe(2);

    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(screen.getAllByRole('menu').length).toBe(1);
    expect(document.activeElement).toBe(labelsRow);
  });

  it('the whole menu still closes on Escape when no fly-out is open', () => {
    makeStore();
    renderPanel();
    openMenu('Actions for Roads Import');
    expect(screen.queryByRole('menu')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('picking a field from the fly-out dismisses the whole menu', () => {
    makeStore();
    renderPanel();
    openMenu('Actions for Roads Import');
    const column = screen.getByRole('menu');
    const labelsRow = within(column).getAllByRole('menuitem')
      .find((el) => (el.getAttribute('aria-label') ?? '').toLowerCase().includes('label'))!;
    fireEvent.mouseEnter(labelsRow);
    const flyout = screen.getAllByRole('menu').find((m) => m !== column)!;
    fireEvent.click(within(flyout).getAllByRole('menuitemradio')[0]);
    expect(screen.queryByRole('menu')).toBeNull();
  });
});

describe('Style and its presets sit in the Advanced fly-out, not the column', () => {
  it('Advanced is the fly-out parent; the column itself shows no style rows until it is opened', () => {
    makeStore();
    renderPanel('layers');
    openMenu('Actions for Blocks');
    const menu = screen.getByRole('menu');
    const advanced = within(menu).getByRole('menuitem', { name: 'Advanced' });
    expect(advanced.getAttribute('aria-haspopup')).toBe('menu');
    expect(labelsIn(menu).some((l) => /style|preset/i.test(l))).toBe(false);
    fireEvent.mouseEnter(advanced);
    expect(screen.getAllByRole('menuitem').some((el) => /style/i.test(el.getAttribute('aria-label') ?? ''))).toBe(true);
  });
});
