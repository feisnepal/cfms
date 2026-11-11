/**
 * One source of truth for the layer menu (plan M-1).
 *
 * Before this existed there were three menu surfaces and two implementations:
 * right-click on a built-in row and right-click on an imported row shared
 * `LayerContextMenu`, while the ⋮ button on a built-in row was ~280 lines of
 * inline JSX in `LayerPanel` with its own conditionals and its own translation
 * keys. Nothing kept them in step, so they drifted: of 28 commands only three
 * appeared in both, and one of those three had two different names ("Zoom to
 * Layer" and "Zoom to {name}") for the same action.
 *
 * This module is deliberately **data, not UI**. It returns keys rather than
 * translated strings and carries no JSX, no i18n call and no store access, so
 * the whole item list for a layer type in a given state can be asserted in a
 * unit test — which is what stops the two renderers drifting apart again.
 *
 * ## Hidden vs disabled
 *
 * The old code disabled almost everything and hid almost nothing, so a
 * permanently impossible action looked temporarily unavailable: "Create
 * Feature" appeared greyed on Sample Plots, a layer the registry marks
 * `alwaysReadOnly`. The rule here:
 *
 * - **omitted** — this command can never apply to this layer type.
 * - **`disabled` + a reason** — it could apply, but not in this state. Fix the
 *   state and it works.
 *
 * A disabled item without a reason is a bug; every one below carries one.
 */

export type LayerMenuGroup = 'view' | 'data' | 'edit' | 'layer' | 'danger';

/** Groups in render order. Destructive last, behind a divider. */
export const GROUP_ORDER: LayerMenuGroup[] = ['view', 'data', 'edit', 'layer', 'danger'];

export interface LayerMenuItem {
  /** Stable id — the handler key the renderers dispatch on. */
  id: string;
  group: LayerMenuGroup;
  /** i18n key. Renderers translate; this module never does. */
  labelKey: string;
  labelParams?: Record<string, string | number>;
  icon: string;
  shortcut?: string;
  disabled?: boolean;
  /** Required whenever `disabled` is true. */
  disabledReasonKey?: string;
  /** Interpolation values for `disabledReasonKey` (e.g. which geometry type the layer holds). */
  disabledReasonParams?: Record<string, string | number>;
  danger?: boolean;
  /** Format choices for Export, label-field choices for Labels. */
  submenu?: LayerMenuItem[];
  /** A row that holds a number control (the layer's opacity, in percent) instead of acting when clicked. */
  spinner?: { value: number; min: number; max: number; step: number };
  /**
   * Set on submenu items that express a CHOICE rather than an action, so the
   * renderer can give them `menuitemradio` + `aria-checked`. Label fields are a
   * choice (one is active); export formats are four separate actions.
   */
  checked?: boolean;
  /**
   * Whether the data this command enters is in: `done`, `missing` (mandatory and not there yet: shown red) or `optional`. Lets the user
   * see from the menu what the step still needs.
   */
  status?: 'done' | 'missing' | 'optional';
}

/** Can a paste land in a layer? See `LayerMenuContext.clipboard.paste`. */
export type PasteState = null | 'never' | { reasonKey: string; params?: Record<string, string | number> };

export interface LayerMenuContext {
  layerId: string;
  kind: 'builtin' | 'imported' | 'raster';
  layerName: string;
  visible: boolean;
  labelsShown: boolean;
  featureCount: number;
  /** Registry `editable` — false for layers that can never be drawn on. */
  editable: boolean;
  /** Registry `alwaysReadOnly` — stronger than `editable`, never togglable. */
  readOnly: boolean;
  /** Per-session UI lock the user toggles. */
  locked: boolean;
  /** Structure lock from the backend (OP submitted). Blocks division. */
  structureLocked?: boolean;
  purpose?: string;
  /** An imported layer still being digitized cannot be appended to. */
  isDraft?: boolean;
  /** Attribute fields available to label by. Empty means no Labels submenu. */
  labelFields?: string[];
  /** Which of `labelFields` is active, so the choice can be announced. */
  currentLabelField?: string | null;
  /** Feature counts across layers — the divide commands need the source count. */
  counts?: Record<string, number>;
  /** The user group step's data (household list/totals, executive committee, other committees); undefined until read. */
  userGroupData?: { households: boolean; executive: boolean; other: boolean };
  isFirst?: boolean;
  isLast?: boolean;
  /**
   * Ids the host cannot perform, because it wired no handler for them. They are
   * **omitted**, not greyed: the same principle as C1 — an action the
   * application cannot carry out should not be advertised, and a greyed item
   * with no reason is exactly what made the old menus frustrating.
   */
  unavailableActions?: string[];
  /**
   * Formats this host can actually produce for this layer. Defaults to KML
   * alone, because that is the only one with a general implementation.
   *
   * The menu used to offer four formats on every layer while three of them
   * silently did nothing — a menu item that no-ops is worse than one that is
   * absent, because the user cannot tell the difference between "broken" and
   * "I did it wrong". Sample Plots really does support all four, through its
   * own exporter, so it passes all four. M-8 generalises the other three.
   */
  exportFormats?: string[];
  /** WORKSPACE_LAYER_STYLING_PLAN.md P1.4 — this layer has a custom style to copy. */
  hasCustomStyle?: boolean;
  /** P1.4 — the in-memory style clipboard holds something to paste. */
  hasStyleClipboard?: boolean;
  /** The layer's whole-layer opacity in percent (0-100). Present = the menu offers the Opacity row (built-in layers). */
  opacityPercent?: number;
  /** Analysis maps that can colour this (unit) layer, for "Colour by"; absent = no such item. `id: null` is "Off". */
  analysisMaps?: Array<{ id: string | null; labelKey: string; checked: boolean }>;
  /**
   * The FEATURE clipboard (Copy / Paste / Paste as layer), from this layer's point
   * of view. Absent = the host wires no feature clipboard: the three commands are
   * omitted. (Not to be confused with the style clipboard above.)
   */
  clipboard?: {
    /** Features currently selected in THIS layer; 0 means Copy takes the whole layer. */
    selectedCount: number;
    /** Features waiting on the clipboard; 0 = nothing to paste. */
    clipboardCount: number;
    /**
     * Can a paste land in this layer? `null` = yes, right now. `'never'` = this
     * layer can never take a paste (blocks, compartments, read-only layers...), so
     * the command is OMITTED, not greyed. Otherwise the reason it cannot *now*
     * (empty clipboard, wrong geometry type, locked): the command is disabled with it.
     */
    paste: PasteState;
  };
  /** `kind === 'raster'` only (RS-2.16/P9, owner directive 2026-10-01): an
   *  Auto-Block layer's promotion state, for the "Assign as…"/"Return to
   *  trial" commands. `null` = unpromoted trial overlay. */
  promotedAs?: 'blocks' | 'compartments' | null;
}

/** Built-ins that own an import purpose. `sample_plots` deliberately has none. */
const BUILTIN_PURPOSE: Record<string, string> = {
  boundary: 'boundary',
  user_group: 'user_group_boundary',
  blocks: 'blocks',
  // FS-4a.19: `sub_blocks` now has its own import purpose
  // (`IMPORT_PURPOSE_SUB_BLOCKS`); same pattern `sub_compartments` follows for
  // `compartments` below — both are Polygon-only.
  sub_blocks: 'sub_blocks',
  compartments: 'compartments',
  sub_compartments: 'compartments',
  sub_areas: 'sub_areas',
  activity_features: 'activity_features',
};

/** Layers whose "draw a new one" command has a name of its own (N2). */
const DRAW_LABEL: Record<string, string> = {
  blocks: 'layerPanel.newBlock',
  compartments: 'layerPanel.newCompartment',
};

/** A readable name for a "Label by field" submenu item — falls back to the
 *  raw field key for every field not listed (unchanged pre-existing
 *  behaviour). Only the 3 Auto-Block classification fields (SLOPE_
 *  COMPARTMENT_AND_STRATIFIED_SAMPLING_PLAN follow-on) are given one here,
 *  since `dominant_slope_band` etc. read as internal column keys otherwise. */
const LABEL_FIELD_DISPLAY_NAME: Record<string, string> = {
  display_label: 'Activity · year',
  activity_name: 'Activity',
  dominant_slope_band: 'Slope Class',
  dominant_aspect: 'Aspect',
  dominant_canopy_class: 'Canopy Class',
  dominant_landcover: 'Land Cover',
  dominant_health_class: 'Forest Health',
};

/** Layers a polygon can be traced from a run of clicked points (U-4). */
const POLYGON_FROM_POINTS_LAYERS = new Set(['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas']);
// FS-4a.16: all four unit types now divide (equal-area and natural-feature)
// — the block branch backend has supported this since FS-4a.5/4a.6, the
// menu simply never offered it. The internal enablement logic just below
// is now a real 4-way branch instead of a `layerId === 'compartments'`
// binary; the deeper "retire the legacy mirror-block flow" rewrite
// (FS-2.8/FS-4a.17, lean L3) is a separate, later task.
const DIVIDE_LAYERS = new Set(['blocks', 'sub_blocks', 'compartments', 'sub_compartments']);
/** A sub-level layer's own top-level counterpart, and vice versa — the
 * "does the source/parent for this divide exist" check below reads
 * whichever count is relevant to `layerId`'s own branch and depth. */
const TOP_LEVEL_OF: Record<string, string> = { sub_blocks: 'blocks', sub_compartments: 'compartments' };
const IS_TOP_LEVEL_LAYER = new Set(['blocks', 'compartments']);
/** Plain-English name for a layer id, for `{{layer}}` message params below —
 * this file deliberately has no imports (kept pure/testable), so this is a
 * small local map rather than pulling `layerRegistry`'s labels in. */
const LAYER_WORD: Record<string, string> = {
  blocks: 'blocks', sub_blocks: 'sub-blocks', compartments: 'compartments', sub_compartments: 'sub-compartments',
};
/** The parent a natural divide carves FROM — always the branch's top-level
 *  unit (block on the block branch, compartment on the compartment branch),
 *  since `auto_block_service.resolve_divide_scope` goes one level deeper
 *  regardless of the layer's own depth (FS-4a.6). Singular, for the
 *  `{{parent}}` param of `layerPanel.autoDivideNatural`. */
const PARENT_WORD: Record<string, string> = {
  blocks: 'block', sub_blocks: 'block', compartments: 'compartment', sub_compartments: 'compartment',
};
/** What every layer can produce: KML (made in the browser) and GeoPackage (made by the server from the same features). See `exportFormats`. */
const DEFAULT_EXPORT_FORMATS = ['kml', 'gpkg'];

/** The single reason an edit is blocked, or null when it is not. */
function editBlockedReason(ctx: LayerMenuContext): string | null {
  if (ctx.locked) return 'layerPanel.lockedUnlockToEdit';
  return null;
}

/**
 * M-7: does any block, compartment or sub-compartment exist?
 *
 * Two server-side refusals hang off this, and the menu used to offer both
 * commands as though they would work:
 *
 * - `auto_block_service` answers **409 BLOCKS_EXIST** to auto-create whenever
 *   any block or compartment already exists.
 * - `assert_boundary_editable` refuses to let the forest boundary move once
 *   structural features tile it, because the blocks' outer edge would
 *   desynchronise from the boundary they are supposed to cover (Rule A).
 *
 * Offering a command that the server will certainly reject is worse than not
 * offering it: the user does the work, then gets an error for it. These are
 * *disabled with a reason* rather than hidden, because they become available
 * again the moment the blocks are removed — the C1 rule for permanence does
 * not apply.
 */
function hasStructuralFeatures(ctx: LayerMenuContext): boolean {
  const c = ctx.counts ?? {};
  return (c.blocks ?? 0) > 0 || (c.sub_blocks ?? 0) > 0 || (c.compartments ?? 0) > 0 || (c.sub_compartments ?? 0) > 0;
}

/**
 * Does the forest have an extent a sub-area can sit inside — a boundary, or any
 * block / compartment? A sub-area is clipped to (boundary ∪ blocks), so the
 * backend refuses to draw or import one before this holds (422 boundary_required).
 */
function hasForestExtent(ctx: LayerMenuContext): boolean {
  return ((ctx.counts ?? {}).boundary ?? 0) > 0 || hasStructuralFeatures(ctx);
}

/**
 * RS-2.16/P9 (owner directive 2026-10-01): "compare the context menu made by
 * Block, Compartment and these Auto-created layers; create these menus for
 * those layers." Self-contained branch (not threaded through every
 * `isImported`/builtin conditional below) because a raster layer's identity
 * (UUID, created by a carve source, holds a promotion state) does not fit
 * either existing branch's assumptions — same reasoning `LayerPanel.tsx`
 * already used to give it its own `activeRasterLayerId` rather than widening
 * `LayerTypeId`. Items match the owner's list where a real command exists
 * today; three are deliberately OMITTED with a comment, not disabled, because
 * C1's own rule applies: an action the application cannot perform at all yet
 * should not be advertised as "temporarily" unavailable.
 */
function buildRasterLayerMenu(ctx: LayerMenuContext): LayerMenuItem[] {
  const items: LayerMenuItem[] = [];
  const unavailable = new Set(ctx.unavailableActions ?? []);
  const push = (item: LayerMenuItem) => {
    if (!unavailable.has(item.id)) items.push(item);
  };
  const empty = ctx.featureCount === 0;
  const promoted = ctx.promotedAs ?? null;

  // ---------------------------------------------------------------- view ----
  push({
    id: 'zoom', group: 'view', labelKey: 'layerPanel.zoomToName',
    labelParams: { name: ctx.layerName }, icon: '🔍', shortcut: 'Z',
    disabled: empty, disabledReasonKey: empty ? 'layerPanel.noFeaturesToZoom' : undefined,
  });
  push({
    id: 'visibility', group: 'view',
    labelKey: ctx.visible ? 'workspace.hideLayer' : 'workspace.showLayer',
    icon: ctx.visible ? '🙈' : '👁️', shortcut: 'V',
  });
  // Style (owner reminder, 2026-10-01): re-checked the earlier "needs a
  // third `layerStyleKey` kind first" reasoning and it was overcautious —
  // `layerStyleKey(id, 'builtin', calcId)` is just `${calcId}::${id}`, and a
  // raster layer's id is a UUID, which can never collide with a real
  // `LayerTypeId` string ('blocks', 'compartments', ...). Reusing the
  // 'builtin' kind for key generation costs nothing and needed no change to
  // `layerStyleKey` itself. Single-symbol mode (colour/opacity/weight) works
  // immediately this way; Categorized/Graduated classification mode still
  // won't find fields (it fetches via `getLayerConfig(layerId as
  // LayerTypeId)`, which returns nothing for a UUID) — a real but smaller
  // gap than "no Style at all", left for its own follow-up rather than
  // blocking the basic override the owner actually asked for.
  push({
    id: 'style', group: 'view', labelKey: 'layerPanel.styleDialog', icon: '🎨', shortcut: 'S',
    disabled: empty, disabledReasonKey: empty ? 'layerPanel.noFeaturesToStyle' : undefined,
  });
  //
  // Labels: OMITTED. Every built-in layer's label field list comes from the
  // registry (`labelFields`); a raster layer has no registry entry to read
  // one from. A single generic "label by Name" is possible but was not asked
  // for, so it is left for the same follow-up as Style rather than guessed.

  // ---------------------------------------------------------------- data ----
  push({
    id: 'attributes', group: 'data', labelKey: 'layerPanel.showAttributes',
    icon: '📋', shortcut: 'A', disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToShow' : undefined,
  });
  // Copy / Paste / Paste-as-layer: OMITTED. The feature clipboard
  // (`useFeatureClipboard`) is wired per built-in/imported layer id; a raster
  // layer's rows are a `raster_layer_id`-scoped slice of `forest_blocks`, not
  // a layer the clipboard's copy/paste backend calls know how to address yet.
  // Follow-up, not a quick addition — pasting INTO a trial layer also raises
  // a question the owner has not answered: does a pasted feature count toward
  // that layer's own source, or is it sourceless?
  push({
    id: 'export', group: 'data', labelKey: 'layerPanel.exportLayer', icon: '📤',
    shortcut: 'E', disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToExport' : undefined,
  });

  // ---------------------------------------------------------------- edit ----
  // "Assign selected layer as…" — the owner's list names Compartment, Block,
  // sub-compartment, sub-block, sub-area. Today's `promote_layer` backend
  // only supports the first two (top-level); sub-block/sub-compartment needs
  // its OWN backend work (owner confirmed design: pick one existing parent,
  // promote the whole layer as its children, matching `commit_children`) and
  // sub-area promotion was never part of this plan (RS-2.16 is about
  // blocks/compartments only — a sub-area is a different structural concept,
  // not a depth level of this hierarchy). The submenu therefore offers only
  // the two built choices today, not all five named — each of the other
  // three stays omitted until its own backend lands, rather than offered and
  // failing.
  push({
    id: 'assign', group: 'edit', labelKey: 'layerPanel.autoBlockAssignAs', icon: '🔗',
    submenu: [
      {
        id: 'assign:blocks', group: 'edit' as const, labelKey: 'layerPanel.autoBlockPromoteAsBlocks', icon: '',
        checked: promoted === 'blocks',
      },
      {
        id: 'assign:compartments', group: 'edit' as const, labelKey: 'layerPanel.autoBlockPromoteAsCompartments', icon: '',
        checked: promoted === 'compartments',
      },
      // Sub-levels: pick one existing block (sub-blocks) / compartment
      // (sub-compartments); the layer becomes that unit's children.
      {
        id: 'assign:sub_blocks', group: 'edit' as const, labelKey: 'layerPanel.autoBlockAssignAsSubBlocks', icon: '',
      },
      {
        id: 'assign:sub_compartments', group: 'edit' as const, labelKey: 'layerPanel.autoBlockAssignAsSubCompartments', icon: '',
      },
    ],
  });
  if (promoted != null) {
    push({ id: 'demote', group: 'edit', labelKey: 'layerPanel.autoBlockDemote', icon: '↩️' });
  }
  // RS-2.17 sub-unit assignment (owner directive 2026-10-01, design
  // confirmed): pick one existing undivided block/compartment, promote the
  // whole layer as its children. Which branch (sub-blocks vs
  // sub-compartments) follows from which parent is picked, so this is ONE
  // command, not the two separate "sub-block"/"sub-compartment" entries the
  // owner's original list named — the backend has no reason to ask the
  // branch twice.
  push({
    id: 'assign_to_parent', group: 'edit', labelKey: 'layerPanel.autoBlockAssignToParent', icon: '🧷',
  });

  // --------------------------------------------------------------- layer ----
  push({
    id: 'lock', group: 'layer',
    labelKey: ctx.locked ? 'layerPanel.unlockLayer' : 'layerPanel.lockLayer',
    icon: ctx.locked ? '🔓' : '🔒',
  });
  // Move up / Move down: OMITTED. Built-in layers have one canonical z-order
  // (`LAYER_REGISTRY[].order`); raster layers render in an unordered list
  // today (`store.rasterLayers`, insertion order only) — reordering needs
  // that list to carry a persisted order first. Follow-up.

  // -------------------------------------------------------------- danger ----
  // Delete layer (owner report 2026-10-01: "I can not remove auto created
  // layer. Make it deletable.") — disabled, not omitted, once promoted: a
  // promoted layer's rows ARE the forest's real structure, not a trial to
  // discard, so deleting it needs Demote first (a reversible, non-destructive
  // step) rather than silently refusing with no path forward.
  push({
    id: 'remove_layer', group: 'danger', labelKey: 'layerPanel.removeLayerNamed',
    labelParams: { name: ctx.layerName }, icon: '❌', danger: true,
    disabled: promoted != null,
    disabledReasonKey: promoted != null ? 'layerPanel.autoBlockCannotDeletePromoted' : undefined,
  });

  return items;
}

export function buildLayerMenu(ctx: LayerMenuContext): LayerMenuItem[] {
  if (ctx.kind === 'raster') return buildRasterLayerMenu(ctx);
  const items: LayerMenuItem[] = [];
  const isImported = ctx.kind === 'imported';
  const empty = ctx.featureCount === 0;
  const editBlocked = editBlockedReason(ctx);
  const unavailable = new Set(ctx.unavailableActions ?? []);
  const push = (item: LayerMenuItem) => {
    if (!unavailable.has(item.id)) items.push(item);
  };

  // ---------------------------------------------------------------- view ----
  push({
    id: 'zoom',
    group: 'view',
    // N1: one name, and it names the layer — several rows look alike otherwise.
    labelKey: 'layerPanel.zoomToName',
    labelParams: { name: ctx.layerName },
    icon: '🔍',
    shortcut: 'Z',
    disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToZoom' : undefined,
  });

  push({
    id: 'visibility',
    group: 'view',
    labelKey: ctx.visible ? 'workspace.hideLayer' : 'workspace.showLayer',
    icon: ctx.visible ? '🙈' : '👁️',
    shortcut: 'V',
  });

  push({
    id: 'style',
    group: 'view',
    labelKey: 'layerPanel.styleDialog',
    icon: '🎨',
    shortcut: 'S',
    // C2: styling nothing opens a dialog that cannot show a result.
    disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToStyle' : undefined,
    // P1.4 — copy / paste a style between layers, and a few named starting points.
    submenu: empty ? undefined : [
      {
        id: 'style_copy', group: 'view' as const, labelKey: 'layerPanel.styleCopy', icon: '',
        disabled: !ctx.hasCustomStyle,
        disabledReasonKey: !ctx.hasCustomStyle ? 'layerPanel.styleCopyNone' : undefined,
      },
      {
        id: 'style_paste', group: 'view' as const, labelKey: 'layerPanel.stylePaste', icon: '',
        disabled: !ctx.hasStyleClipboard,
        disabledReasonKey: !ctx.hasStyleClipboard ? 'layerPanel.stylePasteEmpty' : undefined,
      },
      { id: 'style_preset:muted', group: 'view' as const, labelKey: 'layerPanel.stylePresetMuted', icon: '' },
      { id: 'style_preset:highContrast', group: 'view' as const, labelKey: 'layerPanel.stylePresetHighContrast', icon: '' },
      { id: 'style_preset:printOutline', group: 'view' as const, labelKey: 'layerPanel.stylePresetPrintOutline', icon: '' },
    ],
  });

  // C6: "Label field" used to sit at the top of the ⋮ menu even for layers
  // exposing no fields to label by. It belongs with the other label controls.
  const labelFields = ctx.labelFields ?? [];
  push({
    id: 'labels',
    group: 'view',
    labelKey: ctx.labelsShown ? 'workspace.hideLabels' : 'workspace.showLabels',
    icon: '🏷️',
    shortcut: 'L',
    disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToLabel' : undefined,
    submenu: labelFields.length
      ? labelFields.map((field) => ({
          id: `label_field:${field}`,
          group: 'view' as const,
          labelKey: 'layerPanel.labelFieldNamed',
          labelParams: { field: LABEL_FIELD_DISPLAY_NAME[field] ?? field },
          icon: '',
          checked: (ctx.currentLabelField ?? null) === field,
        }))
      : undefined,
  });

  // Whole-layer opacity: a compact `80% ▲▼` row here instead of a slider on every layer row (which squeezed the layer name).
  if (ctx.opacityPercent != null) {
    push({
      id: 'opacity',
      group: 'view',
      labelKey: 'layerPanel.layerOpacity',
      icon: '◐',
      spinner: { value: Math.max(0, Math.min(100, Math.round(ctx.opacityPercent))), min: 0, max: 100, step: 10 },
    });
  }

  // Colour the units by an analysis map (forest type / orientation / stock): the same choice as the Analysis maps group,
  // one right-click away from the layer it recolours.
  if (ctx.analysisMaps && ctx.analysisMaps.length > 0) {
    push({
      id: 'colour_by',
      group: 'view',
      labelKey: 'layerPanel.colourBy',
      icon: '🎨',
      submenu: ctx.analysisMaps.map((m) => ({
        id: `analysis_map:${m.id ?? 'off'}`,
        group: 'view' as const,
        labelKey: m.labelKey,
        icon: '',
        checked: m.checked,
      })),
    });
  }

  // ---------------------------------------------------------------- data ----
  push({
    id: 'attributes',
    group: 'data',
    labelKey: 'layerPanel.showAttributes',
    icon: '📋',
    shortcut: 'A',
    disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToShow' : undefined,
  });

  // Feature clipboard. Copying is not an edit, so it is offered on a locked or
  // read-only layer too; only Paste depends on what the layer can hold.
  const cb = ctx.clipboard;
  if (cb) {
    const hasSelection = cb.selectedCount > 0;
    push({
      id: 'copy_features',
      group: 'data',
      labelKey: hasSelection ? 'layerPanel.copySelected' : 'layerPanel.copyAll',
      labelParams: { count: hasSelection ? cb.selectedCount : ctx.featureCount },
      icon: '📄',
      disabled: empty,
      disabledReasonKey: empty ? 'layerPanel.noFeaturesToCopy' : undefined,
    });
    if (cb.paste !== 'never') {
      const why = cb.paste;
      push({
        id: 'paste_features',
        group: 'data',
        labelKey: 'layerPanel.pasteHere',
        labelParams: { count: cb.clipboardCount },
        icon: '📋',
        disabled: why !== null,
        disabledReasonKey: why ? why.reasonKey : undefined,
        disabledReasonParams: why ? why.params : undefined,
      });
    }
    // A new layer can always be made from the clipboard, wherever you are.
    const nothingCopied = cb.clipboardCount === 0;
    push({
      id: 'paste_as_layer',
      group: 'data',
      labelKey: 'layerPanel.pasteAsLayer',
      icon: '🗂',
      disabled: nothingCopied,
      disabledReasonKey: nothingCopied ? 'editing.paste.reason.empty_clipboard' : undefined,
    });
  }

  // N3: "Import {name}" and "Add Features to this Layer" were the same act
  // under two names, split only by whether the layer was built-in.
  const purpose = isImported ? ctx.purpose : BUILTIN_PURPOSE[ctx.layerId];
  if (purpose) {
    const draftBlocked = isImported && ctx.isDraft;
    // The sub_areas row's "Import into …" carries a fixed purpose, so it skips
    // the geometry-first purpose filter the generic import dialog applies —
    // gate it here too (backend: 422 boundary_required).
    const subAreaNoExtent =
      !isImported && ctx.layerId === 'sub_areas' && !hasForestExtent(ctx);
    push({
      id: 'import',
      group: 'data',
      labelKey: 'layerPanel.importInto',
      labelParams: { name: ctx.layerName },
      icon: '📥',
      disabled: !!editBlocked || !!draftBlocked || subAreaNoExtent,
      disabledReasonKey:
        editBlocked ??
        (draftBlocked
          ? 'layerPanel.appendFinalizeFirst'
          : subAreaNoExtent
            ? 'layerPanel.subAreaNeedsExtent'
            : undefined),
    });
  }

  // N4/C3: Sample Plots used to carry BOTH "Export as KML" (from the
  // right-click menu, all layers) and "Export sample plots ▸" with four
  // formats (from ⋮). One command, one format list, everywhere.
  const formats = ctx.exportFormats ?? DEFAULT_EXPORT_FORMATS;
  push({
    // The id stays `export` whatever the format count — a command's
    // identity should not shift with how many choices it happens to offer.
    id: 'export',
    group: 'data',
    labelKey: 'layerPanel.exportLayer',
    icon: '📤',
    shortcut: 'E',
    disabled: empty,
    disabledReasonKey: empty ? 'layerPanel.noFeaturesToExport' : undefined,
    // One format needs no submenu — the command just does it. A submenu of one
    // is a click the user should not have to make.
    submenu: formats.length > 1
      ? formats.map((fmt) => ({
          id: `export:${fmt}`,
          group: 'data' as const,
          labelKey: 'layerPanel.exportFormat',
          labelParams: { format: fmt.toUpperCase() },
          icon: '',
        }))
      : undefined,
  });

  // ---------------------------------------------------------------- edit ----
  // Freehand "draw one" — offered ONLY on blocks & compartments, which have a
  // real flow behind it (onNewDraw → scissor draw + "Finish & Create" bar +
  // POST /blocks/draw). Every other layer used to get a generic "New feature
  // in …" that only activated the layer and armed no tool — a dead end for
  // sub-compartments (no draw effect exists) and strictly worse than
  // "Digitize forest boundary" for the boundary. user_group has its own
  // `digitize_user_group` command below.
  if ((ctx.layerId === 'blocks' || ctx.layerId === 'compartments') && !ctx.readOnly) {
    push({
      id: 'draw',
      group: 'edit',
      // N2: "New Block" beats "Create Feature" — the user is thinking in blocks.
      labelKey: DRAW_LABEL[ctx.layerId],
      icon: '✏️',
      shortcut: 'N',
      disabled: !!editBlocked || !ctx.editable,
      disabledReasonKey: editBlocked ?? (!ctx.editable ? 'layerPanel.layerNotEditable' : undefined),
    });
  }

  if (!isImported) {
    if (ctx.layerId === 'sub_areas') {
      const noExtent = !hasForestExtent(ctx);
      push({
        id: 'add_sub_area',
        group: 'edit',
        labelKey: 'layerPanel.addSubArea',
        icon: '➕',
        disabled: !!editBlocked || noExtent,
        disabledReasonKey: editBlocked ?? (noExtent ? 'layerPanel.subAreaNeedsExtent' : undefined),
      });
      // The fire lines (boundaries between units, roads, lines drawn with a width per segment) live on this layer; the panel is
      // where the owner unticks the ones that are not fire lines. Opening it is always allowed; changing is blocked inside it.
      push({
        id: 'fire_lines',
        group: 'edit',
        labelKey: 'layerPanel.fireLines',
        icon: '🔥',
        disabled: noExtent,
        disabledReasonKey: noExtent ? 'layerPanel.subAreaNeedsExtent' : undefined,
      });
      // River banks: 20 m each side of the rivers, a protection area (not productive). Same panel as the fire lines.
      push({
        id: 'river_banks',
        group: 'edit',
        labelKey: 'layerPanel.riverBanks',
        icon: '🌊',
        disabled: noExtent,
        disabledReasonKey: noExtent ? 'layerPanel.subAreaNeedsExtent' : undefined,
      });
      // Delete them all at once (owner, 2026-10-20). They are removed as decisions, so a regenerate does not bring them back.
      for (const [id, labelKey] of [['delete_fire_lines', 'layerPanel.deleteFireLines'], ['delete_river_banks', 'layerPanel.deleteRiverBanks']] as const) {
        push({
          id,
          group: 'danger',
          labelKey,
          icon: '🗑️',
          disabled: !!editBlocked || noExtent,
          disabledReasonKey: editBlocked ?? (noExtent ? 'layerPanel.subAreaNeedsExtent' : undefined),
        });
      }
    }

    // User Group Boundary — auto-buffer from the forest boundary, and run the
    // building / settlement analysis. USER_GROUP_BOUNDARY_PLAN.md P3.
    if (ctx.layerId === 'user_group') {
      push({
        id: 'digitize_user_group',
        group: 'edit',
        labelKey: 'layerPanel.digitizeUserGroup',
        icon: '🖊️',
        disabled: !!editBlocked,
        disabledReasonKey: editBlocked ?? undefined,
      });
      push({
        id: 'user_group_auto_buffer',
        group: 'edit',
        labelKey: 'workspace.userGroup.autoBuffer',
        icon: '⭕',
        disabled: !!editBlocked,
        disabledReasonKey: editBlocked ?? undefined,
      });
      // The user group step's data (owner, 2026-10-11): household information (a list OR just the totals) and the executive committee
      // are mandatory; the advisory and financial committees are optional. Each row says whether it is in.
      const ug = ctx.userGroupData;
      push({
        id: 'user_group_households',
        group: 'data',
        labelKey: 'workspace.userGroup.householdsMenu',
        icon: '🏠',
        status: ug?.households ? 'done' : 'missing',
      });
      push({
        id: 'user_group_executive',
        group: 'data',
        labelKey: 'workspace.userGroup.executiveMenu',
        icon: '🏛️',
        status: ug?.executive ? 'done' : 'missing',
      });
      push({
        id: 'user_group_other_committees',
        group: 'data',
        labelKey: 'workspace.userGroup.otherCommitteesMenu',
        icon: '🤝',
        status: ug?.other ? 'done' : 'optional',
      });
      push({
        id: 'user_group_analysis',
        group: 'data',
        labelKey: 'workspace.userGroup.analysisTitle',
        icon: '📊',
        disabled: (ctx.featureCount ?? 0) === 0,
        disabledReasonKey: (ctx.featureCount ?? 0) === 0 ? 'workspace.userGroup.noExtentToAnalyze' : undefined,
      });
    }

    // Field Book — server-generates the layer's own points on demand
    // (fieldbook_map_layer_plan.md P5). Disabled only when there's no forest
    // boundary to walk yet -- ctx.featureCount === 0 is the NORMAL
    // before-first-generation state, not a reason to disable.
    if (ctx.layerId === 'fieldbook') {
      const noBoundary = (ctx.counts?.boundary ?? 0) === 0;
      push({
        id: 'generate_field_book',
        group: 'data',
        labelKey: (ctx.featureCount ?? 0) > 0 ? 'layerPanel.regenerateFieldbook' : 'layerPanel.generateFieldbook',
        icon: '🧭',
        disabled: noBoundary,
        disabledReasonKey: noBoundary ? 'layerPanel.noBoundaryToGenerateFieldbook' : undefined,
      });
    }

    // Sample Plots — open the sampling design form over the map. One design per
    // forest, and the server needs a boundary (400 calculations.no_geometry) and an
    // unlocked structure (423), so each is a disabled-with-a-reason, not a hidden
    // command: fix the state and it works. Once plots exist the design is deleted
    // from the Sampling page first (400 sampling.design_already_exists).
    if (ctx.layerId === 'sample_plots') {
      const noBoundary = (ctx.counts?.boundary ?? 0) === 0;
      const exists = (ctx.featureCount ?? 0) > 0;
      const reason = ctx.structureLocked
        ? 'layerPanel.samplePlotsStructureLocked'
        : noBoundary
          ? 'layerPanel.noBoundaryToCreateSamplePlots'
          : exists
            ? 'layerPanel.samplePlotsExist'
            : undefined;
      push({
        id: 'create_sample_plots',
        group: 'edit',
        labelKey: 'layerPanel.createSamplePlots',
        icon: '✚',
        disabled: !!reason,
        disabledReasonKey: reason,
      });

      // Sample plots prepared in another system (owner, 2026-10-13): pick the Sample_Plots Excel / CSV; it goes through Add data, which checks it.
      push({
        id: 'import_sample_plots',
        group: 'edit',
        labelKey: 'layerPanel.importSamplePlots',
        icon: '📥',
        disabled: !!reason,
        disabledReasonKey: reason,
      });

      // Owner report 2026-10-02 (rule 1): once a design exists, add ONE more
      // plot rather than recreating the whole design -- the mirror image of
      // `create_sample_plots` above (enabled exactly when that one is
      // disabled for "already exists"). The "no field inventory data yet"
      // gate is enforced by the handler (needs a live check this menu-
      // building function can't make), so this only disables on the cheap,
      // always-known condition: no design to add a plot to yet.
      push({
        id: 'add_sample_plot',
        group: 'edit',
        labelKey: 'layerPanel.addSamplePlot',
        icon: '✚',
        disabled: !exists,
        disabledReasonKey: !exists ? 'layerPanel.noSampleDesign' : undefined,
      });

      // The field inventory is data ABOUT these plots, so it is uploaded from here too (owner rule 2026-10-10). It opens the
      // Field Inventory step on its Upload tab. Needs plots to attach to, hence the same gate as `add_sample_plot`.
      push({
        id: 'import_field_inventory',
        group: 'edit',
        labelKey: 'layerPanel.importFieldInventory',
        icon: '📥',
        disabled: !exists,
        disabledReasonKey: !exists ? 'layerPanel.noSampleDesign' : undefined,
      });
    }

    // Stem Mapping — the layer is a read-only view over the Tree Inventory and
    // owns no dataset of its own (no delete/import of its own geometry). The
    // IMPORT command opens the full Tree Mapping process (upload → column
    // mapping → validation → boundary corrections → processing → export/delete)
    // in a modal over the map, mirroring "Create sample plots". Always enabled:
    // with no census yet it lands on the upload form, with one it lands on the
    // summary containing delete — one entry point, both states.
    if (ctx.layerId === 'stem_mapping') {
      push({
        id: 'import_stem_mapping',
        group: 'edit',
        labelKey: 'layerPanel.importStemMapping',
        icon: '📥',
      });
    }

    // "Auto Create" USED to live here (owner directive, 2026-10-01: removed).
    // Right-clicking the Blocks or Compartments row and auto-creating directly
    // AT that level made the block/compartment choice at CREATION time, which
    // is exactly backwards from how RS-2.16 layers actually work now: a
    // layer's `level` at commit is cosmetic (`promote_layer` overwrites
    // `is_compartment` to match whatever the user picks later), so offering
    // "Auto Create Blocks" here implied a decision was being locked in when it
    // was not. One neutral entry point replaces both rows' commands — the
    // "+ Auto-Block Layer" button in the layer panel header
    // (`LayerPanel.tsx`), not anchored to either row — and "Assign layer
    // as…"/"Assign to existing block/compartment…" (the raster layer's own
    // menu, above) is where the block-vs-compartment choice now actually
    // happens, deliberately later and deliberately reversible.

    // BL-5 (GAP_HANDLING_PLAN.md, block lifecycle decoupling): regenerates the
    // single boundary-mirroring block/compartment on demand, once the user has
    // cleared it via delete (Decision A/B). Top-level layers only — a durable
    // clear for sub-blocks/sub-compartments is out of scope (Decision C).
    // Compartments mirror blocks (the two branches are symmetric per the
    // forest structure rule). Enabled in exactly the state `auto_create`
    // above is disabled for ("no structural features").
    if (ctx.layerId === 'blocks' || ctx.layerId === 'compartments') {
      const structural = hasStructuralFeatures(ctx);
      const isCompartment = ctx.layerId === 'compartments';
      push({
        id: 'import_from_boundary',
        group: 'edit',
        labelKey: isCompartment
          ? 'layerPanel.importCompartmentFromBoundary'
          : 'layerPanel.importBlockFromBoundary',
        icon: '📥',
        disabled: !!editBlocked || structural,
        disabledReasonKey: editBlocked ?? (structural
          ? (isCompartment
            ? 'layerPanel.importCompartmentFromBoundaryBlocksExist'
            : 'layerPanel.importBlockFromBoundaryBlocksExist')
          : undefined),
      });
    }

    if (DIVIDE_LAYERS.has(ctx.layerId)) {
      const counts = ctx.counts ?? {};
      const isTopLevel = IS_TOP_LEVEL_LAYER.has(ctx.layerId);
      const topLevelOf = TOP_LEVEL_OF[ctx.layerId];
      // FS-4a.16: branch-generic across all four layers. A TOP-LEVEL layer
      // (blocks/compartments) divides straight from the forest boundary
      // (the root carve, FS-4a.5) — nothing else is a prerequisite. A
      // SUB-LEVEL layer (sub_blocks/sub_compartments) divides from its own
      // top-level counterpart, which must exist first. (The deeper "retire
      // the legacy compartments-need-a-block chain" rewrite is FS-2.8/
      // FS-4a.17 — this keeps the SET of layers correct and the prerequisite
      // CORRECT [never checks the wrong count], not necessarily its exact
      // wording, which those tasks own.)
      const sourceMissing = isTopLevel
        ? (counts.boundary ?? 0) === 0
        : (counts[topLevelOf] ?? 0) === 0;
      const reason = ctx.structureLocked
        ? 'workspace.divideReasonLocked'
        : ctx.locked
          ? 'workspace.divideReasonLayerLocked'
          : sourceMissing
            ? isTopLevel
              ? 'workspace.divideReasonNoBoundary'
              : 'workspace.divideReasonNoParentUnit'
            : undefined;
      push({
        id: 'divide_equal_area',
        group: 'edit',
        labelKey: 'layerPanel.divideEqualArea',
        icon: '📐',
        disabled: !!reason,
        disabledReasonKey: reason,
        disabledReasonParams: reason === 'workspace.divideReasonNoParentUnit' ? { layer: LAYER_WORD[topLevelOf] } : undefined,
      });
      // Divide the SELECTED unit along a natural basis (river-ridge, slope,
      // aspect, canopy) — the whole-forest "Auto-create" above is once-only,
      // this is not. A SUB-LEVEL layer needs its top-level counterpart to
      // exist (something to divide FROM, one level down). A TOP-LEVEL layer
      // self-divides an EXISTING selected feature of its own — the
      // prerequisite is simply "does at least one exist yet to select"
      // (`auto_block_service.resolve_divide_scope` already supports
      // natural-dividing any block-branch unit "on its own basis", top-level
      // or sub-level — FS-4a.6).
      const parentMissing = isTopLevel
        ? (counts[ctx.layerId] ?? 0) === 0
        : (counts[topLevelOf] ?? 0) === 0;
      // `compartments`' own prerequisite changed shape above (from "no
      // BLOCKS exist" to "no COMPARTMENTS exist yet to select" — the old
      // chain-model assumption), so the old `autoDivideNoBlocks` text
      // ("There is no block to divide") no longer matches its condition
      // either; every case now uses the one new generic key.
      const autoDivideReason = ctx.structureLocked
        ? 'workspace.divideReasonLocked'
        : ctx.locked
          ? 'workspace.divideReasonLayerLocked'
          : parentMissing
            ? 'layerPanel.autoDivideNothingToDivide'
            : undefined;
      push({
        id: 'auto_divide',
        group: 'edit',
        labelKey: 'layerPanel.autoDivideNatural',
        labelParams: { parent: PARENT_WORD[ctx.layerId] },
        icon: '🌊',
        disabled: !!autoDivideReason,
        disabledReasonKey: autoDivideReason,
        disabledReasonParams: autoDivideReason
          ? { layer: LAYER_WORD[isTopLevel ? ctx.layerId : topLevelOf] }
          : undefined,
      });
    }

    // "Update attribute": one command that refreshes whatever attribute components are available (raster analysis, SFM,
    // hazard & erosion; inventory is reported). Only the four unit layers carry those attributes.
    if (ctx.layerId === 'blocks' || ctx.layerId === 'sub_blocks' || ctx.layerId === 'compartments' || ctx.layerId === 'sub_compartments') {
      push({
        id: 'update_attributes',
        group: 'edit',
        labelKey: 'layerPanel.updateAttributes',
        icon: '🔄',
        disabled: !!ctx.locked,
        disabledReasonKey: ctx.locked ? 'layerPanel.lockedUnlockToEdit' : undefined,
      });
    }

    if (POLYGON_FROM_POINTS_LAYERS.has(ctx.layerId)) {
      push({
        id: 'polygon_from_points',
        group: 'edit',
        labelKey: 'layerPanel.polygonFromPoints',
        icon: '🎯',
        disabled: !!editBlocked,
        disabledReasonKey: editBlocked ?? undefined,
      });
    }

    if (ctx.layerId === 'boundary') {
      // Rule A: the boundary is not reshapable once blocks tile it.
      const lockedByStructure = hasStructuralFeatures(ctx);
      const boundaryBlocked = editBlocked ?? (lockedByStructure ? 'layerPanel.boundaryLockedByStructure' : undefined);
      push({
        id: 'digitize_boundary',
        group: 'edit',
        labelKey: 'layerPanel.digitizeBoundary',
        icon: '🖊️',
        disabled: !!boundaryBlocked,
        disabledReasonKey: boundaryBlocked,
      });
      // C4: this lived in BOTH menus. One home.
      push({
        id: 'boundary_from_point_file',
        group: 'edit',
        labelKey: 'layerPanel.boundaryFromPointFile',
        icon: '📄',
        disabled: !!boundaryBlocked,
        disabledReasonKey: boundaryBlocked,
      });
    }
  }

  // --------------------------------------------------------------- layer ----
  if (isImported) {
    push({ id: 'rename', group: 'layer', labelKey: 'layerPanel.renameLayer', icon: '✏️',
      disabled: !!editBlocked, disabledReasonKey: editBlocked ?? undefined });
    push({ id: 'duplicate', group: 'layer', labelKey: 'layerPanel.duplicateLayer', icon: '📑',
      disabled: !!editBlocked, disabledReasonKey: editBlocked ?? undefined });
    push({
      id: 'assign_purpose', group: 'layer', labelKey: 'layerPanel.assignPurpose', icon: '🎯',
      disabled: !!editBlocked || !!ctx.purpose,
      disabledReasonKey: editBlocked ?? (ctx.purpose ? 'layerPanel.alreadyHasPurpose' : undefined),
    });
    push({
      id: 'assign', group: 'layer', labelKey: 'layerPanel.assignLayer', icon: '🔗',
      disabled: !!editBlocked || empty,
      disabledReasonKey: editBlocked ?? (empty ? 'layerPanel.noFeaturesToAssign' : undefined),
    });
  }

  // C7: locking a permanently read-only layer means nothing.
  if (!ctx.readOnly) {
    push({
      id: 'lock',
      group: 'layer',
      labelKey: ctx.locked ? 'layerPanel.unlockLayer' : 'layerPanel.lockLayer',
      icon: ctx.locked ? '🔓' : '🔒',
    });
  }

  if (!isImported) {
    // C5: offering a move that cannot happen.
    push({
      id: 'move_up', group: 'layer', labelKey: 'layerPanel.moveUp',
      labelParams: { name: ctx.layerName }, icon: '⬆️',
      disabled: !!ctx.isFirst, disabledReasonKey: ctx.isFirst ? 'layerPanel.alreadyFirst' : undefined,
    });
    push({
      id: 'move_down', group: 'layer', labelKey: 'layerPanel.moveDown',
      labelParams: { name: ctx.layerName }, icon: '⬇️',
      disabled: !!ctx.isLast, disabledReasonKey: ctx.isLast ? 'layerPanel.alreadyLast' : undefined,
    });
  }

  // -------------------------------------------------------------- danger ----
  // N5: "Delete {name} Data" and "Remove" read as the same act and are not.
  // One empties the layer, the other deletes it. Both are named for what they
  // do, and both sit last.
  if (!isImported && BUILTIN_PURPOSE[ctx.layerId]) {
    push({
      id: 'clear_data',
      group: 'danger',
      labelKey: 'layerPanel.clearLayerData',
      labelParams: { name: ctx.layerName },
      icon: '🗑️',
      danger: true,
      disabled: !!editBlocked || empty,
      disabledReasonKey: editBlocked ?? (empty ? 'layerPanel.nothingToClear' : undefined),
    });
  }

  // Stem Mapping renders the Tree Inventory census; deleting it here is the same
  // act as the legacy Tree Mapping page's Delete button.
  if (!isImported && ctx.layerId === 'stem_mapping') {
    push({
      id: 'delete_stem_mapping',
      group: 'danger',
      labelKey: 'layerPanel.deleteStemMapping',
      icon: '🗑️',
      danger: true,
      disabled: (ctx.featureCount ?? 0) === 0,
      disabledReasonKey: (ctx.featureCount ?? 0) === 0 ? 'layerPanel.nothingToClear' : undefined,
    });
  }

  // Field Book owns real data of its own (unlike Stem Mapping, which is only
  // a view) -- a genuine delete, not a disabled pointer elsewhere.
  if (!isImported && ctx.layerId === 'fieldbook') {
    push({
      id: 'delete_field_book',
      group: 'danger',
      labelKey: 'layerPanel.deleteFieldbook',
      icon: '🗑️',
      danger: true,
      disabled: (ctx.featureCount ?? 0) === 0,
      disabledReasonKey: (ctx.featureCount ?? 0) === 0 ? 'layerPanel.nothingToClear' : undefined,
    });
  }

  // Sample Plots owns real data of its own too, same shape as Field Book --
  // owner report 2026-10-02. The "no field inventory data yet" gate itself
  // is enforced by the handler (it needs a live check, not something this
  // menu-building function can know), so this entry only disables on the
  // cheap, always-known condition: nothing to delete.
  if (!isImported && ctx.layerId === 'sample_plots') {
    push({
      id: 'delete_sample_plots',
      group: 'danger',
      labelKey: 'layerPanel.deleteSamplePlots',
      icon: '🗑️',
      danger: true,
      disabled: (ctx.featureCount ?? 0) === 0,
      disabledReasonKey: (ctx.featureCount ?? 0) === 0 ? 'layerPanel.nothingToClear' : undefined,
    });
  }

  if (isImported) {
    push({
      id: 'remove_layer',
      group: 'danger',
      labelKey: 'layerPanel.removeLayerNamed',
      labelParams: { name: ctx.layerName },
      icon: '❌',
      danger: true,
      disabled: !!editBlocked,
      disabledReasonKey: editBlocked ?? undefined,
    });
  }

  return items;
}

/**
 * Commands used now and then go under one "Advanced" fly-out (owner, 2026-10-17: "several buttons, unwanted things").
 * Applied by the renderers, not by buildLayerMenu (which stays the full model the tests read). Every item keeps its id, so the handlers and the tests that look an id up still work.
 * Fly-outs do not nest, so an item that has a submenu of its own is spread into the Advanced list (Style keeps its dialog too).
 * Dividing a forest stays in the main list until the forest has blocks or compartments, because a new user needs it first.
 */
const ADVANCED_IDS = new Set([
  'style', 'export', 'copy_features', 'paste_features', 'paste_as_layer', 'update_attributes', 'polygon_from_points',
  'move_up', 'move_down', 'duplicate', 'assign_purpose', 'assign',
]);
const ADVANCED_AFTER_STRUCTURE = new Set(['divide_equal_area', 'auto_divide']);

export function tuckAway(items: LayerMenuItem[], counts: Record<string, number> | undefined): LayerMenuItem[] {
  const structured = hasStructuralFeatures({ counts } as LayerMenuContext);
  const tucked: LayerMenuItem[] = [];
  const kept: LayerMenuItem[] = [];
  for (const item of items) {
    if (ADVANCED_IDS.has(item.id) || (structured && ADVANCED_AFTER_STRUCTURE.has(item.id))) tucked.push(item);
    else kept.push(item);
  }
  if (tucked.length === 0) return items;
  const flat: LayerMenuItem[] = [];
  for (const item of tucked) {
    const { submenu, ...own } = item;
    if (!submenu?.length || item.id === 'style') flat.push(submenu?.length ? own : item);
    flat.push(...(submenu ?? []).map((c) => ({ ...c, group: 'layer' as const })));
  }
  const at = kept.findIndex((i) => i.group === 'danger');
  const advanced: LayerMenuItem = {
    id: 'advanced', group: 'layer', labelKey: 'layerPanel.advanced', icon: '⚙️', submenu: flat.map((i) => ({ ...i, group: 'layer' as const })),
  };
  kept.splice(at === -1 ? kept.length : at, 0, advanced);
  return kept;
}

/** The same items, bucketed for a renderer that draws dividers between groups. */
export function groupLayerMenu(items: LayerMenuItem[]): Array<{ group: LayerMenuGroup; items: LayerMenuItem[] }> {
  return GROUP_ORDER
    .map((group) => ({ group, items: items.filter((i) => i.group === group) }))
    .filter((g) => g.items.length > 0);
}
