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
  return mock;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('LayerPanel — Divide Equal-Area in the row ⋮ menu (D5/D6/P14)', () => {
  const openRowMenu = (label: string) => {
    fireEvent.click(screen.getByRole('button', { name: `Actions for ${label}` }));
  };
  // Once the forest has blocks or compartments, divide moves under the menu's "Advanced" fly-out.
  const divItem = (label: string) => {
    const menu = within(screen.getByRole('menu', { name: `Context menu for ${label}` }));
    const adv = menu.queryByRole('menuitem', { name: 'Advanced' });
    if (adv) fireEvent.mouseEnter(adv);
    return screen.queryByRole('menuitem', { name: 'Divide equal-area' });
  };

  it('renders the Compartments divide action disabled only when there is no forest boundary', () => {
    const onDivide = vi.fn();
    makeStore({ featureCounts: { boundary: 0, blocks: 0, compartments: 0 } });
    render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry onDivide={onDivide} />);
    openRowMenu('Compartments');
    const item = divItem('Compartments');
    expect(item).toBeTruthy();
    expect(item!.getAttribute('aria-disabled')).toBe('true');
  });

  it('enables the Compartments divide action from the boundary alone — no Block required', () => {
    const onDivide = vi.fn();
    makeStore({ featureCounts: { boundary: 1, blocks: 0, compartments: 0 } });
    render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry onDivide={onDivide} />);
    openRowMenu('Compartments');
    const item = divItem('Compartments');
    expect(item!.getAttribute('aria-disabled')).toBeNull();
    fireEvent.click(item as HTMLButtonElement);
    expect(onDivide).toHaveBeenCalledWith('compartments');
  });

  it('disables the Sub-Compartments divide action until compartments exist', () => {
    const onDivide = vi.fn();
    makeStore({ featureCounts: { boundary: 1, blocks: 3, compartments: 0 } });
    render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry onDivide={onDivide} />);
    openRowMenu('Sub-Compartments');
    const item = divItem('Sub-Compartments');
    expect(item).toBeTruthy();
    expect(item!.getAttribute('aria-disabled')).toBe('true');
  });

  it('enables the Sub-Compartments divide action once compartments exist', () => {
    const onDivide = vi.fn();
    makeStore({ featureCounts: { boundary: 1, blocks: 3, compartments: 2 } });
    render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry onDivide={onDivide} />);
    openRowMenu('Sub-Compartments');
    const item = divItem('Sub-Compartments');
    expect(item!.getAttribute('aria-disabled')).toBeNull();
    fireEvent.click(item as HTMLButtonElement);
    expect(onDivide).toHaveBeenCalledWith('sub_compartments');
  });

  it('keeps the divide actions disabled when the map is structure-locked (P14)', () => {
    const onDivide = vi.fn();
    makeStore({ featureCounts: { boundary: 1, blocks: 3, compartments: 2 } });
    render(
      <LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry structureLocked onDivide={onDivide} />,
    );
    openRowMenu('Compartments');
    expect(divItem('Compartments')!.getAttribute('aria-disabled')).toBe('true');
    openRowMenu('Sub-Compartments');
    expect(divItem('Sub-Compartments')!.getAttribute('aria-disabled')).toBe('true');
  });

  // M-3 changed this deliberately. D6's "always visible" is about the DATA
  // prerequisite — no blocks yet — and that still holds: the test above proves
  // Divide stays rendered and disabled, with a reason, when blocks are missing.
  // A host that wires no `onDivide` at all is a different thing: the command
  // cannot be performed, so it is omitted rather than shown greyed with nothing
  // to say. MapWorkspace always passes `onDivide`, so no user sees a change.
  it('omits the divide action entirely when the host cannot divide', () => {
    makeStore({ featureCounts: { boundary: 1, blocks: 3, compartments: 2 } });
    render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry />);
    openRowMenu('Compartments');
    expect(divItem('Compartments')).toBeNull();
  });

  it('offers divide when the host can divide and the data is there', () => {
    makeStore({ featureCounts: { boundary: 1, blocks: 3, compartments: 2 } });
    render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry onDivide={vi.fn()} />);
    openRowMenu('Compartments');
    expect(divItem('Compartments')!.getAttribute('aria-disabled')).toBeNull();
  });
});