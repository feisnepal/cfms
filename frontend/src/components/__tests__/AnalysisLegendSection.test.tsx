import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AnalysisLegendSection } from '../AnalysisLegendSection';
import { useWorkspaceStore } from '../../store/workspaceStore';

const info = (type_no: number | null) => ({
  type_no, state: 'classified', land_class: 'forest', plot_count: 5, proposed_type_no: type_no, overridden: false,
  orientation: 'Production', gs_ge40_m3_per_ha: 100, slope_band: null, confidence: null, needs_review: false, reasons_ne: null, reasons_en: null,
}) as never;

describe('AnalysisLegendSection (in the Legend panel)', () => {
  beforeEach(() => useWorkspaceStore.setState({ activeAnalysisMap: null, layerRenderers: {}, sfmBlockTypes: {} }));

  it('renders nothing while no analysis map is on', () => {
    const { container } = render(<AnalysisLegendSection />);
    expect(container.firstChild).toBeNull();
  });

  it('lists only the SFM classes this forest has, with unit counts', () => {
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', sfmBlockTypes: { A: info(7), B: info(7), C: info(3) } });
    render(<AnalysisLegendSection />);
    const section = screen.getByTestId('legend-analysis-map');
    const rows = Array.from(section.querySelectorAll('.legend-item')).map((r) => r.textContent);
    expect(rows).toEqual(['Type-31', 'Type-72']); // class order, label then count
  });
});
