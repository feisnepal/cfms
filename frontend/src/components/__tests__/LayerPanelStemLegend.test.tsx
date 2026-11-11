import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LayerPanel } from '../LayerPanel';
import { createInitialState, useWorkspaceStore } from '../../store/workspaceStore';
import { PRIME_SPECIES_RENDERER } from '../../lib/primeSpecies';

vi.mock('jszip', () => ({
  default: class {
    file = vi.fn();
    generateAsync = vi.fn().mockResolvedValue(new Blob());
  },
}));
vi.mock('../../hooks/useContextMenuUndoRedo', () => ({
  useContextMenuUndoRedo: () => ({
    canUndo: false, canRedo: false, undo: vi.fn(), redo: vi.fn(), pushOp: vi.fn(), pushAndExecute: vi.fn(),
  }),
}));
vi.mock('../../contexts/BoundaryPreviewContext', () => ({
  useBoundaryPreview: () => ({ reviewBoundary: vi.fn() }),
}));

function seed(overrides: Record<string, unknown> = {}) {
  useWorkspaceStore.setState({
    ...createInitialState(),
    calculationId: 'calc-1',
    layerVisibility: { ...createInitialState().layerVisibility, stem_mapping: true },
    layerRenderers: { stem_mapping: PRIME_SPECIES_RENDERER },
    stemLegend: { counts: { '18': 12, other: 3 }, isolated: null },
    ...overrides,
  } as never);
}

const renderPanel = () =>
  render(<LayerPanel map={null} isLoading={false} error={null} mode="layers" hasGeometry />);

beforeEach(() => vi.clearAllMocks());

describe('LayerPanel — species legend sits directly under the Stem Mapping layer', () => {
  it('renders the legend immediately after the Stem Mapping row, before the next layer', () => {
    seed();
    renderPanel();
    const legend = screen.getByTestId('stem-species-legend');
    const rows = screen.getAllByTestId('layer-item');
    const stemRow = rows.find((r) => r.textContent?.includes('Stem Mapping'))!;
    expect(stemRow).toBeTruthy();

    // The legend is the very next sibling of the Stem Mapping row...
    expect(stemRow.nextElementSibling).toBe(legend);
    // ...so it comes after Stem Mapping and before whatever layer follows it.
    const next = rows[rows.indexOf(stemRow) + 1];
    if (next) {
      expect(stemRow.compareDocumentPosition(legend) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(legend.compareDocumentPosition(next) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it('is not part of the map: nothing in the panel legend is positioned over the map area', () => {
    seed();
    renderPanel();
    expect(screen.getByTestId('stem-species-legend').style.position).not.toBe('absolute');
  });

  it('disappears when the Stem Mapping layer is hidden', () => {
    seed({ layerVisibility: { ...createInitialState().layerVisibility, stem_mapping: false } });
    renderPanel();
    expect(screen.queryByTestId('stem-species-legend')).not.toBeInTheDocument();
  });
});
