import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LayerStyleDialog from '../LayerStyleDialog';
import { useWorkspaceStore } from '../../store/workspaceStore';

vi.mock('../../i18n/hooks', () => ({ useT: () => (k: string) => k }));

const POS = { x: 100, y: 100 };

// Partial setState so the store keeps its REAL actions (createInitialState()
// returns stubs — spreading it would make setCustomLayerStyle a no-op).
function setStore(over: Record<string, unknown> = {}) {
  useWorkspaceStore.setState({ calculationId: 'c1', customLayerStyles: {}, importedLayers: [], ...over } as never);
}

describe('LayerStyleDialog — live preview + override palette (P1)', () => {
  beforeEach(() => setStore());

  it('writes a live preview to the store as a slider moves, keyed per calculation', async () => {
    render(<LayerStyleDialog visible layerId="boundary" layerType="builtin" position={POS} onClose={() => {}} />);
    const sliders = screen.getAllByRole('slider');
    // stroke width is the first slider; nudge it
    await userEvent.click(sliders[0]);
    sliders[0].focus();
    await userEvent.keyboard('{ArrowRight}');
    await vi.waitFor(() => {
      expect(useWorkspaceStore.getState().customLayerStyles['c1::boundary']).toBeTruthy();
    });
  });

  it('Cancel restores the style that was present on open (here: none → removed)', async () => {
    render(<LayerStyleDialog visible layerId="boundary" layerType="builtin" position={POS} onClose={vi.fn()} />);
    const sliders = screen.getAllByRole('slider');
    sliders[1].focus(); // fill opacity
    await userEvent.keyboard('{ArrowRight}');
    await vi.waitFor(() => expect(useWorkspaceStore.getState().customLayerStyles['c1::boundary']).toBeTruthy());
    await userEvent.click(screen.getByText('common.cancel'));
    expect(useWorkspaceStore.getState().customLayerStyles['c1::boundary']).toBeUndefined();
  });

  it('a palette layer hides the colour swatches until "override palette" is ticked', async () => {
    render(<LayerStyleDialog visible layerId="blocks" layerType="builtin" position={POS} onClose={() => {}} />);
    expect(screen.queryByText('layerPanel.styleFillColor')).toBeNull();
    await userEvent.click(screen.getByText('layerPanel.styleOverridePalette'));
    expect(screen.getByText('layerPanel.styleFillColor')).toBeInTheDocument();
  });

  it('a non-palette layer (boundary) shows the colour swatches and no override checkbox', () => {
    render(<LayerStyleDialog visible layerId="boundary" layerType="builtin" position={POS} onClose={() => {}} />);
    expect(screen.getByText('layerPanel.styleFillColor')).toBeInTheDocument();
    expect(screen.queryByText('layerPanel.styleOverridePalette')).toBeNull();
  });
});

describe('LayerStyleDialog — thematic symbology (WORKSPACE_LAYER_STYLING_PLAN.md P4.3)', () => {
  beforeEach(() => setStore({
    layerRenderers: {},
    importedLayers: [{ id: 7, name: 'plots', geometryTypes: ['Polygon'] }],
    importedLayerFeatures: {
      7: [
        { type: 'Feature', geometry: null, properties: { zone: 'a', area: 3 } },
        { type: 'Feature', geometry: null, properties: { zone: 'b', area: 8 } },
        { type: 'Feature', geometry: null, properties: { zone: 'a', area: 5 } },
      ],
    },
  }));

  it('single mode shows the colour/opacity controls, not a field picker', () => {
    render(<LayerStyleDialog visible layerId="imported-7" layerType="imported" position={POS} onClose={() => {}} />);
    expect(screen.queryByText('layerPanel.symbologyField')).toBeNull();
    expect(screen.getByText('layerPanel.styleFillColor')).toBeInTheDocument();
  });

  it('Categorized → pick field → Classify writes a categorized spec (one class per distinct value)', async () => {
    render(<LayerStyleDialog visible layerId="imported-7" layerType="imported" position={POS} onClose={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyMode'), 'categorized');
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyField'), 'zone');
    await userEvent.click(screen.getByText('layerPanel.symbologyClassify'));

    const spec = useWorkspaceStore.getState().layerRenderers['imported-7'] as { mode: string; field: string; classes: unknown[] };
    expect(spec.mode).toBe('categorized');
    expect(spec.field).toBe('zone');
    expect(spec.classes).toHaveLength(2);
  });

  it('Graduated → the field picker is limited to numeric fields', async () => {
    render(<LayerStyleDialog visible layerId="imported-7" layerType="imported" position={POS} onClose={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyMode'), 'graduated');
    const opts = Array.from(screen.getByLabelText('layerPanel.symbologyField').querySelectorAll('option')).map((o) => o.value);
    expect(opts).toContain('area');
    expect(opts).not.toContain('zone');
  });

  it('P4.5 — "Colour by condition" writes a categorized forest_condition renderer for blocks', async () => {
    setStore({ layerRenderers: {} });
    render(<LayerStyleDialog visible layerId="blocks" layerType="builtin" position={POS} onClose={() => {}} />);
    await userEvent.click(screen.getByText('layerPanel.symbologyByCondition'));
    const spec = useWorkspaceStore.getState().layerRenderers['blocks'] as { mode: string; field: string };
    expect(spec.mode).toBe('categorized');
    expect(spec.field).toBe('forest_condition');
  });

  it('P4.5 — the condition preset button is not shown for sub_areas', () => {
    render(<LayerStyleDialog visible layerId="sub_areas" layerType="builtin" position={POS} onClose={() => {}} />);
    expect(screen.queryByText('layerPanel.symbologyByCondition')).toBeNull();
  });

  it('Auto-Block classification presets write categorized renderers on their own field, for blocks/compartments/sub_compartments', async () => {
    for (const layerId of ['blocks', 'compartments', 'sub_compartments'] as const) {
      setStore({ layerRenderers: {} });
      const { unmount } = render(<LayerStyleDialog visible layerId={layerId} layerType="builtin" position={POS} onClose={() => {}} />);
      await userEvent.click(screen.getByText('layerPanel.symbologyBySlope'));
      let spec = useWorkspaceStore.getState().layerRenderers[layerId] as { mode: string; field: string };
      expect(spec.field).toBe('dominant_slope_band');

      await userEvent.click(screen.getByText('layerPanel.symbologyByAspect'));
      spec = useWorkspaceStore.getState().layerRenderers[layerId] as { mode: string; field: string };
      expect(spec.field).toBe('dominant_aspect');

      await userEvent.click(screen.getByText('layerPanel.symbologyByCanopy'));
      spec = useWorkspaceStore.getState().layerRenderers[layerId] as { mode: string; field: string };
      expect(spec.field).toBe('dominant_canopy_class');
      unmount();
    }
  });

  it('the Auto-Block classification presets are not shown for sub_areas', () => {
    render(<LayerStyleDialog visible layerId="sub_areas" layerType="builtin" position={POS} onClose={() => {}} />);
    expect(screen.queryByText('layerPanel.symbologyBySlope')).toBeNull();
    expect(screen.queryByText('layerPanel.symbologyByAspect')).toBeNull();
    expect(screen.queryByText('layerPanel.symbologyByCanopy')).toBeNull();
  });

  it('P5.4 — the dialog is aria-modal and takes focus on open', () => {
    render(<LayerStyleDialog visible layerId="boundary" layerType="builtin" position={POS} onClose={() => {}} />);
    const dlg = screen.getByRole('dialog');
    expect(dlg).toHaveAttribute('aria-modal', 'true');
    expect(dlg.contains(document.activeElement)).toBe(true);
  });
});

describe('LayerStyleDialog — raster/Auto-Block layers (owner report 2026-10-02)', () => {
  const RASTER_ID = '11111111-1111-1111-1111-111111111111';

  it('reads fields from store.rasterLayerFeatures, not the static LAYER_REGISTRY (the actual bug)', async () => {
    // Before the fix, layerType="builtin" for a raster UUID made the
    // feature-loading effect call getLayerConfig(UUID), which is always
    // undefined for a raster layer — features stayed [] forever and the
    // field dropdown was permanently empty. layerType="raster" must read
    // the already-loaded store slice instead.
    setStore({
      layerRenderers: {},
      rasterLayerFeatures: {
        [RASTER_ID]: [
          { type: 'Feature', geometry: null, properties: { dominant_slope_band: 1, _source: 'slope' } },
          { type: 'Feature', geometry: null, properties: { dominant_slope_band: 3, _source: 'slope' } },
        ],
      },
      fetchRasterLayerFeatures: vi.fn().mockResolvedValue(undefined),
    });
    render(<LayerStyleDialog visible layerId={RASTER_ID} layerType="raster" position={POS} onClose={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyMode'), 'categorized');
    const opts = Array.from(screen.getByLabelText('layerPanel.symbologyField').querySelectorAll('option')).map((o) => o.value);
    expect(opts).toContain('dominant_slope_band');
  });

  it('fetches features on demand if the panel has not already loaded them', async () => {
    const fetchRasterLayerFeatures = vi.fn().mockImplementation(async (_calcId: string, layerId: string) => {
      useWorkspaceStore.setState((s) => ({
        rasterLayerFeatures: {
          ...s.rasterLayerFeatures,
          [layerId]: [{ type: 'Feature', geometry: null, properties: { dominant_aspect: 4 } }] as unknown as GeoJSON.Feature[],
        },
      }));
    });
    setStore({ layerRenderers: {}, rasterLayerFeatures: {}, fetchRasterLayerFeatures });
    render(<LayerStyleDialog visible layerId={RASTER_ID} layerType="raster" position={POS} onClose={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyMode'), 'categorized');
    expect(fetchRasterLayerFeatures).toHaveBeenCalledWith('c1', RASTER_ID);
    await vi.waitFor(() => {
      const opts = Array.from(screen.getByLabelText('layerPanel.symbologyField').querySelectorAll('option')).map((o) => o.value);
      expect(opts).toContain('dominant_aspect');
    });
  });

  it('a fetch failure surfaces a visible error, not a silent empty dropdown', async () => {
    setStore({
      layerRenderers: {},
      rasterLayerFeatures: {},
      fetchRasterLayerFeatures: vi.fn().mockRejectedValue(new Error('network')),
    });
    render(<LayerStyleDialog visible layerId={RASTER_ID} layerType="raster" position={POS} onClose={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyMode'), 'categorized');
    expect(await screen.findByText('layerPanel.symbologyFieldsFailed')).toBeInTheDocument();
  });

  it('Classify writes the renderer under the bare UUID key, same as a built-in layer', async () => {
    setStore({
      layerRenderers: {},
      rasterLayerFeatures: {
        [RASTER_ID]: [
          { type: 'Feature', geometry: null, properties: { dominant_forest_type: 2 } },
          { type: 'Feature', geometry: null, properties: { dominant_forest_type: 5 } },
        ],
      },
    });
    render(<LayerStyleDialog visible layerId={RASTER_ID} layerType="raster" position={POS} onClose={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyMode'), 'categorized');
    await userEvent.selectOptions(screen.getByLabelText('layerPanel.symbologyField'), 'dominant_forest_type');
    await userEvent.click(screen.getByText('layerPanel.symbologyClassify'));
    const spec = useWorkspaceStore.getState().layerRenderers[RASTER_ID] as { mode: string; field: string };
    expect(spec.mode).toBe('categorized');
    expect(spec.field).toBe('dominant_forest_type');
  });
});
