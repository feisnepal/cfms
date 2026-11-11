import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { LayerPanel } from '../LayerPanel';
import { createInitialState, useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('jszip', () => ({
  default: class {
    file = vi.fn();
    generateAsync = vi.fn().mockResolvedValue(new Blob());
  },
}));

vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({
    canUndo: false,
    canRedo: false,
    undo: vi.fn(),
    redo: vi.fn(),
    pushOp: vi.fn(),
    pushAndExecute: vi.fn(),
  }),
}));
vi.mock('../../contexts/BoundaryPreviewContext', () => ({
  useBoundaryPreview: () => ({ reviewBoundary: vi.fn() }),
}));

function makeStore(overrides: Partial<ReturnType<typeof createInitialState>> = {}) {
  const base = createInitialState();
  const mock = {
    ...base,
    calculationId: 'calc-1',
    ...overrides,
  } as any;
  useWorkspaceStore.setState({ ...mock, ...overrides } as any);
  vi.spyOn(useWorkspaceStore, 'getState').mockReturnValue(mock);
  (useWorkspaceStore as any).__mock = mock;
  return mock;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LayerPanel — New Block / New Compartment draw entry (E.8, in row ⋮ menu)', () => {
  const openRowMenu = (label: string) => {
    fireEvent.click(screen.getByRole('button', { name: `Actions for ${label}` }));
  };
  const newItem = (label: string) =>
    within(screen.getByRole('menu', { name: `Context menu for ${label}` })).queryByRole('menuitem', {
      name: label === 'Blocks' ? 'New block' : 'New compartment',
    });

  it('shows a New block action on the Blocks row ⋮ menu that fires onNewDraw("blocks")', () => {
    const onNewDraw = vi.fn();
    makeStore();
    render(
      <LayerPanel
        map={null}
        isLoading={false}
        mode="layers"
error={null}
        hasGeometry
        onNewDraw={onNewDraw}
      />,
    );
    openRowMenu('Blocks');
    const item = newItem('Blocks');
    expect(item).toBeTruthy();
    fireEvent.click(item as HTMLButtonElement);
    expect(onNewDraw).toHaveBeenCalledWith('blocks');
  });

  it('shows a New compartment action on the Compartments row ⋮ menu that fires onNewDraw("compartments")', () => {
    const onNewDraw = vi.fn();
    makeStore();
    render(
      <LayerPanel
        map={null}
        isLoading={false}
        mode="layers"
error={null}
        hasGeometry
        onNewDraw={onNewDraw}
      />,
    );
    openRowMenu('Compartments');
    const item = newItem('Compartments');
    expect(item).toBeTruthy();
    fireEvent.click(item as HTMLButtonElement);
    expect(onNewDraw).toHaveBeenCalledWith('compartments');
  });

  it('does not render the New actions when onNewDraw is not provided', () => {
    makeStore();
    render(
      <LayerPanel
        map={null}
        isLoading={false}
        mode="layers"
error={null}
        hasGeometry
      />,
    );
    openRowMenu('Blocks');
    expect(newItem('Blocks')).toBeNull();
    openRowMenu('Compartments');
    expect(newItem('Compartments')).toBeNull();
  });

  it('shows an Add Sub-Area action on the Sub-Areas row ⋮ menu that fires onAddSubArea("sub_areas")', () => {
    const onAddSubArea = vi.fn();
    // Add Sub-Area is gated on a forest extent (boundary or blocks) — the
    // backend refuses with 422 boundary_required. Give the store a boundary so
    // the action is enabled (layerMenu.hasForestExtent).
    makeStore({ featureCounts: { boundary: 1 } });
    render(
      <LayerPanel
        map={null}
        isLoading={false}
        mode="layers"
error={null}
        hasGeometry
        onAddSubArea={onAddSubArea}
      />,
    );
    openRowMenu('Sub-Areas');
    const item = within(screen.getByRole('menu', { name: 'Context menu for Sub-Areas' })).getByRole('menuitem', {
      name: 'Add sub-area',
    });
    expect(item).toBeTruthy();
    fireEvent.click(item as HTMLButtonElement);
    expect(onAddSubArea).toHaveBeenCalledWith('sub_areas');
  });

  it('does not render Add Sub-Area when onAddSubArea is not provided', () => {
    makeStore();
    render(
      <LayerPanel
        map={null}
        isLoading={false}
        mode="layers"
error={null}
        hasGeometry
      />,
    );
    openRowMenu('Sub-Areas');
    expect(
      within(screen.getByRole('menu', { name: 'Context menu for Sub-Areas' })).queryByRole('menuitem', {
        name: 'Add sub-area',
      }),
    ).toBeNull();
  });
});

describe('LayerPanel — manual refresh (P2)', () => {
  const renderPanel = () =>
    render(
      <LayerPanel
        map={null}
        isLoading={false}
        mode="layers"
error={null}
        hasGeometry
      />,
    );

  beforeEach(() => {
    useWorkspaceStore.setState({ syncStatus: 'synced', dirty: false, lastRefreshErrors: {} } as any);
  });

  it('renders a refresh button', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: 'Refresh map data' })).toBeTruthy();
  });

  it('calls refreshAll on click', () => {
    const refreshAll = vi.fn().mockResolvedValue(undefined);
    useWorkspaceStore.setState({ refreshAll } as any);
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh map data' }));
    expect(refreshAll).toHaveBeenCalledTimes(1);
  });

  it('is disabled while syncing', () => {
    useWorkspaceStore.setState({ syncStatus: 'syncing' } as any);
    renderPanel();
    expect(screen.getByRole('button', { name: 'Refresh map data' })).toBeDisabled();
  });

  it('is disabled while dirty', () => {
    useWorkspaceStore.setState({ dirty: true } as any);
    renderPanel();
    expect(screen.getByRole('button', { name: 'Refresh map data' })).toBeDisabled();
  });

  it('shows the spinner class while syncing', () => {
    useWorkspaceStore.setState({ syncStatus: 'syncing' } as any);
    renderPanel();
    expect(document.querySelector('.refresh-spin')).toBeTruthy();
  });
});