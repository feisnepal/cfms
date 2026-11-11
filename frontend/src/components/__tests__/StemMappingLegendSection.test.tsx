import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StemMappingLegendSection } from '../StemMappingLegendSection';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { PRIME_SPECIES_RENDERER } from '../../lib/primeSpecies';

function setStore(patch: Record<string, unknown>) {
  useWorkspaceStore.setState({
    layerVisibility: { stem_mapping: true },
    layerRenderers: { stem_mapping: PRIME_SPECIES_RENDERER },
    stemLegend: { counts: {}, isolated: null },
    ...patch,
  } as never);
}

describe('StemMappingLegendSection (under the Stem Mapping layer row)', () => {
  beforeEach(() => setStore({}));

  it('says to zoom in while nothing is on screen', () => {
    render(<StemMappingLegendSection />);
    expect(screen.getByTestId('stem-legend-hint')).toBeInTheDocument();
    expect(screen.queryByTestId('stem-legend-row-18')).not.toBeInTheDocument();
  });

  it('lists the species in view with counts, most trees first and "other" last', () => {
    setStore({ stemLegend: { counts: { '4': 3, other: 50, '18': 10 }, isolated: null } });
    render(<StemMappingLegendSection />);
    const rows = screen.getAllByTestId(/^stem-legend-row-/).map((r) => r.getAttribute('data-testid'));
    expect(rows).toEqual(['stem-legend-row-18', 'stem-legend-row-4', 'stem-legend-row-other']);
    expect(screen.getByTestId('stem-legend-row-18')).toHaveTextContent('Shorea robusta');
    expect(screen.getByTestId('stem-legend-row-18')).toHaveTextContent('10');
    expect(screen.queryByTestId('stem-legend-row-7')).not.toBeInTheDocument(); // Bombax: not in view
  });

  it('clicking a species isolates it; clicking it again, or "Show all", clears', () => {
    setStore({ stemLegend: { counts: { '18': 10, '4': 3 }, isolated: null } });
    render(<StemMappingLegendSection />);
    fireEvent.click(screen.getByTestId('stem-legend-row-18'));
    expect(useWorkspaceStore.getState().stemLegend.isolated).toBe('18');
    expect(screen.getByTestId('stem-legend-row-18')).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByTestId('stem-legend-row-18'));
    expect(useWorkspaceStore.getState().stemLegend.isolated).toBeNull();

    fireEvent.click(screen.getByTestId('stem-legend-row-4'));
    fireEvent.click(screen.getByText('Show all'));
    expect(useWorkspaceStore.getState().stemLegend.isolated).toBeNull();
  });

  it('is hidden with its layer', () => {
    setStore({ layerVisibility: { stem_mapping: false }, stemLegend: { counts: { '18': 1 }, isolated: null } });
    render(<StemMappingLegendSection />);
    expect(screen.queryByTestId('stem-species-legend')).not.toBeInTheDocument();
  });

  it('is hidden when the user replaced the species colouring with their own renderer', () => {
    setStore({
      layerRenderers: { stem_mapping: { mode: 'categorized', field: 'species', classes: [], otherColor: '#999' } },
      stemLegend: { counts: { '18': 1 }, isolated: null },
    });
    render(<StemMappingLegendSection />);
    expect(screen.queryByTestId('stem-species-legend')).not.toBeInTheDocument();
  });

  it('the store ignores a counts write that changes nothing (the map reports on every pan)', () => {
    const { setStemLegendCounts } = useWorkspaceStore.getState();
    setStemLegendCounts({ '18': 2 });
    const before = useWorkspaceStore.getState().stemLegend;
    setStemLegendCounts({ '18': 2 });
    expect(useWorkspaceStore.getState().stemLegend).toBe(before);
    setStemLegendCounts({ '18': 3 });
    expect(useWorkspaceStore.getState().stemLegend).not.toBe(before);
  });
});
