import { describe, it, expect, beforeEach } from 'vitest';
import { useWorkspaceStore } from '../workspaceStore';

const vis = () => useWorkspaceStore.getState().layerVisibility;

describe('choosing an analysis map makes the layers that carry its colours visible', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({
      activeAnalysisMap: null,
      layerVisibility: { ...useWorkspaceStore.getState().layerVisibility, blocks: true, compartments: true, sub_blocks: true, sub_compartments: true },
    });
  });

  it('switches the Sub-Compartments and Sub-Blocks layers on when they were hidden: the colours are on the undivided units', () => {
    useWorkspaceStore.setState({ layerVisibility: { ...vis(), sub_blocks: false, sub_compartments: false } });
    useWorkspaceStore.getState().setActiveAnalysisMap('sfm_type');
    expect(vis().sub_compartments).toBe(true);
    expect(vis().sub_blocks).toBe(true);
  });

  it('does the same for a field-inventory map', () => {
    useWorkspaceStore.setState({ layerVisibility: { ...vis(), sub_compartments: false } });
    useWorkspaceStore.getState().setActiveAnalysisMap('fi_growing_stock');
    expect(vis().sub_compartments).toBe(true);
  });

  it('still turns the top-level layers on when both were hidden, and leaves a visible layer alone', () => {
    useWorkspaceStore.setState({ layerVisibility: { ...vis(), blocks: false, compartments: false } });
    useWorkspaceStore.getState().setActiveAnalysisMap('sfm_stock');
    expect(vis().blocks).toBe(true);
    expect(vis().compartments).toBe(true);
    expect(vis().sub_compartments).toBe(true); // unchanged
  });

  it('does not touch the layers for a hazard map or when the map is switched off', () => {
    useWorkspaceStore.setState({ layerVisibility: { ...vis(), sub_compartments: false } });
    useWorkspaceStore.getState().setActiveAnalysisMap('hazard_soil');
    expect(vis().sub_compartments).toBe(false);
    useWorkspaceStore.getState().setActiveAnalysisMap(null);
    expect(vis().sub_compartments).toBe(false);
  });
});
