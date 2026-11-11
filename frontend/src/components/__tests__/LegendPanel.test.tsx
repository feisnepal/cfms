import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import { LegendPanel } from '../LegendPanel';
import { createInitialState, useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

function setStore(overrides: Record<string, unknown> = {}) {
  useWorkspaceStore.setState({ ...createInitialState(), ...overrides } as never);
}

beforeEach(() => setStore());

describe('LegendPanel — Protection Working Circle row (P5-display)', () => {
  it('is hidden when no protection unit is present', () => {
    setStore({ featureCounts: { compartments: 4 } });
    render(<LegendPanel />);
    expect(screen.queryByTestId('legend-protection-wc')).toBeNull();
  });

  it('shows the "no felling" row with a count when a visible unit layer has protection units', () => {
    setStore({
      layerVisibility: { compartments: true },
      featureCounts: { compartments: 4, 'compartments:protection': 2 },
    });
    render(<LegendPanel />);
    const row = screen.getByTestId('legend-protection-wc');
    expect(row).toBeInTheDocument();
    expect(row).toHaveTextContent('legend.protectionWorkingCircle');
    expect(row).toHaveTextContent('2');
  });

  it('is hidden when the only unit layer carrying protection units is toggled off', () => {
    setStore({
      layerVisibility: { compartments: false },
      featureCounts: { 'compartments:protection': 2 },
    });
    render(<LegendPanel />);
    expect(screen.queryByTestId('legend-protection-wc')).toBeNull();
  });
});

describe('LegendPanel — swatch follows a custom layer style (P1.3)', () => {
  const swatch = (label: string) =>
    screen.getByText(label).parentElement!.querySelector('.legend-swatch') as HTMLElement;

  it('a non-palette layer (boundary) shows the flat custom fill colour', () => {
    setStore({
      calculationId: 'c1',
      layerVisibility: { boundary: true },
      customLayerStyles: { 'c1::boundary': { fillColor: '#ff00ff' } },
    });
    render(<LegendPanel />);
    expect(swatch('layer.forestBoundary').style.background).toContain('rgb(255, 0, 255)');
  });

  it('a palette layer ignores a custom colour unless __flat is set', () => {
    setStore({
      calculationId: 'c1',
      layerVisibility: { blocks: true },
      customLayerStyles: { 'c1::blocks': { fillColor: '#ff0000' } },
    });
    render(<LegendPanel />);
    // no __flat → default block colour, not red
    expect(swatch('layer.blocks').style.background).not.toContain('rgb(255, 0, 0)');
  });

  it('a palette layer with __flat shows the flat colour', () => {
    setStore({
      calculationId: 'c1',
      layerVisibility: { blocks: true },
      customLayerStyles: { 'c1::blocks': { __flat: true, fillColor: '#00ff00' } },
    });
    render(<LegendPanel />);
    expect(swatch('layer.blocks').style.background).toContain('rgb(0, 255, 0)');
  });
});

describe('LegendPanel — thematic renderer (WORKSPACE_LAYER_STYLING_PLAN.md P4.4)', () => {
  it('a categorized renderer replaces the single swatch with one row per class', () => {
    setStore({
      calculationId: 'c1',
      layerVisibility: { blocks: true },
      layerRenderers: {
        blocks: {
          mode: 'categorized',
          field: 'working_circle',
          classes: [
            { value: 'production', color: '#111111', label: 'production' },
            { value: 'protection', color: '#222222', label: 'protection' },
          ],
        },
      },
    });
    render(<LegendPanel />);
    const block = screen.getByTestId('legend-thematic-blocks');
    expect(block).toHaveTextContent('working_circle');
    const rows = block.querySelectorAll('.legend-thematic-row');
    expect(rows).toHaveLength(2);
    expect(block).toHaveTextContent('production');
    expect(block).toHaveTextContent('protection');
  });
});

describe('LegendPanel — Activity Features symbol kinds', () => {
  it('lists one row per kind actually on the map, with its count', () => {
    setStore({
      layerVisibility: { activity_features: true },
      featureCounts: {
        activity_features: 5,
        'activity_features:kind:nursery': 3,
        'activity_features:kind:road': 2,
        'activity_features:kind:coupe': 0,
      },
    });
    render(<LegendPanel />);

    const nursery = screen.getByTestId('legend-kind-nursery');
    expect(nursery).toHaveTextContent('Nursery');
    expect(nursery).toHaveTextContent('3');
    expect(screen.getByTestId('legend-kind-road')).toHaveTextContent('2');
    expect(screen.queryByTestId('legend-kind-coupe')).toBeNull(); // none present
  });

  it('shows no kind rows when the layer is hidden or has no kinds', () => {
    setStore({ layerVisibility: { activity_features: false }, featureCounts: { 'activity_features:kind:nursery': 3 } });
    render(<LegendPanel />);
    expect(screen.queryByTestId('legend-kind-nursery')).toBeNull();
  });

  it('colours the swatch with the kind colour', () => {
    setStore({ layerVisibility: { activity_features: true }, featureCounts: { 'activity_features:kind:fire_line': 1 } });
    render(<LegendPanel />);
    const swatch = screen.getByTestId('legend-kind-fire_line').querySelector('.legend-swatch') as HTMLElement;
    expect(swatch.style.background).toMatch(/#c62828|rgb\(198, 40, 40\)/i);
  });
});
