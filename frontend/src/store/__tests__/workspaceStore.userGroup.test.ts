import { describe, it, expect, beforeEach } from 'vitest';
import { useWorkspaceStore } from '../workspaceStore';

describe('workspaceStore — user-group slice (BG-2/BG-4)', () => {
  beforeEach(() => {
    useWorkspaceStore.setState({ userGroupPoiVisible: {}, activeRasterLayers: [] });
  });

  it('toggleUserGroupPoi flips each POI category independently', () => {
    useWorkspaceStore.getState().toggleUserGroupPoi('health');
    expect(useWorkspaceStore.getState().userGroupPoiVisible).toEqual({ health: true });
    useWorkspaceStore.getState().toggleUserGroupPoi('health');
    expect(useWorkspaceStore.getState().userGroupPoiVisible).toEqual({ health: false });
    expect(Object.keys(useWorkspaceStore.getState().userGroupPoiVisible)).toEqual(['health']);
  });

  it('clearUserGroupPoi empties the POI slice (delete flow)', () => {
    useWorkspaceStore.getState().toggleUserGroupPoi('education');
    useWorkspaceStore.getState().toggleUserGroupPoi('rivers');
    useWorkspaceStore.getState().clearUserGroupPoi();
    expect(useWorkspaceStore.getState().userGroupPoiVisible).toEqual({});
  });

  it('toggleRasterLayer handles the user-group overlay ids like any raster', () => {
    useWorkspaceStore.getState().toggleRasterLayer('ug_landcover');
    expect(useWorkspaceStore.getState().activeRasterLayers).toContain('ug_landcover');
    useWorkspaceStore.getState().toggleRasterLayer('ug_landcover');
    expect(useWorkspaceStore.getState().activeRasterLayers).not.toContain('ug_landcover');
  });

  it('setCalculationId resets the POI slice and user-group rasters (BG-4 deleted path)', () => {
    useWorkspaceStore.setState({
      calculationId: 'calc-old',
      userGroupPoiVisible: { education: true, health: true },
      activeRasterLayers: ['ug_landcover', 'ug_biomass'],
    });
    useWorkspaceStore.getState().setCalculationId('calc-new');
    expect(useWorkspaceStore.getState().userGroupPoiVisible).toEqual({});
    expect(useWorkspaceStore.getState().activeRasterLayers).toEqual([]);
    expect(useWorkspaceStore.getState().calculationId).toBe('calc-new');
  });
})