/**
 * M-4 — the guarantee the whole consolidation exists to provide.
 *
 * Before M-1..M-4 a built-in row had two menus with different contents and an
 * imported row had one, with no ⋮ button at all. Of 28 commands, 3 appeared in
 * both menus and one of those was named two different ways.
 *
 * So this suite asserts the property rather than any particular list: **the two
 * openers show the same commands, in the same order, for the same row** — and
 * every row kind has both openers. A regression here means the menus have begun
 * to drift again, which is the only failure mode worth a dedicated test.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { LayerPanel } from '../LayerPanel';
import { createInitialState, useWorkspaceStore } from '../../store/workspaceStore';

// `useWorkspaceStore` is a real zustand store here — there is no global mock —
// so built-in rows render from the static registry whatever we do, but imported
// rows need actual state. Spying on `getState` alone is not enough: the hook
// subscribes to the store itself.
function makeStore(over: Record<string, unknown> = {}) {
  const base = createInitialState();
  const state = {
    ...base,
    calculationId: 'calc-1',
    featureCounts: { boundary: 1, blocks: 3, compartments: 2, sub_areas: 1 },
    importedLayers: [
      { id: 7, name: 'Roads Import', visible: true, featureCount: 4, purpose: 'blocks', isDraft: false },
    ],
    importedLayerFeatures: { 7: [{ properties: { name: 'a', width: 3 } }] },
    ...over,
  } as any;
  useWorkspaceStore.setState(state, true);
  vi.spyOn(useWorkspaceStore, 'getState').mockReturnValue(state);
  (useWorkspaceStore as any).__mock = state;
  return state;
}

const ALL_HANDLERS = {
  onAddSubArea: vi.fn(),
  onPolygonFromPoints: vi.fn(),
  onAutoCreate: vi.fn(),
  onNewDraw: vi.fn(),
  onDivide: vi.fn(),
};

/** Built-in rows live in the "layers" panel, imported rows in "imported". */
function renderPanel(mode: 'layers' | 'imported' = 'layers') {
  return render(
    <LayerPanel map={null} isLoading={false} error={null} mode={mode} hasGeometry {...ALL_HANDLERS} />,
  );
}

/** Command labels currently on screen, in render order. */
function openMenuItems(): string[] {
  const menu = screen.getByRole('menu');
  return within(menu)
    .queryAllByRole('menuitem')
    .map((el) => el.getAttribute('aria-label') ?? el.textContent ?? '');
}

function closeMenu() {
  fireEvent.keyDown(window, { key: 'Escape' });
}

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

beforeEach(() => vi.clearAllMocks());

describe('both openers exist on every row kind', () => {
  it('a built-in row has a ⋮ button', () => {
    makeStore();
    renderPanel();
    expect(screen.getByRole('button', { name: 'Actions for Blocks' })).toBeTruthy();
  });

  it('an imported row has one too — M-4, it previously had none', () => {
    makeStore();
    renderPanel('imported');
    expect(screen.getByRole('button', { name: 'Actions for Roads Import' })).toBeTruthy();
  });
});

describe('the two openers agree', () => {
  it.each([
    ['Blocks', 'layers' as const],
    ['Roads Import', 'imported' as const],
  ])('right-click and the button show the same commands on the %s row', (rowLabel, mode) => {
    makeStore();
    renderPanel(mode);

    fireEvent.click(screen.getByRole('button', { name: `Actions for ${rowLabel}` }));
    const fromButton = openMenuItems();
    closeMenu();

    const row = screen.getByRole('button', { name: `Actions for ${rowLabel}` }).closest('.layer-item')!;
    fireEvent.contextMenu(row);
    const fromRightClick = openMenuItems();

    expect(fromButton.length).toBeGreaterThan(0);
    expect(fromRightClick).toEqual(fromButton);
  });
});

describe('the menu is the layer it was opened on', () => {
  it('names itself after the row', () => {
    makeStore();
    renderPanel('imported');
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Roads Import' }));
    expect(screen.getByRole('menu', { name: 'Context menu for Roads Import' })).toBeTruthy();
  });

  it('offers an imported layer its own management commands', () => {
    makeStore();
    renderPanel('imported');
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Roads Import' }));
    const items = openMenuItems();
    expect(items).toEqual(expect.arrayContaining(['Rename', 'Advanced']));
    fireEvent.mouseEnter(screen.getByRole('menuitem', { name: 'Advanced' }));  // Duplicate lives in the Advanced fly-out
    expect(screen.getByRole('menuitem', { name: 'Duplicate' })).toBeTruthy();
    // Structural commands belong to built-in layers and must not leak here.
    expect(items).not.toEqual(expect.arrayContaining(['Divide equal-area']));
  });

  it('offers a built-in layer the structural commands', () => {
    makeStore();
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Blocks' }));
    const items = openMenuItems();
    expect(items).toEqual(expect.arrayContaining(['New block']));
    expect(items).not.toEqual(expect.arrayContaining(['Rename']));
  });
});

describe('a keyboard shortcut is not part of a command name', () => {
  it('reads "New block", not "New block N"', () => {
    makeStore();
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Actions for Blocks' }));
    expect(openMenuItems()).toContain('New block');
    expect(openMenuItems().some((l) => /New block\s+N/.test(l))).toBe(false);
  });
});
