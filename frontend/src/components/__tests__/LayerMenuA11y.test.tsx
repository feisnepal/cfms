/**
 * M-12 — keyboard and screen-reader behaviour of the shared layer menu.
 *
 * The audit that produced these tests found a defect that quietly undid M-7.
 * Unavailable commands were rendered with the `disabled` attribute AND skipped
 * by the arrow-key walk, so a keyboard user could never land on one — and the
 * reason it was unavailable lived only in `title`, a mouse-only tooltip. Every
 * explanation M-7 added was therefore invisible to precisely the users least
 * able to guess it.
 *
 * These tests assert the behaviour, not the markup: an unavailable command can
 * be reached, says why, and does nothing when activated.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { LayerPanel } from '../LayerPanel';
import { createInitialState, useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('jszip', () => ({
  default: class { file = vi.fn(); generateAsync = vi.fn().mockResolvedValue(new Blob()); },
}));
vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({
    canUndo: false, canRedo: false, undo: vi.fn(), redo: vi.fn(),
    pushOp: vi.fn(), pushAndExecute: vi.fn(),
  }),
}));
vi.mock('../../contexts/BoundaryPreviewContext', () => ({
  useBoundaryPreview: () => ({ reviewBoundary: vi.fn() }),
}));

const HANDLERS = {
  onAddSubArea: vi.fn(),
  onPolygonFromPoints: vi.fn(),
  onAutoCreate: vi.fn(),
  onImportBlockFromBoundary: vi.fn(),
  onNewDraw: vi.fn(),
  onDivide: vi.fn(),
};

function makeStore(over: Record<string, unknown> = {}) {
  const state = {
    ...createInitialState(),
    calculationId: 'calc-1',
    // Blocks exist, so the boundary commands and auto-create are unavailable —
    // which is exactly the state whose explanations must be reachable.
    featureCounts: { boundary: 1, blocks: 4, compartments: 0 },
    ...over,
  } as never;
  useWorkspaceStore.setState(state, true);
  vi.spyOn(useWorkspaceStore, 'getState').mockReturnValue(state);
  return state;
}

function renderPanel() {
  return render(
    <LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry {...HANDLERS} />,
  );
}

const openVia = (name: string) => fireEvent.click(screen.getByRole('button', { name }));
const items = () => within(screen.getByRole('menu')).queryAllByRole('menuitem');

beforeEach(() => vi.clearAllMocks());

describe('an unavailable command is reachable and explains itself', () => {
  // "Auto-create" used to be this suite's example of a disabled-but-reachable
  // command; it was REMOVED from the Blocks/Compartments menu (owner
  // directive 2026-10-01 — see layerMenu.ts's removal comment). "Create One
  // Block from the Forest Area" is disabled for the exact same reason
  // (structural features already exist) in the exact same test state, so it
  // now carries this suite's assertions instead.
  it('is not removed from the accessibility tree by a `disabled` attribute', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    const importFromBoundary = items().find((el) => (el.getAttribute('aria-label') ?? '').startsWith('Create One Block'));
    expect(importFromBoundary).toBeTruthy();
    // `disabled` would make it unfocusable; `aria-disabled` keeps it reachable.
    expect((importFromBoundary as HTMLButtonElement).disabled).toBe(false);
    expect(importFromBoundary!.getAttribute('aria-disabled')).toBe('true');
  });

  it('announces WHY, via a description rather than by renaming the command', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    const importFromBoundary = items().find((el) => (el.getAttribute('aria-label') ?? '').startsWith('Create One Block'))!;
    // The NAME stays the command; a name that shifted with availability would
    // be a moving target for anything that finds items by name.
    expect(importFromBoundary.getAttribute('aria-label')).not.toContain('unavailable');
    const describedBy = importFromBoundary.getAttribute('aria-describedby');
    expect(describedBy).toBeTruthy();
    const description = document.getElementById(describedBy!);
    expect(description?.textContent).toContain('unavailable');
    expect(description?.textContent).toContain('Blocks or compartments already exist');
  });

  it('does nothing when activated', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    const importFromBoundary = items().find((el) => (el.getAttribute('aria-label') ?? '').startsWith('Create One Block'))!;
    fireEvent.click(importFromBoundary);
    expect(HANDLERS.onImportBlockFromBoundary).not.toHaveBeenCalled();
  });

  it('an available command still works', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    const newBlock = items().find((el) => el.getAttribute('aria-label') === 'New block')!;
    fireEvent.click(newBlock);
    expect(HANDLERS.onNewDraw).toHaveBeenCalledWith('blocks');
  });
});

describe('the keyboard walk covers the whole menu', () => {
  it('reaches unavailable items too, or their reasons are unhearable', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    const all = items();
    const unavailable = all.filter((el) => el.getAttribute('aria-disabled') === 'true');
    expect(unavailable.length).toBeGreaterThan(0);

    // Arrow through the whole menu and collect what receives focus.
    const seen = new Set<string>();
    for (let i = 0; i < all.length + 2; i++) {
      fireEvent.keyDown(window, { key: 'ArrowDown' });
      const active = document.activeElement as HTMLElement | null;
      if (active?.classList.contains('context-menu-item')) {
        seen.add(active.getAttribute('aria-label') ?? '');
      }
    }
    for (const el of unavailable) {
      expect(seen.has(el.getAttribute('aria-label') ?? '')).toBe(true);
    }
  });

  it('Escape closes the menu', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    expect(screen.queryByRole('menu')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });
});

describe('focus goes back where it came from', () => {
  it('returns to the opener when the menu closes', () => {
    makeStore();
    renderPanel();
    const opener = screen.getByRole('button', { name: 'Actions for Blocks' });
    opener.focus();
    fireEvent.click(opener);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(document.activeElement).toBe(opener);
  });
});

describe('a keyboard shortcut is shown but not spoken', () => {
  it('is hidden from assistive technology', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    const menu = screen.getByRole('menu');
    const shortcuts = menu.querySelectorAll('.context-menu-shortcut');
    expect(shortcuts.length).toBeGreaterThan(0);
    shortcuts.forEach((el) => expect(el.getAttribute('aria-hidden')).toBe('true'));
  });
});

describe('the menu names itself and its items honestly', () => {
  it('is labelled with the layer it belongs to', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    expect(screen.getByRole('menu', { name: 'Context menu for Blocks' })).toBeTruthy();
  });

  it('separates groups with a separator rather than running them together', () => {
    makeStore();
    renderPanel();
    openVia('Actions for Blocks');
    expect(within(screen.getByRole('menu')).getAllByRole('separator').length).toBeGreaterThan(0);
  });
});
