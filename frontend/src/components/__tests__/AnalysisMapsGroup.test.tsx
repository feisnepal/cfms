import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { AnalysisMapsGroup, withColour } from '../AnalysisMapsGroup';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { defaultAnalysisRenderer, analysisRendererKey } from '../../lib/analysisMaps';
import type { CategorizedRenderer } from '../../lib/layerRenderers';

const mount = () => render(<MemoryRouter><AnalysisMapsGroup calculationId="c1" /></MemoryRouter>);
const blockInfo = (type_no: number | null, orientation: string | null = 'Production', gs: number | null = 120) => ({
  type_no, state: 'classified', land_class: 'forest', plot_count: 6, proposed_type_no: type_no, overridden: false,
  orientation, gs_ge40_m3_per_ha: gs, slope_band: null, confidence: null, needs_review: false, reasons_ne: null, reasons_en: null,
}) as never;
const header = () => screen.getByRole('button', { name: /Analysis maps/ });

describe('AnalysisMapsGroup', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ activeAnalysisMap: null, layerRenderers: {}, sfmBlockTypes: {} });
  });

  it('is collapsed by default and names the active map in its header', () => {
    mount();
    expect(screen.queryByRole('radiogroup')).toBeNull();
    act(() => useWorkspaceStore.getState().setActiveAnalysisMap('sfm_type'));
    expect(header().textContent).toContain('Forest type');
  });

  it('expands to Off + the SFM maps + soil loss as one radio group', () => {
    mount();
    fireEvent.click(header());
    expect(screen.getAllByRole('radio')).toHaveLength(10);
    fireEvent.click(screen.getByLabelText('Orientation'));
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('sfm_orientation');
    fireEvent.click(screen.getByLabelText('Off'));
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBeNull();
  });

  it('says so when the SFM tab has not been computed', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type' });
    mount();
    fireEvent.click(header());
    expect(screen.getByRole('status').textContent).toMatch(/Not computed yet/);
  });

  it('changing a swatch saves a custom renderer; "Default colours" removes it', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { B1: blockInfo(1), B2: blockInfo(1) } });
    mount();
    fireEvent.click(header());
    expect((screen.getByTestId('analysis-default-colours') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getAllByLabelText(/Change colour: Type-1$/)[0], { target: { value: '#123456' } });
    const saved = useWorkspaceStore.getState().layerRenderers[analysisRendererKey('sfm_type')] as CategorizedRenderer;
    expect(saved.classes.find((c) => c.value === '1')?.color).toBe('#123456');
    fireEvent.click(screen.getByTestId('analysis-default-colours'));
    expect(useWorkspaceStore.getState().layerRenderers[analysisRendererKey('sfm_type')]).toBeUndefined();
  });

  it('the legend is dynamic: only the types this forest has, each with its unit count', () => {
    useWorkspaceStore.setState({
      activeAnalysisMap: 'sfm_type',
      sfmBlockTypes: { A: blockInfo(7), B: blockInfo(7), C: blockInfo(11), D: blockInfo(null, null, null) },
    });
    mount();
    fireEvent.click(header());
    const rows = screen.getByTestId('analysis-legend').querySelectorAll('li');
    expect(Array.from(rows).map((r) => r.textContent)).toEqual(['Type-72', 'Type-111', 'No type (non-forest / no plots)1']);
  });

  it('stock legend lists only the buckets that have units', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_stock', sfmBlockTypes: { A: blockInfo(7, 'Production', 100), B: blockInfo(7, 'Production', 260) } });
    mount();
    fireEvent.click(header());
    expect(screen.getByTestId('analysis-legend').querySelectorAll('li')).toHaveLength(2);
  });

  it('withColour edits the "other" row without touching the classes', () => {
    const spec = defaultAnalysisRenderer('sfm_orientation') as CategorizedRenderer;
    const out = withColour(spec, spec.classes.length, '#000000') as CategorizedRenderer;
    expect(out.otherColor).toBe('#000000');
    expect(out.classes).toEqual(spec.classes);
  });
});
