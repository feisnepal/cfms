import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useLayerRenderers } from '../useLayerRenderers';
import { useWorkspaceStore } from '../../store/workspaceStore';
import { DBH_CLASS_RENDERER } from '../../lib/dbhClassSymbols';
import { PRIME_SPECIES_RENDERER } from '../../lib/primeSpecies';

const getCalculation = vi.fn();
const updateResultData = vi.fn();
vi.mock('../../services/api', () => ({
  forestApi: {
    getCalculation: (...a: unknown[]) => getCalculation(...a),
    updateResultData: (...a: unknown[]) => updateResultData(...a),
  },
}));

describe('useLayerRenderers — Stem Mapping default seed', () => {
  beforeEach(() => {
    getCalculation.mockReset();
    updateResultData.mockReset().mockResolvedValue({});
    useWorkspaceStore.setState({ layerRenderers: {} });
  });

  it('seeds the prime-species renderer for a forest that never configured stem_mapping', async () => {
    getCalculation.mockResolvedValue({ result_data: { layer_renderers: {} } });
    renderHook(() => useLayerRenderers('calc-1'));
    await waitFor(() => {
      expect(useWorkspaceStore.getState().layerRenderers.stem_mapping).toEqual(PRIME_SPECIES_RENDERER);
    });
  });

  it('leaves an already-configured stem_mapping renderer alone', async () => {
    const custom = { mode: 'categorized' as const, field: 'species', classes: [], otherColor: '#000' };
    getCalculation.mockResolvedValue({ result_data: { layer_renderers: { stem_mapping: custom } } });
    renderHook(() => useLayerRenderers('calc-2'));
    await waitFor(() => {
      expect(useWorkspaceStore.getState().layerRenderers.stem_mapping).toEqual(custom);
    });
  });

  it('refreshes a stem_mapping renderer that still matches an old shipped default exactly (stale auto-seed)', async () => {
    const staleAutoSeed = {
      mode: 'graduated' as const,
      field: 'dbh_cm',
      method: 'equal' as const,
      breaks: [10, 20, 30, 40, 50, 60, 70],
      colors: ['#8B0000', '#E57373', '#CC9900', '#FFE066', '#00008B', '#64B5F6', '#81C784', '#1B5E20'],
      ramp: 'custom',
    };
    getCalculation.mockResolvedValue({ result_data: { layer_renderers: { stem_mapping: staleAutoSeed } } });
    renderHook(() => useLayerRenderers('calc-4'));
    await waitFor(() => {
      expect(useWorkspaceStore.getState().layerRenderers.stem_mapping).toEqual(PRIME_SPECIES_RENDERER);
    });
  });

  it('upgrades the previous (traffic-light DBH) default to colour-by-species, but not a customised one', async () => {
    getCalculation.mockResolvedValue({ result_data: { layer_renderers: { stem_mapping: DBH_CLASS_RENDERER } } });
    renderHook(() => useLayerRenderers('calc-5'));
    await waitFor(() => {
      expect(useWorkspaceStore.getState().layerRenderers.stem_mapping).toEqual(PRIME_SPECIES_RENDERER);
    });

    useWorkspaceStore.setState({ layerRenderers: {} });
    const tweaked = { ...DBH_CLASS_RENDERER, colors: [...DBH_CLASS_RENDERER.colors.slice(0, 7), '#000000'] };
    getCalculation.mockResolvedValue({ result_data: { layer_renderers: { stem_mapping: tweaked } } });
    renderHook(() => useLayerRenderers('calc-6'));
    await waitFor(() => {
      expect(useWorkspaceStore.getState().layerRenderers.stem_mapping).toEqual(tweaked);
    });
  });

  it('does not touch other layers already configured', async () => {
    getCalculation.mockResolvedValue({
      result_data: { layer_renderers: { blocks: DBH_CLASS_RENDERER } },
    });
    renderHook(() => useLayerRenderers('calc-3'));
    await waitFor(() => {
      const r = useWorkspaceStore.getState().layerRenderers;
      expect(r.blocks).toEqual(DBH_CLASS_RENDERER);
      expect(r.stem_mapping).toEqual(PRIME_SPECIES_RENDERER);
    });
  });
});
