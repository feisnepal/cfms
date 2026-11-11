import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const get = vi.fn();
vi.mock('../../services/api', async (orig) => ({ ...(await orig<typeof import('../../services/api')>()), default: { get: (...a: unknown[]) => get(...a) } }));

import { AnalysisMapsGroup } from '../AnalysisMapsGroup';
import { useWorkspaceStore } from '../../store/workspaceStore';

const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><AnalysisMapsGroup calculationId="c1" /></MemoryRouter>
    </QueryClientProvider>,
  );

describe('Analysis maps — hazard (soil loss)', () => {
  beforeEach(() => {
    get.mockReset();
    useWorkspaceStore.setState({ activeAnalysisMap: null, layerRenderers: {}, sfmBlockTypes: {}, analysisOpacity: 0.85, analysisArea: 'forest', activeChart: null });
  });

  it('lists the hazard map under its own heading and selecting it activates it', () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    fireEvent.click(screen.getByLabelText('Soil loss'));
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('hazard_soil');
  });

  it('shows only the classes this forest has, with area and share', async () => {
    get.mockResolvedValue({
      data: {
        state: 'ready', key: 'soil', relative: false, params_hash: 'h', cell_m: 30, total_ha: 100,
        classes: [
          { index: 0, color: '#fee5d9', label_ne: 'थोरै', label_en: 'Slight', from: 0, to: 5, area_ha: 40, share_pct: 40 },
          { index: 4, color: '#a50f15', label_ne: 'गम्भीर', label_en: 'Severe', from: 40, to: 80, area_ha: 60, share_pct: 60 },
        ],
      },
    });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_soil' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByTestId('analysis-legend')).toBeTruthy());
    const rows = Array.from(screen.getByTestId('analysis-legend').querySelectorAll('li')).map((r) => r.textContent);
    expect(rows).toEqual(['Slight40 ha · 40%', 'Severe60 ha · 60%']);
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/hazard-legend/soil', { params: { area: 'forest' } });
  });

  it('says so, with a link to the tab, when nothing is cached', async () => {
    get.mockResolvedValue({ data: { state: 'not_computed', key: 'soil' } });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_soil' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Not computed yet/));
    expect(screen.getByRole('button', { name: /Open in Hazard & Erosion tab/ })).toBeTruthy();
  });

  it('the opacity slider changes the stored opacity (clamped)', async () => {
    get.mockResolvedValue({ data: { state: 'ready', key: 'soil', relative: false, params_hash: 'h', cell_m: 30, total_ha: 1, classes: [] } });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_soil' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    const slider = await screen.findByRole('slider');
    fireEvent.change(slider, { target: { value: '40' } });
    expect(useWorkspaceStore.getState().analysisOpacity).toBeCloseTo(0.4);
    useWorkspaceStore.getState().setAnalysisOpacity(5);
    expect(useWorkspaceStore.getState().analysisOpacity).toBe(1);
  });

  it('offers Forest / User group, asks the server for the chosen area, and explains a missing user group', async () => {
    get.mockImplementation((_url: string, cfg: { params: { area: string } }) =>
      Promise.resolve({ data: cfg.params.area === 'user_group' ? { state: 'no_user_group', key: 'soil' } : { state: 'ready', key: 'soil', relative: false, params_hash: 'h', cell_m: 30, total_ha: 1, classes: [] } }),
    );
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_soil' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    expect((screen.getByLabelText('Forest') as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByLabelText('User group'));
    expect(useWorkspaceStore.getState().analysisArea).toBe('user_group');
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/No user group boundary/));
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/hazard-legend/soil', { params: { area: 'user_group' } });
  });

  it('a factor layer is picked from one dropdown and asks the server for that layer', async () => {
    get.mockResolvedValue({ data: { state: 'not_computed', key: 'f_soil_r' } });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    const select = screen.getByLabelText('Factor layers') as HTMLSelectElement;
    expect(select.options.length).toBe(15); // none + 14
    fireEvent.change(select, { target: { value: 'hazard_f_soil_r' } });
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('hazard_f_soil_r');
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/calculations/c1/hazard-legend/f_soil_r', { params: { area: 'forest' } }));
  });

  it('household vulnerability shows a score gradient, the counts and the basis', async () => {
    get.mockResolvedValue({
      data: { state: 'ready', kind: 'households', area: 'forest', basis: 'buildings', count: 46, n_priority: 7, min: 0.22, max: 0.38, features: [] },
    });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_hh' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByTestId('analysis-dots-legend')).toBeTruthy());
    expect(screen.getByTestId('analysis-detail-hazard_hh').textContent).toMatch(/0\.22.*0\.38/);
    expect(screen.getByTestId('analysis-detail-hazard_hh').textContent).toMatch(/46 households · 7 priority/);
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/hazard-households/households', { params: { area: 'forest' } });
  });

  it('dots say what they need when the hazard grids are not cached', async () => {
    get.mockResolvedValue({ data: { state: 'not_computed', kind: 'settlements' } });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_settle' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/Needs the soil-loss, landslide and stability maps first/));
  });

  it('a hazard legend swatch saves ONLY the changed class; "Default colours" removes it; the document note shows', async () => {
    get.mockResolvedValue({
      data: {
        state: 'ready', key: 'soil', relative: false, params_hash: 'h', cell_m: 30, total_ha: 100,
        classes: [
          { index: 0, color: '#fee5d9', label_ne: 'थोरै', label_en: 'Slight', from: 0, to: 5, area_ha: 40, share_pct: 40 },
          { index: 4, color: '#a50f15', label_ne: 'गम्भीर', label_en: 'Severe', from: 40, to: 80, area_ha: 60, share_pct: 60 },
        ],
      },
    });
    useWorkspaceStore.setState({ activeAnalysisMap: 'hazard_soil' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByTestId('analysis-legend')).toBeTruthy());
    expect((screen.getByTestId('analysis-default-colours') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Change colour: Severe'), { target: { value: '#00ff00' } });
    expect(useWorkspaceStore.getState().layerRenderers['analysis:hazard_soil']).toEqual({ mode: 'indexed', colors: { '4': '#00ff00' } });
    fireEvent.change(screen.getByLabelText('Change colour: Slight'), { target: { value: '#112233' } });
    expect(useWorkspaceStore.getState().layerRenderers['analysis:hazard_soil']).toEqual({ mode: 'indexed', colors: { '4': '#00ff00', '0': '#112233' } });
    expect(screen.getByTestId('analysis-colours-note').textContent).toMatch(/Operational Plan document/);
    fireEvent.click(screen.getByTestId('analysis-default-colours'));
    expect(useWorkspaceStore.getState().layerRenderers['analysis:hazard_soil']).toBeUndefined();
  });

  it('every map row carries a placeholder icon, and the chart is an independent overlay chosen from a dropdown', async () => {
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    for (const id of ['sfm_type', 'sfm_orientation', 'sfm_stock', 'hazard_soil', 'hazard_lsi', 'hazard_fs', 'hazard_prone', 'hazard_hh', 'hazard_settle']) {
      expect(screen.getByTestId(`placeholder-icon-${id}`), id).toBeTruthy();
    }
    // the chart picker is separate from the exclusive colouring: choosing a chart leaves the colouring alone
    useWorkspaceStore.setState({ activeAnalysisMap: 'sfm_type', activeChart: null });
    get.mockResolvedValue({ data: { state: 'not_computed', kind: 'timber-by-size' } });
    const pick = screen.getByLabelText('Chart') as HTMLSelectElement;
    expect(pick.options.length).toBe(12); // none + 11 charts
    fireEvent.change(pick, { target: { value: 'chart_timber' } });
    expect(useWorkspaceStore.getState().activeChart).toBe('chart_timber');
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('sfm_type');
    expect(screen.getByTestId('placeholder-icon-chart_timber')).toBeTruthy();
    await waitFor(() => expect(screen.getByTestId('analysis-detail-chart_timber').textContent).toMatch(/No field inventory yet/));
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/field-glyphs/timber-by-size');
    fireEvent.change(pick, { target: { value: '' } });
    expect(useWorkspaceStore.getState().activeChart).toBeNull();
  });

  it('the chart legend lists only the size classes the forest has, with editable colours that save by class index', async () => {
    get.mockResolvedValue({
      data: {
        state: 'ready', kind: 'timber-by-size', custom_colours: false, max_total: 80, units: [],
        legend: [
          { index: 4, key: '30_40', label_ne: 'सानो रुख', label_en: 'Small tree (30–40 cm)', color: '#41ab5d' },
          { index: 5, key: '40_50', label_ne: 'मझौला रुख', label_en: 'Medium tree (40–50 cm)', color: '#238b45' },
        ],
      },
    });
    useWorkspaceStore.setState({ activeChart: 'chart_timber' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByTestId('analysis-detail-chart_timber').querySelectorAll('li')).toHaveLength(2));
    fireEvent.change(screen.getByLabelText('Change colour: Medium tree (40–50 cm)'), { target: { value: '#123456' } });
    expect(useWorkspaceStore.getState().layerRenderers['analysis:chart_timber']).toEqual({ mode: 'indexed', colors: { '5': '#123456' } });
  });

  it('a field-inventory map is chosen from one dropdown; its legend shows only the classes in use and saves a changed colour by key', async () => {
    get.mockResolvedValue({
      data: {
        state: 'ready', token: 'thememap:unit__forest_condition', custom_colours: false, units: {},
        legend: [
          { key: 'Good', color: '#2e7d32', label: 'राम्रो', label_ne: 'राम्रो', label_en: 'Good', count: 2, editable: true },
          { key: 'Weak', color: '#c62828', label: 'कमजोर', label_ne: 'कमजोर', label_en: 'Weak', count: 3, editable: true },
        ],
      },
    });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    const select = screen.getByLabelText('Field inventory') as HTMLSelectElement;
    expect(select.options.length).toBe(22); // none + 21
    fireEvent.change(select, { target: { value: 'fi_condition' } });
    expect(useWorkspaceStore.getState().activeAnalysisMap).toBe('fi_condition');
    await waitFor(() => expect(screen.getByTestId('analysis-detail-fi_condition').querySelectorAll('li')).toHaveLength(2));
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/unit-maps/unit__forest_condition');
    fireEvent.change(screen.getByLabelText('Change colour: Weak'), { target: { value: '#123456' } });
    expect(useWorkspaceStore.getState().layerRenderers['analysis:fi_condition']).toEqual({ mode: 'indexed', colors: { Weak: '#123456' } });
    expect(screen.getByTestId('analysis-colours-note').textContent).toMatch(/Operational Plan document/);
  });

  it('a legend row that cannot be recoloured (the bivariate map) has no colour picker', async () => {
    get.mockResolvedValue({
      data: {
        state: 'ready', token: 'thememap:unit__condition_x_stocking', custom_colours: false, units: {},
        legend: [{ key: '0', color: '#e8e8e8', label: 'A1·B1', label_ne: 'A1·B1', label_en: 'A1·B1', count: 2, editable: false }],
      },
    });
    useWorkspaceStore.setState({ activeAnalysisMap: 'fi_condition_stocking' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByTestId('analysis-legend').querySelectorAll('li')).toHaveLength(1));
    expect(screen.getByTestId('analysis-legend').querySelector('input[type="color"]')).toBeNull();
  });

  it('each chart asks the server for its own slug; the radar legend has no colour pickers (its colours are fixed)', async () => {
    get.mockResolvedValue({
      data: {
        state: 'ready', kind: 'health-radar', shape: 'radar', editable: false, custom_colours: false, max_total: 0, units: [],
        legend: [{ index: 0, key: 'forest_condition', label_ne: 'वन अवस्था', label_en: 'Forest condition', color: '' }],
      },
    });
    useWorkspaceStore.setState({ activeChart: 'chart_health' });
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Analysis maps/ }));
    await waitFor(() => expect(screen.getByTestId('analysis-detail-chart_health').querySelectorAll('li')).toHaveLength(1));
    expect(get).toHaveBeenCalledWith('/api/calculations/c1/field-glyphs/health-radar');
    expect(screen.getByTestId('analysis-detail-chart_health').querySelector('input[type="color"]')).toBeNull();
    expect(screen.queryByTestId('analysis-default-colours')).toBeNull();
  });
});

