import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const container = document.createElement('div');
vi.mock('react-leaflet', async (orig) => ({ ...(await orig<typeof import('react-leaflet')>()), useMap: () => ({ getContainer: () => container }) }));

import { AnalysisMapsGroup } from '../AnalysisMapsGroup';
import { UnitFactsCard } from '../map/UnitFactsCard';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { getFeatureLayerRegistry } from '../../lib/featureLayerRegistry';

const info = (gs: number, area = 10) => ({
  type_no: 7, state: 'classified', land_class: 'forest', plot_count: 6, proposed_type_no: 7, overridden: false,
  orientation: 'Production', gs_ge40_m3_per_ha: gs, area_ha: area, slope_band: 2, confidence: null, needs_review: false, reasons_ne: null, reasons_en: null,
}) as never;

const layer = (name: string, layerId: string, extra: Record<string, unknown> = {}) => ({
  feature: { properties: { name, area_hectares: 12.5, ...extra } }, __unitLayerId: layerId, on: vi.fn(),
  getBounds: () => ({ isValid: () => true, extend: (o: unknown) => o }),
}) as never;

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>
);

const reset = () => {
  if (!container.isConnected) document.body.appendChild(container); // the map container the card is drawn into
  getFeatureLayerRegistry().clear();
  useWorkspaceStore.setState({
    activeAnalysisMap: null, compareMap: null, analysisHighlight: null, layerRenderers: {}, sfmBlockTypes: {}, hazardUnits: {},
    fieldInventoryUnits: {}, unitMap: null, selection: { layerId: null, featureIds: [], mode: 'replace' }, inspectedUnit: null,
  });
};

describe('UnitFactsCard — click a unit, see everything about it', () => {
  beforeEach(reset);

  it('shows the sections the unit has data for, from the same stores as the colours and the table', () => {
    getFeatureLayerRegistry().register('u1', layer('blocks-3', 'blocks'));
    useWorkspaceStore.setState({
      sfmBlockTypes: { 'blocks-3': info(80) },
      hazardUnits: { 'blocks-3': { soil: { mean: 48, severe_pct: 59, area_ha: 12 } } } as never,
      fieldInventoryUnits: { 'blocks-3': { fi_stock: 80.1, fi_condition: 'Weak' } },
      selection: { layerId: 'blocks', featureIds: ['u1'], mode: 'replace' },
    });
    render(<UnitFactsCard />);
    const card = screen.getByTestId('unit-facts-card');
    expect(card.textContent).toContain('blocks-3');
    for (const s of ['unit', 'sfm', 'hazard', 'inventory']) expect(screen.getByTestId(`unit-facts-${s}`)).toBeTruthy();
    expect(screen.getByTestId('unit-facts-hazard').textContent).toContain('48 t/ha/yr');
    expect(screen.getByTestId('unit-facts-inventory').textContent).toContain('80.1 m³/ha');
    expect(screen.getByTestId('unit-facts-sfm').textContent).toContain('Type-7');
  });

  it('a unit with no analysis data shows just its own facts, never blanks', () => {
    getFeatureLayerRegistry().register('u2', layer('blocks-9', 'compartments'));
    useWorkspaceStore.setState({ selection: { layerId: 'compartments', featureIds: ['u2'], mode: 'replace' } });
    render(<UnitFactsCard />);
    expect(screen.getByTestId('unit-facts-unit')).toBeTruthy();
    expect(screen.queryByTestId('unit-facts-sfm')).toBeNull();
    expect(screen.queryByTestId('unit-facts-hazard')).toBeNull();
    expect(screen.queryByTestId('unit-facts-inventory')).toBeNull();
  });

  it('is absent for no selection, several units, or a layer that is not a unit layer', () => {
    getFeatureLayerRegistry().register('u1', layer('A', 'blocks'));
    getFeatureLayerRegistry().register('u2', layer('B', 'blocks'));
    getFeatureLayerRegistry().register('p1', layer('plot-1', 'sample_plots'));
    const { rerender } = render(<UnitFactsCard />);
    expect(screen.queryByTestId('unit-facts-card')).toBeNull();
    useWorkspaceStore.setState({ selection: { layerId: 'blocks', featureIds: ['u1', 'u2'], mode: 'replace' } });
    rerender(<UnitFactsCard />);
    expect(screen.queryByTestId('unit-facts-card')).toBeNull();
    useWorkspaceStore.setState({ selection: { layerId: 'sample_plots', featureIds: ['p1'], mode: 'replace' } });
    rerender(<UnitFactsCard />);
    expect(screen.queryByTestId('unit-facts-card')).toBeNull();
  });

  it('a clicked unit opens the card with NO selection (selection needs the layer armed; looking is not editing)', () => {
    getFeatureLayerRegistry().register('u1', layer('blocks-3', 'blocks'));
    useWorkspaceStore.setState({ inspectedUnit: { layerId: 'blocks', id: 'u1' }, selection: { layerId: null, featureIds: [], mode: 'replace' } });
    render(<UnitFactsCard />);
    expect(screen.getByTestId('unit-facts-card').textContent).toContain('blocks-3');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(useWorkspaceStore.getState().inspectedUnit).toBeNull();
  });

  it('the inspected unit is forgotten when the selection changes or is cleared elsewhere', () => {
    useWorkspaceStore.setState({ inspectedUnit: { layerId: 'blocks', id: 'u1' } });
    useWorkspaceStore.getState().selectFeatures('blocks', ['u2']);
    expect(useWorkspaceStore.getState().inspectedUnit).toBeNull();
    useWorkspaceStore.setState({ inspectedUnit: { layerId: 'blocks', id: 'u1' } });
    useWorkspaceStore.getState().clearSelection();
    expect(useWorkspaceStore.getState().inspectedUnit).toBeNull();
  });

  it('a unit-layer id only: an inspected feature of another layer opens nothing', () => {
    getFeatureLayerRegistry().register('p1', layer('plot-1', 'sample_plots'));
    useWorkspaceStore.setState({ inspectedUnit: { layerId: 'sample_plots', id: 'p1' } });
    render(<UnitFactsCard />);
    expect(screen.queryByTestId('unit-facts-card')).toBeNull();
  });

  it('the close button clears the selection', () => {
    getFeatureLayerRegistry().register('u1', layer('A', 'blocks'));
    useWorkspaceStore.setState({ selection: { layerId: 'blocks', featureIds: ['u1'], mode: 'replace' } });
    render(<UnitFactsCard />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(useWorkspaceStore.getState().selection.featureIds).toEqual([]);
  });

  it('a unit name is rendered as text, never as markup', () => {
    getFeatureLayerRegistry().register('u1', layer('<img src=x onerror=alert(1)>', 'blocks'));
    useWorkspaceStore.setState({ selection: { layerId: 'blocks', featureIds: ['u1'], mode: 'replace' } });
    render(<UnitFactsCard />);
    expect(screen.getByTestId('unit-facts-card').querySelector('img')).toBeNull();
    expect(screen.getByTestId('unit-facts-card').textContent).toContain('<img src=x onerror=alert(1)>');
  });
});

describe('Analysis maps group — ranking, class actions, compare, class area', () => {
  beforeEach(reset);
  const mount = (map: unknown = null) => render(wrap(<AnalysisMapsGroup calculationId="c1" map={map as never} />));
  const open = () => fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));

  it('the stock map lists the units highest first; a click zooms to the unit and selects it', () => {
    getFeatureLayerRegistry().register('u1', layer('A', 'blocks'));
    getFeatureLayerRegistry().register('u2', layer('B', 'blocks'));
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_stock', sfmBlockTypes: { A: info(50), B: info(150) } });
    const map = { fitBounds: vi.fn() };
    mount(map);
    open();
    const rank = screen.getByTestId('analysis-ranking');
    expect(Array.from(rank.querySelectorAll('li')).map((li) => li.textContent)).toEqual(['B150 m³/ha', 'A50 m³/ha']);
    fireEvent.click(screen.getByRole('button', { name: 'B' }));
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(useWorkspaceStore.getState().selection).toMatchObject({ layerId: 'blocks', featureIds: ['u2'] });
  });

  it('a class map (forest type) has no ranking', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(50) } });
    mount();
    open();
    expect(screen.queryByTestId('analysis-ranking')).toBeNull();
  });

  it('the SFM legend shows each class’s units and hectares', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(50, 10), B: info(60, 5.5) } });
    mount();
    open();
    expect(screen.getByTestId('analysis-legend').textContent).toContain('2 · 15.5 ha');
  });

  it('an isolated class offers "Select in table" and "Zoom to" for exactly its units', () => {
    getFeatureLayerRegistry().register('u1', layer('A', 'blocks'));
    getFeatureLayerRegistry().register('u2', layer('B', 'blocks'));
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(50), B: { ...(info(60) as object), type_no: 3 } as never } });
    const map = { fitBounds: vi.fn() };
    mount(map);
    open();
    expect(screen.queryByTestId('analysis-class-actions')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Type-7' }));
    expect(screen.getByTestId('analysis-class-actions').textContent).toContain('1 units in this class');
    fireEvent.click(screen.getByRole('button', { name: 'Select in table' }));
    expect(useWorkspaceStore.getState().selection).toMatchObject({ layerId: 'blocks', featureIds: ['u1'] });
    fireEvent.click(screen.getByRole('button', { name: 'Zoom to' }));
    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });

  it('"Compare with" lists the other maps, never the active one, and sets the second map', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_stock', sfmBlockTypes: { A: info(50) } });
    mount();
    open();
    const sel = screen.getByLabelText('Compare with') as HTMLSelectElement;
    const values = Array.from(sel.options).map((o) => o.value);
    expect(values).not.toContain('sfm_stock');
    expect(values).toContain('hazard_soil');
    expect(values).toContain('fi_growing_stock');
    expect(values).not.toContain('hazard_hh');
    fireEvent.change(sel, { target: { value: 'hazard_soil' } });
    expect(useWorkspaceStore.getState().compareMap).toBe('hazard_soil');
    fireEvent.change(sel, { target: { value: '' } });
    expect(useWorkspaceStore.getState().compareMap).toBeNull();
  });

  it('no active map: nothing to compare with', () => {
    mount();
    open();
    expect(screen.queryByTestId('analysis-compare')).toBeNull();
  });
});
