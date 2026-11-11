/**
 * M-9 — the item list per layer type × state.
 *
 * These tests are the reason M-1 returns data instead of JSX. The defect being
 * fixed was two renderers drifting apart; asserting the *list* is what keeps
 * them honest, because both now render from this one function.
 *
 * Two rules are asserted globally, since a violation of either is what the old
 * menus did wrong:
 *   - every disabled item carries a reason
 *   - nothing appears twice
 */
import { describe, it, expect } from 'vitest';
import { buildLayerMenu, groupLayerMenu, GROUP_ORDER, type LayerMenuContext } from '../layerMenu';

const base: LayerMenuContext = {
  layerId: 'blocks',
  kind: 'builtin',
  layerName: 'Blocks',
  visible: true,
  labelsShown: false,
  featureCount: 5,
  editable: true,
  readOnly: false,
  locked: false,
  counts: { boundary: 1, blocks: 5, compartments: 3 },
};

const ctx = (over: Partial<LayerMenuContext> = {}): LayerMenuContext => ({ ...base, ...over });
const ids = (c: LayerMenuContext) => buildLayerMenu(c).map((i) => i.id);
const byId = (c: LayerMenuContext, id: string) => buildLayerMenu(c).find((i) => i.id === id);

const ALL_LAYERS: Array<Partial<LayerMenuContext>> = [
  { layerId: 'boundary', layerName: 'Forest Boundary' },
  { layerId: 'user_group', layerName: 'User Group Boundary' },
  { layerId: 'blocks', layerName: 'Blocks' },
  { layerId: 'compartments', layerName: 'Compartments' },
  { layerId: 'sub_compartments', layerName: 'Sub-Compartments' },
  { layerId: 'sub_areas', layerName: 'Sub-Areas' },
  { layerId: 'activity_features', layerName: 'Activity Features' },
  { layerId: 'sample_plots', layerName: 'Sample Plots', readOnly: true, editable: false },
  { layerId: 'stem_mapping', layerName: 'Stem Mapping', readOnly: true, editable: false },
  { layerId: 'fieldbook', layerName: 'Field Book', readOnly: true, editable: false },
  { layerId: 'imported-1', layerName: 'My Import', kind: 'imported', purpose: 'blocks' },
];

describe('invariants that hold for every layer and state', () => {
  it.each(ALL_LAYERS)('a disabled item always says why — $layerName', (over) => {
    for (const state of [{}, { locked: true }, { featureCount: 0 }, { structureLocked: true }]) {
      for (const item of buildLayerMenu(ctx({ ...over, ...state }))) {
        if (item.disabled) {
          expect(item.disabledReasonKey, `${item.id} is disabled with no reason`).toBeTruthy();
        }
      }
    }
  });

  it.each(ALL_LAYERS)('no command appears twice — $layerName', (over) => {
    const list = ids(ctx(over));
    expect(new Set(list).size).toBe(list.length);
  });

  it.each(ALL_LAYERS)('every item lands in a known group — $layerName', (over) => {
    for (const item of buildLayerMenu(ctx(over))) {
      expect(GROUP_ORDER).toContain(item.group);
    }
  });

  it('destructive commands come last', () => {
    const list = buildLayerMenu(ctx({ layerId: 'blocks' }));
    const lastNonDanger = list.map((i) => i.group).lastIndexOf('layer');
    const firstDanger = list.findIndex((i) => i.group === 'danger');
    expect(firstDanger).toBeGreaterThan(lastNonDanger);
  });
});

describe('style submenu — copy / paste / presets (WORKSPACE_LAYER_STYLING_PLAN.md P1.4)', () => {
  it('the style item carries a copy/paste/preset submenu once the layer has features', () => {
    const item = buildLayerMenu(ctx({ layerId: 'blocks' })).find((i) => i.id === 'style')!;
    const ids = (item.submenu ?? []).map((s) => s.id);
    expect(ids).toEqual([
      'style_copy', 'style_paste',
      'style_preset:muted', 'style_preset:highContrast', 'style_preset:printOutline',
    ]);
  });

  it('Copy is disabled (with a reason) when the layer has no custom style; Paste when the clipboard is empty', () => {
    const sub = (over: Partial<LayerMenuContext>) =>
      buildLayerMenu(ctx({ layerId: 'blocks', ...over })).find((i) => i.id === 'style')!.submenu!;
    const none = sub({ hasCustomStyle: false, hasStyleClipboard: false });
    expect(none.find((s) => s.id === 'style_copy')!.disabled).toBe(true);
    expect(none.find((s) => s.id === 'style_copy')!.disabledReasonKey).toBeTruthy();
    expect(none.find((s) => s.id === 'style_paste')!.disabled).toBe(true);
    const both = sub({ hasCustomStyle: true, hasStyleClipboard: true });
    expect(both.find((s) => s.id === 'style_copy')!.disabled).toBeFalsy();
    expect(both.find((s) => s.id === 'style_paste')!.disabled).toBeFalsy();
  });

  it('an empty layer has no style submenu at all', () => {
    const item = buildLayerMenu(ctx({ layerId: 'blocks', featureCount: 0 })).find((i) => i.id === 'style')!;
    expect(item.submenu).toBeUndefined();
  });
});

describe('user_group — import + auto-buffer + analyse (USER_GROUP_BOUNDARY_PLAN.md P3)', () => {
  const ug = (over: Partial<LayerMenuContext> = {}) =>
    ctx({ layerId: 'user_group', layerName: 'User Group Boundary', featureCount: 1, ...over });

  it('offers Import, Auto-buffer and User Group Analysis (modal command)', () => {
    const list = ids(ug());
    expect(list).toContain('import');
    expect(list).toContain('user_group_auto_buffer');
    expect(list).toContain('user_group_analysis');
  });

  it('User Group Analysis is disabled (with a reason) when there is no extent yet', () => {
    const item = byId(ug({ featureCount: 0 }), 'user_group_analysis')
    expect(item?.disabled).toBe(true)
    expect(item?.disabledReasonKey).toBeTruthy()
  });

  it('offers the user group data commands, and shows what is in: household data and the executive committee are mandatory', () => {
    const none = buildLayerMenu(ug({ userGroupData: { households: false, executive: false, other: false } }));
    const status = (list: typeof none, id: string) => list.find((i) => i.id === id)?.status;
    expect(status(none, 'user_group_households')).toBe('missing');
    expect(status(none, 'user_group_executive')).toBe('missing');
    expect(status(none, 'user_group_other_committees')).toBe('optional'); // advisory / financial committees are optional
    const all = buildLayerMenu(ug({ userGroupData: { households: true, executive: true, other: true } }));
    expect(['user_group_households', 'user_group_executive', 'user_group_other_committees'].map((id) => status(all, id))).toEqual(['done', 'done', 'done']);
    // before anything is read the mandatory ones read as missing, the safe reminder
    expect(status(buildLayerMenu(ug()), 'user_group_households')).toBe('missing');
  });

  it('the data commands are on the user group layer only', () => {
    expect(ids(ctx({ layerId: 'blocks', layerName: 'Blocks', featureCount: 1 }))).not.toContain('user_group_households');
  });

  it('does not offer block-only actions', () => {
    const list = ids(ug());
    expect(list).not.toContain('auto_create');
    expect(list).not.toContain('divide_equal_area');
    expect(list).not.toContain('add_sub_area');
  });

  it('offers "digitize" directly instead of the generic "new feature" draw command', () => {
    const list = ids(ug());
    expect(list).toContain('digitize_user_group');
    expect(list).not.toContain('draw');
  });

  it('digitize is disabled (with a reason) when the layer is locked', () => {
    const item = byId(ug({ locked: true }), 'digitize_user_group');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBeTruthy();
  });
});

describe('stem_mapping — read-only view; Import opens the Tree Mapping process (SM-2)', () => {
  const sm = (over: Partial<LayerMenuContext> = {}) =>
    ctx({ layerId: 'stem_mapping', layerName: 'Stem Mapping', readOnly: true, editable: false, featureCount: 12, ...over });

  it('offers "Import Stem Mapping" — always enabled, one entry to the full Tree Mapping process', () => {
    const item = byId(sm(), 'import_stem_mapping');
    expect(item).toBeDefined();
    expect(item?.labelKey).toBe('layerPanel.importStemMapping');
    expect(item?.group).toBe('edit');
    expect(item?.disabled).toBeFalsy();
  });

  it('stays enabled in both states: no census yet (upload form) and a census already present (summary + delete)', () => {
    expect(ids(sm({ featureCount: 0 }))).toContain('import_stem_mapping');
    expect(ids(sm({ featureCount: 161 }))).toContain('import_stem_mapping');
    expect(byId(sm({ featureCount: 0 }), 'import_stem_mapping')?.disabled).toBeFalsy();
    expect(byId(sm({ featureCount: 161 }), 'import_stem_mapping')?.disabled).toBeFalsy();
  });

  it('never offers a real clear/delete/remove action of its own (no dedicated dataset)', () => {
    const list = ids(sm());
    expect(list).not.toContain('clear_data');
    expect(list).not.toContain('remove_layer');
    expect(list).not.toContain('stem_mapping_delete_info');
  });
});

describe('fieldbook — generate command (fieldbook_map_layer_plan.md P5)', () => {
  const fb = (over: Partial<LayerMenuContext> = {}) =>
    ctx({ layerId: 'fieldbook', layerName: 'Field Book', readOnly: true, editable: false, featureCount: 0, counts: { boundary: 1 }, ...over });

  it('offers "Generate Field Book" when there is a boundary and no points yet', () => {
    const item = byId(fb(), 'generate_field_book');
    expect(item).toBeDefined();
    expect(item?.disabled).toBeFalsy();
    expect(item?.labelKey).toBe('layerPanel.generateFieldbook');
  });

  it('relabels to "Regenerate" once points already exist — still enabled', () => {
    const item = byId(fb({ featureCount: 161, counts: { boundary: 1 } }), 'generate_field_book');
    expect(item?.labelKey).toBe('layerPanel.regenerateFieldbook');
    expect(item?.disabled).toBeFalsy();
  });

  it('is disabled (with a reason) when there is no forest boundary to walk', () => {
    const item = byId(fb({ counts: { boundary: 0 } }), 'generate_field_book');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.noBoundaryToGenerateFieldbook');
  });

  it('having zero points yet is NOT itself a reason to disable — that is the normal pre-generation state', () => {
    const item = byId(fb({ featureCount: 0, counts: { boundary: 1 } }), 'generate_field_book');
    expect(item?.disabled).toBeFalsy();
  });

  it('does not offer block-only or sub-area-only actions', () => {
    const list = ids(fb());
    expect(list).not.toContain('auto_create');
    expect(list).not.toContain('divide_equal_area');
    expect(list).not.toContain('add_sub_area');
    expect(list).not.toContain('draw');
  });

  it('still offers view/export/attributes — read-only does not mean invisible', () => {
    expect(ids(fb())).toEqual(expect.arrayContaining(['zoom', 'visibility', 'export', 'attributes']));
  });
});

describe('fieldbook — delete command (fieldbook_map_layer_plan.md P9)', () => {
  const fb = (over: Partial<LayerMenuContext> = {}) =>
    ctx({ layerId: 'fieldbook', layerName: 'Field Book', readOnly: true, editable: false, featureCount: 0, counts: { boundary: 1 }, ...over });

  it('offers a real "Delete Field Book" (not the disabled Stem Mapping-style pointer) once points exist', () => {
    const item = byId(fb({ featureCount: 161 }), 'delete_field_book');
    expect(item).toBeDefined();
    expect(item?.labelKey).toBe('layerPanel.deleteFieldbook');
    expect(item?.group).toBe('danger');
    expect(item?.disabled).toBeFalsy();
  });

  it('is disabled (with a reason) when there is nothing to delete yet', () => {
    const item = byId(fb({ featureCount: 0 }), 'delete_field_book');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBeTruthy();
  });

  it('never offers the generic clear_data or the Stem Mapping import command', () => {
    const list = ids(fb({ featureCount: 161 }));
    expect(list).not.toContain('clear_data');
    expect(list).not.toContain('import_stem_mapping');
  });
});

describe('C1 — a read-only layer is not offered edits it can never accept', () => {
  const samplePlots = ctx({ layerId: 'sample_plots', layerName: 'Sample Plots', readOnly: true, editable: false });

  it('omits the draw command entirely rather than greying it', () => {
    expect(ids(samplePlots)).not.toContain('draw');
  });

  it('omits lock, which would mean nothing on an always-read-only layer', () => {
    expect(ids(samplePlots)).not.toContain('lock');
  });

  it('omits import and clear-data, since it owns no purpose', () => {
    expect(ids(samplePlots)).not.toContain('import');
    expect(ids(samplePlots)).not.toContain('clear_data');
  });

  it('still offers viewing and export — being read-only does not mean invisible', () => {
    expect(ids(samplePlots)).toEqual(expect.arrayContaining(['zoom', 'visibility', 'export', 'attributes']));
  });
});

describe('C3 — one export command, and only formats that work', () => {
  const plots = ctx({
    layerId: 'sample_plots', readOnly: true, editable: false,
    exportFormats: ['csv', 'geojson', 'gpx', 'kml'],
  });

  it('Sample Plots has a single export entry, with its four formats beneath it', () => {
    expect(ids(plots).filter((id) => id === 'export')).toHaveLength(1);
    expect(byId(plots, 'export')?.submenu?.map((s) => s.labelParams?.format))
      .toEqual(['CSV', 'GEOJSON', 'GPX', 'KML']);
  });

  it('Field Book exports its own 4 real formats — no KML builder exists for it (E5)', () => {
    const fb = ctx({
      layerId: 'fieldbook', readOnly: true, editable: false,
      exportFormats: ['csv', 'excel', 'gpx', 'geojson'],
    });
    expect(ids(fb).filter((id) => id === 'export')).toHaveLength(1);
    expect(byId(fb, 'export')?.submenu?.map((s) => s.labelParams?.format))
      .toEqual(['CSV', 'EXCEL', 'GPX', 'GEOJSON']);
  });

  it('an ordinary layer offers KML and GeoPackage', () => {
    const item = byId(ctx(), 'export');
    expect(item).toBeTruthy();
    expect(item?.submenu?.map((s: any) => s.id)).toEqual(['export:kml', 'export:gpkg']);
  });

  it('a format the host cannot produce is ABSENT, not greyed', () => {
    // Greying implies "fixable"; an unimplemented format is not. The rule is
    // the same one C1 applies to Create Feature on a read-only layer.
    const list = buildLayerMenu(ctx({ exportFormats: ['kml'] }));
    const formatIds = list.flatMap((i) => (i.submenu ?? []).map((sub) => sub.id));
    expect(formatIds).not.toContain('export:geojson');
    expect(formatIds).not.toContain('export:csv');
    expect(formatIds).not.toContain('export:gpx');
    // and nothing anywhere in the menu is disabled without saying why
    for (const item of list) expect(!item.disabled || !!item.disabledReasonKey).toBe(true);
  });
});

describe('C4 — commands that used to sit in both menus now have one home', () => {
  it('Add Sub-Area appears once, on Sub-Areas only', () => {
    expect(ids(ctx({ layerId: 'sub_areas' })).filter((i) => i === 'add_sub_area')).toHaveLength(1);
    expect(ids(ctx({ layerId: 'blocks' }))).not.toContain('add_sub_area');
  });

  it('Boundary from Point File appears once, on Boundary only', () => {
    expect(ids(ctx({ layerId: 'boundary' })).filter((i) => i === 'boundary_from_point_file')).toHaveLength(1);
    expect(ids(ctx({ layerId: 'blocks' }))).not.toContain('boundary_from_point_file');
  });
});

describe('a sub-area needs a forest extent (boundary or blocks) first', () => {
  const noExtent = { layerId: 'sub_areas' as const, counts: {} };

  it('Add sub-area is disabled with a reason when there is no boundary/blocks', () => {
    const item = byId(ctx(noExtent), 'add_sub_area');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.subAreaNeedsExtent');
  });

  it('Import into Sub-Areas is disabled with the same reason', () => {
    const item = byId(ctx(noExtent), 'import');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.subAreaNeedsExtent');
  });

  it.each([
    ['a boundary', { boundary: 1 }],
    ['blocks', { blocks: 4 }],
    ['compartments', { compartments: 2 }],
  ])('is enabled once %s exists', (_label, counts) => {
    expect(byId(ctx({ layerId: 'sub_areas', counts }), 'add_sub_area')?.disabled).toBeFalsy();
    expect(byId(ctx({ layerId: 'sub_areas', counts }), 'import')?.disabled).toBeFalsy();
  });
});

describe('polygon-from-points is offered only where a polygon can be traced', () => {
  it.each(['blocks', 'compartments', 'sub_compartments', 'sub_areas'])('offered on %s', (layerId) => {
    expect(ids(ctx({ layerId }))).toContain('polygon_from_points');
  });

  it.each(['boundary', 'activity_features'])('not offered on %s', (layerId) => {
    expect(ids(ctx({ layerId }))).not.toContain('polygon_from_points');
  });
});

describe('C5 — a move that cannot happen is disabled, with a reason', () => {
  it('first row cannot move up', () => {
    const item = byId(ctx({ isFirst: true }), 'move_up');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.alreadyFirst');
  });

  it('last row cannot move down', () => {
    expect(byId(ctx({ isLast: true }), 'move_down')?.disabled).toBe(true);
  });

  it('a middle row can move either way', () => {
    expect(byId(ctx(), 'move_up')?.disabled).toBeFalsy();
    expect(byId(ctx(), 'move_down')?.disabled).toBeFalsy();
  });
});

describe('C6 — label fields only when there are fields to label by', () => {
  it('no submenu when the layer exposes none', () => {
    expect(byId(ctx({ labelFields: [] }), 'labels')?.submenu).toBeUndefined();
  });

  it('a submenu entry per field when it does', () => {
    expect(byId(ctx({ labelFields: ['name', 'area_ha'] }), 'labels')?.submenu).toHaveLength(2);
  });
});

describe('N2 — the draw command is named for what the user is making', () => {
  it('Blocks says New Block', () => {
    expect(byId(ctx({ layerId: 'blocks' }), 'draw')?.labelKey).toBe('layerPanel.newBlock');
  });

  it('Compartments says New Compartment', () => {
    expect(byId(ctx({ layerId: 'compartments' }), 'draw')?.labelKey).toBe('layerPanel.newCompartment');
  });

  it('no generic "New feature in …" on non-block/compartment layers', () => {
    for (const layerId of ['boundary', 'sub_compartments', 'sub_areas', 'activity_features'] as const) {
      expect(ids(ctx({ layerId, layerName: layerId }))).not.toContain('draw');
    }
  });
});

describe('N5 — the two destructive commands are told apart', () => {
  it('a built-in layer clears its data and is never removed', () => {
    const list = ids(ctx({ layerId: 'blocks' }));
    expect(list).toContain('clear_data');
    expect(list).not.toContain('remove_layer');
  });

  it('an imported layer is removed and never "cleared"', () => {
    const list = ids(ctx({ kind: 'imported', layerId: 'imported-1', purpose: 'blocks' }));
    expect(list).toContain('remove_layer');
    expect(list).not.toContain('clear_data');
  });

  it('both are flagged danger so a renderer can set them apart', () => {
    expect(byId(ctx({ layerId: 'blocks' }), 'clear_data')?.danger).toBe(true);
    expect(byId(ctx({ kind: 'imported', purpose: 'blocks' }), 'remove_layer')?.danger).toBe(true);
  });

  it('clearing an already-empty layer is refused with a reason', () => {
    const item = byId(ctx({ layerId: 'blocks', featureCount: 0 }), 'clear_data');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.nothingToClear');
  });
});

describe('divide equal-area carries the reason it cannot run', () => {
  it('is blocked when the structure is locked', () => {
    const item = byId(ctx({ layerId: 'compartments', structureLocked: true }), 'divide_equal_area');
    expect(item?.disabledReasonKey).toBe('workspace.divideReasonLocked');
  });

  it('is blocked on Compartments only when there is no forest boundary (a Block is no longer required)', () => {
    // No boundary → cannot divide into compartments.
    const noBoundary = byId(ctx({ layerId: 'compartments', counts: { boundary: 0, blocks: 0 } }), 'divide_equal_area');
    expect(noBoundary?.disabled).toBe(true);
    expect(noBoundary?.disabledReasonKey).toBe('workspace.divideReasonNoBoundary');

    // Boundary but zero blocks → still enabled (the mirror block is auto-made).
    const noBlocks = byId(ctx({ layerId: 'compartments', counts: { boundary: 1, blocks: 0 } }), 'divide_equal_area');
    expect(noBlocks?.disabled).toBeFalsy();
  });

  it('is blocked on Sub-Compartments when no compartments exist', () => {
    const item = byId(ctx({ layerId: 'sub_compartments', counts: { compartments: 0 } }), 'divide_equal_area');
    expect(item?.disabledReasonKey).toBe('workspace.divideReasonNoParentUnit');
    expect(item?.disabledReasonParams).toEqual({ layer: 'compartments' });
  });

  it('is blocked on Sub-Blocks when no blocks exist (FS-4a.16: same shape, block branch)', () => {
    const item = byId(ctx({ layerId: 'sub_blocks', counts: { blocks: 0 } }), 'divide_equal_area');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('workspace.divideReasonNoParentUnit');
    expect(item?.disabledReasonParams).toEqual({ layer: 'blocks' });
  });

  it('is blocked on Blocks only when there is no forest boundary (FS-4a.16: same as Compartments)', () => {
    const item = byId(ctx({ layerId: 'blocks', counts: { boundary: 0 } }), 'divide_equal_area');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('workspace.divideReasonNoBoundary');
  });

  it('is offered where it applies, and nowhere else', () => {
    expect(ids(ctx({ layerId: 'compartments' }))).toContain('divide_equal_area');
    expect(ids(ctx({ layerId: 'blocks' }))).toContain('divide_equal_area');
    expect(ids(ctx({ layerId: 'boundary' }))).not.toContain('divide_equal_area');
  });
});

describe('M-7 — commands the server would refuse are not offered as though they work', () => {
  // "Auto Create" on the Blocks/Compartments row was REMOVED (owner directive
  // 2026-10-01): it made the block-vs-compartment choice at CREATION time,
  // which is backwards from how RS-2.16 layers work (the choice happens
  // later, via a layer's own "Assign as…"). See the removal comment at
  // `layerMenu.ts`'s old `AUTO_CREATE_LAYERS` site. Nothing here to assert
  // for 'blocks'/'compartments' any more; `auto_create` is never offered.

  // BL-5 (GAP_HANDLING_PLAN.md, block lifecycle decoupling): "Import Block
  // from Forest Boundary" still exists on its own (unrelated to the removed
  // Auto Create) — enabled exactly when structural features already exist,
  // blocks layer only.
  it('import-from-boundary is refused once blocks exist, and says why', () => {
    const item = byId(ctx({ layerId: 'blocks', counts: { blocks: 4 } }), 'import_from_boundary');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.importBlockFromBoundaryBlocksExist');
  });

  it('import-from-boundary is available once blocks are cleared', () => {
    expect(byId(ctx({ layerId: 'blocks', counts: { blocks: 0, compartments: 0 } }), 'import_from_boundary')?.disabled)
      .toBeFalsy();
  });

  it('import-from-boundary mirrors on compartments, with its own reason key', () => {
    const disabled = byId(ctx({ layerId: 'compartments', counts: { compartments: 4 } }), 'import_from_boundary');
    expect(disabled?.disabled).toBe(true);
    expect(disabled?.disabledReasonKey).toBe('layerPanel.importCompartmentFromBoundaryBlocksExist');

    const enabled = byId(ctx({ layerId: 'compartments', counts: { blocks: 0, compartments: 0 } }), 'import_from_boundary');
    expect(enabled?.disabled).toBeFalsy();
    expect(enabled?.labelKey).toBe('layerPanel.importCompartmentFromBoundary');
  });

  it('import-from-boundary is not offered on sub-blocks or sub-compartments (top-level only)', () => {
    expect(ids(ctx({ layerId: 'sub_blocks', counts: { blocks: 0 } })))
      .not.toContain('import_from_boundary');
    expect(ids(ctx({ layerId: 'sub_compartments', counts: { compartments: 0 } })))
      .not.toContain('import_from_boundary');
  });

  // Rule A: assert_boundary_editable refuses to move the boundary once blocks
  // tile it, because their outer edge would desynchronise from it.
  it.each(['digitize_boundary', 'boundary_from_point_file'])(
    'boundary command %s is refused while blocks exist, and says why',
    (id) => {
      const item = byId(ctx({ layerId: 'boundary', layerName: 'Forest Boundary', counts: { blocks: 3 } }), id);
      expect(item?.disabled).toBe(true);
      expect(item?.disabledReasonKey).toBe('layerPanel.boundaryLockedByStructure');
    },
  );

  it('the same boundary commands work before any structure exists', () => {
    const empty = ctx({ layerId: 'boundary', layerName: 'Forest Boundary', counts: {} });
    for (const id of ['digitize_boundary', 'boundary_from_point_file']) {
      expect(byId(empty, id)?.disabled).toBeFalsy();
    }
  });

  it('sub-compartments count as structure too', () => {
    const item = byId(ctx({ layerId: 'boundary', counts: { sub_compartments: 2 } }), 'digitize_boundary');
    expect(item?.disabled).toBe(true);
  });

  it('viewing the boundary is never blocked by structure', () => {
    const locked = ctx({ layerId: 'boundary', counts: { blocks: 3 } });
    expect(byId(locked, 'zoom')?.disabled).toBeFalsy();
    expect(byId(locked, 'export')?.disabled).toBeFalsy();
  });
});

describe('a locked layer blocks edits but not reads', () => {
  const locked = ctx({ locked: true });

  it('every edit command says the layer is locked', () => {
    for (const id of ['draw', 'import', 'auto_create', 'import_from_boundary', 'clear_data']) {
      const item = byId(locked, id);
      if (item) expect(item.disabledReasonKey).toBe('layerPanel.lockedUnlockToEdit');
    }
  });

  it('viewing is untouched', () => {
    expect(byId(locked, 'zoom')?.disabled).toBeFalsy();
    expect(byId(locked, 'visibility')?.disabled).toBeFalsy();
  });

  it('unlock is still offered, or the layer could never be unlocked', () => {
    expect(byId(locked, 'lock')?.labelKey).toBe('layerPanel.unlockLayer');
    expect(byId(locked, 'lock')?.disabled).toBeFalsy();
  });
});

describe('an empty layer disables what needs features', () => {
  const empty = ctx({ featureCount: 0 });
  it.each(['zoom', 'style', 'labels', 'attributes', 'export'])('%s is disabled', (id) => {
    expect(byId(empty, id)?.disabled).toBe(true);
  });

  it('but drawing the first feature is still offered', () => {
    expect(byId(empty, 'draw')?.disabled).toBeFalsy();
  });
});

describe('imported layers', () => {
  const imported = ctx({ kind: 'imported', layerId: 'imported-1', layerName: 'My Import', purpose: 'blocks' });

  it('get the layer-management commands', () => {
    expect(ids(imported)).toEqual(expect.arrayContaining(['rename', 'duplicate', 'assign', 'remove_layer']));
  });

  it('do not get built-in-only structural commands', () => {
    expect(ids(imported)).not.toContain('divide_equal_area');
    expect(ids(imported)).not.toContain('auto_create');
    expect(ids(imported)).not.toContain('import_from_boundary');
    expect(ids(imported)).not.toContain('move_up');
  });

  it('cannot be re-purposed once they have a purpose', () => {
    expect(byId(imported, 'assign_purpose')?.disabledReasonKey).toBe('layerPanel.alreadyHasPurpose');
  });

  it('cannot be appended to while still a draft', () => {
    const draft = ctx({ ...imported, isDraft: true });
    expect(byId(draft, 'import')?.disabledReasonKey).toBe('layerPanel.appendFinalizeFirst');
  });
});

describe('grouping', () => {
  it('returns groups in a fixed order, empty ones dropped', () => {
    const groups = groupLayerMenu(buildLayerMenu(ctx({ layerId: 'stem_mapping', readOnly: true, editable: false })));
    const order = groups.map((g) => g.group);
    expect(order).toEqual([...order].sort((a, b) => GROUP_ORDER.indexOf(a) - GROUP_ORDER.indexOf(b)));
    // stem_mapping offers Delete (same as the legacy Tree Mapping page), so 'danger' is present
    expect(order).toContain('danger');
    expect(byId(ctx({ layerId: 'stem_mapping', readOnly: true, editable: false }), 'delete_stem_mapping')).toBeDefined();
  });

  it('keeps every item when grouping', () => {
    const list = buildLayerMenu(ctx());
    const grouped = groupLayerMenu(list).flatMap((g) => g.items);
    expect(grouped).toHaveLength(list.length);
  });
});

// ---------------------------------------------------------------------------
// Feature clipboard: Copy / Paste here / Paste as new layer
// ---------------------------------------------------------------------------
describe('buildLayerMenu — feature clipboard commands', () => {
  const cb = (over: Partial<NonNullable<LayerMenuContext['clipboard']>> = {}) => ({
    selectedCount: 0, clipboardCount: 0, paste: null, ...over,
  });

  it('offers nothing when the host wires no feature clipboard', () => {
    const got = ids(ctx());
    expect(got).not.toContain('copy_features');
    expect(got).not.toContain('paste_features');
    expect(got).not.toContain('paste_as_layer');
  });

  it('adds the three commands to the data group, after "Show attributes"', () => {
    const items = buildLayerMenu(ctx({ clipboard: cb({ clipboardCount: 2 }) }));
    const order = items.map((i) => i.id);
    expect(order).toEqual(expect.arrayContaining(['copy_features', 'paste_features', 'paste_as_layer']));
    expect(order.indexOf('attributes')).toBeLessThan(order.indexOf('copy_features'));
    for (const id of ['copy_features', 'paste_features', 'paste_as_layer']) {
      expect(items.find((i) => i.id === id)!.group).toBe('data');
    }
  });

  it('Copy says what it will take: the selection when there is one, else the whole layer', () => {
    const all = byId(ctx({ featureCount: 5, clipboard: cb() }), 'copy_features')!;
    expect(all.labelKey).toBe('layerPanel.copyAll');
    expect(all.labelParams).toEqual({ count: 5 });
    const some = byId(ctx({ featureCount: 5, clipboard: cb({ selectedCount: 2 }) }), 'copy_features')!;
    expect(some.labelKey).toBe('layerPanel.copySelected');
    expect(some.labelParams).toEqual({ count: 2 });
  });

  it('Copy is disabled, with a reason, on an empty layer — and stays available on locked / read-only layers', () => {
    const empty = byId(ctx({ featureCount: 0, clipboard: cb() }), 'copy_features')!;
    expect(empty.disabled).toBe(true);
    expect(empty.disabledReasonKey).toBe('layerPanel.noFeaturesToCopy');

    const locked = byId(ctx({ locked: true, structureLocked: true, readOnly: true, editable: false, clipboard: cb() }), 'copy_features')!;
    expect(locked.disabled).toBeFalsy(); // copying is not an edit
  });

  it('Paste here is omitted where a layer can never take a paste', () => {
    expect(ids(ctx({ clipboard: cb({ clipboardCount: 3, paste: 'never' }) }))).not.toContain('paste_features');
  });

  it('Paste here is enabled when the paste can land, and carries the count', () => {
    const item = byId(ctx({ layerId: 'sub_areas', clipboard: cb({ clipboardCount: 3 }) }), 'paste_features')!;
    expect(item.disabled).toBeFalsy();
    expect(item.labelParams).toEqual({ count: 3 });
  });

  it('Paste here is disabled with the reason — and its parameters — when it cannot land right now', () => {
    const item = byId(ctx({
      clipboard: cb({
        clipboardCount: 3,
        paste: { reasonKey: 'editing.paste.reason.geometry_mismatch', params: { have: 'Point', need: 'Polygon' } },
      }),
    }), 'paste_features')!;
    expect(item.disabled).toBe(true);
    expect(item.disabledReasonKey).toBe('editing.paste.reason.geometry_mismatch');
    expect(item.disabledReasonParams).toEqual({ have: 'Point', need: 'Polygon' });
  });

  it('Paste as new layer is always offered, and disabled only while the clipboard is empty', () => {
    // even where a plain paste is omitted entirely
    const never = byId(ctx({ clipboard: cb({ clipboardCount: 0, paste: 'never' }) }), 'paste_as_layer')!;
    expect(never.disabled).toBe(true);
    expect(never.disabledReasonKey).toBe('editing.paste.reason.empty_clipboard');
    const ready = byId(ctx({ clipboard: cb({ clipboardCount: 4, paste: 'never' }) }), 'paste_as_layer')!;
    expect(ready.disabled).toBeFalsy();
  });

  it('respects unavailableActions like every other command', () => {
    const got = ids(ctx({ clipboard: cb({ clipboardCount: 1 }), unavailableActions: ['paste_features', 'copy_features'] }));
    expect(got).not.toContain('copy_features');
    expect(got).not.toContain('paste_features');
    expect(got).toContain('paste_as_layer');
  });
});

describe('sample plots — "Upload field inventory…" (the inventory is data about these plots)', () => {
  const sp = (over: Partial<LayerMenuContext> = {}) =>
    ctx({
      layerId: 'sample_plots', layerName: 'Sample Plots', readOnly: true, editable: false,
      featureCount: 25, counts: { boundary: 1 }, ...over,
    });

  it('is offered, enabled, once plots exist', () => {
    const item = byId(sp(), 'import_field_inventory');
    expect(item).toBeDefined();
    expect(item?.disabled).toBeFalsy();
    expect(item?.labelKey).toBe('layerPanel.importFieldInventory');
    expect(item?.group).toBe('edit');
  });

  it('is disabled, with a reason, while there are no plots to attach the inventory to', () => {
    const item = byId(sp({ featureCount: 0 }), 'import_field_inventory');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.noSampleDesign');
  });

  it('is offered on the sample-plots layer only', () => {
    expect(ids(ctx({ layerId: 'blocks' }))).not.toContain('import_field_inventory');
    expect(ids(ctx({ layerId: 'stem_mapping' }))).not.toContain('import_field_inventory');
  });
});

describe('sample plots — "Create sample plots…" (opens the sampling design form)', () => {
  const sp = (over: Partial<LayerMenuContext> = {}) =>
    ctx({
      layerId: 'sample_plots', layerName: 'Sample Plots', readOnly: true, editable: false,
      featureCount: 0, counts: { boundary: 1 }, ...over,
    });

  it('is offered, enabled, when the forest has a boundary and no design yet', () => {
    const item = byId(sp(), 'create_sample_plots');
    expect(item).toBeDefined();
    expect(item?.disabled).toBeFalsy();
    expect(item?.labelKey).toBe('layerPanel.createSamplePlots');
    expect(item?.group).toBe('edit');
  });

  it('is disabled, with a reason, once a design exists (one design per forest)', () => {
    const item = byId(sp({ featureCount: 25 }), 'create_sample_plots');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.samplePlotsExist');
  });

  it('is disabled, with a reason, when there is no forest boundary', () => {
    const item = byId(sp({ counts: { boundary: 0 } }), 'create_sample_plots');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.noBoundaryToCreateSamplePlots');
  });

  it('is disabled, with a reason, while the structure is locked', () => {
    const item = byId(sp({ structureLocked: true }), 'create_sample_plots');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.samplePlotsStructureLocked');
  });

  it('is left out when the host wires no handler for it', () => {
    expect(ids(sp({ unavailableActions: ['create_sample_plots'] }))).not.toContain('create_sample_plots');
  });

  it('is offered on the Sample Plots layer only', () => {
    for (const layerId of ['blocks', 'compartments', 'sub_areas', 'boundary', 'fieldbook', 'user_group']) {
      expect(ids(ctx({ layerId })), layerId).not.toContain('create_sample_plots');
    }
    expect(ids(ctx({ kind: 'imported', layerId: '7', purpose: 'other' }))).not.toContain('create_sample_plots');
  });
});

describe('divide by natural feature (river-ridge / slope / aspect / canopy) — per selected feature', () => {
  it('is offered on all four unit layers (FS-4a.16), next to the equal-area divide', () => {
    expect(ids(ctx({ layerId: 'blocks', counts: { boundary: 1, blocks: 1 } }))).toContain('auto_divide');
    expect(ids(ctx({ layerId: 'sub_blocks', counts: { boundary: 1, blocks: 2 } }))).toContain('auto_divide');
    expect(ids(ctx({ layerId: 'compartments', counts: { boundary: 1, compartments: 1 } }))).toContain('auto_divide');
    expect(ids(ctx({ layerId: 'sub_compartments', counts: { boundary: 1, compartments: 2 } }))).toContain('auto_divide');
  });

  it('is not offered on other layers', () => {
    expect(ids(ctx({ layerId: 'sub_areas' }))).not.toContain('auto_divide');
    expect(ids(ctx({ layerId: 'boundary' }))).not.toContain('auto_divide');
  });

  // FS-4a.16: a TOP-LEVEL layer self-divides an EXISTING selected feature of
  // its own — the prerequisite is "does at least one exist yet to select",
  // never a cross-branch count. The OLD "compartments needs a block first"
  // chain-model check (retired here, fully removed in FS-2.8/FS-4a.17) is
  // gone: existing blocks neither help nor hinder compartments' own
  // auto_divide any more.
  it('names the parent it carves FROM in the label — block on the block branch, compartment on the compartment branch, one level deeper regardless of depth (FS-4a.6)', () => {
    expect(byId(ctx({ layerId: 'blocks', counts: { boundary: 1, blocks: 1 } }), 'auto_divide')?.labelParams).toEqual({ parent: 'block' });
    expect(byId(ctx({ layerId: 'sub_blocks', counts: { boundary: 1, blocks: 2 } }), 'auto_divide')?.labelParams).toEqual({ parent: 'block' });
    expect(byId(ctx({ layerId: 'compartments', counts: { boundary: 1, compartments: 1 } }), 'auto_divide')?.labelParams).toEqual({ parent: 'compartment' });
    expect(byId(ctx({ layerId: 'sub_compartments', counts: { boundary: 1, compartments: 2 } }), 'auto_divide')?.labelParams).toEqual({ parent: 'compartment' });
  });

  it('on Compartments, existing blocks are irrelevant — only compartments existing matters', () => {
    const withBlocksNoCompartments = byId(
      ctx({ layerId: 'compartments', counts: { boundary: 1, blocks: 3, compartments: 0 } }), 'auto_divide',
    );
    expect(withBlocksNoCompartments?.disabled).toBe(true);
    expect(withBlocksNoCompartments?.disabledReasonKey).toBe('layerPanel.autoDivideNothingToDivide');
    expect(withBlocksNoCompartments?.disabledReasonParams).toEqual({ layer: 'compartments' });

    const withCompartmentsNoBlocks = byId(
      ctx({ layerId: 'compartments', counts: { boundary: 1, blocks: 0, compartments: 4 } }), 'auto_divide',
    );
    expect(withCompartmentsNoBlocks?.disabled).toBeFalsy();
  });

  it('on Blocks, it needs at least one existing block to select (FS-4a.16, same self-divide shape)', () => {
    const item = byId(ctx({ layerId: 'blocks', counts: { boundary: 1, blocks: 0 } }), 'auto_divide');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.autoDivideNothingToDivide');
    expect(item?.disabledReasonParams).toEqual({ layer: 'blocks' });
  });

  it('on Sub-compartments it needs a compartment', () => {
    const item = byId(ctx({ layerId: 'sub_compartments', counts: { boundary: 1, compartments: 0 } }), 'auto_divide');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.autoDivideNothingToDivide');
    expect(item?.disabledReasonParams).toEqual({ layer: 'compartments' });
  });

  it('on Sub-blocks it needs a block (FS-4a.16, same shape, block branch)', () => {
    const item = byId(ctx({ layerId: 'sub_blocks', counts: { boundary: 1, blocks: 0 } }), 'auto_divide');
    expect(item?.disabled).toBe(true);
    expect(item?.disabledReasonKey).toBe('layerPanel.autoDivideNothingToDivide');
    expect(item?.disabledReasonParams).toEqual({ layer: 'blocks' });
  });

  it('is blocked when the structure is locked', () => {
    const item = byId(ctx({ layerId: 'compartments', structureLocked: true, counts: { boundary: 1, blocks: 1 } }), 'auto_divide');
    expect(item?.disabledReasonKey).toBe('workspace.divideReasonLocked');
  });
});

describe('raster layers (RS-2.16/P9, owner directive 2026-10-01)', () => {
  const rasterCtx = (over: Partial<LayerMenuContext> = {}): LayerMenuContext => ({
    layerId: 'abc-123',
    kind: 'raster',
    layerName: 'slope',
    visible: true,
    labelsShown: false,
    featureCount: 6,
    editable: true,
    readOnly: false,
    locked: false,
    promotedAs: null,
    ...over,
  });

  it('offers the real commands: zoom, visibility, style, attributes, export, assign, assign_to_parent, lock', () => {
    const idList = ids(rasterCtx());
    expect(idList).toEqual(
      expect.arrayContaining([
        'zoom', 'visibility', 'style', 'attributes', 'export', 'assign', 'assign_to_parent', 'lock',
      ]),
    );
  });

  it('omits labels, copy/paste, move, delete — none are real commands yet', () => {
    const idList = ids(rasterCtx());
    for (const missing of [
      'labels', 'copy_features', 'paste_features', 'paste_as_layer',
      'move_up', 'move_down', 'clear_data',
    ]) {
      expect(idList).not.toContain(missing);
    }
  });

  it('assign offers only blocks/compartments, not the owner\'s other three (no backend yet)', () => {
    const assign = buildLayerMenu(rasterCtx()).find((i) => i.id === 'assign');
    expect(assign?.submenu?.map((s) => s.id)).toEqual(['assign:blocks', 'assign:compartments', 'assign:sub_blocks', 'assign:sub_compartments']);
  });

  it('demote appears only once promoted', () => {
    expect(ids(rasterCtx({ promotedAs: null }))).not.toContain('demote');
    expect(ids(rasterCtx({ promotedAs: 'blocks' }))).toContain('demote');
  });

  it('remove_layer (owner report 2026-10-01) is offered, disabled only once promoted', () => {
    expect(byId(rasterCtx({ promotedAs: null }), 'remove_layer')?.disabled).toBeFalsy();
    const whilePromoted = byId(rasterCtx({ promotedAs: 'blocks' }), 'remove_layer');
    expect(whilePromoted?.disabled).toBe(true);
    expect(whilePromoted?.disabledReasonKey).toBeTruthy();
  });

  it('every disabled item still carries a reason (same global rule as builtin/imported)', () => {
    for (const item of buildLayerMenu(rasterCtx({ featureCount: 0 }))) {
      if (item.disabled) expect(item.disabledReasonKey).toBeTruthy();
    }
  });
});

describe('Colour by (analysis maps)', () => {
  const maps = [
    { id: null, labelKey: 'analysisMaps.off', checked: false },
    { id: 'sfm_type', labelKey: 'analysisMaps.sfm_type', checked: true },
    { id: 'sfm_orientation', labelKey: 'analysisMaps.sfm_orientation', checked: false },
  ];
  it('is offered as a radio fly-out on a unit layer that supplies the maps', () => {
    const item = buildLayerMenu(ctx({ analysisMaps: maps })).find((i) => i.id === 'colour_by')!;
    expect(item.submenu!.map((m) => m.id)).toEqual(['analysis_map:off', 'analysis_map:sfm_type', 'analysis_map:sfm_orientation']);
    expect(item.submenu!.find((m) => m.checked)!.id).toBe('analysis_map:sfm_type');
  });
  it('is absent when the host supplies none (any other layer)', () => {
    expect(ids(ctx())).not.toContain('colour_by');
    expect(ids(ctx({ analysisMaps: [] }))).not.toContain('colour_by');
  });
});


describe('fire lines and river banks (FIRELINE_RIVERBANK_PLAN.md)', () => {
  it('the sub-areas layer offers both panels, and no other layer does', () => {
    const sub = ids(ctx({ layerId: 'sub_areas' }))
    expect(sub).toContain('fire_lines')
    expect(sub).toContain('river_banks')
    for (const layerId of ['blocks', 'compartments', 'boundary', 'user_group'] as const) {
      const other = ids(ctx({ layerId }))
      expect(other).not.toContain('fire_lines')
      expect(other).not.toContain('river_banks')
    }
  })

  it('both are disabled, with a reason, until the forest has an extent', () => {
    const noExtent = ctx({ layerId: 'sub_areas', counts: {} })
    for (const id of ['fire_lines', 'river_banks']) {
      const item = byId(noExtent, id)!
      if (item.disabled) expect(item.disabledReasonKey).toBe('layerPanel.subAreaNeedsExtent')
      expect(item.labelKey).toBe(id === 'fire_lines' ? 'layerPanel.fireLines' : 'layerPanel.riverBanks')
    }
  })

  it('the sub-areas layer can delete all the fire lines or all the river banks at once, and no other layer can', () => {
    const sub = ids(ctx({ layerId: 'sub_areas' }))
    expect(sub).toContain('delete_fire_lines')
    expect(sub).toContain('delete_river_banks')
    expect(byId(ctx({ layerId: 'sub_areas' }), 'delete_fire_lines')!.group).toBe('danger')
    for (const layerId of ['blocks', 'compartments', 'boundary'] as const) {
      expect(ids(ctx({ layerId }))).not.toContain('delete_fire_lines')
    }
  })
})
