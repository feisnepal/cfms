import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import { readDetail } from '../hooks/useErrorHandler';
import i18n from '../i18n';

// === DIAGNOSTIC: Store instance identity (DEV only) ===
const STORE_INSTANCE_ID = Math.random().toString(36).slice(2, 10);
if (import.meta.env.DEV) {
  (window as any).__workspaceStoreInstances = (window as any).__workspaceStoreInstances || [];
  (window as any).__workspaceStoreInstances.push({
    id: STORE_INSTANCE_ID,
    url: import.meta.url,
    stack: new Error().stack?.split('\n').slice(1, 4).join(' | '),
  });
  console.log(`[StoreInstance] Created instance ${STORE_INSTANCE_ID} from ${import.meta.url}`);
}
import type { GeoJSON } from 'geojson';
import type { LayerTypeId, ToolbarMode } from '../lib/layerRegistry';
import { LAYER_DEFAULT_VISIBILITY, LAYER_ORDER, resolveLayerOrder } from '../lib/layerRegistry';
import type { RasterLayerMeta } from '../lib/rasterLegends';
import type { RasterLayerInfo } from '../services/api';
import { withGeoProps } from '../utils/computeGeometryProps';
import { defaultPropertiesForPurpose } from '../lib/defaultProperties';
import type { MapComposition } from '../lib/mapComposition';
import type { RendererSpec } from '../lib/layerRenderers';
import type { AnalysisMapId } from '../lib/analysisMaps';
import type { HazardUnits } from '../lib/hazardFeatureProps';
import type { UnitMapData, FieldInventoryUnits } from '../lib/unitMapProps';
import type { AttributeFilter } from '../lib/attributeFilter';
import type { GeometryOperation } from '../lib/editOperations';
import { CommandHistory } from '../lib/commandHistory';

/** Built-in overlay layer kinds (U06) */
export type OverlayKind = 'tree_clusters' | 'sampling';

/** POI categories returned by `GET /user-group/poi` (layer_type=all). */
export type UserGroupPoiType = 'education' | 'health' | 'poi' | 'rivers';

/** Fetch state for each overlay layer (U06/U01 A.2) */
export type OverlayFetchState = 'idle' | 'loading' | 'error' | 'ready';

/** Leaflet path options — avoids direct leaflet dep in store */
/** Completion of the user group step's data, for the User Group Boundary layer menu. */
export type UserGroupAnalysisState = 'idle' | 'running' | 'done' | 'failed' | 'skipped';

export interface UserGroupDataStatus {
  households: boolean;
  executive: boolean;
  other: boolean;
}

export interface PathStyleOptions {
  color?: string;
  weight?: number;
  opacity?: number;
  fillColor?: string;
  fillOpacity?: number;
  dashArray?: string;
  radius?: number;
}

export interface ImportedLayerInfo {
  id: number;
  name: string;
  purpose: string;
  format: string;
  featureCount: number;
  geometryTypes: string[];
  visible: boolean;
  order: number;
  fileSizeBytes?: number;
  createdAt?: string;
  /** GD: draft digitize layers (digitized on-screen) — finalized layers leave this false */
  isDraft?: boolean;
  /** GD: draft lifecycle — active | syncing | validation_failed | finalized */
  draftStatus?: string;
}

/** GD: sync state machine for the digitize draft buffer (Gap 3.1) */
export type DigitizeSyncState = 'idle' | 'syncing' | 'error' | 'recovery';

/** GD: the layer the Geoman draw path currently targets (Gap 3.2 union) */
export type ActiveDigitizeContext =
  | { mode: 'draft'; layer: ImportedLayerInfo }
  | { mode: 'append'; layer: ImportedLayerInfo; sourceLayerId: number }
  | null;

export interface EditEntry {
  type: 'column_label';
  layerId: number;
  key: string;
  oldLabel: string;
  newLabel: string;
}

export interface SelectionState {
  layerId: string | null;
  featureIds: string[];
  mode: 'replace' | 'add' | 'remove' | 'range';
}

export interface LayerVisibility {
  [layerId: string]: boolean;
}

export interface LayerOrder {
  [layerId: string]: number;
}

export interface BaseMapOption {
  id: string;
  label: string;
  labelKey?: string;
  url: string;
  attribution: string;
  maxZoom: number;
}

export interface WorkspaceState {
  activeLayerId: LayerTypeId | null;
  setActiveLayer: (id: LayerTypeId | null) => void;

  activeImportedLayerId: number | null;
  setActiveImportedLayer: (id: number | null) => void;

  layerVisibility: LayerVisibility;
  toggleLayerVisibility: (id: string) => void;
  setLayerVisibility: (id: string, visible: boolean) => void;
  showAllLayers: () => void;
  hideAllLayers: () => void;

  /** Per-layer manual lock (UI-only): layerId → 1 = user locked it. Unlocked by default. */
  layerLocks: Record<string, boolean>;
  setLayerLock: (id: string, locked: boolean) => void;
  toggleLayerLock: (id: string) => void;

  layerOrder: LayerOrder;
  moveLayerUp: (id: string) => void;
  moveLayerDown: (id: string) => void;
  setLayerOrder: (order: LayerOrder) => void;

  selection: SelectionState;
  selectFeatures: (layerId: string, featureIds: string[], mode?: SelectionState['mode'], rowOrder?: string[]) => void;
  clearSelection: () => void;
  toggleFeatureSelection: (layerId: string, featureId: string) => void;
  isFeatureSelected: (layerId: string, featureId: string) => boolean;

  toolbarMode: ToolbarMode;
  setToolbarMode: (mode: ToolbarMode) => void;

  activeBaseMap: string;
  setActiveBaseMap: (id: string) => void;
  baseMapOptions: BaseMapOption[];

  isLoading: Record<string, boolean>;
  setLoading: (key: string, loading: boolean) => void;
  errors: Record<string, string | null>;
  setError: (key: string, error: string | null) => void;
  clearAllErrors: () => void;

  featureCounts: Record<string, number>;
  setFeatureCount: (layerId: string, count: number) => void;

  /**
   * Monotonic per-layer load counter, bumped every time a layer's feature data
   * is successfully re-fetched. react-leaflet v5's GeoJSON never re-applies a
   * changed `data` prop (only `style`), so the map only shows fresh geometry
   * when its GeoJSON key remounts — keying on `geometryVersion` alone is not
   * enough because the refetch resolves *after* the bump-triggered remount.
   */
  layerLoadKeys: Record<string, number>;
  noteLayerLoaded: (layerId: string) => void;

  subLayerVisibility: Record<string, Record<string, boolean>>;
  toggleSubLayer: (parentId: string, subLayerId: string) => void;

  calculationId: string | null;
  setCalculationId: (id: string) => void;

  forestName: string;
  setForestName: (name: string) => void;

  dimensionMode: 'compartment' | 'block';
  toggleDimensionMode: () => void;

  structureLocked: boolean;
  setStructureLocked: (locked: boolean) => void;

  /** What the user group step already has (household list/totals, executive committee, other committees); null until read. */
  userGroupData: UserGroupDataStatus | null;
  setUserGroupData: (status: UserGroupDataStatus | null) => void;

  /** The automatic user group analysis (settlements, then land cover & biomass): shown as a status on the layer. */
  userGroupAnalysis: { state: UserGroupAnalysisState; message?: string | null; finishedAt?: string | null } | null;
  setUserGroupAnalysis: (status: { state: UserGroupAnalysisState; message?: string | null; finishedAt?: string | null } | null) => void;

  boundaryStatus: string;
  setBoundaryStatus: (status: string) => void;

  showLabels: boolean;
  setShowLabels: (show: boolean) => void;
  /** the forest-type card that follows the pointer over a classified unit; a viewing preference, remembered */
  showHoverInfo: boolean;
  setShowHoverInfo: (show: boolean) => void;

  /** Whether the map container is currently visible (for never-unmount invalidation). */
  mapVisible: boolean;
  setMapVisible: (visible: boolean) => void;

  /** Focus mode — hides all chrome (top nav, tabs, headers) for maximum map space. */
  focusMode: boolean;
  toggleFocusMode: () => void;
  setFocusMode: (enabled: boolean) => void;

  pendingFeature: GeoJSON.Feature | null;
  setPendingFeature: (feature: GeoJSON.Feature | null) => void;

  importedLayers: ImportedLayerInfo[];
  replaceImportedLayers: (layers: ImportedLayerInfo[]) => void;
  addImportedLayer: (layer: ImportedLayerInfo) => void;
  removeImportedLayer: (id: number) => void;
  renameImportedLayer: (id: number, name: string) => void;
  duplicateImportedLayer: (id: number) => void;
  setImportedLayerVisibility: (id: number, visible: boolean) => void;
  reorderImportedLayer: (id: number, direction: 'up' | 'down') => void;

  /** RS-2.16/P2.5: independent Auto-Block layers (one per source, unpromoted
   *  until promoted to be the forest's real blocks/compartments). Mirrors
   *  the imported-layer pattern above: an API-fetched array in the store,
   *  not a static LAYER_REGISTRY entry (LayerTypeId is a compile-time union). */
  rasterLayers: RasterLayerInfo[];
  replaceRasterLayers: (layers: RasterLayerInfo[]) => void;
  refreshRasterLayers: (calcId: string) => Promise<void>;

  // Owner directive 2026-10-01: an Auto-Block layer renders in the main
  // layer list, on the map, and in the attribute table exactly like a
  // built-in layer — its own geometry, its own one attribute column. Kept
  // as its own id/features pair (not merged into `activeLayerId`, which is
  // typed `LayerTypeId`, a closed compile-time union) rather than widening
  // that type across every consumer that branches on it.
  activeRasterLayerId: string | null;
  setActiveRasterLayer: (id: string | null) => void;
  rasterLayerFeatures: Record<string, GeoJSON.Feature[]>;
  fetchRasterLayerFeatures: (calcId: string, layerId: string) => Promise<void>;
  setRasterLayerFeatures: (id: string, features: GeoJSON.Feature[]) => void;

  importedLayerFeatures: Record<number, GeoJSON.Feature[]>;
  setImportedLayerFeatures: (id: number, features: GeoJSON.Feature[]) => void;

  importedFeatureVersion: Record<number, number>;

  /** GD: active digitize context — the layer the Geoman draw path targets */
  activeDigitizeContext: ActiveDigitizeContext;
  setActiveDigitizeContext: (ctx: ActiveDigitizeContext) => void;

  /** GD: buffered digitized features (authoritative pending list, flushed by useDraftSync) */
  digitizeDraftFeatures: Record<number, GeoJSON.Feature[]>;
  enqueueDigitizeFeature: (layerId: number, feature: GeoJSON.Feature) => void;
  removeDigitizeFeature: (layerId: number, featureId: string) => void;
  /** GD 1.3.4: replace the whole draft buffer (IndexedDB rehydration / server re-fetch) */
  setDigitizeDraftFeatures: (layerId: number, features: GeoJSON.Feature[]) => void;
  /** GD 1.3.4: clear the draft buffer after a successful flush */
  clearDigitizeDraftFeatures: (layerId: number) => void;

  /** GD: sync state machine for the draft buffer (Gap 3.1) */
  digitizeSyncState: DigitizeSyncState;
  setDigitizeSyncState: (state: DigitizeSyncState) => void;

  /** GD: draft digitize-layer lifecycle actions */
  createDigitizeLayer: (calcId: string, purpose: string, name: string) => Promise<ImportedLayerInfo>;
  finalizeDigitizeLayer: (calcId: string, layerId: number) => Promise<Record<string, unknown>>;
  /** GD 2.2.4 (review #1): discard a draft — soft-delete on server, clear buffer/context */
  discardDigitizeLayer: (calcId: string, layerId: number) => Promise<void>;

  layerLabelsVisible: Record<string, boolean>;
  setLayerLabelsVisible: (id: string, visible: boolean) => void;

  customLayerStyles: Record<string, PathStyleOptions>;
  setCustomLayerStyle: (layerId: string, style: PathStyleOptions) => void;
  removeCustomLayerStyle: (layerId: string) => void;

  // P4 — thematic renderer specs, keyed by bare layer id (`blocks`) or
  // `imported-<id>`. NOT persisted to localStorage (D8): the hook loads them
  // from and saves them to `calculation.result_data.layer_renderers`.
  layerRenderers: Record<string, RendererSpec>;
  setLayerRenderer: (layerKey: string, spec: RendererSpec | null) => void;
  hydrateLayerRenderers: (specs: Record<string, RendererSpec>) => void;

  // "Analysis maps" group: which SFM / hazard map colours the unit layers (or draws hazard tiles). One at a time;
  // null = off. Session-only. Colours the user changed live in `layerRenderers['analysis:<id>']`.
  activeAnalysisMap: AnalysisMapId | null;
  setActiveAnalysisMap: (id: AnalysisMapId | null) => void;
  /** what each cached hazard map says about every unit (labels, table columns); {} until loaded / when none computed */
  hazardUnits: HazardUnits;
  setHazardUnits: (u: HazardUnits) => void;
  /** which area the hazard maps show: the forest, or the user group (the print maps' __user_group variant) */
  analysisArea: 'forest' | 'user_group';
  setAnalysisArea: (a: 'forest' | 'user_group') => void;
  /** The floating Forest summary panel (open by default; closing and reopening is remembered per forest on the server). */
  forestSummaryOpen: boolean;
  setForestSummaryOpen: (open: boolean) => void;
  /** the active single-number field-inventory map's per-unit colours/labels from the server; null when none is active */
  unitMap: UnitMapData | null;
  setUnitMap: (d: UnitMapData | null) => void;
  /** raw per-unit field-inventory numbers (attribute-table columns); {} until loaded / when no inventory */
  fieldInventoryUnits: FieldInventoryUnits;
  setFieldInventoryUnits: (u: FieldInventoryUnits) => void;
  /** what "Run analysis" computed per unit, keyed by unit id (`an_*` values for the attribute tables); {} until loaded */
  unitAnalysis: Record<string, Record<string, string | number | boolean>>;
  setUnitAnalysis: (u: Record<string, Record<string, string | number | boolean>>) => void;
  /** the legend colour (lower-case #rrggbb) of the class the user clicked to isolate on the map; null = none. Cleared when the
   *  analysis map changes. */
  analysisHighlight: string | null;
  toggleAnalysisHighlight: (color: string) => void;
  /** the unit whose card is open: set by clicking a unit while an analysis map / chart is on (selection needs the layer armed in the panel;
   *  looking at a unit must not). Cleared whenever the selection changes or is cleared, and by the card's close button. */
  inspectedUnit: { layerId: string; id: string } | null;
  setInspectedUnit: (u: { layerId: string; id: string } | null) => void;
  /** a SECOND analysis map whose fact is added to the hover card (compare two maps without changing the colouring); null = none */
  compareMap: AnalysisMapId | null;
  setCompareMap: (id: AnalysisMapId | null) => void;
  /** the field-inventory chart drawn over the map (one at a time; null = none); independent of the exclusive Analysis map */
  activeChart: AnalysisMapId | null;
  setActiveChart: (id: AnalysisMapId | null) => void;
  /** opacity of the active hazard tile layer (0-1) */
  analysisOpacity: number;
  setAnalysisOpacity: (v: number) => void;

  // Stem Mapping "species in view" legend: what the map reports (tree count per prime species,
  // keyed by species code or 'other') and the species the user isolated, or null. Session-only
  // viewing aid, so it is not in `partialize`. The legend itself renders under the layer row.
  stemLegend: { counts: Record<string, number>; isolated: string | null };
  setStemLegendCounts: (counts: Record<string, number>) => void;
  setStemIsolated: (key: string | null) => void;

  // P4.6 — the active "show only matches on map" attribute filter, or null.
  // Session-only; MapCanvas hides non-matching features of `filter.layerId`.
  tableFilter: AttributeFilter | null;
  setTableFilter: (filter: AttributeFilter | null) => void;

  // P5.1 — features hidden from the map from the ⋮ row menu, per layer id.
  // Client-only, session-scoped.
  hiddenFeatureIds: Record<string, string[]>;
  toggleFeatureHidden: (layerId: string, featureId: string) => void;
  clearHiddenFeatures: (layerId: string) => void;

  // P5.2 — whole-layer opacity multiplier (0–1), per layer id. 1 = unchanged.
  layerAlpha: Record<string, number>;
  setLayerAlpha: (layerId: string, alpha: number) => void;

  /** Column label overrides for imported layers: layerId → originalKey → displayLabel */
  columnLabels: Record<number, Record<string, string>>;
  setColumnLabel: (layerId: number, originalKey: string, label: string) => void;

  /** Per imported layer: which attribute field to use for map labels. null = none */
  labelField: Record<number, string | null>;
  setLabelField: (layerId: number, field: string | null) => void;

  /** Per built-in layer: which attribute field to use for map labels. null = default label */
  builtinLabelField: Record<string, string | null>;
  /** Effective SFM forest type per block name, for the map's "Type-N" labels and hover cards (not persisted). */
  sfmBlockTypes: Record<string, import('../services/api').SfmBlockTypeInfo>;
  setSfmBlockTypes: (types: Record<string, import('../services/api').SfmBlockTypeInfo>) => void;
  setBuiltinLabelField: (layerId: string, field: string | null) => void;

  /** Session-only column width overrides (px): scopeKey → columnKey → width. scopeKey = layerId or `imported:<id>` */
  columnWidths: Record<string, Record<string, number>>;
  setColumnWidth: (scopeKey: string, colKey: string, width: number) => void;

  /** Session-only column display order: scopeKey → ordered column keys */
  columnOrder: Record<string, string[]>;
  setColumnOrder: (scopeKey: string, keys: string[]) => void;

  /** Column show/hide overrides: scopeKey → columnKey → visible. A missing
   *  entry means "use the column's `defaultHidden`". (P2.2) */
  columnVisibility: Record<string, Record<string, boolean>>;
  setColumnVisibility: (scopeKey: string, colKey: string, visible: boolean) => void;

  /** "Show only selected" toggle per layer scope (scopeKey = layerId or `imported:<id>`).
   *  Session-only; not persisted to localStorage. */
  showOnlySelected: Record<string, boolean>;
  setShowOnlySelected: (scopeKey: string, value: boolean) => void;
  getShowOnlySelected: (scopeKey: string) => boolean;

  /** Read-only raster overlays (session-only, no persistence) */
  activeRasterLayers: string[];
  toggleRasterLayer: (id: string) => void;
  rasterOpacity: number;
  setRasterOpacity: (opacity: number) => void;
  /** Raster catalog fetched from the backend (session-only, shared with LegendPanel) */
  rasterCatalog: RasterLayerMeta[];
  setRasterCatalog: (catalog: RasterLayerMeta[]) => void;

  /** POI overlay visibility inside the user-group results section (per type). */
  userGroupPoiVisible: Partial<Record<UserGroupPoiType, boolean>>;
  toggleUserGroupPoi: (type: UserGroupPoiType) => void;
  clearUserGroupPoi: () => void;

  /** Edit history for undo/redo */
  editHistory: EditEntry[];
  editFuture: EditEntry[];
  pushEdit: (entry: EditEntry) => void;
  undoEdit: () => EditEntry | null;
  redoEdit: () => EditEntry | null;

  /** Map lifecycle state machine (P3) */
  mapLifecycleStatus: string;
  setMapLifecycleStatus: (status: string) => void;

  // ── Map & Workspace Unification shell-state (U01) ────────────────────────
  /** SSOT for "the one selected feature". `selection.featureIds` is a derived projection (see notes). */
  selectedFeatureId: string | null;
  selectFeatureGlobal: (id: string | null) => void;

  // U10 — next/prev feature navigation (survey order with wrap-around)
  selectNextFeature: () => void;
  selectPreviousFeature: () => void;

  /** Persisted print/preview layout configs (U04). */
  mapCompositions: MapComposition[];
  activeCompositionId: string | null;
  setMapCompositions: (compositions: MapComposition[]) => void;
  setActiveComposition: (id: string | null) => void;

  /** Optimistic-lock clock (U02/A.5): bumped only AFTER a successful 2xx commit. */
  geometryVersion: number;
  bumpGeometryVersion: () => void;

  /** Owner report 2026-10-02: a narrower refetch trigger than
   *  `geometryVersion` for sample-plot add/move/delete, which don't change
   *  any OTHER layer -- bumping the global version on every plot drag
   *  refetched blocks/compartments/sub_areas/activity_features/boundary/...
   *  too, which is what made a single move feel slow. */
  samplePlotsRefreshVersion: number;
  bumpSamplePlotsRefreshVersion: () => void;

  /** True while there are uncommitted local geometry/attribute edits. */
  dirty: boolean;
  setDirty: (value: boolean) => void;

  /** 'simple' | 'advanced' workspace mode, persisted to localStorage. */
  uiMode: 'simple' | 'advanced';
  setUiMode: (mode: 'simple' | 'advanced') => void;

  /** Roles decoded from JWT at login (U01); source for toolEnabled (U07). */
  userRoles: string[];
  setUserRoles: (roles: string[]) => void;

  /** Background sync lifecycle (U02). */
  syncStatus: 'synced' | 'syncing' | 'error';
  setSyncStatus: (status: 'synced' | 'syncing' | 'error') => void;

  /** Unified refresh SSOT: re-pull imported features + bump geometryVersion once. */
  refreshAll: () => Promise<void>;

  /** Conflict flag raised when a server bump arrives while dirty (never auto-merges). */
  syncConflict: 'none' | 'stale_server';
  /** The authoritative server geometry_version last reported by a query/fetch. */
  serverGeometryVersion: number;
  /** Per-domain errors from the last refreshAll (keys like 'imported:<layerId>'). Empty object on clean refresh. */
  lastRefreshErrors: Record<string, string>;
  /**
   * U02 reconcile: absorb-when-clean / flag-when-dirty; never auto-rebase (single-primary-writer).
   * Returns `{}` when the field is unchanged (so a non-React subscription can detect equal state).
   */
  reconcileVersion: (serverVersion: number) => { rejected: boolean };

  // ── Built-in overlay layers (U06) ──────────────────────────────────────────
  /** Visible built-in overlay kinds (tree_clusters, sampling). */
  visibleBuiltins: OverlayKind[];
  /** Toggle a built-in overlay on/off. */
  toggleBuiltinOverlay: (kind: OverlayKind) => void;
  /** Set built-in overlay visibility explicitly. */
  setBuiltinOverlay: (kind: OverlayKind, visible: boolean) => void;

  /** Per-overlay fetch state (idle | loading | error | ready). */
  overlayFetchState: Record<OverlayKind, OverlayFetchState>;
  /** Update fetch state for an overlay. */
  setOverlayFetchState: (kind: OverlayKind, state: OverlayFetchState) => void;

  reset: () => void;

  // ── Command History (U13) ────────────────────────────────────────────────────
  /** Command history for undo/redo with dependency-graph cascade. */
  commandHistory: any; // CommandHistory instance
  /** Monotonic revision bumped on every push/undo/redo/clear so UI re-renders. */
  historyRevision: number;
  /** Primary operation of the last undo (for toolbar toast/button state). */
  lastUndoOperation: GeometryOperation | null;
  /** Primary operation of the last redo (for toolbar toast/button state). */
  lastRedoOperation: GeometryOperation | null;
  /** Push a geometry operation to history. */
  pushToHistory: (op: GeometryOperation) => void;
  /** Undo last operation (with dependency cascade). */
  undoFromHistory: () => GeometryOperation | null;
  /** Redo last undone operation. */
  redoFromHistory: () => GeometryOperation | null;
  /** Clear history. */
  clearHistory: () => void;
  /** Get history state for UI. */
  getHistoryState: () => { canUndo: boolean; canRedo: boolean; undoDepth: number; redoDepth: number; };
}

export const BASE_MAP_OPTIONS: BaseMapOption[] = [
  {
    id: 'none',
    label: 'None',
    labelKey: 'workspace.baseMap.none',
    url: '',
    attribution: '',
    maxZoom: 0,
  },
  {
    id: 'esri_satellite',
    label: 'Satellite',
    labelKey: 'workspace.baseMap.esriSatellite',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: '&copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 19,
  },
  {
    id: 'opentopo',
    label: 'Topographic',
    labelKey: 'workspace.baseMap.opentopo',
    url: 'https://tile.opentopomap.org/{z}/{x}/{y}.png',
    attribution: '&copy; OpenTopoMap contributors, SRTM | &copy; OpenStreetMap contributors',
    maxZoom: 17,
  },
  {
    id: 'osm_standard',
    label: 'OSM',
    labelKey: 'workspace.baseMap.osmStandard',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxZoom: 19,
  },
  {
    id: 'carto_dark',
    label: 'Dark',
    labelKey: 'workspace.baseMap.cartoDark',
    url: 'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  },
];

const DEFAULT_BASE_MAP = 'esri_satellite';

/**
 * Default show/hide for every built-in layer, DERIVED from
 * `LAYER_REGISTRY[].defaultVisible` rather than hand-written. The previous map
 * listed 4 of 11 layers and every read site fell back to "visible" for the
 * other 7 (`isVisible = layerVisibility[id] !== false`), so the registry and the
 * store could disagree with nothing to catch it. Now the registry is the only
 * place a default is written.
 */
const initialLayerVisibility: LayerVisibility = { ...LAYER_DEFAULT_VISIBILITY };

const initialVisibleBuiltins: OverlayKind[] = ['tree_clusters']; // default on
const initialOverlayFetchState: Record<OverlayKind, OverlayFetchState> = {
  tree_clusters: 'idle',
  sampling: 'idle',
};

/**
 * Default panel order for every built-in layer, DERIVED from
 * `LAYER_REGISTRY[].order`. The previous map seeded 4 layers, so `LayerPanel`'s
 * sort (`layerOrder[id] ?? 0`) tied the other 7 at zero and their real position
 * fell out of an array literal elsewhere — which is why the panel showed a
 * different order from the map and from the registry.
 */
const initialLayerOrder: LayerOrder = { ...LAYER_ORDER };

const initialSubLayerVisibility: Record<string, Record<string, boolean>> = {
  activity_features: {
    point: true,
    line: true,
    polygon: true,
  },
};

/**
 * Get ordered feature IDs for a given layer in survey order.
 * For imported layers, uses the feature order from importedLayerFeatures.
 * For built-in layers (blocks, sub_areas, etc.), returns feature IDs from the active layer's features.
 */
function getOrderedFeatureIds(state: WorkspaceState, layerId: string): string[] {
  // Imported layer: use the order from importedLayerFeatures (survey order)
  if (layerId.startsWith('imported:')) {
    const importedId = parseInt(layerId.replace('imported:', ''), 10);
    const features = state.importedLayerFeatures[importedId];
    if (features && features.length > 0) {
      return features.map((f) => f.properties?.featureId || f.properties?.id || f.id).filter(Boolean);
    }
    return [];
  }

  // Built-in layers: use featureIds from selection or active layer features
  // For now, fall back to selection.featureIds if available, else empty
  // TODO: Integrate with built-in layer feature stores when available
  const selection = state.selection;
  if (selection.featureIds.length > 0) {
    return selection.featureIds;
  }

  return [];
}

/**
 * Persist migration for the `workspace-store` localStorage slice. Exported so
 * it can be unit-tested independently of zustand's rehydration.
 * v2: drop stale imported-layer fields. v3 (WORKSPACE_LAYER_STYLING_PLAN.md P0):
 * built-in layer styles were bare-keyed (`blocks`) and shared across forests —
 * and never rendered. They are now `<calcId>::<layerId>`; drop the orphans.
 * v4 (FS-4a.18): `sub_blocks` (the block branch's own sub-level layer,
 * FS-4a.16) is a real registry layer now, but a `layerOrder` a returning user
 * already customised (via move up/down, which writes an EXPLICIT numeric
 * index for every layer it touches) predates it and carries no entry — the
 * `?? 0` read fallback (`LayerPanel.tsx`'s sort) would then tie `sub_blocks`
 * with whichever OTHER un-customised layer also defaults to 0, landing it in
 * an arbitrary slot instead of next to `blocks`. Seed it explicitly, same
 * relative offset the registry itself uses (`blocks: 1` → `sub_blocks: 1.5`).
 * `layerVisibility` gets the same treatment for symmetry, though every read
 * site already falls back to `true` for a missing key.
 * v5 (owner 2026-09-29: "I want the layer order as in the expected order
 * column"): the panel's order and show/hide defaults now come from ONE source —
 * `LAYER_REGISTRY[].order` / `.defaultVisible` — instead of a hand-written
 * 4-entry map in this file plus a `?? 0` / `?? true` fallback at each of ~7
 * read sites. Two consequences for a returning user:
 *   - `layerOrder` is REPLACED with the registry order. A stored order is not
 *     "the user's arrangement" — with only 4 of 11 layers ever seeded, 7 of them
 *     tied at 0 and their real position came from an array literal in
 *     `LayerPanel.tsx`. There was no meaningful customisation to preserve, and
 *     the owner asked for a specific order. Layers the user genuinely moved are
 *     the only casualty, and move up/down is one click to redo.
 *   - `layerVisibility` is FILLED IN for any built-in layer that has no entry.
 *     An entry the user set by clicking the eye is left alone; only missing keys
 *     are seeded, so a deliberate hide survives while a layer that was merely
 *     "visible because nothing said otherwise" now takes the registry default.
 */
export function migrateWorkspacePersist(persistedState: unknown, version: number): Record<string, unknown> {
  const state = persistedState as Record<string, unknown>;
  if (!version || version < 2) {
    delete state.importedLayers;
    delete state.importedLayerFeatures;
    delete state.importedFeatureVersion;
    delete state.activeImportedLayerId;
  }
  if (version < 3) {
    const styles = state.customLayerStyles as Record<string, unknown> | undefined;
    if (styles) {
      for (const k of Object.keys(styles)) {
        if (!k.startsWith('imported-') && !k.includes('::')) delete styles[k];
      }
    }
  }
  if (version < 4) {
    const order = state.layerOrder as Record<string, number> | undefined;
    if (order && !('sub_blocks' in order)) {
      order.sub_blocks = (order.blocks ?? 1) + 0.5;
    }
    const visibility = state.layerVisibility as Record<string, boolean> | undefined;
    if (visibility && !('sub_blocks' in visibility)) {
      visibility.sub_blocks = true;
    }
  }
  if (version < 5) {
    state.layerOrder = { ...LAYER_ORDER };
    const visibility = state.layerVisibility as Record<string, boolean> | undefined;
    if (visibility) {
      for (const [id, visible] of Object.entries(LAYER_DEFAULT_VISIBILITY)) {
        if (!(id in visibility)) visibility[id] = visible;
      }
    }
  }
  return state;
}

export function createInitialState(): WorkspaceState {
  return {
    activeLayerId: null,
    activeImportedLayerId: null,
    layerVisibility: { ...initialLayerVisibility },
    layerLocks: {},
    layerOrder: { ...initialLayerOrder },
    selection: { layerId: null, featureIds: [], mode: 'replace' },
    toolbarMode: 'select',
    activeBaseMap: DEFAULT_BASE_MAP,
    baseMapOptions: BASE_MAP_OPTIONS,
    isLoading: {},
    errors: {},
    featureCounts: {},
    layerLoadKeys: {},
    subLayerVisibility: { ...initialSubLayerVisibility },
    calculationId: null,
    forestName: '',
    dimensionMode: 'block',
    structureLocked: false,
    userGroupData: null,
    userGroupAnalysis: null,
    boundaryStatus: 'draft',
    showLabels: true,
    showHoverInfo: true,
    mapVisible: true,
    focusMode: false,
    setMapVisible: () => {},
    setFocusMode: () => {},
    toggleFocusMode: () => {},
    pendingFeature: null,
    setActiveLayer: () => {},
    toggleLayerVisibility: () => {},
    setLayerVisibility: () => {},
    setLayerLock: () => {},
    toggleLayerLock: () => {},
    showAllLayers: () => {},
    hideAllLayers: () => {},
    moveLayerUp: () => {},
    moveLayerDown: () => {},
    setLayerOrder: () => {},
    selectFeatures: () => {},
    clearSelection: () => {},
    toggleFeatureSelection: () => {},
    isFeatureSelected: () => false,
    setToolbarMode: () => {},
    setActiveBaseMap: () => {},
    setLoading: () => {},
    setError: () => {},
    clearAllErrors: () => {},
    setFeatureCount: () => {},
    noteLayerLoaded: () => {},
    toggleSubLayer: () => {},
    setCalculationId: () => {},
    setForestName: () => {},
    toggleDimensionMode: () => {},
    setPendingFeature: () => {},
    setBoundaryStatus: () => {},
    setStructureLocked: () => {},
    setUserGroupData: () => {},
    setUserGroupAnalysis: () => {},
    mapLifecycleStatus: 'draft',
    setMapLifecycleStatus: () => {},
    selectedFeatureId: null,
    selectFeatureGlobal: () => {},
    // U10
    selectNextFeature: () => {},
    selectPreviousFeature: () => {},
    mapCompositions: [],
    activeCompositionId: null,
    setMapCompositions: () => {},
    setActiveComposition: () => {},
    geometryVersion: 0,
    bumpGeometryVersion: () => {},
    samplePlotsRefreshVersion: 0,
    bumpSamplePlotsRefreshVersion: () => {},
    dirty: false,
    setDirty: () => {},
    uiMode: 'advanced',
    setUiMode: () => {},
    userRoles: [],
    setUserRoles: () => {},
    syncStatus: 'synced',
    setSyncStatus: () => {},
    refreshAll: async () => {},
    syncConflict: 'none',
    serverGeometryVersion: 0,
    lastRefreshErrors: {},
    reconcileVersion: () => ({ rejected: false }),
    importedLayers: [],
    replaceImportedLayers: () => {},
    addImportedLayer: () => {},
    removeImportedLayer: () => {},
    renameImportedLayer: () => {},
    duplicateImportedLayer: () => {},
    setImportedLayerVisibility: () => {},
    reorderImportedLayer: () => {},
    rasterLayers: [],
    replaceRasterLayers: () => {},
    refreshRasterLayers: async () => {},
    activeRasterLayerId: null,
    setActiveRasterLayer: () => {},
    rasterLayerFeatures: {},
    fetchRasterLayerFeatures: async () => {},
    setRasterLayerFeatures: () => {},
    importedLayerFeatures: {},
    setImportedLayerFeatures: () => {},
    importedFeatureVersion: {},
    activeDigitizeContext: null,
    setActiveDigitizeContext: () => {},
    digitizeDraftFeatures: {},
    enqueueDigitizeFeature: () => {},
    removeDigitizeFeature: () => {},
    setDigitizeDraftFeatures: () => {},
    clearDigitizeDraftFeatures: () => {},
    digitizeSyncState: 'idle',
    setDigitizeSyncState: () => {},
    createDigitizeLayer: async () => { throw new Error('not implemented'); },
    finalizeDigitizeLayer: async () => ({}),
    discardDigitizeLayer: async () => {},
    layerLabelsVisible: {},
    setLayerLabelsVisible: () => {},
    columnLabels: {},
    setColumnLabel: () => {},
    labelField: {},
    setLabelField: () => {},
    builtinLabelField: {},
    sfmBlockTypes: {},
    setBuiltinLabelField: () => {},
    setSfmBlockTypes: () => {},
    columnWidths: {},
    setColumnWidth: () => {},
    columnOrder: {},
    setColumnOrder: () => {},
    columnVisibility: {},
    setColumnVisibility: () => {},
    showOnlySelected: {},
    setShowOnlySelected: () => {},
    getShowOnlySelected: () => false,
    editHistory: [],
    editFuture: [],
    pushEdit: () => {},
    undoEdit: () => null,
    redoEdit: () => null,
    customLayerStyles: {},
    setCustomLayerStyle: () => {},
    removeCustomLayerStyle: () => {},
    layerRenderers: {},
    setLayerRenderer: () => {},
    hydrateLayerRenderers: () => {},
    activeAnalysisMap: null,
    setActiveAnalysisMap: () => {},
    hazardUnits: {},
    setHazardUnits: () => {},
    analysisArea: 'forest',
    setAnalysisArea: () => {},
    forestSummaryOpen: true,
    setForestSummaryOpen: () => {},
    activeChart: null,
    setActiveChart: () => {},
    analysisHighlight: null,
    toggleAnalysisHighlight: () => {},
    compareMap: null,
    setCompareMap: () => {},
    inspectedUnit: null,
    setInspectedUnit: () => {},
    unitMap: null,
    setUnitMap: () => {},
    fieldInventoryUnits: {},
    setFieldInventoryUnits: () => {},
    unitAnalysis: {},
    setUnitAnalysis: () => {},
    analysisOpacity: 0.85,
    setAnalysisOpacity: () => {},
    stemLegend: { counts: {}, isolated: null },
    setStemLegendCounts: () => {},
    setStemIsolated: () => {},
    tableFilter: null,
    setTableFilter: () => {},
    hiddenFeatureIds: {},
    toggleFeatureHidden: () => {},
    clearHiddenFeatures: () => {},
    layerAlpha: {},
    setLayerAlpha: () => {},
    activeRasterLayers: [],
    toggleRasterLayer: () => {},
    rasterOpacity: 0.5,
    setRasterOpacity: () => {},
    rasterCatalog: [],
    setRasterCatalog: () => {},
    userGroupPoiVisible: {},
    toggleUserGroupPoi: () => {},
    clearUserGroupPoi: () => {},
    setShowLabels: () => {},
    setShowHoverInfo: () => {},
    setActiveImportedLayer: () => {},
    // ── Built-in overlays (U06) ──────────────────────────────────────────────
    visibleBuiltins: initialVisibleBuiltins,
    toggleBuiltinOverlay: () => {},
    setBuiltinOverlay: () => {},
    overlayFetchState: initialOverlayFetchState,
    setOverlayFetchState: () => {},
    // ── Command History (U13) ────────────────────────────────────────────────
    commandHistory: null,
    historyRevision: 0,
    lastUndoOperation: null,
    lastRedoOperation: null,
    pushToHistory: () => {},
    undoFromHistory: () => null,
    redoFromHistory: () => null,
    clearHistory: () => {},
    getHistoryState: () => ({ canUndo: false, canRedo: false, undoDepth: 0, redoDepth: 0 }),
    reset: () => {},
  };
}

/**
 * Owner directive 2026-10-02: switching the layer panel's active layer while
 * mid-draw (Geoman armed via `activeDigitizeContext`) on a DIFFERENT imported
 * layer must not pop a confirm/discard dialog -- digitize drafts already
 * auto-save on their own (30s debounce, beforeunload, IndexedDB backing in
 * `useDraftSync`), so there is nothing a dialog would meaningfully protect.
 * Instead, flush the outgoing draft best-effort and silently drop out of the
 * draw session so Geoman doesn't stay armed for a layer the panel no longer
 * shows as active. `newImportedLayerId` is the imported-layer id the switch
 * is landing on, or null for a builtin/raster target (always "different").
 */
function bestEffortFlushDigitizeDraft(calcId: string, layerId: number, buffer: GeoJSON.Feature[]): void {
  if (buffer.length === 0) return;
  const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
  const token = localStorage.getItem('access_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const idempotencyKey = (crypto as any)?.randomUUID?.() ?? `draft-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  const chunks: GeoJSON.Feature[][] = [];
  for (let i = 0; i < buffer.length; i += 25) chunks.push(buffer.slice(i, i + 25));
  (async () => {
    try {
      for (const chunk of chunks) {
        const payload = {
          features: chunk.map((f) => ({
            clientTempId: (f.properties as Record<string, unknown>)?.featureId
              ?? (f.properties as Record<string, unknown>)?.id
              ?? (f as { id?: unknown }).id
              ?? '',
            feature: f,
            operation: 'upsert' as const,
          })),
          idempotency_key: idempotencyKey,
          mode: 'draft' as const,
        };
        const res = await fetch(
          `${baseUrl}/api/v1/workspace/${calcId}/digitize-layers/${layerId}/features/bulk`,
          { method: 'POST', headers: { ...headers, 'Idempotency-Key': idempotencyKey }, credentials: 'include', body: JSON.stringify(payload) },
        );
        if (!res.ok) throw new Error(`flush failed (${res.status})`);
      }
    } catch (err) {
      console.error('Background digitize draft flush on layer switch failed:', err);
    }
  })();
}

function exitDigitizeContextOnSwitch(
  get: () => WorkspaceState,
  set: (partial: Partial<WorkspaceState>) => void,
  newImportedLayerId: number | null,
): void {
  const s = get();
  const ctx = s.activeDigitizeContext;
  if (!ctx || ctx.layer.id === newImportedLayerId || !s.calculationId) return;
  const buffer = s.digitizeDraftFeatures[ctx.layer.id] || [];
  bestEffortFlushDigitizeDraft(s.calculationId, ctx.layer.id, buffer);
  set({ activeDigitizeContext: null });
}

export const useWorkspaceStore = create<WorkspaceState>()(
  devtools(
    persist(
      (set, get) => ({
        ...createInitialState(),

        setActiveLayer: (id) => {
          exitDigitizeContextOnSwitch(get, set, null);
          set({ activeLayerId: id, activeImportedLayerId: null, activeRasterLayerId: null });
          set({ toolbarMode: 'select' });
          if (id) {
            set((s) => ({ isLoading: { ...s.isLoading, [`features:${id}`]: true } }));
            // Working in a layer you cannot see is the failure the codebase
            // already patches over at each create/import handler ("a layer the
            // user had hidden would otherwise 'create nothing' as far as they
            // can see"). Those handlers only cover the three layers with a
            // create-modal. Doing it here covers every layer, and it is what
            // makes a hidden-by-default layer usable: Activity Features, Stem
            // Mapping, Sub-Areas, User Group and Field Book all start hidden by
            // default (owner 2026-09-29), so selecting one to draw into it
            // would otherwise leave the user drawing blind.
            set((s) =>
              s.layerVisibility[id] === false
                ? { layerVisibility: { ...s.layerVisibility, [id]: true } }
                : {},
            );
          }
          performance.mark(`layer:switch:${id}`);
        },

        setActiveImportedLayer: (id) => {
          exitDigitizeContextOnSwitch(get, set, id);
          set({ activeImportedLayerId: id, activeLayerId: null, activeRasterLayerId: null, toolbarMode: 'select' });
        },

        toggleLayerVisibility: (id) => {
          set((s) => ({
            // Layers are "visible unless explicitly false" everywhere they are
            // READ (isVisible = layerVisibility[id] !== false; the panel uses
            // `?? true`). `!s.layerVisibility[id]` broke that for any layer not
            // seeded in `initialLayerVisibility` — stem_mapping, compartments,
            // sub_compartments, sample_plots, user_group all start `undefined`,
            // and `!undefined === true`, so the first click to HIDE such a
            // layer set it to `true` (still visible) and it took two clicks.
            layerVisibility: { ...s.layerVisibility, [id]: s.layerVisibility[id] === false },
          }));
        },

        setLayerVisibility: (id, visible) => {
          set((s) => ({
            layerVisibility: { ...s.layerVisibility, [id]: visible },
          }));
        },

        setLayerLock: (id, locked) => {
          set((s) => ({
            layerLocks: { ...s.layerLocks, [id]: locked },
          }));
        },

        toggleLayerLock: (id) => {
          set((s) => ({
            layerLocks: { ...s.layerLocks, [id]: !s.layerLocks[id] },
          }));
        },

        // These two iterate `layerVisibility`'s own keys, so they only reached
        // the layers that had an entry. `initialLayerVisibility` now seeds all
        // 11 built-ins, which is what makes "show all" / "hide all" actually mean
        // all — before, 7 of 11 layers were untouched by either button.
        showAllLayers: () => {
          const allVisible: LayerVisibility = {};
          Object.keys(get().layerVisibility).forEach((k) => { allVisible[k] = true; });
          set({ layerVisibility: allVisible });
        },

        hideAllLayers: () => {
          const allHidden: LayerVisibility = {};
          Object.keys(get().layerVisibility).forEach((k) => { allHidden[k] = false; });
          set({ layerVisibility: allHidden });
        },

        // Move up/down swap a layer's index with its nearest neighbour, and both
        // resolve through `resolveLayerOrder` (explicit entry, else the registry
        // default). That fallback is what makes these work at all: while
        // `layerOrder` seeded only 4 layers, `order[id]` was `undefined` for the
        // other 7, every `v < undefined` comparison was false, and moving an
        // un-seeded layer silently did nothing.
        moveLayerUp: (id) => {
          set((s) => {
            const order = { ...s.layerOrder };
            const current = resolveLayerOrder(s.layerOrder, id as LayerTypeId);
            // Entries are [layerId, storedIndex]; compare by RESOLVED order so a
            // layer with no explicit index is still a real neighbour.
            const lowerEntries = Object.keys(order).filter(
              (k) => resolveLayerOrder(s.layerOrder, k as LayerTypeId) < current,
            );
            if (lowerEntries.length === 0) return s;
            // The nearest layer below `id`.
            const swapId = lowerEntries.sort(
              (a, b) => resolveLayerOrder(s.layerOrder, b as LayerTypeId) - resolveLayerOrder(s.layerOrder, a as LayerTypeId),
            )[0];
            order[id] = order[swapId];
            order[swapId] = current;
            return { layerOrder: order };
          });
        },

        moveLayerDown: (id) => {
          set((s) => {
            const order = { ...s.layerOrder };
            const current = resolveLayerOrder(s.layerOrder, id as LayerTypeId);
            const higherEntries = Object.keys(order).filter(
              (k) => resolveLayerOrder(s.layerOrder, k as LayerTypeId) > current,
            );
            if (higherEntries.length === 0) return s;
            // The nearest layer above `id`.
            const swapId = higherEntries.sort(
              (a, b) => resolveLayerOrder(s.layerOrder, a as LayerTypeId) - resolveLayerOrder(s.layerOrder, b as LayerTypeId),
            )[0];
            order[id] = order[swapId];
            order[swapId] = current;
            return { layerOrder: order };
          });
        },

        setLayerOrder: (order) => set({ layerOrder: order }),

        selectFeatures: (layerId, featureIds, mode = 'replace', rowOrder?) => {
          const current = get().selection;
          let newFeatureIds: string[];

          switch (mode) {
            case 'add':
              newFeatureIds = current.layerId === layerId
                ? [...new Set([...current.featureIds, ...featureIds])]
                : featureIds;
              break;
            case 'remove':
              newFeatureIds = current.layerId === layerId
                ? current.featureIds.filter((id) => !featureIds.includes(id))
                : current.featureIds;
              break;
            case 'range':
              newFeatureIds = calculateRangeSelection(
                current.featureIds,
                featureIds,
                current.layerId === layerId,
                rowOrder,
              );
              break;
            case 'replace':
            default:
              newFeatureIds = featureIds;
              break;
          }

          set({
            selection: { layerId, featureIds: newFeatureIds, mode: 'replace' },
            inspectedUnit: null,
          });
        },

        clearSelection: () => {
          set({ selection: { layerId: null, featureIds: [], mode: 'replace' }, inspectedUnit: null });
        },

        toggleFeatureSelection: (layerId, featureId) => {
          const current = get().selection;
          if (current.layerId !== layerId) {
            set({ selection: { layerId, featureIds: [featureId], mode: 'replace' } });
          } else {
            const exists = current.featureIds.includes(featureId);
            const newFeatureIds = exists
              ? current.featureIds.filter((id) => id !== featureId)
              : [...current.featureIds, featureId];
            set({ selection: { layerId, featureIds: newFeatureIds, mode: 'replace' } });
          }
        },

        isFeatureSelected: (layerId, featureId) => {
          const s = get().selection;
          return s.layerId === layerId && s.featureIds.includes(featureId);
        },

        setToolbarMode: (mode) => set({ toolbarMode: mode }),

        setActiveBaseMap: (id) => set({ activeBaseMap: id }),

        setLoading: (key, loading) => {
          set((s) => ({ isLoading: { ...s.isLoading, [key]: loading } }));
        },

        setError: (key, error) => {
          set((s) => ({ errors: { ...s.errors, [key]: error } }));
        },

        clearAllErrors: () => set({ errors: {} }),

        setFeatureCount: (layerId, count) => {
          set((s) => ({ featureCounts: { ...s.featureCounts, [layerId]: count } }));
        },

        noteLayerLoaded: (layerId) => {
          set((s) => ({
            layerLoadKeys: { ...s.layerLoadKeys, [layerId]: (s.layerLoadKeys[layerId] ?? 0) + 1 },
          }));
        },

        toggleSubLayer: (parentId, subLayerId) => {
          set((s) => {
            const parent = s.subLayerVisibility[parentId];
            if (!parent) return s;
            return {
              subLayerVisibility: {
                ...s.subLayerVisibility,
                [parentId]: { ...parent, [subLayerId]: !parent[subLayerId] },
              },
            };
          });
        },

        setCalculationId: (id) =>
          set({
            calculationId: id,
            importedLayers: [],
            importedLayerFeatures: {},
            importedFeatureVersion: {},
            activeImportedLayerId: null,
            activeRasterLayers: [],
            rasterCatalog: [],
            // RS-2.16 Auto-Block layers (distinct from `activeRasterLayers`
            // above, which is the raster TILE catalog, e.g. DEM/slope basemap
            // overlays) -- reset per calculation like importedLayers.
            rasterLayers: [],
            activeRasterLayerId: null,
            rasterLayerFeatures: {},
            userGroupPoiVisible: {},
            activeDigitizeContext: null,
            digitizeDraftFeatures: {},
            digitizeSyncState: 'idle',
          }),
        setForestName: (name) => set({ forestName: name }),

        toggleDimensionMode: () => {
          set((s) => ({
            dimensionMode: s.dimensionMode === 'block' ? 'compartment' : 'block',
          }));
        },

        setPendingFeature: (feature) => set({ pendingFeature: feature }),

        setStructureLocked: (locked) => set({ structureLocked: locked }),

        setUserGroupData: (status) => set({ userGroupData: status }),

        setUserGroupAnalysis: (status) => set({ userGroupAnalysis: status }),

        setBoundaryStatus: (status) => set({ boundaryStatus: status }),
        setMapLifecycleStatus: (status) => set({ mapLifecycleStatus: status }),

        replaceRasterLayers: (layers) => {
          set({ rasterLayers: layers });
        },

        refreshRasterLayers: async (calcId) => {
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = {};
          if (token) headers['Authorization'] = `Bearer ${token}`;
          try {
            const res = await fetch(
              `${baseUrl}/api/v1/calculations/${calcId}/auto-block-layers`,
              { headers, credentials: 'include' },
            );
            if (!res.ok) return;
            const data = await res.json();
            const layers: RasterLayerInfo[] = data.layers ?? [];
            get().replaceRasterLayers(layers);
          } catch (err) {
            // Best-effort refresh -- a failed re-fetch leaves the panel
            // showing the previous (possibly stale) list rather than
            // breaking the calling flow (matches the Auto-Block commit's
            // own error handling, which already reported success/failure).
            console.error('refreshRasterLayers failed:', err);
          }
        },

        setActiveRasterLayer: (id) => {
          exitDigitizeContextOnSwitch(get, set, null);
          set({
            activeRasterLayerId: id,
            activeLayerId: null,
            activeImportedLayerId: null,
            toolbarMode: 'select',
          });
        },

        fetchRasterLayerFeatures: async (calcId, layerId) => {
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = {};
          if (token) headers['Authorization'] = `Bearer ${token}`;
          try {
            const res = await fetch(
              `${baseUrl}/api/v1/calculations/${calcId}/auto-block-layers/${layerId}/features`,
              { headers, credentials: 'include' },
            );
            if (!res.ok) return;
            const data = await res.json();
            const features: GeoJSON.Feature[] = data.features ?? [];
            set((s) => ({
              rasterLayerFeatures: { ...s.rasterLayerFeatures, [layerId]: features },
            }));
          } catch (err) {
            console.error('fetchRasterLayerFeatures failed:', err);
          }
        },

        setRasterLayerFeatures: (id, features) => {
          set((s) => ({
            rasterLayerFeatures: { ...s.rasterLayerFeatures, [id]: features },
          }));
        },

        addImportedLayer: (layer) => {
          set((s) => ({
            importedLayers: [...s.importedLayers, {
              ...layer,
              visible: true,
              order: s.importedLayers.length,
            }],
          }));
        },

        replaceImportedLayers: (layers) => {
          set((s) => ({
            importedLayers: layers.map((l, i) => ({
              ...l,
              visible: l.visible ?? s.importedLayers.find((p) => p.id === l.id)?.visible ?? true,
              order: l.order ?? i,
            })),
          }));
        },

        removeImportedLayer: (id) => {
          set((s) => {
            const { [id]: _, ...rest } = s.importedLayerFeatures;
            const { [id]: _lf, ...labelField } = s.labelField;
            const { [id]: _cl, ...columnLabels } = s.columnLabels;
            const scopeKey = `imported:${id}`;
            const { [scopeKey]: _cw, ...columnWidths } = s.columnWidths;
            const { [scopeKey]: _co, ...columnOrder } = s.columnOrder;
            return {
              importedLayers: s.importedLayers.filter((l) => l.id !== id),
              importedLayerFeatures: rest,
              labelField,
              columnLabels,
              columnWidths,
              columnOrder,
            };
          });
        },

        setImportedLayerVisibility: (id, visible) => {
          set((s) => ({
            importedLayers: s.importedLayers.map((l) =>
              l.id === id ? { ...l, visible } : l,
            ),
          }));
        },

        reorderImportedLayer: (id, direction) => {
          set((s) => {
            const layers = [...s.importedLayers];
            const idx = layers.findIndex((l) => l.id === id);
            if (idx === -1) return s;
            const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
            if (swapIdx < 0 || swapIdx >= layers.length) return s;
            [layers[idx], layers[swapIdx]] = [layers[swapIdx], layers[idx]];
            return { importedLayers: layers };
          });
        },

        setImportedLayerFeatures: (id, features) => {
          set((s) => {
            const labelUpdates: Record<string, any> = {};
            const current = s.labelField[id];
            if (current === undefined || current === null) {
              const firstProps = features[0]?.properties;
              if (firstProps) {
                const nameKey = Object.keys(firstProps).find(
                  (k) => k.toLowerCase() === 'name',
                );
                if (nameKey) {
                  labelUpdates.labelField = { ...s.labelField, [id]: nameKey };
                }
              }
            }
            // Guarantee geo_* derived properties exist on every feature
            // (backfill for layers imported before backend auto-computation).
            const enriched = (features || []).map((f) => ({
              ...f,
              properties: withGeoProps(f.properties ?? {}, f.geometry),
            }));
            return {
              ...labelUpdates,
              importedLayerFeatures: { ...s.importedLayerFeatures, [id]: enriched },
              importedFeatureVersion: {
                ...s.importedFeatureVersion,
                [id]: (s.importedFeatureVersion[id] || 0) + 1,
              },
            };
          });
        },

        setActiveDigitizeContext: (ctx) => {
          set((s) => {
            // GD 1.4.3 (Gap 3.2): reject transitions while a flush is in-flight —
            // mutual exclusion, no draft + append at once.
            if (s.digitizeSyncState === 'syncing') return s;
            return { activeDigitizeContext: ctx };
          });
        },

        enqueueDigitizeFeature: (layerId, feature) => {
          set((s) => {
            // GD 2.2.5 (review #6): seed purpose defaults on every new feature so
            // the AttributeTable shows a stable, purpose-appropriate schema.
            const layer = s.importedLayers.find((l) => l.id === layerId);
            const defaults = layer ? defaultPropertiesForPurpose(layer.purpose) : {};
            const seeded: GeoJSON.Feature = {
              ...feature,
              properties: { ...defaults, ...(feature.properties || {}) },
            };
            return {
              digitizeDraftFeatures: {
                ...s.digitizeDraftFeatures,
                [layerId]: [...(s.digitizeDraftFeatures[layerId] || []), seeded],
              },
            };
          });
        },

        removeDigitizeFeature: (layerId, featureId) => {
          set((s) => {
            const current = s.digitizeDraftFeatures[layerId] || [];
            const next = current.filter((f) => {
              const id = (f.properties as Record<string, unknown>)?.featureId
                ?? (f.properties as Record<string, unknown>)?.id
                ?? (f as { id?: unknown }).id;
              return id !== featureId;
            });
            if (next.length === current.length) return s;
            return { digitizeDraftFeatures: { ...s.digitizeDraftFeatures, [layerId]: next } };
          });
        },

        setDigitizeDraftFeatures: (layerId, features) => {
          set((s) => ({
            digitizeDraftFeatures: { ...s.digitizeDraftFeatures, [layerId]: features },
          }));
        },

        clearDigitizeDraftFeatures: (layerId) => {
          set((s) => {
            if (!s.digitizeDraftFeatures[layerId]) return s;
            const next = { ...s.digitizeDraftFeatures };
            delete next[layerId];
            return { digitizeDraftFeatures: next };
          });
        },

        setDigitizeSyncState: (state) => set({ digitizeSyncState: state }),

        createDigitizeLayer: async (calcId, purpose, name) => {
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (token) headers['Authorization'] = `Bearer ${token}`;
          try {
            const res = await fetch(
              `${baseUrl}/api/v1/workspace/${calcId}/digitize-layers`,
              { method: 'POST', headers, credentials: 'include', body: JSON.stringify({ purpose, name }) },
            );
            if (!res.ok) {
              const detail = await readErrorDetail(res);
              throw new Error(detail || i18n.t('workspace.digitizeCreateFailed', { status: res.status }));
            }
            const data = await res.json();
            const layer: ImportedLayerInfo = {
              id: data.id as number,
              name: data.name as string,
              purpose: data.purpose as string,
              format: 'digitize',
              featureCount: data.feature_count as number,
              geometryTypes: (data.geometry_types as string[]) || [],
              visible: true,
              order: get().importedLayers.length,
              isDraft: true,
              draftStatus: (data.draft_status as string) || 'active',
            };
            get().addImportedLayer(layer);
            return layer;
          } catch (err) {
            console.error('createDigitizeLayer failed:', err);
            throw err;
          }
        },

        finalizeDigitizeLayer: async (calcId, layerId) => {
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (token) headers['Authorization'] = `Bearer ${token}`;
          try {
            const res = await fetch(
              `${baseUrl}/api/v1/workspace/${calcId}/digitize-layers/${layerId}/finalize`,
              { method: 'POST', headers, credentials: 'include', body: JSON.stringify({}) },
            );
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              const detail = data?.detail || i18n.t('workspace.digitizeFinalizeFailed', { status: res.status });
              set((s) => ({
                importedLayers: s.importedLayers.map((l) =>
                  l.id === layerId ? { ...l, draftStatus: 'validation_failed' } : l,
                ),
              }));
              throw new Error(detail);
            }
            const status = (data as Record<string, unknown>)?.status as string | undefined;
            const draftStatus = (data as Record<string, unknown>)?.draft_status as string | undefined;
            const finalized = status === 'succeeded' || draftStatus === 'finalized';
            set((s) => ({
              importedLayers: s.importedLayers.map((l) =>
                l.id === layerId
                  ? {
                      ...l,
                      isDraft: !finalized,
                      draftStatus: finalized ? 'finalized' : (draftStatus || 'syncing'),
                    }
                  : l,
              ),
            }));
            return data as Record<string, unknown>;
          } catch (err) {
            console.error('finalizeDigitizeLayer failed:', err);
            throw err;
          }
        },

        discardDigitizeLayer: async (calcId, layerId) => {
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (token) headers['Authorization'] = `Bearer ${token}`;
          try {
            const res = await fetch(
              `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${layerId}`,
              { method: 'DELETE', headers, credentials: 'include' },
            );
            if (!res.ok) {
              const detail = await readErrorDetail(res).catch(() => null);
              throw new Error(detail || i18n.t('workspace.digitizeDiscardFailed', { status: res.status }));
            }
            // Clear buffer + context + store entry, exit draw mode.
            set((s) => {
              const draftFeatures = { ...s.digitizeDraftFeatures };
              delete draftFeatures[layerId];
              return {
                digitizeDraftFeatures: draftFeatures,
                activeDigitizeContext: s.activeDigitizeContext?.layer.id === layerId ? null : s.activeDigitizeContext,
                toolbarMode: 'select',
                activeImportedLayerId: s.activeImportedLayerId === layerId ? null : s.activeImportedLayerId,
                digitizeSyncState: 'idle',
                importedLayers: s.importedLayers.filter((l) => l.id !== layerId),
                importedLayerFeatures: (() => {
                  const rest = { ...s.importedLayerFeatures };
                  delete rest[layerId];
                  return rest;
                })(),
              };
            });
          } catch (err) {
            console.error('discardDigitizeLayer failed:', err);
            throw err;
          }
        },

        renameImportedLayer: async (id, name) => {
          const prev = get().importedLayers.find((l) => l.id === id);
          set((s) => ({
            importedLayers: s.importedLayers.map((l) =>
              l.id === id ? { ...l, name } : l,
            ),
          }));
          const calcId = get().calculationId;
          if (!calcId || !prev || prev.name === name) return;
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (token) headers['Authorization'] = `Bearer ${token}`;
          const rollback = () => {
            set((s) => ({
              importedLayers: s.importedLayers.map((l) =>
                l.id === id ? { ...l, name: prev.name } : l,
              ),
            }));
          };
          try {
            const res = await fetch(
              `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${id}`,
              { method: 'PATCH', headers, credentials: 'include', body: JSON.stringify({ name }) },
            );
            if (!res.ok) rollback();
          } catch {
            rollback();
          }
        },

        duplicateImportedLayer: (id) => {
          set((s) => {
            const src = s.importedLayers.find((l) => l.id === id);
            if (!src) return s;
            const dupId = -(Date.now() % 1000000);
            const dup: ImportedLayerInfo = {
              ...src,
              id: dupId,
              name: i18n.t('workspace.layerCopySuffix', { name: src.name }),
              order: s.importedLayers.length,
            };
            const srcLabelField = s.labelField[id];
            return {
              importedLayers: [...s.importedLayers, dup],
              labelField: srcLabelField != null
                ? { ...s.labelField, [dupId]: srcLabelField }
                : s.labelField,
            };
          });
        },

        setCustomLayerStyle: (layerId, style) => {
          set((s) => ({
            customLayerStyles: { ...s.customLayerStyles, [layerId]: style },
          }));
        },

        removeCustomLayerStyle: (layerId) => {
          set((s) => {
            const rest = { ...s.customLayerStyles };
            delete rest[layerId];
            return { customLayerStyles: rest };
          });
        },

        setLayerRenderer: (layerKey, spec) => {
          set((s) => {
            const next = { ...s.layerRenderers };
            if (spec) next[layerKey] = spec;
            else delete next[layerKey];
            return { layerRenderers: next };
          });
        },
        hydrateLayerRenderers: (specs) => set({ layerRenderers: { ...specs } }),
        hazardUnits: {},
        setHazardUnits: (u) => set({ hazardUnits: u }),
        analysisArea: 'forest',
        setAnalysisArea: (a) => set({ analysisArea: a }),
        setForestSummaryOpen: (open) => set({ forestSummaryOpen: open }),
        activeChart: null,
        setActiveChart: (id) => set({ activeChart: id }),
        compareMap: null,
        setCompareMap: (id) => set({ compareMap: id }),
        inspectedUnit: null,
        setInspectedUnit: (u) => set({ inspectedUnit: u }),
        analysisHighlight: null,
        toggleAnalysisHighlight: (color) => set((s) => ({ analysisHighlight: s.analysisHighlight === color.toLowerCase() ? null : color.toLowerCase() })),
        unitMap: null,
        setUnitMap: (d) => set({ unitMap: d }),
        fieldInventoryUnits: {},
        setFieldInventoryUnits: (u) => set({ fieldInventoryUnits: u }),
        unitAnalysis: {},
        setUnitAnalysis: (u) => set({ unitAnalysis: u }),
        analysisOpacity: 0.85,
        setAnalysisOpacity: (v) => set({ analysisOpacity: Math.max(0.1, Math.min(1, v)) }),
        activeAnalysisMap: null,
        setActiveAnalysisMap: (id) =>
          set((s) => ({
            activeAnalysisMap: id,
            analysisHighlight: null, // a class isolated on the previous map means nothing on this one
            // an analysis map labels each unit with its main summary: make sure labels are on
            ...(id ? { showLabels: true } : {}),
            // an SFM / field-inventory map colours the unit layers: make sure they are on. The colours sit on the UNDIVIDED units (the
            // Sub-Blocks / Sub-Compartments layers hold every undivided unit), so those are switched on too - with only a divided parent
            // showing, the map would look uncoloured and the user would have to tick the sub layer by hand.
            layerVisibility: id && (id.startsWith('sfm_') || id.startsWith('fi_'))
              ? {
                  ...s.layerVisibility,
                  ...(s.layerVisibility.blocks === false && s.layerVisibility.compartments === false ? { blocks: true, compartments: true } : {}),
                  ...(s.layerVisibility.sub_blocks === false ? { sub_blocks: true } : {}),
                  ...(s.layerVisibility.sub_compartments === false ? { sub_compartments: true } : {}),
                }
              : s.layerVisibility,
          })),

        setStemLegendCounts: (counts) =>
          set((s) => {
            // The map reports on every pan; skip the write (and the re-render of the whole panel)
            // when nothing actually changed.
            const prev = s.stemLegend.counts;
            const keys = Object.keys(counts);
            const same = keys.length === Object.keys(prev).length && keys.every((k) => prev[k] === counts[k]);
            return same ? s : { stemLegend: { ...s.stemLegend, counts } };
          }),
        setStemIsolated: (key) => set((s) => ({ stemLegend: { ...s.stemLegend, isolated: key } })),

        setTableFilter: (filter) => set({ tableFilter: filter }),

        // hiddenFeatureIds + layerAlpha are keyed per calculation (`<calcId>::<layerId>`)
        // like customLayerStyles, so a choice on one forest never bleeds into another
        // and both survive a reload (persisted).
        toggleFeatureHidden: (layerId, featureId) => set((s) => {
          const key = `${s.calculationId ?? 'nc'}::${layerId}`;
          const cur = s.hiddenFeatureIds[key] ?? [];
          const next = cur.includes(featureId) ? cur.filter((x) => x !== featureId) : [...cur, featureId];
          return { hiddenFeatureIds: { ...s.hiddenFeatureIds, [key]: next } };
        }),
        clearHiddenFeatures: (layerId) => set((s) => {
          const rest = { ...s.hiddenFeatureIds };
          delete rest[`${s.calculationId ?? 'nc'}::${layerId}`];
          return { hiddenFeatureIds: rest };
        }),
        setLayerAlpha: (layerId, alpha) => set((s) => ({
          layerAlpha: { ...s.layerAlpha, [`${s.calculationId ?? 'nc'}::${layerId}`]: alpha },
        })),

        toggleRasterLayer: (id) => {
          set((s) => ({
            activeRasterLayers: s.activeRasterLayers.includes(id)
              ? s.activeRasterLayers.filter((l) => l !== id)
              : [...s.activeRasterLayers, id],
          }));
        },

        setRasterOpacity: (opacity) => set({ rasterOpacity: opacity }),

        setRasterCatalog: (catalog) => set({ rasterCatalog: catalog }),

        toggleUserGroupPoi: (type) => set((s) => ({
          userGroupPoiVisible: { ...s.userGroupPoiVisible, [type]: !s.userGroupPoiVisible[type] },
        })),

        clearUserGroupPoi: () => set({ userGroupPoiVisible: {} }),

        setLayerLabelsVisible: (id, visible) => {
          set((s) => ({
            layerLabelsVisible: { ...s.layerLabelsVisible, [id]: visible },
          }));
        },

        setColumnLabel: (layerId, originalKey, label) => {
          set((s) => ({
            columnLabels: {
              ...s.columnLabels,
              [layerId]: { ...(s.columnLabels[layerId] || {}), [originalKey]: label },
            },
          }));
        },

        setLabelField: (layerId, field) => {
          set((s) => {
            const current = s.labelField[layerId];
            if (current === field) return s;
            return {
              labelField: { ...s.labelField, [layerId]: field },
              importedFeatureVersion: {
                ...s.importedFeatureVersion,
                [layerId]: (s.importedFeatureVersion[layerId] || 0) + 1,
              },
            };
          });
        },

        setSfmBlockTypes: (types) => set({ sfmBlockTypes: types }),

        setBuiltinLabelField: (layerId, field) => {
          set((s) => {
            const current = s.builtinLabelField[layerId];
            if (current === field) return s;
            return { builtinLabelField: { ...s.builtinLabelField, [layerId]: field } };
          });
        },

        setColumnWidth: (scopeKey, colKey, width) => {
          set((s) => ({
            columnWidths: {
              ...s.columnWidths,
              [scopeKey]: { ...(s.columnWidths[scopeKey] || {}), [colKey]: Math.max(40, Math.round(width)) },
            },
          }));
        },

        setColumnOrder: (scopeKey, keys) => {
          set((s) => ({ columnOrder: { ...s.columnOrder, [scopeKey]: keys } }));
        },

        setColumnVisibility: (scopeKey, colKey, visible) => {
          set((s) => ({
            columnVisibility: {
              ...s.columnVisibility,
              [scopeKey]: { ...(s.columnVisibility[scopeKey] || {}), [colKey]: visible },
            },
          }));
        },

        setShowOnlySelected: (scopeKey, value) => {
          set((s) => ({
            showOnlySelected: {
              ...s.showOnlySelected,
              [scopeKey]: value,
            },
          }));
        },

        getShowOnlySelected: (scopeKey) => {
          return get().showOnlySelected[scopeKey] ?? false;
        },

        pushEdit: (entry) => {
          set((s) => ({
            editHistory: [...s.editHistory.slice(-49), entry],
            editFuture: [],
          }));
        },

        undoEdit: () => {
          const state = get();
          if (state.editHistory.length === 0) return null;
          const entry = state.editHistory[state.editHistory.length - 1];

          if (entry.type === 'column_label') {
            const currentLabels = state.columnLabels[entry.layerId] || {};
            set({
              editHistory: state.editHistory.slice(0, -1),
              editFuture: [...state.editFuture, entry],
              columnLabels: {
                ...state.columnLabels,
                [entry.layerId]: { ...currentLabels, [entry.key]: entry.oldLabel },
              },
            });
          }

          return entry;
        },

        redoEdit: () => {
          const state = get();
          if (state.editFuture.length === 0) return null;
          const entry = state.editFuture[state.editFuture.length - 1];

          if (entry.type === 'column_label') {
            const currentLabels = state.columnLabels[entry.layerId] || {};
            set({
              editFuture: state.editFuture.slice(0, -1),
              editHistory: [...state.editHistory, entry],
              columnLabels: {
                ...state.columnLabels,
                [entry.layerId]: { ...currentLabels, [entry.key]: entry.newLabel },
              },
            });
          }

          return entry;
        },

        setShowLabels: (show) => set({ showLabels: show }),
        setShowHoverInfo: (show) => set({ showHoverInfo: show }),

        setMapVisible: (visible: boolean) => set({ mapVisible: visible }),

        /** Focus mode — hides all chrome for maximum map space. */
        setFocusMode: (enabled: boolean) => set({ focusMode: enabled }),
        toggleFocusMode: () => set((s) => ({ focusMode: !s.focusMode })),
        selectFeatureGlobal: (id) => {
          const state = get();
          if (state.selectedFeatureId === id) return; // guard same-id no-op
          // selectedFeatureId is the SSOT; keep selection.featureIds in sync (derived projection).
          set({
            selectedFeatureId: id,
            selection: id
              ? { layerId: state.activeLayerId, featureIds: [id], mode: 'replace' }
              : { layerId: null, featureIds: [], mode: 'replace' },
          });
        },

        // U10 — next/prev feature navigation (survey order with wrap-around)
        selectNextFeature: () => {
          const state = get();
          const currentId = state.selectedFeatureId;
          const activeLayerId = state.activeLayerId || (state.activeImportedLayerId ? `imported:${state.activeImportedLayerId}` : null);
          if (!currentId || !activeLayerId) return;

          const orderedIds = getOrderedFeatureIds(state, activeLayerId);
          if (orderedIds.length <= 1) return;

          const currentIndex = orderedIds.indexOf(currentId);
          if (currentIndex === -1) return;

          const nextIndex = (currentIndex + 1) % orderedIds.length;
          state.selectFeatureGlobal(orderedIds[nextIndex]);
        },

        selectPreviousFeature: () => {
          const state = get();
          const currentId = state.selectedFeatureId;
          const activeLayerId = state.activeLayerId || (state.activeImportedLayerId ? `imported:${state.activeImportedLayerId}` : null);
          if (!currentId || !activeLayerId) return;

          const orderedIds = getOrderedFeatureIds(state, activeLayerId);
          if (orderedIds.length <= 1) return;

          const currentIndex = orderedIds.indexOf(currentId);
          if (currentIndex === -1) return;

          const prevIndex = (currentIndex - 1 + orderedIds.length) % orderedIds.length;
          state.selectFeatureGlobal(orderedIds[prevIndex]);
        },

        setMapCompositions: (compositions) => set({ mapCompositions: compositions }),

        setActiveComposition: (id) => set({ activeCompositionId: id }),

        bumpGeometryVersion: () =>
          // Only called after a successful 2xx commit; a commit also clears the stale-server conflict.
          set((s) => ({ geometryVersion: s.geometryVersion + 1, syncConflict: 'none' })),

        bumpSamplePlotsRefreshVersion: () =>
          set((s) => ({ samplePlotsRefreshVersion: s.samplePlotsRefreshVersion + 1 })),

        setDirty: (value) => set({ dirty: value }),

        setUiMode: (mode) => set({ uiMode: mode }),

        setUserRoles: (roles) => set({ userRoles: roles }),

        setSyncStatus: (status) => set({ syncStatus: status }),

        refreshAll: async () => {
          const s = get();
          if (s.syncStatus === 'syncing') return;
          const calcId = s.calculationId;
          if (!calcId) return;
          set({ syncStatus: 'syncing', lastRefreshErrors: {} });
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = {};
          if (token) headers['Authorization'] = `Bearer ${token}`;

          const errors: Record<string, string> = {};
          const layers = s.importedLayers;
          if (layers.length > 0) {
            await Promise.all(
              layers.map(async (layer) => {
                try {
                  const res = await fetch(
                    `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${layer.id}/features`,
                    { headers, credentials: 'include' },
                  );
                  if (res.ok) {
                    const data = await res.json();
                    get().setImportedLayerFeatures(layer.id, data.features || []);
                  } else {
                    errors[`imported:${layer.id}`] = i18n.t('workspace.httpStatus', { status: res.status });
                  }
                } catch (err: any) {
                  errors[`imported:${layer.id}`] = err?.message || i18n.t('workspace.refreshImportedFailed');
                }
              }),
            );
          }

          set((st) => ({
            geometryVersion: st.geometryVersion + 1,
            syncStatus: 'synced',
            lastRefreshErrors: errors,
          }));
        },

        reconcileVersion: (serverVersion) => {
          const s = get();
          if (serverVersion <= s.geometryVersion) return { rejected: false }; // no-op
          if (!s.dirty) {
            // Safe absorb: external base change invalidates redo; no UI.
            set({ geometryVersion: serverVersion, serverGeometryVersion: serverVersion, syncConflict: 'none' });
            return { rejected: false };
          }
          // Dirty + newer server → DO NOT absorb, DO NOT auto-rebase. Raise the stale_server conflict.
          set({ serverGeometryVersion: serverVersion, syncConflict: 'stale_server' });
          return { rejected: true };
        },

        // ── Built-in overlays (U06) ──────────────────────────────────────────────
        toggleBuiltinOverlay: (kind) =>
          set((s) => ({
            visibleBuiltins: s.visibleBuiltins.includes(kind)
              ? s.visibleBuiltins.filter((k) => k !== kind)
              : [...s.visibleBuiltins, kind],
          })),
        setBuiltinOverlay: (kind, visible) =>
          set((s) => ({
            visibleBuiltins: visible
              ? s.visibleBuiltins.includes(kind)
                ? s.visibleBuiltins
                : [...s.visibleBuiltins, kind]
              : s.visibleBuiltins.filter((k) => k !== kind),
          })),
        setOverlayFetchState: (kind, state) =>
          set((s) => ({
            overlayFetchState: { ...s.overlayFetchState, [kind]: state },
          })),

        // ── Command History (U13) ────────────────────────────────────────────────
        pushToHistory: (op) => {
          const s = get();
          let history = s.commandHistory;
          if (!history) {
            history = new CommandHistory();
          }
          history.push(op);
          set({ commandHistory: history, historyRevision: s.historyRevision + 1 });
        },
        undoFromHistory: () => {
          const s = get();
          if (!s.commandHistory || !s.commandHistory.canUndo) return null;
          const result = s.commandHistory.undo();
          const primary = result?.primary ?? null;
          set({
            commandHistory: s.commandHistory,
            historyRevision: s.historyRevision + 1,
            lastUndoOperation: primary,
            lastRedoOperation: null,
          });
          return primary;
        },
        redoFromHistory: () => {
          const s = get();
          if (!s.commandHistory || !s.commandHistory.canRedo) return null;
          const result = s.commandHistory.redo();
          const primary = result?.primary ?? null;
          set({
            commandHistory: s.commandHistory,
            historyRevision: s.historyRevision + 1,
            lastRedoOperation: primary,
            lastUndoOperation: null,
          });
          return primary;
        },
        clearHistory: () => {
          const s = get();
          if (s.commandHistory) {
            s.commandHistory.clear();
          }
          set({ commandHistory: s.commandHistory, historyRevision: s.historyRevision + 1 });
        },
        getHistoryState: () => {
          const s = get();
          if (!s.commandHistory) {
            return { canUndo: false, canRedo: false, undoDepth: 0, redoDepth: 0 };
          }
          return {
            canUndo: s.commandHistory.canUndo,
            canRedo: s.commandHistory.canRedo,
            undoDepth: s.commandHistory.undoStackDepth,
            redoDepth: s.commandHistory.redoStackDepth,
          };
        },

        reset: () => set(createInitialState()),
      }),
      {
        name: 'workspace-store',
        version: 5,
        migrate: (persistedState, version) => migrateWorkspacePersist(persistedState, version),
        partialize: (state) => ({
          showHoverInfo: state.showHoverInfo,
          activeBaseMap: state.activeBaseMap,
          layerVisibility: state.layerVisibility,
          layerOrder: state.layerOrder,
          customLayerStyles: state.customLayerStyles,
          layerAlpha: state.layerAlpha,
          hiddenFeatureIds: state.hiddenFeatureIds,
          layerLabelsVisible: state.layerLabelsVisible,
          columnLabels: state.columnLabels,
          labelField: state.labelField,
          builtinLabelField: state.builtinLabelField,
          uiMode: state.uiMode,
          visibleBuiltins: state.visibleBuiltins,
        }),
      },
    ),
    { name: 'WorkspaceStore' },
  ),
);

async function readErrorDetail(res: Response): Promise<string | null> {
  try {
    const body = (await res.json()) as { detail?: unknown; correlation_id?: unknown } | null;
    return readDetail(body?.detail, body?.correlation_id);
  } catch {
    return null;
  }
}

function calculateRangeSelection(
  currentIds: string[],
  clickedIds: string[],
  sameLayer: boolean,
  rowOrder?: string[],
): string[] {
  if (!sameLayer || currentIds.length === 0) return clickedIds;

  const orderedIds = rowOrder ?? [...new Set([...currentIds, ...clickedIds])];
  const anchor = currentIds[currentIds.length - 1];
  const click = clickedIds[0];
  const anchorIdx = orderedIds.indexOf(anchor);
  const clickIdx = orderedIds.indexOf(click);

  if (anchorIdx === -1 || clickIdx === -1) return clickedIds;

  const start = Math.min(anchorIdx, clickIdx);
  const end = Math.max(anchorIdx, clickIdx);
  return orderedIds.slice(start, end + 1);
}
