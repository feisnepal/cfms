import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const get = vi.fn();
vi.mock('../../services/api', async (orig) => ({ ...(await orig<typeof import('../../services/api')>()), default: { get: (...a: unknown[]) => get(...a) } }));

import { AnalysisMapsGroup } from '../AnalysisMapsGroup';
import { AnalysisLegendSection } from '../AnalysisLegendSection';
import { useWorkspaceStore } from '../../store/workspaceStore';

const info = (type_no: number) => ({
  type_no, state: 'classified', land_class: 'forest', plot_count: 6, proposed_type_no: type_no, overridden: false,
  orientation: 'Production', gs_ge40_m3_per_ha: 100, slope_band: null, confidence: null, needs_review: false, reasons_ne: null, reasons_en: null,
}) as never;
const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter>{ui}</MemoryRouter>
  </QueryClientProvider>
);

describe('isolate a class from the legend', () => {
  beforeEach(() => {
    get.mockReset();
    useWorkspaceStore.setState({ activeAnalysisMap: null, layerRenderers: {}, sfmBlockTypes: {}, analysisHighlight: null, activeChart: null });
  });

  it('the store toggles one class (lower-cased) and a click on it again clears it', () => {
    const s = useWorkspaceStore.getState();
    s.toggleAnalysisHighlight('#74C476');
    expect(useWorkspaceStore.getState().analysisHighlight).toBe('#74c476');
    useWorkspaceStore.getState().toggleAnalysisHighlight('#74c476');
    expect(useWorkspaceStore.getState().analysisHighlight).toBeNull();
    useWorkspaceStore.getState().toggleAnalysisHighlight('#aaaaaa');
    useWorkspaceStore.getState().toggleAnalysisHighlight('#bbbbbb'); // another class replaces it
    expect(useWorkspaceStore.getState().analysisHighlight).toBe('#bbbbbb');
  });

  it('choosing another analysis map (or none) forgets the isolated class', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', analysisHighlight: '#74c476' });
    useWorkspaceStore.getState().setActiveAnalysisMap('sfm_orientation');
    expect(useWorkspaceStore.getState().analysisHighlight).toBeNull();
    useWorkspaceStore.setState({ analysisHighlight: '#74c476' });
    useWorkspaceStore.getState().setActiveAnalysisMap(null);
    expect(useWorkspaceStore.getState().analysisHighlight).toBeNull();
  });

  it('the SFM legend name is a button: click isolates the class, pressed state shows, click again shows all', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(7), B: info(3) } });
    render(wrap(<AnalysisMapsGroup calculationId="c1" />));
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    const btn = screen.getByRole('button', { name: 'Type-7' });
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    expect(useWorkspaceStore.getState().analysisHighlight).toMatch(/^#[0-9a-f]{6}$/);
    fireEvent.click(btn);
    expect(useWorkspaceStore.getState().analysisHighlight).toBeNull();
  });

  it('a click on the colour swatch changes the colour — it does not isolate (two different controls)', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(7) } });
    render(wrap(<AnalysisMapsGroup calculationId="c1" />));
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    fireEvent.change(screen.getByLabelText('Change colour: Type-7'), { target: { value: '#123456' } });
    expect(useWorkspaceStore.getState().analysisHighlight).toBeNull();
  });

  it('the Legend panel rows of a unit-class map are pickable too (keyboard included)', async () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(7), B: info(3) } });
    render(wrap(<AnalysisLegendSection />));
    const row = screen.getByTestId('legend-analysis-map').querySelectorAll('.legend-item')[1] as HTMLElement;
    expect(row.getAttribute('role')).toBe('button');
    fireEvent.click(row);
    expect(row.getAttribute('aria-pressed')).toBe('true');
    fireEvent.keyDown(row, { key: 'Enter' });
    await waitFor(() => expect(useWorkspaceStore.getState().analysisHighlight).toBeNull());
  });

  it('hazard legend rows (tiles, no per-unit class) are not pickable', async () => {
    get.mockResolvedValue({
      data: { state: 'ready', key: 'soil', relative: false, params_hash: 'h', cell_m: 30, total_ha: 1,
        classes: [{ index: 0, color: '#fee5d9', label_ne: 'क', label_en: 'Slight', from: 0, to: 5, area_ha: 1, share_pct: 100 }] },
    });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_soil', calculationId: 'c1' });
    render(wrap(<AnalysisLegendSection />));
    await waitFor(() => expect(screen.getByTestId('legend-analysis-map').querySelectorAll('.legend-item').length).toBeGreaterThan(0));
    expect(screen.getByTestId('legend-analysis-map').querySelector('[role="button"]')).toBeNull();
  });
});
