import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import L from 'leaflet';
import * as turf from '@turf/turf';
import '@geoman-io/leaflet-geoman-free';
import '@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css';
import { Button, message, Modal } from 'antd';
import { forestApi, userGroupApi, samplingApi, fieldInventoryApi } from '../services/api';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useT } from '../i18n/hooks';
import i18nInstance from '../i18n/index';
import { readDetail } from '../hooks/useErrorHandler';
import { apiErrorText } from '../lib/apiErrorText';
import { parseLocaleNumber } from '../i18n/numberFormat';
import { readBoundaryValidation, findingText } from '../lib/boundaryValidation';
import { LayerPanel } from './LayerPanel';
import { AttributeTable } from './AttributeTable';
import GeometryEditorToolbar from './GeometryEditorToolbar';
import { PasteCategoryModal } from './PasteCategoryModal';
import { useContextMenuUndoRedo } from '../hooks/useContextMenuUndoRedo';
import { useFeatureClipboard } from '../hooks/useFeatureClipboard';
import { useDraftSync } from '../hooks/useDraftSync';
import { useLayerRenderers } from '../hooks/useLayerRenderers';
import { filterForMap, dropHiddenFeatures } from '../lib/attributeFilter';
import { WorkspaceStatusBar } from './WorkspaceStatusBar';
import { WorkspaceHeader } from './WorkspaceHeader';
import { WorkspaceError } from './WorkspaceError';
import { MapCanvas } from './MapCanvas';
import { ForestSummaryPanel } from './ForestSummaryPanel';
import { LegendPanel } from './LegendPanel';
import { getLayerConfig, LAYER_REGISTRY } from '../lib/layerRegistry';
import { mergeUnitLayerProps } from '../lib/unitLayerMerge';
import type { LayerTypeId } from '../lib/layerRegistry';
import { buildStylePatch, coerceAttributeValue } from '../lib/layerStyles';
import { zoomToLayerBounds, fitBoundsWhenVisible } from '../lib/mapZoom';
import { SubAreaCategoryPicker } from './SubAreaCategoryPicker';
import { isTouchDevice } from '../lib/touchDevice';
import { getTouchGeomanOptions, getTouchPmDrawOptions } from '../lib/touchGeometry';
import { snapToBlock } from '../lib/snapToBlock';
import { setMapRef } from '../lib/mapRef';
import { getFeatureLayerRegistry } from '../lib/featureLayerRegistry';
import { useBoundaryPreview } from '../contexts/BoundaryPreviewContext';
import { needsBoundaryReview, provisionalFromError } from '../lib/boundaryPreviewPending';
import { enableRegistryLayerGeoman } from '../lib/geomanSpikeEdit';
import { enableGeometryEdit, enableMoveGesture } from '../lib/geometryEditLifecycle';
import { SharedEdgeIndex } from '../lib/sharedEdgeIndex';
import { computeSharedMoves, computeSharedVertexChange, type SharedMoveResult } from '../lib/vertexSharedMove';
import {
  collectVertexMarkers,
  featureGeometryOf,
  liveGeometryOf,
  shellGeometryFor,
} from '../lib/vertexEditMask';
import {
  classifyVertices,
  coordAtIndex,
  isOnBoundary,
  LAYER_TYPES,
  type ClassifiableLayerType,
  type VertexClassification,
} from '../lib/vertexClassifier';
import { applyImportedMerge, featureIdOf } from '../lib/geometryMerge';
import { authHeaders } from '../lib/geometryUndo';
import { computeSplitPreview } from '../lib/splitPreview';
import { computeNewDrawPreview } from '../lib/newDrawPreview';
import { buildPendingPlacesLayer } from '../lib/pendingPlacesLayer';
import { startCustomDrawSession, type CustomDrawSession, type DrawKind, type DrawMeasurement } from '../lib/customDrawSession';
import { BlockEditCollisionWarning } from './BlockEditCollisionWarning';
import { CompletionModal } from './CompletionModal';
import { AutoBlockDesigner } from './AutoBlockDesigner';
import { UpdateAttributeDialog } from './UpdateAttributeDialog';
import { useNavigate } from 'react-router-dom';
import { toSurfaceId } from '../lib/calcSurface';
import SamplePlotCreateModal from './SamplePlotCreateModal';
import StemMappingModal from './StemMappingModal';
import UserGroupModal from './UserGroupModal';
import UserGroupDataModal from './UserGroupDataModal';
import { useUserGroupDataStatus } from '../hooks/useUserGroupDataStatus';
import { useAutoAnalysisRun } from '../hooks/useAutoAnalysisRun';
import { ACTIVITY_KIND_IDS, activityKindCountKey } from '../lib/activityKinds';
import { EqualAreaDividePanel } from './EqualAreaDividePanel';
import { FireLinePanel } from './FireLinePanel';
import AssignLayerModal from './AssignLayerModal';
import AssignPurposeModal from './AssignPurposeModal';
import { DockPanel } from './DockPanel';
import { useWorkspaceLayout } from '../hooks/useWorkspaceLayout';
import { Group, Panel, Separator } from 'react-resizable-panels';
import type { LayoutChangedMeta } from 'react-resizable-panels';
import { allowedGeometryTypes } from '../lib/purposeGeometryRules';
import { pointsAreNonCollinear } from '../lib/geometryValidation';
import { saveActivityFeatureEdit } from '../features/yearly-plan/featureEdit';
import { formatNumber } from '../i18n/numberFormat';
import { planTableErrorMessage } from '../features/yearly-plan/planErrors';
import { PlanExportMenu } from '../features/yearly-plan/PlanExportMenu';
import { NextStepBar } from '../features/yearly-plan/NextStepBar';
import { YearlyDoneBar } from './YearlyActivities/YearlyDoneBar';
import { ActivityWizard } from '../features/yearly-plan/wizard/ActivityWizard';
import { useWizardHost } from '../features/yearly-plan/wizard/useWizardHost';
import { usePlanAccess } from '../features/yearly-plan/usePlanAccess';
import { PlanTable, TableViewSwitch } from '../features/yearly-plan/PlanTable';
import type { TableView } from '../features/yearly-plan/planTableRules';
import { isYearlyPlanGuidanceEnabled } from '../config/featureFlags';
import { createAttributeEditOperation, createDigitizeAddOperation, createDigitizeDeleteByIdOperation, createFeatureDeleteOperation, createSplitOperation, createMergeOperation, createVertexEditOperation } from '../lib/operationFactories';
import type { ActiveDigitizeContext } from '../store/workspaceStore';
import { PlanLinesChoiceError, chooseWhatHappensToPlanLines } from '../lib/planLinesChoice';
import { SubAreaPlanBadge, SubAreaPlanDialog, useSubAreaPlanStatus } from '../features/yearly-plan/SubAreaPlanDialog';
import {
  fetchDeleteGuard,
  snapshotFeature,
  deleteFeatureRow,
  type FeatureRowContext,
  type FeatureDeleteLayerType,
} from '../lib/featureRowOps';

/** The four unit layers the operations engine's divide/auto-divide entry
 *  points work on (FS-4a.17) — the two branches (block / compartment), each
 *  with its own sub-level. */
type DivideLayerId = 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments';

// === DIAGNOSTIC: Module execution proof (DEV only) ===
const MODULE_MARKER = 'MW_V9_' + Math.random().toString(36).slice(2, 6);
if (import.meta.env.DEV) {
  (window as any).__moduleMarkers = (window as any).__moduleMarkers || {};
  (window as any).__moduleMarkers['MapWorkspace'] = {
    marker: MODULE_MARKER,
    time: Date.now(),
    url: import.meta.url,
  };
  console.log(`[ModuleMarker] MapWorkspace executed with marker ${MODULE_MARKER}`);
}
// UNCONDITIONAL sentinel — set even in prod bundles; proves which JS executed.
if (typeof document !== 'undefined' && document.documentElement) {
  document.documentElement.dataset.mwMarker = MODULE_MARKER;
}

/**
 * Resolve a feature→layer from the registry, retrying briefly to absorb the
 * MapCanvas remount race (onEachFeature registers during render / after async
 * data loads; layers are removed→re-added on every refresh).
 */
const E2_ID = Math.random().toString(36).slice(2, 8);

function useRegisteredLayer(
  featureId: string | null,
  enabled: boolean,
  maxWaitMs = 400,
  /** Bumped after each successful commit; re-polls the registry so the hook
   *  resolves the post-refetch *live* layer instead of a stale pre-remount copy.
   *  This is what stops "add-vertex then markers vanish": without it the
   *  vertex_edit effect re-arms Geoman against the doomed old layer. */
  version: number = 0,
): L.Layer | null {
  const [layer, setLayer] = useState<L.Layer | null>(null);
  useEffect(() => {
    if (!featureId || !enabled) {
      setLayer(null);
      return;
    }
    let cancelled = false;
    const start = Date.now();
    const check = () => {
      if (cancelled) return;
      const reg = getFeatureLayerRegistry();
      if (reg.has(featureId)) {
        setLayer(reg.get(featureId) as L.Layer);
        return;
      }
      if (Date.now() - start < maxWaitMs) {
        window.setTimeout(check, 40);
      } else {
        setLayer(null);
      }
    };
    check();
    return () => {
      cancelled = true;
      setLayer(null);
    };
    }, [featureId, enabled, maxWaitMs, version]);
  return layer;
}

interface MapWorkspaceProps {
  calculationId: string;
  forestName?: string;
  initialActiveLayer?: LayerTypeId;
  context?: 'block_naming' | 'sub_areas' | 'activity_features' | 'boundary_edit' | 'unified' | 'compartments' | 'sub_compartments';
}

/**
 * Surface a boundary-validation report from a drawn boundary: a rejection
 * (errors) opens a modal with the reasons; a clip-to-Nepal (warnings) pops a
 * warning toast. Returns true when there were errors (caller should stop).
 */
function reportDrawnBoundary(
  source: unknown,
  t: (k: string) => string,
): boolean {
  const rep = readBoundaryValidation(source);
  if (!rep) return false;
  const lang = i18nInstance.language;
  if (rep.errors.length) {
    Modal.error({
      title: t('boundaryValidation.rejectedTitle'),
      content: (
        <ul style={{ paddingLeft: 18, margin: '8px 0 0' }}>
          {rep.errors.map((f, i) => (
            <li key={`${f.code}-${i}`}>{findingText(f, lang)}</li>
          ))}
        </ul>
      ),
    });
    return true;
  }
  if (rep.warnings.length) {
    message.warning(rep.warnings.map((w) => findingText(w, lang)).join(' '));
  }
  return false;
}

export function MapWorkspace({
  calculationId,
  forestName,
  initialActiveLayer,
  context,
}: MapWorkspaceProps) {
  const store = useWorkspaceStore();
  const t = useT();
  const { reviewBoundary } = useBoundaryPreview();
  // The workspace is opened with the forest's id (the wrapper passes no name), so it asks for the name itself. Without it the header said
  // "Calculation #5f982600", the print map was titled "Forest" and the exports were named Forest_...
  const [loadedForestName, setLoadedForestName] = useState('');
  useEffect(() => {
    if (forestName) return undefined;
    let cancelled = false;
    forestApi
      .getCalculation(calculationId)
      .then((c) => {
        if (!cancelled) setLoadedForestName(c?.forest_name || c?.block_name || '');
      })
      .catch(() => undefined); // the name is a label: without it the header falls back to the id
    return () => {
      cancelled = true;
    };
  }, [calculationId, forestName]);
  const shownForestName = forestName || loadedForestName;
  const setStoreForestName = store.setForestName;
  useEffect(() => {
    if (shownForestName) setStoreForestName(shownForestName);
  }, [shownForestName, setStoreForestName]);
  const [map, setMap] = useState<L.Map | null>(null);
  const [pendingCategory, setPendingCategory] = useState<string | null>(null);
  const [showCategoryPicker, setShowCategoryPicker] = useState(false);
  // P6 category-first draw: armed when "Add Sub-Area" launched the picker to
  // choose a category BEFORE drawing. Mirrors pendingCategory for draw closure.
  const [addSubAreaArm, setAddSubAreaArm] = useState(false);
  // U-4 (Task 4.1, case E): interactive "Create Polygon from Points".
  const [pointPick, setPointPick] = useState<{ target: string; points: [number, number][]; layerId?: LayerTypeId } | null>(null);
  const pendingCategoryRef = useRef<string | null>(null);
  // Block-boundary invariant (E.8): set when "New Block / New Compartment"
  // armed the builtin polygon-draw tool. Guards against the digitize-draw
  // effect stealing the same pm:create event.
  const newDrawArmRef = useRef<'blocks' | 'compartments' | null>(null);
  const [snapEnabled, setSnapEnabled] = useState(true);
  // Split cut-line draft: vertices are accumulated from Geoman (`pm:vertexadded`)
  // and the cut is committed via an explicit "Finish & Split" button — never by
  // a drawing gesture, which misfires and leaves 2-3 point cuts (UE-0.x).
  const splitCutRef = useRef<L.LatLng[]>([]);
  const [splitCutCount, setSplitCutCount] = useState(0);
  // UE-0.1 EXT: live split area preview — recomputed on every cut click/vertex
  // drag, mirrors the backend cut_polygon exactly.
  const [splitPreview, setSplitPreview] = useState<ReturnType<typeof computeSplitPreview> | null>(null);
  const splitPreviewElsRef = useRef<{ layers: L.Layer[]; labels: L.Marker[] }>({ layers: [], labels: [] });
  // E.8 EXT (scissor-like + button): the "＋ New Block / New Compartment" draw is
  // armed exactly like the split cut-line — click to add ANY number of vertices
  // (zig-zag included), a live area preview for the resulting block, and commit
  // only via the explicit "Finish & Create" button.
  const newDrawCutRef = useRef<L.LatLng[]>([]);
  const [newDrawCount, setNewDrawCount] = useState(0);
  const [newDrawPreview, setNewDrawPreview] = useState<ReturnType<typeof computeNewDrawPreview> | null>(null);
  // Unified Geometry Drawing plan (P1/P3/P4): sub-area polygon draw now uses
  // customDrawSession — movable/deletable vertices while drawing + a live
  // area readout (Asks 2/3) — instead of Geoman's own Polygon draw, which has
  // neither (P0 finding). Mirrors the E.8 pattern above.
  const subAreaDrawSessionRef = useRef<CustomDrawSession | null>(null);
  const [subAreaDrawVertexCount, setSubAreaDrawVertexCount] = useState(0);
  const [subAreaDrawMeasurement, setSubAreaDrawMeasurement] = useState<DrawMeasurement | null>(null);
  // Forest boundary digitize: a forest can be several disjoint islands, so the
  // draw tool ACCUMULATES polygons and commits them together on an explicit
  // "Finish" — one → PUT boundary, many → mergeForestBoundary (MultiPolygon).
  const boundaryIslandsRef = useRef<GeoJSON.Polygon[]>([]);
  const [boundaryIslandCount, setBoundaryIslandCount] = useState(0);
  // Unified Geometry Drawing plan (P1): the current in-progress island's
  // customDrawSession — Asks 2/3 (movable/deletable vertices + a live vertex
  // count while drawing THIS piece), replacing Geoman's Polygon draw.
  const boundaryDrawSessionRef = useRef<CustomDrawSession | null>(null);
  const [boundaryDrawVertexCount, setBoundaryDrawVertexCount] = useState(0);
  const [boundaryDrawMeasurement, setBoundaryDrawMeasurement] = useState<DrawMeasurement | null>(null);
  const userGroupDrawSessionRef = useRef<CustomDrawSession | null>(null);
  const [userGroupDrawVertexCount, setUserGroupDrawVertexCount] = useState(0);
  const [userGroupDrawMeasurement, setUserGroupDrawMeasurement] = useState<DrawMeasurement | null>(null);
  const activityDrawSessionRef = useRef<CustomDrawSession | null>(null);
  const [activityDrawVertexCount, setActivityDrawVertexCount] = useState(0);
  const [activityDrawMeasurement, setActivityDrawMeasurement] = useState<DrawMeasurement | null>(null);
  // UE-2: resolved active-layer context used by merge/move commit payloads
  // (works for builtin layers and imported workspace layers alike).  Kept in a
  // ref so imperative handlers read the CURRENT layer without re-arming.
  type ActiveLayerCtx = { kind: 'builtin' | 'imported'; id: string; layerType: string; layerId?: number };
  const activeLayerRef = useRef<ActiveLayerCtx | null>(null);
  useEffect(() => {
    if (store.activeLayerId) {
      activeLayerRef.current = { kind: 'builtin', id: store.activeLayerId, layerType: store.activeLayerId };
    } else if (store.activeImportedLayerId != null) {
      activeLayerRef.current = { kind: 'imported', id: `imported:${store.activeImportedLayerId}`, layerType: 'imported', layerId: store.activeImportedLayerId };
    } else {
      activeLayerRef.current = null;
    }
  }, [store.activeLayerId, store.activeImportedLayerId]);
  const [activityRefreshKey, setActivityRefreshKey] = useState(0);
  // the add-activity wizard (YEARLY_ACTIVITIES plan P3): its data, and the link to the drawing tools
  const wizardHost = useWizardHost(calculationId, store, store.geometryVersion);
  // D9: only the owner plans the yearly activities. For anyone else the plan routes answer 404, so the write controls
  // are not offered at all (a wizard that cannot save is worse than none), and the plan table says why.
  const planAccess = usePlanAccess(calculationId, isYearlyPlanGuidanceEnabled());
  const canPlan = planAccess !== 'notOwner';
  const canPlanRef = useRef(canPlan);
  canPlanRef.current = canPlan;
  // the dock table shows either the active layer's features or the yearly plan behind the Activity Features (P4)
  const [tableView, setTableView] = useState<TableView>('features');
  // bumped when the plan changes from the Yearly plan table (a line confirmed) so the Next-step bar re-reads it
  const [planVersion, setPlanVersion] = useState(0);
  // Sub-areas must be tied to the yearly plan: after drawing one we ask "What will you do here?"; the badge lists what is still open.
  const [subAreaPlanDialog, setSubAreaPlanDialog] = useState<{ open: boolean; focusId: string | null }>({ open: false, focusId: null });
  const subAreaPlan = useSubAreaPlanStatus(calculationId, `${store.geometryVersion}:${planVersion}`);
  const planViewOn = isYearlyPlanGuidanceEnabled() && tableView === 'plan';
  const showTableSwitch = isYearlyPlanGuidanceEnabled() && (store.activeLayerId === 'activity_features' || tableView === 'plan');
  const [collisionWarning, setCollisionWarning] = useState<{ visible: boolean; blockId: string; blockName: string; pendingAction: (() => void) | null }>({ visible: false, blockId: '', blockName: '', pendingAction: null });
  const [completionModalOpen, setCompletionModalOpen] = useState(false);
  const lastStatusRef = useRef(store.mapLifecycleStatus);
  // Auto-Block MMU (Phase B): null when closed; level when the designer is open.
  const [autoBlockLevel, setAutoBlockLevel] = useState<'blocks' | 'compartments' | null>(null);
  // Divide ONE selected block / compartment by a natural basis (river-ridge, slope, aspect, canopy).
  const [autoDivideParent, setAutoDivideParent] = useState<{ id: string; name: string } | null>(null);
  // "Update attribute" (layer menu / attribute-table toolbar): refresh the available attribute components.
  const [updateAttributeOpen, setUpdateAttributeOpen] = useState(false);
  useEffect(() => {
    const open = () => setUpdateAttributeOpen(true);
    window.addEventListener('open-update-attribute', open);
    return () => window.removeEventListener('open-update-attribute', open);
  }, []);
  // Sub-areas layer menu -> "Fire lines…": the tick-list of boundaries and roads, and the draw tool with a width per segment.
  const [fireLinesOpen, setFireLinesOpen] = useState(false);
  useEffect(() => {
    const open = () => setFireLinesOpen(true);
    window.addEventListener('open-fire-lines', open);
    return () => window.removeEventListener('open-fire-lines', open);
  }, []);
  // ... and "River banks…": the same panel for the 20 m banks of the rivers (a protection area)
  const [riverBanksOpen, setRiverBanksOpen] = useState(false);
  useEffect(() => {
    const open = () => setRiverBanksOpen(true);
    window.addEventListener('open-river-banks', open);
    return () => window.removeEventListener('open-river-banks', open);
  }, []);
  // Sample-plots layer menu -> "Upload field inventory": the Field Inventory step, whose first tab is Upload data.
  const navigateToInventory = useNavigate();
  useEffect(() => {
    const open = () => {
      if (calculationId) navigateToInventory(`/calculations/${calculationId}?surface=${toSurfaceId('field', 'fieldinventory')}`);
    };
    window.addEventListener('open-field-inventory', open);
    return () => window.removeEventListener('open-field-inventory', open);
  }, [calculationId, navigateToInventory]);
  // Sample Plots layer → "Create sample plots…": the sampling design form, over the map.
  const [samplePlotModalOpen, setSamplePlotModalOpen] = useState(false);
  // Stem Mapping layer → "Import Stem Mapping": the full Tree Mapping process, over the map.
  const [stemMappingModalOpen, setStemMappingModalOpen] = useState(false);
  // User Group Boundary layer → "User Group Analysis": the analysis + results, over the map.
  const [userGroupModalOpen, setUserGroupModalOpen] = useState(false);
  // User Group Boundary layer → household information / executive committee / other committees, over the map. The menu shows what is in.
  const [userGroupData, setUserGroupDataDialog] = useState<{ open: boolean; section: 'households' | 'committee' }>({ open: false, section: 'households' });
  const refreshUserGroupData = useUserGroupDataStatus(calculationId);
  // The analysis starts by itself when the polygons change; when a run finishes the layer and its data are re-read.
  useAutoAnalysisRun(calculationId, () => store.bumpGeometryVersion());
  useEffect(() => {
    const open = (e: Event) => setUserGroupDataDialog({ open: true, section: (e as CustomEvent).detail?.section === 'committee' ? 'committee' : 'households' });
    window.addEventListener('open-user-group-data', open);
    return () => window.removeEventListener('open-user-group-data', open);
  }, []);
  // `?open=households|committee` (the export checklist's shortcuts): open that dialog once, then drop the parameter so a
  // reload does not reopen it.
  useEffect(() => {
    const url = new URL(window.location.href);
    const want = url.searchParams.get('open');
    if (want !== 'households' && want !== 'committee') return;
    setUserGroupDataDialog({ open: true, section: want });
    url.searchParams.delete('open');
    window.history.replaceState(window.history.state, '', url.pathname + (url.search || '') + url.hash);
  }, []);
  // `?draw=<plan line id>` (the Draw button of a row on the Yearly Activities step): open the add-activity questions for that line at
  // "where", with its shape armed. `&return=yearly` brings the user back to the grid once the place is saved.
  const returnToYearlyGridRef = useRef(false);
  useEffect(() => {
    const url = new URL(window.location.href);
    const lineId = url.searchParams.get('draw');
    if (!lineId) return;
    returnToYearlyGridRef.current = url.searchParams.get('return') === 'yearly';
    url.searchParams.delete('draw');
    url.searchParams.delete('return');
    window.history.replaceState(window.history.state, '', url.pathname + (url.search || '') + url.hash);
    void wizardHost.openForStep({ key: 'NO_LOCATION', text: '', button: '', action: 'show_on_map', activityId: lineId, confirmable: false });
    // once, on arrival
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // Compartment rewire (B.4/B.5): set when the "Divide Equal-Area" row button
  // picks a target layer + selected parent feature.
  const [divideTarget, setDivideTarget] = useState<{ layerId: DivideLayerId; featureId: string } | null>(null);
  const [assignLayerModalInfo, setAssignLayerModalInfo] = useState<{ visible: boolean; layerId: number | null; layerName: string }>({ visible: false, layerId: null, layerName: '' });
  const [assignPurposeModalInfo, setAssignPurposeModalInfo] = useState<{ visible: boolean; layerId: number | null; layerName: string }>({ visible: false, layerId: null, layerName: '' });

  useEffect(() => {
    const handleOpenAssign = (e: any) => {
      setAssignLayerModalInfo({
        visible: true,
        layerId: e.detail?.layerId ?? null,
        layerName: e.detail?.layerName ?? '',
      });
    };
    const handleOpenAssignPurpose = (e: any) => {
      setAssignPurposeModalInfo({
        visible: true,
        layerId: e.detail?.layerId ?? null,
        layerName: e.detail?.layerName ?? '',
      });
    };
    window.addEventListener('open-assign-layer-modal', handleOpenAssign as EventListener);
    window.addEventListener('open-assign-purpose-modal', handleOpenAssignPurpose as EventListener);
    return () => {
      window.removeEventListener('open-assign-layer-modal', handleOpenAssign as EventListener);
      window.removeEventListener('open-assign-purpose-modal', handleOpenAssignPurpose as EventListener);
    };
  }, []);

  // Esc clears the feature selection (QGIS-style). Skipped while typing in a
  // field, or while a draw/edit tool is armed — there, Esc cancels the tool.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      const s = useWorkspaceStore.getState();
      if (s.activeDigitizeContext) return;
      if (s.toolbarMode && s.toolbarMode !== 'select') return;
      if (s.selection.featureIds.length || s.selectedFeatureId) {
        s.clearSelection();
        s.selectFeatureGlobal(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const openAutoBlockDesigner = useCallback((lvl: 'blocks' | 'compartments') => {
    setAutoBlockLevel(lvl);
  }, []);
  const closeAutoBlockDesigner = useCallback(() => setAutoBlockLevel(null), []);
  const openSamplePlotModal = useCallback(() => setSamplePlotModalOpen(true), []);
  const closeSamplePlotModal = useCallback(() => setSamplePlotModalOpen(false), []);
  const openStemMappingModal = useCallback(() => setStemMappingModalOpen(true), []);
  const closeStemMappingModal = useCallback(() => setStemMappingModalOpen(false), []);
  const openUserGroupModal = useCallback(() => setUserGroupModalOpen(true), []);
  const closeUserGroupModal = useCallback(() => setUserGroupModalOpen(false), []);

  // BL-5 (GAP_HANDLING_PLAN.md, block lifecycle decoupling): "Import
  // Block/Compartment from Forest Boundary" — regenerates the single
  // boundary-mirroring block or compartment once the user has deliberately
  // cleared it (Decision A/B). Reuses the existing create-single-block
  // endpoint (is_compartment=true for the compartments layer); enabled only
  // when no structural features exist (layerMenu.ts gates the menu item
  // itself, per layer).
  const handleImportBlockFromBoundary = useCallback(async (layerId?: string) => {
    if (!calculationId) return;
    const isCompartment = layerId === 'compartments';
    try {
      await forestApi.createSingleBlock(calculationId, undefined, isCompartment);
      store.bumpGeometryVersion();
      message.success(t(isCompartment
        ? 'layerPanel.importCompartmentFromBoundarySuccess'
        : 'layerPanel.importBlockFromBoundarySuccess'));
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      message.error(
        typeof detail === 'string'
          ? detail
          : t(isCompartment
            ? 'layerPanel.importCompartmentFromBoundaryFailed'
            : 'layerPanel.importBlockFromBoundaryFailed'),
      );
    }
  }, [calculationId, store, t]);

  // B.2 — context-driven initial active layer (compartments / sub_compartments
  // contexts reopen their own layer pre-activated so divide stays surface-level).
  // The `store.activeLayerId !== layer` guard is load-bearing: `store` is the
  // whole (selector-less) store object, so it gets a fresh identity on every
  // state change and this effect re-runs constantly. `setActiveLayer` always
  // writes a new `isLoading` object, so calling it unconditionally here feeds
  // itself — render → setActiveLayer → new store ref → effect → setActiveLayer …
  // → "Maximum update depth exceeded". With the guard the re-run is a no-op
  // once the layer is active.
  useEffect(() => {
    if (!context && !initialActiveLayer) return;
    const layer = initialActiveLayer
      ?? (context === 'compartments' ? 'compartments'
        : context === 'sub_compartments' ? 'sub_compartments' : null);
    if (layer && store.activeLayerId !== layer) store.setActiveLayer(layer);
  }, [context, initialActiveLayer, store]);

  // Block-boundary invariant (E.8): "New Block / New Compartment" — arm the
  // scissor-style click-draw tool on the builtin layer; the draw effect below
  // accumulates a multi-point polygon and the "Finish & Create" button posts it
  // to POST /calculations/{id}/blocks/draw.
  const handleNewDraw = useCallback((lvl: 'blocks' | 'compartments') => {
    newDrawArmRef.current = lvl;
    newDrawCutRef.current = [];
    setNewDrawCount(0);
    setNewDrawPreview(null);
    store.setActiveLayer(lvl);
    store.setToolbarMode('draw_polygon');
    message.info(t('workspace.draw.newFeatureHint', {
      type: lvl === 'compartments' ? t('workspace.types.compartment') : t('workspace.types.block'),
    }), 4);
  }, [store, t]);
  const { canUndo, canRedo, undo, redo, pushOp, pushAndExecute } = useContextMenuUndoRedo();
  const initialFetchDone = useRef(false);

  // E-2 race fix: resolve the registry layer with a short bounded retry so the
  // effect below arms even when MapCanvas is mid-remount (registry briefly empty).
  // Vertex edit is selectionless (V-3) — it arms the WHOLE active layer, so no
  // per-feature registry hook is needed; the effect self-retries instead.
  const [vertexRetryTick, setVertexRetryTick] = useState(0);

  const splitFeatureId =
    store.toolbarMode === 'split' &&
    store.activeLayerId && store.activeLayerId !== 'activity_features' &&
    store.selection.featureIds.length === 1
      ? String(store.selection.featureIds[0])
      : null;
  const splitLayer = useRegisteredLayer(splitFeatureId, store.toolbarMode === 'split', 400, store.geometryVersion);

  const cutLineFeatureId =
    store.toolbarMode === 'split' &&
    store.activeLayerId === 'activity_features' &&
    store.selection.featureIds.length === 1
      ? String(store.selection.featureIds[0])
      : null;
  const cutLineLayer = useRegisteredLayer(cutLineFeatureId, store.toolbarMode === 'split', 400, store.geometryVersion);

  const moveFeatureId =
    store.toolbarMode === 'move' &&
    store.activeLayerId && store.activeLayerId !== 'activity_features' &&
    store.selection.featureIds.length === 1
      ? String(store.selection.featureIds[0])
      : null;
  const moveLayer = useRegisteredLayer(moveFeatureId, store.toolbarMode === 'move', 400, store.geometryVersion);

  const handleMapReady = useCallback((m: L.Map | null) => {
    setMap(m);
    setMapRef(m);
  }, []);

  // DEV-only test hooks (E2E): expose the live map + layer registry so a
  // headless driver can invalidate/fitBounds and locate an exact layer `_path`
  // to drag (second-opinion remedy for the collapsed-container drag failure).
  useEffect(() => {
    (window as any).__testOnly = {
      map,
      zoomToFeature: (fid: string) => {
        if (!map) return { ok: false, error: 'map not ready' };
        const layer = getFeatureLayerRegistry().get(fid);
        if (!layer) return { ok: false, error: 'layer not in registry: ' + fid };
        const bounds = (layer as any).getBounds?.();
        if (!bounds || !bounds.isValid()) return { ok: false, error: 'no valid bounds' };
        map.invalidateSize({ animate: false, pan: false });
        map.fitBounds(bounds, { animate: false, maxZoom: 18, padding: [50, 50] });
        return { ok: true, container: { w: map.getContainer().clientWidth, h: map.getContainer().clientHeight }, bounds: bounds.toBBoxString() };
      },
      getPathCenter: (fid: string) => {
        const layer = getFeatureLayerRegistry().get(fid) as any;
        const path = layer?._path as SVGElement | undefined;
        if (!path || !path.isConnected) return null;
        const r = path.getBoundingClientRect();
        return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height };
      },
    };
  }, [map]);

  // UE-0.x: explicit split commit — builds the cut LineString from the drawn
  // vertices (splitCutRef) and POSTs it.  No drawing gesture finishes the cut.
  const confirmSplitCut = useCallback(async () => {
    const sel = store.selection;
    const layerRef = activeLayerRef.current;
    if (!layerRef || !sel || sel.featureIds.length !== 1) return;
    const featureId = String(sel.featureIds[0]);
    const pts = splitCutRef.current;
    if (pts.length < 2) {
      message.warning(t('workspace.split.minTwoPointsWarning'));
      return;
    }
    const coordinates = pts.map((ll: L.LatLng) => [ll.lng, ll.lat] as [number, number]);
    console.log('[Split] posting cut with', coordinates.length, 'points');
    const layerType = layerRef.layerType;
    const layerId = layerRef.kind === 'imported' ? layerRef.layerId : undefined;

    // UE-3.2 — capture the undo context BEFORE the mutation (source snapshot /
    // source feature + index), so the pushed op can restore the original.
    let sourceSnapshot: Record<string, unknown> | undefined;
    let sourceFeature: GeoJSON.Feature | undefined;
    let sourceFeatureIndex: number | undefined;
    if (layerRef.kind === 'imported' && layerRef.layerId != null) {
      const cur = store.importedLayerFeatures[layerRef.layerId] ?? [];
      sourceFeatureIndex = cur.findIndex((f) => featureIdOf(f) === featureId);
      sourceFeature = sourceFeatureIndex >= 0 ? cur[sourceFeatureIndex] : undefined;
    } else if (
      layerRef.kind === 'builtin' &&
      ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas', 'user_group'].includes(layerType)
    ) {
      try {
        const snap = await snapshotFeature({ calcId: calculationId, layerType: layerType as FeatureDeleteLayerType, featureId });
        sourceSnapshot = snap.snapshot;
      } catch { /* snapshot best-effort; undo still deletes pieces */ }
    }
    const sourceGeom: GeoJSON.Geometry | undefined = (splitLayer as any)?.toGeoJSON?.()?.geometry;

    try {
      const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
      const token = localStorage.getItem('access_token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const resp = await fetch(
        `${baseUrl}/api/v1/calculations/${calculationId}/geometry/cut-polygon`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({
            layer_type: layerType,
            layer_id: layerId,
            feature_id: featureId,
            cut_line: { type: 'LineString', coordinates },
          }),
        },
      );
      if (resp.ok) {
        const body = await resp.json().catch(() => null);
        const pieces = ((body as any)?.pieces as unknown[]) ?? [];
        const pieceIds = (body as any)?.piece_ids as string[] | undefined;
        const pieceFeatureIds = (body as any)?.piece_feature_ids as string[] | undefined;
        const boundaryPieceBlockIds = (body as any)?.boundary_piece_block_ids as string[] | undefined;
        pushOp(createSplitOperation(
          layerRef.id,
          featureId,
          sourceGeom ?? { type: 'Polygon', coordinates: [] as never },
          { type: 'LineString', coordinates },
          pieces.map((g, i) => ({
            pieceId: pieceIds?.[i] ?? pieceFeatureIds?.[i] ?? `${featureId}-piece-${i + 1}`,
            geometry: g as GeoJSON.Geometry,
            properties: {},
          })),
          'user',
          undefined,
          {
            calcId: calculationId,
            layerType,
            importLayerId: layerId,
            sourceSnapshot,
            pieceIds,
            pieceFeatureIds,
            boundaryPieceBlockIds,
            sourceFeature,
            sourceFeatureIndex: (sourceFeatureIndex ?? -1) >= 0 ? sourceFeatureIndex : undefined,
          },
        ));
        message.success(t('workspace.split.successSplit'));
        store.bumpGeometryVersion();
      } else {
        const body = await resp.json().catch(() => null);
        const detail = (body as any)?.detail;
        message.error(typeof detail === 'string' ? detail : t('workspace.split.cutMustCross'));
      }
    } catch {
      message.error(t('workspace.split.networkError'));
    }
    store.setToolbarMode('select');
  }, [calculationId, store, store.bumpGeometryVersion, activeLayerRef, pushOp, splitLayer, featureIdOf, t]);

  // ── UE-2.3 merge: POST /geometry/merge-features for the >/=/≥-selected
  // source features, then refresh + clear the selection.
  const doMergePost = useCallback(async (layerRef: ActiveLayerCtx, ids: string[]) => {
    try {
      // UE-3.2 — capture the undo context BEFORE the mutation: per-source
      // snapshots (builtin) or source features + indices (imported), so the
      // pushed op can restore BOTH sources exactly.
      const sourceSnapshots: Record<string, unknown>[] = [];
      const sourceFeatures: GeoJSON.Feature[] = [];
      const sourceIndices: number[] = [];
      if (layerRef.kind === 'imported' && layerRef.layerId != null) {
        const cur = store.importedLayerFeatures[layerRef.layerId] ?? [];
        for (const id of ids) {
          const idx = cur.findIndex((f) => featureIdOf(f) === id);
          if (idx >= 0) { sourceIndices.push(idx); sourceFeatures.push(cur[idx]); }
        }
      } else if (layerRef.kind === 'builtin') {
        for (const id of ids) {
          try {
            const snap = await snapshotFeature({ calcId: calculationId, layerType: layerRef.layerType as FeatureDeleteLayerType, featureId: id });
            sourceSnapshots.push(snap.snapshot);
          } catch { sourceSnapshots.push({}); }
        }
      }
      const token = localStorage.getItem('access_token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const resp = await fetch(
        `/api/v1/calculations/${calculationId}/geometry/merge-features`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({
            layer_type: layerRef.layerType,
            layer_id: layerRef.kind === 'imported' ? layerRef.layerId : undefined,
            feature_ids: ids,
          }),
        },
      );
      const body = await resp.json().catch(() => null);
      if (!resp.ok) {
        const detail = (body as any)?.detail;
        message.error(typeof detail === 'string' ? detail : (detail?.message ?? t('workspace.merge.failed')));
        store.setToolbarMode('select');
        return;
      }
      // Imported layers keep a client-side feature cache — mirror the merged
      // feature back into it (removing the source ids that were consumed).
      if (layerRef.kind === 'imported' && layerRef.layerId != null) {
        const cur = store.importedLayerFeatures[layerRef.layerId] ?? [];
        const merged = (body as any)?.merged ?? (body as any)?.feature ?? (body as any);
        const next = applyImportedMerge(cur, ids, merged);
        if (next !== cur) {
          store.setImportedLayerFeatures(layerRef.layerId, next);
        }
      }
      // UE-3.2 — push the merge op so Ctrl+Z restores both sources.
      const merged = (body as any)?.feature ?? (body as any)?.merged ?? (body as any);
      const mergedFeatureId = featureIdOf(merged) || `${ids[0]}-merged`;
      pushOp(createMergeOperation(
        layerRef.id,
        ids,
        ids.map(() => ({ type: 'Polygon', coordinates: [] as never })),
        ids.map(() => ({})),
        mergedFeatureId,
        (merged as any)?.geometry ?? { type: 'Polygon', coordinates: [] as never },
        (merged as any)?.properties ?? {},
        'user',
        undefined,
        {
          calcId: calculationId,
          layerType: layerRef.layerType,
          importLayerId: layerRef.kind === 'imported' ? layerRef.layerId : undefined,
          sourceSnapshots,
          mergedRowId: layerRef.kind === 'imported' ? undefined : (merged as any)?.id,
          sourceFeatures,
          sourceIndices,
        },
      ));
      store.clearSelection();
      store.bumpGeometryVersion();
      const warnings = (body as any)?.warnings as string[] | undefined;
      if (Array.isArray(warnings) && warnings.includes('CLIPPED_TO_BOUNDARY')) {
        message.warning(t('workspace.geometry.clippedToBoundary'));
      }
      message.success(t('workspace.merge.success'));
      store.setToolbarMode('select');
    } catch {
      message.error(t('workspace.merge.networkError'));
      store.setToolbarMode('select');
    }
  }, [calculationId, store, pushOp, t]);

  const confirmMerge = useCallback((layerRef: ActiveLayerCtx, ids: string[]) => {
    Modal.confirm({
      title: t('workspace.merge.confirmTitle', { count: ids.length }),
      okText: t('workspace.merge.confirm'),
      cancelText: t('common.cancel'),
      onOk: () => doMergePost(layerRef, ids),
    });
  }, [doMergePost, t]);

  // GD 1.3.4: buffered write / auto-save for the active digitize layer.
  const digitizeCtx = store.activeDigitizeContext as ActiveDigitizeContext | null;
  const activeDraftLayerId = digitizeCtx?.layer.id;
  const { flush: flushDraft } = useDraftSync({
    calcId: calculationId,
    layerId: activeDraftLayerId,
    active: activeDraftLayerId != null,
    // GD 2.4: appends target an existing non-draft layer — flush in append mode.
    mode: digitizeCtx?.mode === 'append' ? 'append' : 'draft',
    onAppendFlushed: useCallback((count: number, layerId: number) => {
      const layer = useWorkspaceStore.getState().importedLayers.find((l) => l.id === layerId);
      if (!layer) return;
      message.success(t('workspace.digitize.addedToLayer', { count, name: layer.name }));
    }, [t]),
  });

  const {
    collapsed: panelCollapsed,
    registerGroup,
    registerPanel,
    togglePanel,
    setPanelCollapsed,
    scheduleSave,
  } = useWorkspaceLayout();

  const handleLayoutChanged = useCallback(
    (_layout: Record<string, number>, meta: LayoutChangedMeta) => {
      if (meta.isUserInteraction) scheduleSave();
    },
    [scheduleSave],
  );

  const handleCollapseToggle = useCallback(
    (id: string) => togglePanel(id as Parameters<typeof togglePanel>[0]),
    [togglePanel],
  );

  // Open the Yearly plan table (P4, YA-4.6): the same dock panel, on the plan instead of the layer's places — reachable
  // without the Activity Features layer, and unfolded if the panel was collapsed.
  const openPlanView = useCallback(() => {
    setTableView('plan');
    if (panelCollapsed.attributeTable) togglePanel('attributeTable');
  }, [panelCollapsed.attributeTable, togglePanel]);

  const panelToggles: { id: string; label: string; icon: string; visible: boolean }[] = [
    { id: 'layers', label: t('workspace.layers'), icon: '▤', visible: !panelCollapsed.layers },
    { id: 'basemap', label: t('workspace.basemap'), icon: '▧', visible: !panelCollapsed.basemap },
    { id: 'imported', label: t('workspace.importedLayers'), icon: '⬈', visible: !panelCollapsed.imported },
    { id: 'raster', label: t('workspace.rasterLayers'), icon: '▨', visible: !panelCollapsed.raster },
    { id: 'attributeTable', label: t('workspace.attributeTable'), icon: '☷', visible: !panelCollapsed.attributeTable },
    { id: 'legend', label: t('workspace.legend'), icon: '◈', visible: !panelCollapsed.legend },
  ];

  // Ref to the main horizontal panel group for imperative recalculation on focus mode change
  const horizontalGroupRef = useRef<HTMLDivElement | null>(null);

  // Listen to focus mode changes and trigger layout recalculation
  const focusMode = useWorkspaceStore((s) => s.focusMode);

  useEffect(() => {
    // Trigger recalculation when focus mode changes
    const timer = setTimeout(() => {
      // 1. Dispatch resize to wake up react-resizable-panels
      window.dispatchEvent(new Event('resize'));

      // 2. Invalidate Leaflet map size if map exists
      const leafletContainer = document.querySelector('.leaflet-container');
      if (leafletContainer && (leafletContainer as any)._leaflet_map) {
        (leafletContainer as any)._leaflet_map.invalidateSize();
      }

      // 3. Also try map instance from dev hook
      const devMap = (window as any).__mapInstance;
      if (devMap && typeof devMap.invalidateSize === 'function') {
        devMap.invalidateSize();
      }

      // 4. Force PanelGroup recalculation if ref is available
      if (horizontalGroupRef.current) {
        // The Group component from react-resizable-panels may need a resize event
        // or we can trigger a layout update by briefly toggling a size
        horizontalGroupRef.current.style.height = '100%';
      }
    }, 50);

    return () => clearTimeout(timer);
  }, []);


  const fetchImportedLayerFeatures = useCallback(async (force?: boolean) => {
    const layers = store.importedLayers;
    if (layers.length === 0) return;
    const baseUrl = import.meta.env.VITE_API_URL ?? '';
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    for (const layer of layers) {
      if (!force && store.importedLayerFeatures[layer.id]) continue;
      try {
        const res = await fetch(
          `${baseUrl}/api/v1/workspace/${calculationId}/import-layers/${layer.id}/features`,
          { headers, credentials: 'include' },
        );
        if (res.ok) {
          const data = await res.json();
          store.setImportedLayerFeatures(layer.id, data.features || []);
        }
      } catch (err) {
        console.error(`Failed to fetch features for imported layer ${layer.id}:`, err);
      }
    }
  }, [calculationId, store.importedLayers.length]);

  useEffect(() => {
    store.setCalculationId(calculationId);
    initialFetchDone.current = false;
  }, [calculationId]);

  useEffect(() => {
    let cancelled = false;
    const baseUrl = import.meta.env.VITE_API_URL ?? '';
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const load = async () => {
      try {
        const res = await fetch(
          `${baseUrl}/api/v1/workspace/${calculationId}/import-layers`,
          { headers, credentials: 'include' },
        );
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled || !Array.isArray(data)) return;
        store.replaceImportedLayers(
          data.map((layer: Record<string, unknown>, i: number) => ({
            id: layer.id as number,
            name: layer.name as string,
            purpose: layer.purpose as string,
            format: layer.source_format as string,
            featureCount: layer.feature_count as number,
            fileSizeBytes: layer.file_size_bytes as number,
            geometryTypes: Array.isArray(layer.geometry_types)
              ? (layer.geometry_types as string[])
              : [],
            visible: true,
            order: i,
            createdAt: layer.created_at as string,
          })),
        );
      } catch (err) {
        console.error('Failed to load imported layers:', err);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [calculationId]);

  // RS-2.16: independent Auto-Block layers, fetched on calc load the same
  // way imported layers are above -- so a layer created in a previous
  // session still shows up without needing a fresh commit this session.
  useEffect(() => {
    store.refreshRasterLayers(calculationId);
  }, [calculationId]);

  useEffect(() => {
    if (store.importedLayers.length === 0) return;
    fetchImportedLayerFeatures(!initialFetchDone.current);
    initialFetchDone.current = true;
  }, [fetchImportedLayerFeatures]);

  useEffect(() => {
    const prev = lastStatusRef.current;
    const cur = store.mapLifecycleStatus;
    lastStatusRef.current = cur;
    if (prev !== cur && (cur === 'completed' || cur === 'locked')) {
      setCompletionModalOpen(true);
    }
  }, [store.mapLifecycleStatus]);

  // P4 — load / persist thematic renderer specs (result_data.layer_renderers).
  useLayerRenderers(calculationId);

  const boundaryQuery = useLayerData('boundary', calculationId);
  const userGroupQuery = useLayerData('user_group', calculationId);
  const blocksQuery = useLayerData('blocks', calculationId);
  const subBlocksQuery = useLayerData('sub_blocks', calculationId);
  const compartmentsQuery = useLayerData('compartments', calculationId);
  const subCompartmentsQuery = useLayerData('sub_compartments', calculationId);
  const subAreasQuery = useLayerData('sub_areas', calculationId);
  const activityQuery = useLayerData('activity_features', calculationId);
  const samplePlotsQuery = useLayerData('sample_plots', calculationId, true, store.samplePlotsRefreshVersion);
  // Lazy — the map renders Stem Mapping via StemMappingClusters' own viewport
  // tile fetches, not this full feature list. Only fetch the (potentially
  // thousands-of-rows) full list once the layer is actually selected, for the
  // attribute table / legend count.
  const stemMappingQuery = useLayerData('stem_mapping', calculationId, store.activeLayerId === 'stem_mapping');
  const fieldbookQuery = useLayerData('fieldbook', calculationId);

  // P4.6 / P5.1 — the features each layer draws on the map = the raw query data
  // minus the "show only matches" filter (tableFilter) minus hidden features.
  // Memoised so the `.filter()` passes don't re-run on every unrelated render.
  const mapFeatures = useMemo(() => {
    const forMap = (data: GeoJSON.Feature[] | null | undefined, id: string) =>
      dropHiddenFeatures(
        filterForMap(data, store.tableFilter, id),
        store.hiddenFeatureIds[`${calculationId ?? 'nc'}::${id}`],
      );
    return {
      boundary: forMap(boundaryQuery.data, 'boundary'),
      user_group: forMap(userGroupQuery.data, 'user_group'),
      blocks: forMap(blocksQuery.data, 'blocks'),
      sub_blocks: forMap(subBlocksQuery.data, 'sub_blocks'),
      compartments: forMap(compartmentsQuery.data, 'compartments'),
      sub_compartments: forMap(subCompartmentsQuery.data, 'sub_compartments'),
      sub_areas: forMap(subAreasQuery.data, 'sub_areas'),
      activity_features: forMap(activityQuery.data, 'activity_features'),
      sample_plots: forMap(samplePlotsQuery.data, 'sample_plots'),
      fieldbook: forMap(fieldbookQuery.data, 'fieldbook'),
    };
  }, [
    calculationId, store.tableFilter, store.hiddenFeatureIds,
    boundaryQuery.data, userGroupQuery.data, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data,
    subCompartmentsQuery.data, subAreasQuery.data, activityQuery.data, samplePlotsQuery.data,
    fieldbookQuery.data,
  ]);

  // Purpose-first: a boundary-less draft has no geometry yet, so the first
  // "Add Geometry" must pick a geometry purpose (Forest boundary / Block).
  const hasGeometry = !!(
    (boundaryQuery.data && boundaryQuery.data.length > 0) ||
    (blocksQuery.data && blocksQuery.data.length > 0) ||
    (compartmentsQuery.data && compartmentsQuery.data.length > 0)
  );
  const hasBoundary = !!(boundaryQuery.data && boundaryQuery.data.length > 0);

  const initialZoomDone = useRef(false);

  const LAYER_ZOOM_PRIORITY: LayerTypeId[] = ['compartments', 'blocks', 'boundary', 'sub_blocks', 'sub_compartments', 'sub_areas', 'activity_features', 'sample_plots', 'stem_mapping'];

  useEffect(() => {
    if (initialZoomDone.current || !map) return;
    for (const id of LAYER_ZOOM_PRIORITY) {
      const features = getLayerFeatures(id);
      if (features && features.length > 0) {
        zoomToLayer(id);
        initialZoomDone.current = true;
        break;
      }
    }
  }, [map, boundaryQuery.data, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, subAreasQuery.data, activityQuery.data]);

  const handleLayerSelect = (id: LayerTypeId) => {
    store.setActiveLayer(id);
  };

  const getLayerFeatures = (layerId: LayerTypeId): GeoJSON.Feature[] | null => {
    switch (layerId) {
      case 'boundary': return boundaryQuery.data;
      case 'blocks': return blocksQuery.data;
      case 'sub_blocks': return subBlocksQuery.data;
      case 'compartments': return compartmentsQuery.data;
      case 'sub_compartments': return subCompartmentsQuery.data;
      case 'sub_areas': return subAreasQuery.data;
      case 'activity_features': return activityQuery.data;
      case 'sample_plots': return samplePlotsQuery.data;
      case 'stem_mapping': return stemMappingQuery.data;
      case 'fieldbook': return fieldbookQuery.data;
      case 'user_group': return userGroupQuery.data;
      default: return null;
    }
  };

  // A sub-level layer's own top-level counterpart (undefined for a top-level
  // layer itself). Mirrors `layerMenu.ts`'s `TOP_LEVEL_OF` — kept as a
  // separate local copy since that module deliberately has no imports.
  const DIVIDE_TOP_LEVEL_OF: Partial<Record<DivideLayerId, DivideLayerId>> = {
    sub_blocks: 'blocks', sub_compartments: 'compartments',
  };
  // Natural-feature divide always goes one level deeper (`resolve_divide_scope`
  // is branch-generic: any non-compartment row yields sub_blocks, any
  // compartment row yields sub_compartments, regardless of the row's own
  // depth — FS-4a.6), so a layer's "natural child" is fixed reading its own
  // union type — a top-level layer's natural child is its sub-level, a
  // sub-level layer's natural child is itself (deeper nesting, A1).
  const NATURAL_CHILD: Record<DivideLayerId, DivideLayerId> = {
    blocks: 'sub_blocks', sub_blocks: 'sub_blocks',
    compartments: 'sub_compartments', sub_compartments: 'sub_compartments',
  };
  const SINGULAR_KEY: Record<DivideLayerId, string> = {
    blocks: 'workspace.types.block', sub_blocks: 'workspace.types.subBlock',
    compartments: 'workspace.types.compartment', sub_compartments: 'workspace.types.subCompartment',
  };
  const PLURAL_KEY: Record<DivideLayerId, string> = {
    blocks: 'workspace.types.blocks', sub_blocks: 'workspace.types.subBlocks',
    compartments: 'workspace.types.compartments', sub_compartments: 'workspace.types.subCompartments',
  };
  const divideLayerData = (id: DivideLayerId): GeoJSON.Feature[] =>
    (id === 'blocks' ? blocksQuery.data
      : id === 'sub_blocks' ? subBlocksQuery.data
      : id === 'compartments' ? compartmentsQuery.data
      : subCompartmentsQuery.data) ?? [];
  const hasAnyStructuralFeature = () =>
    (blocksQuery.data?.length ?? 0) > 0
    || (subBlocksQuery.data?.length ?? 0) > 0
    || (compartmentsQuery.data?.length ?? 0) > 0
    || (subCompartmentsQuery.data?.length ?? 0) > 0;

  // Equal-area divide (D5 / boundary-parent shortcut) — all four unit types
  // (FS-4a.17, lean L3): the legacy "mint a boundary-mirror block, then divide
  // IT into compartments" hack is gone. The backend now carves the forest's
  // FIRST top-level set (blocks or compartments) directly from the boundary
  // (FS-4a.5 root divide) — the parallel-branches rule (D1) means there is no
  // "compartments needs a block" chain left to route around.
  //   blocks / compartments (TOP-LEVEL) → explicit single selection of itself
  //                       wins (self-divide, more of the same kind);
  //                       otherwise exactly one EXISTING feature → use it;
  //                       otherwise nothing of either branch exists yet and a
  //                       boundary does → root-divide the boundary itself.
  //   sub_blocks / sub_compartments (SUB-LEVEL) → divides its top-level
  //                       counterpart. Explicit single selection of the
  //                       counterpart OR of itself wins (the backend
  //                       auto-detects a same-layer selection as a SELF-divide
  //                       — split it further into equal-area pieces of its own
  //                       type — instead of a parent-kept carve); otherwise
  //                       exactly one counterpart on the map → use it, else ask.
  const handleDivide = useCallback((layerId: DivideLayerId) => {
    const topOf = DIVIDE_TOP_LEVEL_OF[layerId];
    store.setActiveLayer(layerId);
    const target = (fid: string) => setDivideTarget({ layerId, featureId: fid });
    const featId = (f: GeoJSON.Feature) =>
      String(f.properties?.id ?? f.properties?.featureId ?? (f as { id?: unknown }).id ?? '');

    if (
      ((topOf && store.selection.layerId === topOf) || store.selection.layerId === layerId)
      && store.selection.featureIds.length === 1
    ) {
      target(String(store.selection.featureIds[0]));
      return;
    }
    if (topOf) {
      const parents = divideLayerData(topOf);
      if (parents.length === 1) {
        const fid = featId(parents[0]);
        if (fid) { target(fid); return; }
      }
      message.info(
        t('workspace.divide.selectExactlyOne', {
          parent: t(SINGULAR_KEY[topOf]),
          children: t(PLURAL_KEY[layerId]),
        }),
        4,
      );
      return;
    }
    const own = divideLayerData(layerId);
    if (own.length === 1) {
      const fid = featId(own[0]);
      if (fid) { target(fid); return; }
    }
    if (!hasAnyStructuralFeature() && (boundaryQuery.data?.length ?? 0) > 0) {
      target('');
      return;
    }
    message.info(
      t('workspace.divide.selectExactlyOne', {
        parent: t(SINGULAR_KEY[layerId]),
        children: t(PLURAL_KEY[layerId]),
      }),
      4,
    );
  }, [store, t, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, boundaryQuery.data]);

  // "Divide by natural feature…" — always targets an EXISTING feature one
  // level up from what gets created: a top-level layer divides one of its OWN
  // units into its sub-level (the only thing `resolve_divide_scope` ever
  // returns for it); a sub-level layer divides its top-level counterpart, same
  // as the equal-area parent-kept carve. With exactly one candidate on the map
  // it is used without a selection.
  const handleAutoDivide = useCallback((layerId: DivideLayerId) => {
    const topOf = DIVIDE_TOP_LEVEL_OF[layerId];
    const sourceLayer = topOf ?? layerId;
    const candidates = divideLayerData(sourceLayer);
    const featId = (f: GeoJSON.Feature) =>
      String(f.properties?.id ?? f.properties?.featureId ?? (f as { id?: unknown }).id ?? '');
    const open = (f: GeoJSON.Feature | undefined) => {
      const id = f ? featId(f) : '';
      if (!id) return false;
      const name = String(f?.properties?.block_name ?? f?.properties?.name ?? id);
      store.setActiveLayer(layerId);
      setAutoDivideParent({ id, name });
      return true;
    };
    // A sub-unit selected on its own layer (e.g. one slope piece) is divided
    // itself (deeper nesting, A1) -- never swapped for its top-level parent,
    // which already has children and trips the "divided once" guard.
    if (topOf && store.selection.layerId === layerId && store.selection.featureIds.length === 1) {
      const sel = String(store.selection.featureIds[0]);
      if (open(divideLayerData(layerId).find((f) => featId(f) === sel))) return;
    }
    if (store.selection.layerId === sourceLayer && store.selection.featureIds.length === 1) {
      const sel = String(store.selection.featureIds[0]);
      if (open(candidates.find((f) => featId(f) === sel))) return;
    }
    if (candidates.length === 1 && open(candidates[0])) return;
    message.info(
      t('workspace.divide.selectExactlyOne', {
        parent: t(SINGULAR_KEY[sourceLayer]),
        children: t(PLURAL_KEY[NATURAL_CHILD[layerId]]),
      }),
      4,
    );
  }, [store, t, blocksQuery.data, compartmentsQuery.data, subBlocksQuery.data, subCompartmentsQuery.data]);

  const zoomToLayer = (layerId: string) => {
    const features = getLayerFeatures(layerId as LayerTypeId);
    if (!map || !features || features.length === 0) return;

    try {
      const bounds = L.geoJSON(features as any).getBounds();
      zoomToLayerBounds(map, bounds);
    } catch (e) {
      console.warn('Failed to zoom to layer:', e);
    }
  };

  // After an import, the map must zoom to the imported layer's extent. Custom
  // layer geometry arrives async via store.importedLayerFeatures (fetched after
  // addImportedLayer); builtin conversions refetch their built-in query. The
  // effect fires once the features are present.
  const [pendingImportZoom, setPendingImportZoom] = useState<{ layerId?: number; purpose?: string } | null>(null);
  const BUILTIN_IMPORT_TARGETS: string[] = ['boundary', 'blocks', 'compartments', 'sub_compartments', 'sub_areas'];

  const handleLayerImported = useCallback((layerId?: number, purpose?: string) => {
    setPendingImportZoom({ layerId, purpose });
  }, []);

  useEffect(() => {
    if (!pendingImportZoom) return;
    const { layerId, purpose } = pendingImportZoom;
    const isBuiltin = !!purpose && BUILTIN_IMPORT_TARGETS.includes(purpose);
    if (!map || (!isBuiltin && layerId == null)) {
      setPendingImportZoom(null);
      return;
    }
    const features = isBuiltin
      ? getLayerFeatures(purpose as LayerTypeId)
      : (layerId != null ? store.importedLayerFeatures[layerId] : null);
    if (!features || features.length === 0) return;
    setPendingImportZoom(null);
    try {
      const bounds = L.geoJSON(features as any).getBounds();
      zoomToLayerBounds(map, bounds);
    } catch (e) {
      console.warn('Failed to zoom to imported layer:', e);
    }
  }, [pendingImportZoom, map, store, boundaryQuery.data, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, subAreasQuery.data]);

  const handleSubAreaCreated = useCallback(async (feature: GeoJSON.Feature) => {
    setPendingCategory(null);
    setShowCategoryPicker(true);
  }, []);

  const handleCategorySelected = useCallback(async (category: string) => {
    setShowCategoryPicker(false);
    setPendingCategory(category);
    const layerConfig = getLayerConfig('sub_areas');
    if (!layerConfig) { setPendingCategory(null); return; }

    // P6 category-first draw: picker was armed by "Add Sub-Area" → arm draw_polygon.
    if (addSubAreaArm) {
      setAddSubAreaArm(false);
      pendingCategoryRef.current = category;
      store.setActiveLayer('sub_areas');
      store.setToolbarMode('draw_polygon');
      return;
    }

    if (store.pendingFeature) {
      try {
        const feature = {
          ...store.pendingFeature,
          properties: { ...store.pendingFeature.properties, category },
        };
        const created = (await layerConfig.dataSource.create(calculationId, feature)) as unknown as { id?: string } | undefined;
        store.setPendingFeature(null);
        store.bumpGeometryVersion();
        if (created?.id) setSubAreaPlanDialog({ open: true, focusId: String(created.id) });
      } catch (err: any) {
        store.setError('sub_areas', err?.message || t('workspace.subArea.createFailed'));
      }
    } else if (store.selection.featureIds.length > 0) {
      const featureId = store.selection.featureIds[0];
      try {
        await layerConfig.dataSource.update(calculationId, featureId, {
          properties: { category },
        } as any);
        store.setToolbarMode('select');
        store.bumpGeometryVersion();
      } catch (err: any) {
        store.setError('sub_areas', err?.message || t('workspace.subArea.categoryUpdateFailed'));
      }
    }
    setPendingCategory(null);
  }, [calculationId, store, addSubAreaArm, t]);

  const handleAddSubArea = useCallback(() => {
    store.setActiveLayer('sub_areas');
    setAddSubAreaArm(true);
    setPendingCategory(null);
    setShowCategoryPicker(true);
  }, [store]);

  // ── U-4 (Task 4.1, case E): interactive "Create Polygon from Points" ─────
  const handlePolygonFromPoints = useCallback((layerId: string, purpose: string) => {
    store.setActiveLayer(layerId as LayerTypeId);
    store.setToolbarMode('select');
    setPointPick({ target: purpose, points: [], layerId: layerId as LayerTypeId });
  }, [store]);

  const handlePointPickAdd = useCallback((lngLat: [number, number]) => {
    setPointPick((prev) => {
      if (!prev) return prev;
      const last = prev.points[prev.points.length - 1];
      if (last && Math.abs(last[0] - lngLat[0]) < 1e-7 && Math.abs(last[1] - lngLat[1]) < 1e-7) {
        return prev; // ignore accidental double-click on the exact same spot
      }
      return { ...prev, points: [...prev.points, lngLat] };
    });
  }, []);

  const handlePointPickClear = useCallback(() => {
    setPointPick((prev) => (prev ? { ...prev, points: [] } : prev));
  }, []);

  const handlePointPickCancel = useCallback(() => {
    setPointPick(null);
  }, []);

  const handlePointPickFinish = useCallback(async () => {
    if (!pointPick || pointPick.points.length < 3) return;
    const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      const res = await fetch(
        `${baseUrl}/api/v1/workspace/${calculationId}/polygon-from-points`,
        {
          method: 'POST',
          headers,
          credentials: 'include',
          body: JSON.stringify({
            points: pointPick.points,
            target_type: pointPick.target,
            name: 'Polygon',
          }),
        },
      );
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(readDetail(err?.detail) || t('workspace.polygon.createFailed'));
      }
      const body = await res.json();
      message.success(t('workspace.polygon.created', { area: body.area_hectares?.toFixed?.(2) ?? '' }));
      setPointPick(null);
      store.bumpGeometryVersion();
    } catch (err: any) {
      store.setError('polygon_from_points', err?.message || t('workspace.polygon.createFailed'));
    }
  }, [pointPick, calculationId, store, t]);

  // Non-collinearity: the finish button only enables with >=3 points that don't
  // all lie on one line (area of the simple closed ring > 0).
  const pointPickCanFinish = useMemo(
    () => (pointPick ? pointsAreNonCollinear(pointPick.points) : false),
    [pointPick],
  );

  // Map click collection while the mode is active.
  useEffect(() => {
    if (!map || !pointPick) return;
    const onClick = (e: L.LeafletMouseEvent) => {
      const { lat, lng } = e.latlng;
      handlePointPickAdd([lng, lat]);
    };
    map.on('click', onClick);
    return () => {
      map.off('click', onClick);
    };
  }, [map, pointPick, handlePointPickAdd]);

  // Show the vertices as they are clicked — "Create polygon from points" used to
  // collect points into state with nothing drawn on the map, so the user could
  // not see what they were digitizing.
  useEffect(() => {
    if (!map || !pointPick || pointPick.points.length === 0) return;
    const group = L.layerGroup().addTo(map);
    const latlngs = pointPick.points.map(([lng, lat]) => [lat, lng] as [number, number]);
    if (latlngs.length >= 3) {
      L.polygon(latlngs, {
        color: '#2f7d32', weight: 0, fillColor: '#2f7d32', fillOpacity: 0.12, interactive: false,
      }).addTo(group);
    }
    if (latlngs.length >= 2) {
      L.polyline(latlngs.length >= 3 ? [...latlngs, latlngs[0]] : latlngs, {
        color: '#2f7d32', weight: 2, dashArray: '6, 4', interactive: false,
      }).addTo(group);
    }
    latlngs.forEach((ll, i) => {
      L.circleMarker(ll, {
        radius: 5, color: '#ffffff', weight: 2, fillColor: '#2f7d32', fillOpacity: 1, interactive: false,
      })
        .bindTooltip(String(i + 1), { permanent: true, direction: 'top', offset: [0, -6], className: 'point-pick-vertex-label' })
        .addTo(group);
    });
    return () => { if (map.hasLayer(group)) map.removeLayer(group); };
  }, [map, pointPick]);

  const handleSaveSubAreaProperty = useCallback((feature: GeoJSON.Feature, colKey: string, value: string) => {
    const layerConfig = getLayerConfig('sub_areas');
    if (!layerConfig) return;
    const featureId = feature.properties?.id || (feature as any).id;
    if (!featureId) {
      store.setError('sub_areas', t('workspace.subArea.missingId'));
      return;
    }
    const fid = String(featureId);
    const runUpdate = (payload: Record<string, unknown>) =>
      layerConfig.dataSource.update(calculationId, fid, payload as Partial<GeoJSON.Feature>)
        .then(() => store.bumpGeometryVersion())
        .catch((err: any) => store.setError('sub_areas', err?.message || t('workspace.subArea.updateFailed', { field: colKey })));

    // name / category / per-feature style all persist and are undoable (P3.5);
    // the `properties`-wrapped fallback is a server no-op, so it is fired plain.
    const stylePatch = buildStylePatch(feature.properties?.style, colKey, value);
    if (stylePatch !== undefined) {
      const payload = { style: stylePatch };
      const prev = { style: feature.properties?.style ?? null };
      pushAndExecute(
        createAttributeEditOperation(calculationId, 'sub_areas', fid, 'Edit colour', prev, payload, 'user'),
        () => { void runUpdate(payload); },
      );
    } else if (colKey === 'name' || colKey === 'category') {
      const payload = { [colKey]: value };
      const prev = { [colKey]: feature.properties?.[colKey] ?? null };
      pushAndExecute(
        createAttributeEditOperation(calculationId, 'sub_areas', fid, `Edit ${colKey}`, prev, payload, 'user'),
        () => { void runUpdate(payload); },
      );
    } else {
      void runUpdate({ properties: { [colKey]: value } });
    }
  }, [calculationId, store, t, pushAndExecute]);

  // YEARLY_ACTIVITIES plan P2 — a drawn place's name, years and symbol are edited in the table. One saved edit
  // is one undo entry; an unplanned year is only planned after the person says yes.
  const handleSaveActivityFeatureProperty = useCallback((feature: GeoJSON.Feature, colKey: string, value: string) => {
    const layerConfig = getLayerConfig('activity_features');
    if (!layerConfig) return;
    void saveActivityFeatureEdit(feature, colKey, value, {
      calcId: calculationId,
      update: (fid, payload) => layerConfig.dataSource.update(calculationId, fid, payload as Partial<GeoJSON.Feature>),
      confirmPlanYears: (activity, years) =>
        new Promise<boolean>((resolve) => {
          Modal.confirm({
            title: t('yearlyPlan.table.planYearTitle'),
            content: t('yearlyPlan.table.planYearBody', { activity, years: years.map((y) => formatNumber(y)).join(', ') }),
            okText: t('yearlyPlan.table.planYearOk'),
            cancelText: t('yearlyPlan.table.planYearCancel'),
            onOk: () => resolve(true),
            onCancel: () => resolve(false),
          });
        }),
      pushOp,
      refresh: () => store.bumpGeometryVersion(),
      report: (err) => message.error(planTableErrorMessage(err, t)),
    });
  }, [calculationId, store, t, pushOp]);

  // Phase C (auto-block): rename blocks / compartments / sub-compartments
  // from the attribute table. `name` is the display label shown on the map
  // and mirrors `block_name` (the auto-generated serial); `natural_name` is
  // the best-effort river/ridge label. All three are persisted to the block
  // row (block_name / natural_name columns) so the AutoBlock flow stays in
  // sync with what the user sees.
  const handleSaveBlockProperty = useCallback((feature: GeoJSON.Feature, colKey: string, value: string) => {
    const activeLayerId = store.activeLayerId;
    const layerConfig = getLayerConfig(activeLayerId as LayerTypeId);
    if (!layerConfig || !activeLayerId) return;
    const featureId = feature.properties?.id || (feature as any).id;
    if (!featureId) {
      store.setError(activeLayerId, t('workspace.block.missingId'));
      return;
    }
    const fid = String(featureId);
    const runUpdate = (payload: Record<string, unknown>) =>
      layerConfig.dataSource.update(calculationId, fid, payload as Partial<GeoJSON.Feature>)
        .then(() => store.bumpGeometryVersion())
        .catch((err: any) => store.setError(activeLayerId, err?.message || t('workspace.block.updateFailed', { field: colKey })));

    const stylePatch = buildStylePatch(feature.properties?.style, colKey, value);
    const payload = stylePatch !== undefined
      ? { style: stylePatch }
      : { [colKey]: coerceAttributeValue(colKey, value) };
    const prev = stylePatch !== undefined
      ? { style: feature.properties?.style ?? null }
      : { [colKey]: feature.properties?.[colKey] ?? null };
    pushAndExecute(
      createAttributeEditOperation(
        calculationId, activeLayerId, fid,
        `Edit ${stylePatch !== undefined ? 'colour' : colKey}`, prev, payload, 'user',
      ),
      () => { void runUpdate(payload); },
    );
  }, [calculationId, store, t, pushAndExecute]);

  // BOUNDARY_PIECES_PLAN.md P4: renaming a boundary piece, from the `boundary`
  // layer's own attribute table (one row per disjoint piece — see that
  // layer's `fetch`). Rename-only (no style/geometry column here, per D7) —
  // a smaller version of handleSaveBlockProperty, same undo-stack wiring.
  const handleSaveBoundaryPieceProperty = useCallback((feature: GeoJSON.Feature, colKey: string, value: string) => {
    const layerConfig = getLayerConfig('boundary');
    if (!layerConfig) return;
    const featureId = feature.properties?.id || (feature as any).id;
    if (!featureId) {
      store.setError('boundary', t('workspace.boundaryPieces.missingId'));
      return;
    }
    const fid = String(featureId);
    const payload = { [colKey]: value };
    const prev = { [colKey]: feature.properties?.[colKey] ?? '' };
    const runUpdate = () =>
      layerConfig.dataSource.update(calculationId, fid, payload as Partial<GeoJSON.Feature>)
        .then(() => store.bumpGeometryVersion())
        .catch((err: any) => store.setError('boundary', err?.message || t('workspace.boundaryPieces.updateFailed')));
    pushAndExecute(
      createAttributeEditOperation(calculationId, 'boundary', fid, `Edit ${colKey}`, prev, payload, 'user'),
      () => { void runUpdate(); },
    );
  }, [calculationId, store, t, pushAndExecute]);

  // P3.5 (follow-up) — an inline property rename on an imported-layer feature,
  // routed through the same undo stack as builtin edits.
  const handleSaveImportedProperty = useCallback((feature: GeoJSON.Feature, colKey: string, value: string) => {
    const layerId = store.activeImportedLayerId;
    if (layerId == null) return;
    const errKey = `imported:${layerId}`;
    const list = store.importedLayerFeatures[layerId] ?? [];
    const idOf = (f: GeoJSON.Feature) =>
      String(f.properties?.id ?? f.properties?.featureId ?? (f as { id?: unknown }).id ?? '');
    const targetId = idOf(feature);
    const featureIndex = targetId ? list.findIndex((f) => idOf(f) === targetId) : list.indexOf(feature);
    if (featureIndex < 0) {
      store.setError(errKey, t('attributeTable.featureExpired'));
      return;
    }
    const payload = { properties: { [colKey]: value } };
    const prev = { properties: { [colKey]: feature.properties?.[colKey] ?? '' } };
    const runUpdate = (body: { properties: Record<string, unknown> }) =>
      forestApi.updateImportedFeature(calculationId, layerId, featureIndex, body.properties)
        .then((res) => {
          const cur = store.importedLayerFeatures[layerId] ?? [];
          if (cur[featureIndex]) {
            const next = [...cur];
            next[featureIndex] = { ...next[featureIndex], properties: { ...next[featureIndex].properties, ...(res?.properties ?? body.properties) } };
            store.setImportedLayerFeatures(layerId, next);
          }
          store.bumpGeometryVersion();
        })
        .catch((err) => store.setError(errKey, (err as Error)?.message || t('attributeTable.networkErrorProperty')));
    pushAndExecute(
      createAttributeEditOperation(
        calculationId, `imported-${layerId}`, targetId, `Edit ${colKey}`, prev, payload, 'user',
        { importLayerId: layerId, featureIndex },
      ),
      () => { void runUpdate(payload); },
    );
  }, [calculationId, store, t, pushAndExecute]);

  // A raster/Auto-Block layer's features ARE ForestBlock rows already
  // (tagged with raster_layer_id, same table builtin blocks use) -- the
  // generic blocks PATCH endpoint already accepts them, so renaming reuses
  // that `dataSource.update`, same as handleSaveBlockProperty, then patches
  // `store.rasterLayerFeatures` locally (rather than relying on a refetch)
  // so the map tooltip and attribute table update without any manual
  // refresh. Before this handler existed, `onSaveProperty` resolved to
  // `undefined` for an active raster layer, so an inline rename here was a
  // silent no-op: nothing was persisted and nothing on screen changed.
  const handleSaveRasterProperty = useCallback((feature: GeoJSON.Feature, colKey: string, value: string) => {
    const layerId = store.activeRasterLayerId;
    if (layerId == null) return;
    const errKey = `raster:${layerId}`;
    const list = store.rasterLayerFeatures[layerId] ?? [];
    const idOf = (f: GeoJSON.Feature) =>
      String(f.properties?.id ?? f.properties?.featureId ?? (f as { id?: unknown }).id ?? '');
    const targetId = idOf(feature);
    const featureIndex = targetId ? list.findIndex((f) => idOf(f) === targetId) : list.indexOf(feature);
    if (!targetId || featureIndex < 0) {
      store.setError(errKey, t('attributeTable.featureExpired'));
      return;
    }
    const blocksConfig = getLayerConfig('blocks');
    const payload = { [colKey]: coerceAttributeValue(colKey, value) };
    const prev = { [colKey]: feature.properties?.[colKey] ?? null };
    const runUpdate = () =>
      Promise.resolve(blocksConfig?.dataSource.update(calculationId, targetId, payload as Partial<GeoJSON.Feature>))
        .then((res: any) => {
          const cur = store.rasterLayerFeatures[layerId] ?? [];
          if (cur[featureIndex]) {
            const next = [...cur];
            next[featureIndex] = {
              ...next[featureIndex],
              properties: { ...next[featureIndex].properties, [colKey]: res?.[colKey] ?? value },
            };
            store.setRasterLayerFeatures(layerId, next);
          }
          store.bumpGeometryVersion();
        })
        .catch((err: any) => store.setError(errKey, err?.message || t('workspace.block.updateFailed', { field: colKey })));
    pushAndExecute(
      createAttributeEditOperation(calculationId, `raster-${layerId}`, targetId, `Edit ${colKey}`, prev, payload, 'user'),
      () => { void runUpdate(); },
    );
  }, [calculationId, store, t, pushAndExecute]);

  /**
   * E3 — per-row delete for ANY active layer (builtin geometry, activity
   * features, imported finalized layers). Guard (R4) → confirm (R5) →
   * snapshot → DELETE → undo entry. Draft digitize layers keep the existing
   * digitize-delete-by-id path (buffered, no backend row yet).
   */
  // Owner report 2026-10-02: a map-workspace Delete for one sample plot, but
  // ONLY while no field inventory data has been uploaded for this forest yet
  // -- `FieldInventorySamplePlot` matches a crew's uploaded rows by block_name
  // + a plot number from that upload file, with no FK back to this sampling
  // design, so deleting/renumbering a plot here would silently desync real
  // field data once it exists. Kept separate from the generic
  // snapshot/undo/delete-guard path (`runDeleteFlow`) below -- sample plots
  // aren't geometry rows in that system (no undo support here; deleting one
  // is a confirm-gated destructive action, same weight as deleting the whole
  // design).
  const handleDeleteSamplePlot = useCallback(async (feature: GeoJSON.Feature) => {
    const props = feature.properties as Record<string, unknown> | undefined;
    const designId = props?.design_id as string | undefined;
    const plotNumber = props?.plot_number as number | undefined;
    if (!designId || plotNumber == null) {
      store.setError('sample_plots', t('workspace.delete.rowNoId'));
      return;
    }

    let hasFieldData = false;
    try {
      await fieldInventoryApi.getByCalculation(calculationId);
      hasFieldData = true;
    } catch {
      hasFieldData = false;
    }
    if (hasFieldData) {
      Modal.error({
        title: t('workspace.delete.blockedTitle', { layer: 'sample_plots' }),
        content: t('sampling.cannotDeletePlotFieldDataExists'),
      });
      return;
    }

    Modal.confirm({
      title: t('workspace.delete.confirmTitle', { layer: 'sample_plots' }),
      content: t('workspace.delete.confirmContent'),
      okText: t('common.delete'),
      okType: 'danger',
      cancelText: t('common.cancel'),
      onOk: async () => {
        try {
          await samplingApi.deleteSamplePlot(designId, plotNumber);
          store.bumpSamplePlotsRefreshVersion();
        } catch (err: any) {
          store.setError('sample_plots', err?.response?.data?.detail?.message || err?.message || t('workspace.block.updateFailed', { field: 'plot' }));
        }
      },
    });
  }, [calculationId, store, t]);

  // Owner report 2026-10-02 (rules 1/2/3/4): dragging a Sample Plot marker on
  // the map moves it. The backend (`PATCH /sampling/{design}/points/{n}`)
  // recomputes block/compartment/sub-area assignment and UTM/elevation from
  // the new location automatically (bumpGeometryVersion refetches, so the
  // attribute table picks up the recomputed values), and refuses the move
  // outright if the new point falls outside the forest boundary or if field
  // inventory data already exists -- `revert` snaps the marker back in
  // either case so the map never shows a position the backend didn't accept.
  const handleSamplePlotMoved = useCallback(async (
    feature: GeoJSON.Feature, lng: number, lat: number, revert: () => void,
  ) => {
    const props = feature.properties as Record<string, unknown> | undefined;
    const designId = props?.design_id as string | undefined;
    const plotNumber = props?.plot_number as number | undefined;
    if (!designId || plotNumber == null) {
      revert();
      store.setError('sample_plots', t('workspace.delete.rowNoId'));
      return;
    }
    try {
      await samplingApi.moveSamplePlot(designId, plotNumber, lng, lat);
      store.bumpSamplePlotsRefreshVersion();
    } catch (err: any) {
      revert();
      const msg = readDetail(err?.response?.data?.detail) ?? apiErrorText(err, t('workspace.block.updateFailed', { field: 'plot' }));
      store.setError('sample_plots', msg);
      message.error(msg, 8); // a plot dragged outside the forest snaps back; say why
    }
  }, [store, t]);

  // A coordinate typed into the Sample Plots table: latitude / longitude (WGS84) or UTM easting / northing. The server converts, checks that the
  // point is a number in range and inside the forest, and answers a friendly message (English or Nepali) when it is not; the cell then keeps the
  // old value because nothing changed. A saved value refreshes the layer, so the map, the table and the other coordinate system follow.
  const handleSaveSamplePlotCoordinate = useCallback(async (feature: GeoJSON.Feature, colKey: string, value: string) => {
    const props = feature.properties as Record<string, unknown> | undefined;
    const designId = props?.design_id as string | undefined;
    const plotNumber = props?.plot_number as number | undefined;
    if (!designId || plotNumber == null) {
      store.setError('sample_plots', t('workspace.delete.rowNoId'));
      return;
    }
    const field = ({ latitude: 'latitude', longitude: 'longitude', utm_easting: 'utm_easting', utm_northing: 'utm_northing' } as Record<string, string>)[colKey];
    if (!field) return;
    const number = parseLocaleNumber(value);
    // shown as a pop-up the user can read (the stored error is not displayed anywhere); the cell keeps its old value when refused
    const refuse = (msg: string) => { store.setError('sample_plots', msg); message.error(msg, 8); };
    if (value.trim() === '' || Number.isNaN(number)) {
      refuse(t('attributeTable.coordinateNotANumber', { defaultValue: 'That is not a number. The plot keeps its position.' }));
      return;
    }
    try {
      await samplingApi.setSamplePlotCoordinate(designId, plotNumber, { [field]: number });
      store.setError('sample_plots', null);
      store.bumpSamplePlotsRefreshVersion();
    } catch (err: any) {
      refuse(readDetail(err?.response?.data?.detail) ?? apiErrorText(err, t('workspace.block.updateFailed', { field: 'plot' })));
    }
  }, [store, t]);

  const handleDeleteFeature = useCallback((feature: GeoJSON.Feature, index = 0) => {
    const activeLayer = store.activeLayerId;
    const activeImportedId = store.activeImportedLayerId;

    if (!activeLayer && activeImportedId == null) return;
    if (activeLayer === 'sample_plots') {
      void handleDeleteSamplePlot(feature);
      return;
    }
    const calcId = calculationId;

    // Draft digitize rows: still only in the local buffer — keep old path.
    if (activeImportedId != null) {
      const layer = store.importedLayers.find((l) => l.id === activeImportedId);
      if (layer?.isDraft) {
        const fid = (feature.properties as Record<string, unknown>)?.featureId
          ?? (feature.properties as Record<string, unknown>)?.id
          ?? (feature as { id?: unknown }).id;
        if (fid == null) return;
        pushAndExecute(
          createDigitizeDeleteByIdOperation(activeImportedId, String(fid), feature, 'user'),
          () => store.removeDigitizeFeature(activeImportedId, String(fid)),
        );
        return;
      }
    }

    // Resolve the source feature id + full row context.
    const featureId = (feature.properties as Record<string, unknown>)?.featureId
      ?? (feature.properties as Record<string, unknown>)?.id
      ?? (feature as { id?: unknown }).id;
    if (featureId == null) {
      store.setError('attribute_table', t('workspace.delete.rowNoId'));
      return;
    }

    const layerType: FeatureDeleteLayerType | null = activeImportedId != null
      ? `import_${activeImportedId}`
      : (activeLayer as FeatureDeleteLayerType | null);
    if (!layerType) return;

    // `index` from the table is a filtered/sorted position — resolve the REAL
    // array index for the imported layer so feature_index stays stable on the
    // server (undo re-inserts at the same position, R5).
    let rawIndex: number | undefined;
    if (activeImportedId != null) {
      rawIndex = (store.importedLayerFeatures[activeImportedId] || []).findIndex(
        (f) => (f.properties as Record<string, unknown>)?.featureId === featureId
          || (f.properties as Record<string, unknown>)?.id === featureId
          || (f as { id?: unknown }).id === featureId,
      );
      if (rawIndex < 0) rawIndex = 0;
    }

    const ctx: FeatureRowContext = {
      calcId,
      layerType,
      featureId: String(featureId),
      importLayerId: activeImportedId ?? undefined,
      featureIndex: activeImportedId != null ? rawIndex : undefined,
    };

    void runDeleteFlow(ctx, feature);
  }, [store, calculationId, pushAndExecute, t, handleDeleteSamplePlot]);

  const runDeleteFlow = useCallback(async (ctx: FeatureRowContext, feature: GeoJSON.Feature) => {
    const buildin = !ctx.layerType.startsWith('import_');
    try {
      // Inventory guard (R4/R5) — only meaningful for builtin geometry rows.
      if (buildin && ctx.layerType !== 'activity_features') {
        let guard;
        try {
          guard = await fetchDeleteGuard(ctx);
        } catch {
          // legacy layers without a guard endpoint → skip guard, rely on confirm.
        }
        if (guard?.blocked) {
          const lines = (guard.reasons || []).map((r) => `${r.type.replace(/_/g, ' ')}: ${r.count}`).join(' · ');
          Modal.error({
            title: t('workspace.delete.blockedTitle', { layer: ctx.layerType }),
            content: lines
              ? t('workspace.delete.blockedContent', { lines })
              : t('workspace.delete.blockedNoDetail'),
          });
          return;
        }
      }

      Modal.confirm({
        title: t('workspace.delete.confirmTitle', { layer: ctx.layerType }),
        content: t('workspace.delete.confirmContent'),
        okText: t('common.delete'),
        okType: 'danger',
        cancelText: t('common.cancel'),
        onOk: async () => {
          // snapshot BEFORE delete so undo can restore the exact row (R5).
          let snapshot: Record<string, unknown> = {};
          if (ctx.importLayerId != null) {
            snapshot = { feature };
          } else if (ctx.layerType === 'boundary') {
            snapshot = { geometry: feature.geometry, area_hectares: feature.properties?.area_hectares };
          } else {
            try {
              snapshot = (await snapshotFeature(ctx)).snapshot;
            } catch {
              snapshot = { feature };
            }
          }
          try {
            await deleteFeatureRow(ctx);
          } catch (err) {
            if (!(err instanceof PlanLinesChoiceError)) throw err;
            const choice = await chooseWhatHappensToPlanLines(err.detail, t);
            if (!choice) return;
            await deleteFeatureRow({ ...ctx, planLines: choice });
            setPlanVersion((v) => v + 1);
          }
          pushAndExecute(
            createFeatureDeleteOperation(ctx.calcId, ctx.layerType, ctx.featureId, snapshot, 'user', {
              importLayerId: ctx.importLayerId,
              featureIndex: ctx.featureIndex,
            }),
            () => {
              if (ctx.importLayerId != null) {
                const list = store.importedLayerFeatures[ctx.importLayerId] || [];
                store.setImportedLayerFeatures(ctx.importLayerId, list.filter((_, i) => i !== ctx.featureIndex));
              }
              store.bumpGeometryVersion();
            },
          );
        },
      });
    } catch (err: any) {
      store.setError('delete', err?.message || t('workspace.delete.failed'));
    }
  }, [store, pushAndExecute, t]);

  const handleZoomToFeature = useCallback((feature: GeoJSON.Feature) => {
    if (!map || !feature?.geometry) { if (import.meta.env.DEV) console.log('[Zoom] bail', !!map, !!feature?.geometry); return; }
    try {
      const feat = L.geoJSON(feature as any);
      const bounds = feat.getBounds();
      if (import.meta.env.DEV) console.log('[Zoom]', feature?.properties?.name, 'valid=', bounds.isValid(), 'bounds=', JSON.stringify(bounds.toBBoxString?.() ?? null));
      if (bounds.isValid()) {
        fitBoundsWhenVisible(map, bounds, { padding: [60, 60], maxZoom: 18 });
      }
    } catch (e) {
      console.warn('Failed to zoom to feature:', e);
    }
  }, [map]);

  const featId = (f: GeoJSON.Feature): string =>
    String(f.properties?.id ?? f.properties?.featureId ?? (f as { id?: unknown }).id ?? '');

  // P4.6 — fit the map to the union of the currently-selected features.
  const handleZoomToSelection = useCallback(() => {
    const layerId = store.activeLayerId;
    if (!map || !layerId) return;
    const sel = store.selection.layerId === layerId ? store.selection.featureIds : [];
    if (sel.length === 0) return;
    const feats = (getLayerFeatures(layerId) ?? []).filter((f) => sel.includes(featId(f)) && f.geometry);
    if (feats.length === 0) return;
    try {
      const bounds = L.geoJSON({ type: 'FeatureCollection', features: feats } as never).getBounds();
      if (bounds.isValid()) fitBoundsWhenVisible(map, bounds, { padding: [60, 60], maxZoom: 18 });
    } catch (e) {
      if (import.meta.env.DEV) console.warn('Failed to zoom to selection:', e);
    }
  }, [map, store.activeLayerId, store.selection, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, subAreasQuery.data, activityQuery.data, samplePlotsQuery.data, fieldbookQuery.data, boundaryQuery.data]);

  // P4.6 — select every active-layer feature that intersects the current view.
  // "Places" cell of the Yearly plan view: select that plan line's places on the map and zoom to them (P4, YA-4.3)
  const handleSelectPlanPlaces = useCallback((line: { id: string }) => {
    const feats = (activityQuery.data ?? []).filter((f) => f.properties?.proposed_activity_id === line.id && f.geometry);
    if (feats.length === 0) return;
    store.setActiveLayer('activity_features');
    store.selectFeatures('activity_features', feats.map(featId).filter(Boolean), 'replace');
    if (map) {
      try {
        const bounds = L.geoJSON({ type: 'FeatureCollection', features: feats } as never).getBounds();
        if (bounds.isValid()) fitBoundsWhenVisible(map, bounds, { padding: [60, 60], maxZoom: 18 });
      } catch (e) {
        if (import.meta.env.DEV) console.warn('Failed to zoom to the places of a plan line:', e);
      }
    }
  }, [map, store, activityQuery.data]);

  const handleSelectInView = useCallback(() => {
    const layerId = store.activeLayerId;
    if (!map || !layerId) return;
    const view = map.getBounds();
    const ids: string[] = [];
    for (const f of getLayerFeatures(layerId) ?? []) {
      if (!f.geometry) continue;
      try {
        if (view.intersects(L.geoJSON(f as never).getBounds())) ids.push(featId(f));
      } catch { /* skip an unreadable geometry */ }
    }
    store.selectFeatures(layerId, ids.filter(Boolean), 'replace');
  }, [map, store, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, subAreasQuery.data, activityQuery.data, samplePlotsQuery.data, fieldbookQuery.data, boundaryQuery.data]);

  useEffect(() => {
    if (store.toolbarMode === 'subarea_category' && store.activeLayerId === 'sub_areas') {
      const sel = store.selection;
      if (sel && sel.featureIds.length > 0) {
        setShowCategoryPicker(true);
        setPendingCategory(null);
      }
    }
  }, [store.toolbarMode, store.activeLayerId, store.selection]);

  const handleCategoryCancel = useCallback(() => {
    setShowCategoryPicker(false);
    setPendingCategory(null);
    pendingCategoryRef.current = null;
    setAddSubAreaArm(false);
    store.setPendingFeature(null);
  }, [store]);

  useEffect(() => {
    if (!map || store.activeLayerId !== 'sub_areas' || store.toolbarMode !== 'draw_polygon') return;

    const commit = (geojson: GeoJSON.Feature) => {
      const layerConfig = getLayerConfig('sub_areas');
      if (!layerConfig) return;

      // P6 category-first: a category (pendingCategoryRef) is already armed →
      // create the drawn polygon with that category immediately, no post-draw picker.
      const armedCategory = pendingCategoryRef.current;
      if (armedCategory) {
        const feature = {
          ...geojson,
          properties: { ...(geojson.properties || {}), category: armedCategory },
        };
        layerConfig.dataSource.create(calculationId, feature)
          .then(async (created) => {
            pendingCategoryRef.current = null;
            setPendingCategory(null);
            store.setToolbarMode('select');
            store.bumpGeometryVersion();
            const newId = (created as unknown as { id?: string } | undefined)?.id;
            if (newId) setSubAreaPlanDialog({ open: true, focusId: String(newId) });
          })
          .catch((err: any) => {
            store.setError('sub_areas', err?.message || t('workspace.subArea.createFailed'));
            pendingCategoryRef.current = null;
            setPendingCategory(null);
            store.setToolbarMode('select');
          });
        return;
      }

      store.setPendingFeature(geojson);
      store.setToolbarMode('select');
      setShowCategoryPicker(true);
    };

    setSubAreaDrawVertexCount(0);
    setSubAreaDrawMeasurement(null);
    const session = startCustomDrawSession({
      map,
      kind: 'Polygon',
      color: '#4169E1',
      onChange: (latlngs, measurement) => {
        setSubAreaDrawVertexCount(latlngs.length);
        setSubAreaDrawMeasurement(measurement);
      },
      onFinish: (latlngs) => {
        const coords = latlngs.map((ll) => [ll.lng, ll.lat] as [number, number]);
        const geometry: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[...coords, coords[0]]] };
        commit({ type: 'Feature', properties: {}, geometry });
      },
      onCancel: () => {
        store.setToolbarMode('select');
      },
    });
    subAreaDrawSessionRef.current = session;

    return () => {
      subAreaDrawSessionRef.current = null;
      session.destroy();
      setSubAreaDrawVertexCount(0);
      setSubAreaDrawMeasurement(null);
    };
  }, [map, store.activeLayerId, store.toolbarMode, calculationId, store.bumpGeometryVersion, t]);

  const confirmSubAreaDraw = useCallback(() => {
    subAreaDrawSessionRef.current?.finish();
  }, []);
  const cancelSubAreaDraw = useCallback(() => {
    subAreaDrawSessionRef.current?.cancel();
  }, []);

  // Entering boundary-digitize starts a fresh island set (mode-transition based,
  // so a mid-draw registry remount that re-arms the effect keeps the polygons).
  const boundaryDrawWasActive = useRef(false);
  useEffect(() => {
    const active = store.activeLayerId === 'boundary' && store.toolbarMode === 'draw_polygon';
    if (active && !boundaryDrawWasActive.current) {
      boundaryIslandsRef.current = [];
      setBoundaryIslandCount(0);
    }
    boundaryDrawWasActive.current = active;
  }, [store.activeLayerId, store.toolbarMode]);

  // Assemble every drawn island and commit as ONE boundary write.
  const finishBoundaryDigitize = useCallback(async () => {
    const calcId = store.calculationId;
    const islands = boundaryIslandsRef.current;
    if (!calcId || islands.length === 0) return;
    const forestName = store.forestName || 'Forest';
    const n = islands.length;
    const geometry: GeoJSON.Geometry = n === 1
      ? islands[0]
      : { type: 'MultiPolygon', coordinates: islands.map((p) => p.coordinates) };
    const done = () => {
      message.success(t('workspace.forestBoundarySet', { count: n }));
      boundaryIslandsRef.current = [];
      setBoundaryIslandCount(0);
      store.bumpGeometryVersion();
      store.setToolbarMode('select');
    };
    try {
      // Pre-flight the overlap/gap gate over the assembled geometry.
      if (typeof forestApi.previewBoundaryOverlap === 'function') {
        try {
          const rel = await forestApi.previewBoundaryOverlap({ geometry, method: 'digitize', forest_id: calcId });
          if (rel?.overlapping_forests?.length || rel?.gaps?.length) {
            reviewBoundary({ geometry, forestName, method: 'digitize', calculationId: calcId, onResolved: done });
            return;
          }
        } catch { /* preview unavailable — fall through to the direct write */ }
      }
      if (n === 1) {
        const areaHa = turf.area({ type: 'Feature', properties: {}, geometry }) / 10000;
        const resp: any = await forestApi.updateBoundaryGeometry(calcId, { geometry, area_hectares: areaHa });
        if (resp?.needs_overlap_review) {
          reviewBoundary({ geometry: resp.preview_geometry || geometry, forestName, method: 'digitize', calculationId: calcId, onResolved: done });
          return;
        }
        reportDrawnBoundary(resp, t);
      } else {
        const mres = await forestApi.mergeForestBoundary(calcId, islands);
        reportDrawnBoundary(mres, t);
      }
      done();
    } catch (err: any) {
      const prov = provisionalFromError(err);
      if (prov?.needs_overlap_review && prov?.preview_geometry) {
        reviewBoundary({ geometry: prov.preview_geometry, forestName, method: 'digitize', calculationId: calcId, onResolved: done });
        return;
      }
      // The four boundary rules (outside Nepal / >1000 ha / >40% built-up /
      // protected area) — surface the reason, not a bare error.
      if (reportDrawnBoundary(err, t)) return;
      message.error(err?.message || t('workspace.failedSetBoundary'));
    }
  }, [store, calculationId, t, reviewBoundary]);

  const cancelBoundaryDigitize = useCallback(() => {
    boundaryDrawSessionRef.current?.destroy();
    boundaryDrawSessionRef.current = null;
    boundaryIslandsRef.current = [];
    setBoundaryIslandCount(0);
    setBoundaryDrawVertexCount(0);
    store.setToolbarMode('select');
  }, [store]);

  const closeBoundaryPiece = useCallback(() => {
    boundaryDrawSessionRef.current?.finish();
  }, []);
  const cancelBoundaryPiece = useCallback(() => {
    boundaryDrawSessionRef.current?.cancel();
  }, []);

  // ── Boundary digitize (builtin layer) — draw N islands, commit on Finish ────
  // Unified Geometry Drawing plan (P1): each island is now one
  // customDrawSession (Asks 2/3 — movable/deletable vertices + live vertex
  // count + live area while drawing a piece), replacing Geoman's Polygon
  // draw, which had neither. A finished piece pushes into boundaryIslandsRef
  // and immediately re-arms a fresh session for the next one — same
  // accumulate-then-commit shape as before, just without Geoman's own
  // re-arm-on-next-tick quirk.
  //
  // Owner-reported bug (2026-09-23): a closed piece looked "deleted" once the
  // next piece started drawing. The underlying data was never lost — it's
  // still in boundaryIslandsRef and gets merged correctly on Finish — but the
  // old preview (18% fill, thin dashed line, no label) was too faint to
  // notice next to a crisp in-progress shape. Bumped visibility + added a
  // numbered label per closed piece so "still there" is obvious at a glance.
  useEffect(() => {
    if (!map || store.activeLayerId !== 'boundary' || store.toolbarMode !== 'draw_polygon') return;

    const previewLayer = L.geoJSON().addTo(map);
    const labelLayer = L.featureGroup().addTo(map);
    const renderIslands = () => {
      previewLayer.clearLayers();
      labelLayer.clearLayers();
      boundaryIslandsRef.current.forEach((poly, i) => {
        previewLayer.addData({ type: 'Feature', properties: {}, geometry: poly } as GeoJSON.Feature);
        try {
          const centroid = turf.centroid({ type: 'Feature', properties: {}, geometry: poly });
          const [lng, lat] = centroid.geometry.coordinates;
          L.marker([lat, lng], {
            icon: L.divIcon({
              className: 'boundary-piece-label',
              html: `<div class="boundary-piece-label-dot">${i + 1}</div>`,
              iconSize: [22, 22],
              iconAnchor: [11, 11],
            }),
            interactive: false,
          }).addTo(labelLayer);
        } catch { /* a degenerate ring — skip its label, the outline still renders */ }
      });
      previewLayer.setStyle({ color: '#1D4ED8', weight: 3, fillColor: '#3B82F6', fillOpacity: 0.4, dashArray: '6, 3' } as L.PathOptions);
    };
    renderIslands();

    let disposed = false;
    const startIslandSession = () => {
      if (disposed) return;
      setBoundaryDrawVertexCount(0);
      setBoundaryDrawMeasurement(null);
      const session = startCustomDrawSession({
        map,
        kind: 'Polygon',
        color: '#4169E1',
        onChange: (latlngs, measurement) => {
          setBoundaryDrawVertexCount(latlngs.length);
          setBoundaryDrawMeasurement(measurement);
        },
        onFinish: (latlngs) => {
          const coords = latlngs.map((ll) => [ll.lng, ll.lat] as [number, number]);
          const polygon: GeoJSON.Polygon = { type: 'Polygon', coordinates: [[...coords, coords[0]]] };
          boundaryIslandsRef.current.push(polygon);
          setBoundaryIslandCount(boundaryIslandsRef.current.length);
          renderIslands();
          startIslandSession();
        },
        onCancel: () => {
          // Escape clears only the in-progress piece — already-closed islands
          // stay; the bar's own ✕ (cancelBoundaryDigitize) is what abandons
          // the whole multi-island draw.
          startIslandSession();
        },
      });
      boundaryDrawSessionRef.current = session;
    };
    startIslandSession();

    return () => {
      disposed = true;
      boundaryDrawSessionRef.current?.destroy();
      boundaryDrawSessionRef.current = null;
      if (map.hasLayer(previewLayer)) map.removeLayer(previewLayer);
      if (map.hasLayer(labelLayer)) map.removeLayer(labelLayer);
      setBoundaryDrawVertexCount(0);
      setBoundaryDrawMeasurement(null);
    };
  }, [map, store.activeLayerId, store.toolbarMode]);

  // ── User Group Boundary digitize (single-feature builtin) ──────────────────
  // Drawing a polygon → POST .../user-group/manual, which REPLACES the current
  // extent (single-feature model). No overlap review, no sub-area clipping —
  // this is an external catchment, not forest structure. In-place vertex-edit /
  // drag persistence is a deferred follow-up; for now editing = redraw.
  // Unified Geometry Drawing plan (P1): customDrawSession replaces Geoman's
  // Polygon draw here too (Asks 2/3 — movable/deletable vertices while
  // drawing). Geoman's old "click the first vertex to close the ring" gesture
  // has no equivalent in the new engine (P0 finding — no native mid-draw
  // vertex support to build on in the first place), so this layer now needs
  // its own small confirm bar (added below) the same way sub_areas/boundary
  // already have one.
  useEffect(() => {
    if (!map || store.activeLayerId !== 'user_group' || store.toolbarMode !== 'draw_polygon' || !calculationId) return;

    const onFinish = async (latlngs: L.LatLng[]) => {
      const coords = latlngs.map((ll) => [ll.lng, ll.lat] as [number, number]);
      const geometry: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[...coords, coords[0]]] };
      try {
        const res = await userGroupApi.createManualExtent(calculationId, geometry);
        if (/Analysis (skipped|could not)/.test(res?.message ?? '')) message.warning(res.message, 8);
        else message.success(t('workspace.userGroup.saved'));
        store.bumpGeometryVersion();
      } catch (err: unknown) {
        const detail = readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail);
        store.setError('user_group', detail || (err as { message?: string })?.message || t('workspace.userGroup.saveFailed'));
      } finally {
        store.setToolbarMode('select');
      }
    };

    setUserGroupDrawVertexCount(0);
    setUserGroupDrawMeasurement(null);
    const session = startCustomDrawSession({
      map,
      kind: 'Polygon',
      color: '#4338CA',
      onChange: (latlngs, measurement) => {
        setUserGroupDrawVertexCount(latlngs.length);
        setUserGroupDrawMeasurement(measurement);
      },
      onFinish,
      onCancel: () => store.setToolbarMode('select'),
    });
    userGroupDrawSessionRef.current = session;

    return () => {
      userGroupDrawSessionRef.current = null;
      session.destroy();
      setUserGroupDrawVertexCount(0);
      setUserGroupDrawMeasurement(null);
    };
  }, [map, store.activeLayerId, store.toolbarMode, calculationId, store.bumpGeometryVersion, t]);

  const finishUserGroupDraw = useCallback(() => {
    userGroupDrawSessionRef.current?.finish();
  }, []);
  const cancelUserGroupDraw = useCallback(() => {
    userGroupDrawSessionRef.current?.cancel();
  }, []);

  // pm:edit/pm:remove for activity_features drawn features — kept as its own
  // effect, gated ONLY on the active layer (not on toolbarMode), matching the
  // original behavior exactly. Unrelated to the draw-session effect below.
  useEffect(() => {
    if (!map || store.activeLayerId !== 'activity_features') return;
    const handleEdit = async (e: any) => {
      const layer = e.layer as any;
      const id = layer.feature?.properties?.id;
      if (!id) return;
      const geojson = layer.toGeoJSON();
      try {
        await fetch(`/api/yearly-activities/calculations/${calculationId}/drawn-features/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ geometry: geojson.geometry }),
        });
        store.bumpGeometryVersion();
      } catch (err) {
        console.error('Failed to update feature:', err);
      }
    };
    const handleRemove = async (e: any) => {
      const layer = e.layer as any;
      const id = layer.feature?.properties?.id;
      if (!id) return;
      try {
        await fetch(`/api/yearly-activities/calculations/${calculationId}/drawn-features/${id}`, { method: 'DELETE' });
        setActivityRefreshKey(k => k + 1);
        store.bumpGeometryVersion();
      } catch (err) {
        console.error('Failed to delete feature:', err);
      }
    };
    map.on('pm:edit', handleEdit);
    map.on('pm:remove', handleRemove);
    return () => {
      map.off('pm:edit', handleEdit);
      map.off('pm:remove', handleRemove);
    };
  }, [map, store.activeLayerId, calculationId, store.bumpGeometryVersion]);

  // Unified Geometry Drawing plan (P1/P3): activity-place draw (Point/Line/
  // Polygon, all feed the same add-activity wizard) now uses
  // customDrawSession instead of Geoman — Ask 1 (fuchsia numbered point while
  // it's briefly on the map before the wizard takes it), Ask 2 (movable/
  // deletable vertices for a Line/Polygon place), Ask 3 (live area/length).
  // Point still finishes on the first click (parity with the old Marker
  // draw); Line/Polygon need an explicit finish — Geoman's old "double-click
  // / click-the-first-vertex" gestures have no equivalent in the new engine
  // (P0 finding: nothing native to build that on), so they get the same
  // confirm-bar pattern every other migrated site already uses.
  useEffect(() => {
    if (!map || store.activeLayerId !== 'activity_features') return;
    const activeMode = store.toolbarMode;
    if (activeMode !== 'draw_point' && activeMode !== 'draw_line' && activeMode !== 'draw_polygon') return;
    const kind: DrawKind = activeMode === 'draw_point' ? 'Point' : activeMode === 'draw_line' ? 'Line' : 'Polygon';

    const commitPlace = (geometry: GeoJSON.Geometry) => {
      const { geometry: snapped } = snapToBlock({ geometry, blockFeatures: blocksQuery.data, enabled: snapEnabled });
      // A place is drawn FOR an activity (plan §5.1): it joins the add-activity wizard, which asks what it is
      // for, the years and the numbers, and saves everything together. (The old POST went to a route that
      // never existed, so a drawn place vanished without a word.)
      if (!canPlanRef.current) {
        message.info(t('yearlyPlan.error.notOwner'));
      } else {
        wizardHost.controller.addPlace({ geometry: snapped });
      }
      // the wizard shows the place; the drawn shape itself is not kept on the map
    };

    setActivityDrawVertexCount(0);
    setActivityDrawMeasurement(null);
    const session = startCustomDrawSession({
      map,
      kind,
      color: '#2f7d32',
      onChange: (latlngs, measurement) => {
        setActivityDrawVertexCount(latlngs.length);
        setActivityDrawMeasurement(measurement);
      },
      onFinish: (latlngs) => {
        const geometry: GeoJSON.Geometry = kind === 'Point'
          ? { type: 'Point', coordinates: [latlngs[0].lng, latlngs[0].lat] }
          : kind === 'Line'
          ? { type: 'LineString', coordinates: latlngs.map((ll) => [ll.lng, ll.lat]) }
          : { type: 'Polygon', coordinates: [[...latlngs.map((ll) => [ll.lng, ll.lat] as [number, number]), [latlngs[0].lng, latlngs[0].lat]]] };
        commitPlace(geometry);
      },
      onCancel: () => store.setToolbarMode('select'),
    });
    activityDrawSessionRef.current = session;

    return () => {
      activityDrawSessionRef.current = null;
      session.destroy();
      setActivityDrawVertexCount(0);
      setActivityDrawMeasurement(null);
    };
  }, [map, store.activeLayerId, store.toolbarMode, snapEnabled, blocksQuery.data, t, wizardHost.controller.drawNonce]);

  // Places drawn for the add-activity questions but not saved yet stay on the map (fuchsia = "not saved yet", like a point being
  // placed). Before this, a shape was taken off the map the moment it was finished - a point at its first click - so the user
  // could not see what had been mapped until the questions were saved.
  const pendingPlaces = wizardHost.controller.state.places;
  useEffect(() => {
    if (!map || pendingPlaces.length === 0) return undefined;
    const group = buildPendingPlacesLayer(pendingPlaces).addTo(map);
    return () => {
      if (map.hasLayer(group)) map.removeLayer(group);
    };
  }, [map, pendingPlaces]);

  const finishActivityDraw = useCallback(() => {
    activityDrawSessionRef.current?.finish();
  }, []);
  const cancelActivityDraw = useCallback(() => {
    activityDrawSessionRef.current?.cancel();
  }, []);

  // Owner report 2026-10-02: "Add Sample Plot" now arms click-to-place
  // (armed by LayerPanel's menu action, store.setToolbarMode('draw_point')
  // with activeLayerId 'sample_plots') instead of always dropping the new
  // plot at the map's center. The click itself never places anything
  // locally -- the backend is the one authority on "is this inside the
  // forest boundary" (same `ST_Contains` check `handleSamplePlotMoved`
  // relies on for a drag), so a click outside the boundary gets refused
  // (400) and bumpGeometryVersion is simply never called: no marker ever
  // appears, exactly rule 4 ("no clickable, no point generated" outside the
  // boundary).
  useEffect(() => {
    if (!map || store.activeLayerId !== 'sample_plots' || store.toolbarMode !== 'draw_point') return;

    const session = startCustomDrawSession({
      map,
      kind: 'Point',
      color: '#fbbf24',
      onFinish: async (latlngs) => {
        store.setToolbarMode('select');
        const { lng, lat } = latlngs[0];
        try {
          const designs = await samplingApi.list(calculationId);
          if (!designs || designs.length === 0) {
            message.info(t('layerPanel.noSampleDesign'));
            return;
          }
          const result = await samplingApi.addSamplePlot(designs[0].id, lng, lat);
          message.success(t('layerPanel.samplePlotAdded', { number: result.plot_number }));
          store.bumpSamplePlotsRefreshVersion();
        } catch (err: any) {
          const detail = err?.response?.data?.detail;
          message.error(
            (typeof detail === 'string' ? detail : detail?.message) || err?.message || t('workspace.failedDeleteData'),
          );
        }
      },
      onCancel: () => store.setToolbarMode('select'),
    });

    return () => session.destroy();
  }, [map, store.activeLayerId, store.toolbarMode, calculationId, t]);

  // ── Block-boundary invariant (E.8): "New Block / New Compartment" draw ─────
  // Armed by LayerPanel's ＋ button (newDrawArmRef). Scissor-style: click to add
  // ANY number of vertices (zig-zag included), a live area preview of the
  // resulting block (clipped to boundary / overlap warnings), and commit only
  // via the explicit "Finish & Create" button → POST /blocks/draw.  Uses the
  // same custom click-accumulator as the split tool — NOT Geoman's polygon
  // draw, whose `allowSelfIntersection:false` rejects concave zig-zag shapes
  // and which had no live area preview (UE-0.1 split lesson).
  const newDrawWasActive = useRef(false);
  useEffect(() => {
    const isDraw = store.toolbarMode === 'draw_polygon' && newDrawArmRef.current != null;
    if (isDraw && !newDrawWasActive.current) {
      newDrawCutRef.current = [];
      setNewDrawCount(0);
      setNewDrawPreview(null);
    }
    newDrawWasActive.current = isDraw;
  }, [store.toolbarMode]);

  // E.8 scissor-style draw effect: accumulate map clicks into newDrawCutRef,
  // redraw the draft polyline + preview polygon, and render the live preview.
  useEffect(() => {
    if (!map) return;
    const level = newDrawArmRef.current;
    if (!level) return;
    if (store.activeLayerId !== 'blocks' && store.activeLayerId !== 'compartments') return;
    if (store.toolbarMode !== 'draw_polygon') return;

    const existingForLevel = level === 'blocks' ? blocksQuery.data : compartmentsQuery.data;
    const boundaryFeatures = boundaryQuery.data;

    const cutLayer = L.featureGroup().addTo(map);
    const previewLayer = L.featureGroup().addTo(map);

    const renderPreview = () => {
      previewLayer.clearLayers();
      const pts = newDrawCutRef.current;
      if (pts.length < 3) {
        setNewDrawPreview(null);
        return;
      }
      const coords = pts.map((ll: L.LatLng) => [ll.lng, ll.lat] as [number, number]);
      const result = computeNewDrawPreview(coords, boundaryFeatures ?? undefined, existingForLevel ?? undefined);
      setNewDrawPreview(result);
      L.geoJSON(
        {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [[...coords, coords[0]]] },
          properties: {},
        } as any,
        {
          style: { color: '#2E7D32', weight: 2, opacity: 0.9, fillColor: '#81C784', fillOpacity: 0.25 },
          interactive: false,
        },
      ).addTo(previewLayer);
    };

    const line = L.polyline([], { color: '#2E7D32', weight: 2 }).addTo(cutLayer);
    const vertexMarkers: L.Marker[] = [];
    const handleIcon = L.divIcon({
      className: 'split-vertex-handle',
      html: '<div class="split-vertex-dot"></div>',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
    const redrawCut = () => {
      while (vertexMarkers.length) cutLayer.removeLayer(vertexMarkers.pop()!);
      line.setLatLngs(newDrawCutRef.current);
      const pts = newDrawCutRef.current;
      for (let i = 0; i < pts.length; i++) {
        const m = L.marker(pts[i], {
          icon: handleIcon,
          draggable: true,
          zIndexOffset: 2000,
        });
        m.on('drag', () => {
          line.setLatLngs(newDrawCutRef.current);
        });
        m.on('dragend', () => {
          const ll = m.getLatLng();
          newDrawCutRef.current[i] = ll;
          setNewDrawCount(newDrawCutRef.current.length);
          redrawCut();
          renderPreview();
        });
        m.addTo(cutLayer);
        vertexMarkers.push(m);
      }
    };
    const onNewDrawClick = (e: L.LeafletMouseEvent) => {
      const pts = newDrawCutRef.current;
      const last = pts[pts.length - 1];
      if (last && Math.abs(last.lat - e.latlng.lat) < 1e-9 && Math.abs(last.lng - e.latlng.lng) < 1e-9) return;
      pts.push(e.latlng);
      setNewDrawCount(pts.length);
      redrawCut();
      renderPreview();
    };
    redrawCut();
    renderPreview();
    map.on('click', onNewDrawClick);

    return () => {
      map.off('click', onNewDrawClick);
      if (map.hasLayer(cutLayer)) map.removeLayer(cutLayer);
      if (map.hasLayer(previewLayer)) map.removeLayer(previewLayer);
      setNewDrawPreview(null);
    };
  }, [map, store.activeLayerId, store.toolbarMode, boundaryQuery.data, blocksQuery.data, compartmentsQuery.data]);

  // E.8 commit: build the closed Polygon from the accumulated clicks and POST
  // it to the E.7 draw endpoint, then surface clip / remainder / reject toasts.
  const confirmNewDraw = useCallback(async () => {
    const level = newDrawArmRef.current;
    if (!level) return;
    const pts = newDrawCutRef.current;
    if (pts.length < 3) {
      message.warning(t('workspace.draw.minThreePoints'));
      return;
    }
    const coordinates = pts.map((ll: L.LatLng) => [ll.lng, ll.lat] as [number, number]);
    const geometry: GeoJSON.Geometry = { type: 'Polygon', coordinates: [[...coordinates, coordinates[0]]] };
    const typeLabel = level === 'compartments' ? t('workspace.types.compartment') : t('workspace.types.block');
    newDrawCutRef.current = [];
    setNewDrawCount(0);
    setNewDrawPreview(null);
    newDrawArmRef.current = null;
    try {
      const result = await forestApi.drawBlock(calculationId, { level, geometry });
      const notes: string[] = [];
      if (result.clipped && result.removed_ha > 0) {
        notes.push(t('workspace.draw.clippedNote', { ha: result.removed_ha.toFixed(4) }));
      }
      if (result.invariant?.remainder_added) {
        notes.push(t('workspace.draw.remainderNote', { type: typeLabel, ha: result.invariant.gap_ha.toFixed(4) }));
      }
      message.success(
        notes.length > 0
          ? t('workspace.draw.createdWithNote', { type: typeLabel, name: result.block.name, area: result.block.area_hectares, notes: notes.join('; ') })
          : t('workspace.draw.created', { type: typeLabel, name: result.block.name, area: result.block.area_hectares }),
        6,
      );
      store.bumpGeometryVersion();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const raw = readDetail(detail);
      const dcode = detail && typeof detail === 'object' ? (detail as any)?.code : null;
      const isOutside = dcode === 'OUTSIDE_BOUNDARY' || (typeof detail === 'string' && detail.includes('OUTSIDE_BOUNDARY'));
      const isTopology = dcode === 'TOPOLOGY_REJECTED' || (typeof detail === 'string' && detail.includes('TOPOLOGY_REJECTED'));
      if (isOutside) {
        message.error(t('workspace.draw.outsideBoundary', { type: typeLabel }), 6);
      } else if (isTopology) {
        message.error(t('workspace.draw.overlapsExisting', { type: typeLabel }), 6);
      } else {
        message.error(raw || err?.message || t('workspace.draw.createFailed', { type: typeLabel }), 6);
      }
    }
    store.setToolbarMode('select');
  }, [calculationId, store, forestApi, t]);

  const cancelNewDraw = useCallback(() => {
    newDrawArmRef.current = null;
    newDrawCutRef.current = [];
    setNewDrawCount(0);
    setNewDrawPreview(null);
    store.setToolbarMode('select');
  }, [store]);

  // ── GD 1.3.2: Digitize draw path (draft layers) ──────────────────────────
  // Single-active-context rule: this block only runs when a digitize context is
  // set AND no domain layer (sub_areas/activity_features) is being edited.
  useEffect(() => {
    console.log('[DigitizeDraw] Effect running', { 
      hasMap: !!map, 
      activeDigitizeContext: store.activeDigitizeContext,
      activeLayerId: store.activeLayerId,
      toolbarMode: store.toolbarMode,
      digitizeSyncState: store.digitizeSyncState,
    });
    if (!map) return;
    const ctx = store.activeDigitizeContext as ActiveDigitizeContext | null;
    if (!ctx) {
      console.log('[DigitizeDraw] No active digitize context');
      return;
    }
    // Mutual exclusion with domain-layer draw blocks (single-active-context rule)
    if (store.activeLayerId === 'sub_areas' || store.activeLayerId === 'activity_features') {
      console.log('[DigitizeDraw] Blocked by domain layer:', store.activeLayerId);
      return;
    }
    const layer = ctx.layer;
    if (!layer) {
      console.log('[DigitizeDraw] No layer in context');
      return;
    }
    if (store.digitizeSyncState !== 'idle') {
      console.log('[DigitizeDraw] Sync state not idle:', store.digitizeSyncState);
      return;
    }

    const allowed = allowedGeometryTypes(layer.purpose);
    console.log('[DigitizeDraw] Layer purpose:', layer.purpose, 'allowed:', allowed);
    
    // Map toolbarMode to Geoman shape names
    const shapeMap: Record<string, string> = {
      draw_point: 'Marker',
      draw_line: 'Line',
      draw_polygon: 'Polygon',
    };
    const shape = store.toolbarMode ? shapeMap[store.toolbarMode] : undefined;
    if (!shape) {
      console.log('[DigitizeDraw] No shape for toolbarMode:', store.toolbarMode);
      return;
    }
    const allowedGeomType = shape === 'Marker' ? 'Point' : shape === 'Line' ? 'LineString' : 'Polygon';
    if (!allowed.includes(allowedGeomType)) {
      console.log('[DigitizeDraw] Geometry type not allowed:', allowedGeomType);
      return;
    }

    // 1. Create the destination FeatureGroup
    const drawLayer = L.featureGroup().addTo(map);
    console.log('[DigitizeDraw] drawLayer added to map, hasLayer:', map.hasLayer(drawLayer));

    // 2. Opt-in fix: if app uses L.PM.setOptIn(true), explicitly enable this layer
    // (drawLayer as any).options.pmIgnore = false;
    // if ((L as any).PM?.reInitLayer) { (L as any).PM.reInitLayer(drawLayer); }

    // 3. Enable draw mode ON THE MAP, scoped to your FeatureGroup
    const drawOptions = {
      layerGroup: drawLayer,        // ← draws INTO this group
      snappable: snapEnabled,
      snapDistance: 5,
      allowSelfIntersection: shape === 'Line',
      continueDrawing: true,        // keep drawing mode active for multiple features
      ...getTouchPmDrawOptions(),
    };

    console.log('[DigitizeDraw] Enabling draw mode:', shape, 'options:', drawOptions);
    (map as any).pm.enableDraw(shape, drawOptions);

    // 4. Debug: verify draw mode is actually active
    console.log('[DigitizeDraw] Draw mode active?', (map as any).pm.globalDrawModeEnabled());
    console.log('[DigitizeDraw] Active shape?', (map as any).pm.Draw?.getActiveShape());

    // 5. Listen on the map (standard Geoman behavior - pm:create fires on map)
    const handleCreate = async (e: any) => {
      console.log('[DigitizeDraw] pm:create fired', e);
      // e.layer is the newly created layer, already inside drawLayer
      // e.shape is 'Marker' | 'Line' | 'Polygon'
      const layerObj = e.layer as L.Layer;
      const geojson = (layerObj as any).toGeoJSON() as GeoJSON.Feature;
      if (!geojson?.geometry) {
        console.log('[DigitizeDraw] No geometry in created feature');
        return;
      }
      // Purpose geometry gate (SSOT)
      const gtype = geojson.geometry.type as 'Point' | 'LineString' | 'Polygon';
      if (!allowed.includes(gtype)) {
        console.warn(`[DigitizeDraw] Geometry type ${gtype} not allowed for purpose '${layer.purpose}'`);
        (map as any).pm.disableDraw();
        store.setToolbarMode('select');
        return;
      }
      const featureId = `digitize-temp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const withId: GeoJSON.Feature = {
        ...geojson,
        properties: { ...(geojson.properties || {}), featureId },
      };
      // Buffer-only write (NOT a direct PATCH) — flushed later by useDraftSync
      pushAndExecute(
        createDigitizeAddOperation(layer.id, withId, 'user'),
        () => store.enqueueDigitizeFeature(layer.id, withId),
      );
    };
    map.on('pm:create', handleCreate);

    return () => {
      console.log('[DigitizeDraw] Cleanup');
      // 6. CRITICAL: Disable draw mode BEFORE removing the layer
      // This prevents Geoman from holding references to destroyed layers
      (map as any).pm.disableDraw();
      
      map.off('pm:create', handleCreate);
      drawLayer.removeFrom(map);
      console.log('[DigitizeDraw] Cleanup complete');
    };
  }, [map, store.activeDigitizeContext, store.activeLayerId, store.toolbarMode, store.digitizeSyncState, snapEnabled, pushAndExecute]);

  // ── E-2 production Geoman editing pipeline (replaces the E-0 spike).
  // vertex_edit on any polygon built-in layer: snapshot on dragstart, local
  // R6 topology pre-check + one POST on drag-release, immediate POST on
  // vertex add/delete, never POST on continuous `pm:edit`, revert+toast on
  // local GAP/OVERLAP or server 409 TOPOLOGY_REJECTED.
  const isDev = import.meta.env.DEV;

  // ── VR-0 diagnostics: `window.__vertexDebug()` in the browser console.
  // The vertex_edit effect installs the real probe into this ref while armed;
  // calling it at any other time reports WHY it is not armed instead of
  // throwing, so the console session is self-explaining.
  const vertexDebugRef = useRef<(() => unknown) | null>(null);
  useEffect(() => {
    if (!isDev || typeof window === 'undefined') return;
    const probe = () => vertexDebugRef.current?.() ?? {
      armed: false,
      hint: 'Vertex tool is not armed. Select a polygon layer and press V.',
      toolbarMode: useWorkspaceStore.getState().toolbarMode,
      activeLayerId: useWorkspaceStore.getState().activeLayerId,
      breadcrumbs: (document.documentElement.dataset.geoLog
        && JSON.parse(document.documentElement.dataset.geoLog)) || [],
    };
    (window as any).__vertexDebug = probe;
    // Delete ONLY if we still own the global.  MapWorkspace remounts during
    // load (and StrictMode double-invokes effects), so an unconditional delete
    // in cleanup lets the OLD instance tear down the NEW instance's probe —
    // which is exactly why the first VR-0 run reported "__vertexDebug not
    // installed" while its breadcrumbs proved the module was live.
    return () => {
      if ((window as any).__vertexDebug === probe) delete (window as any).__vertexDebug;
    };
  }, [isDev]);

  useEffect(() => {
    const dbg: string[] = [];
    const mark = (s: string) => {
      dbg.push(s); if (isDev) (window as any).__geoDebug = dbg;
      if (isDev && typeof document !== 'undefined' && document.documentElement) {
        document.documentElement.dataset.geoDebug = E2_ID + ':' + dbg.join(' → ');
        const d = document.documentElement;
        const log = d.dataset.geoLog ? JSON.parse(d.dataset.geoLog) : [];
        const prevCount = (d.dataset.geoRunCount && JSON.parse(d.dataset.geoRunCount)) || {};
        const n = (prevCount[E2_ID] || 0) + 1;
        prevCount[E2_ID] = n;
        d.dataset.geoRunCount = JSON.stringify(prevCount);
        log.push(E2_ID + ' #' + n + ' ' + s + ' t=' + Date.now());
        d.dataset.geoLog = JSON.stringify(log.slice(-30));
      }
    };
    if (!map) { mark('bail:no-map'); return; }
    if (store.toolbarMode !== 'vertex_edit') { mark('bail:not-vertex-mode(' + store.toolbarMode + ')'); return; }
    const activeLayerId = store.activeLayerId;
    if (!activeLayerId) { mark('bail:no-layer'); return; }
    if (activeLayerId === 'activity_features') { mark('bail:activity'); return; }

    // Selectionless V-3: arm the WHOLE active layer — no manual row selection.
    // The layer data below is the source of truth for what is editable; the
    // registry is re-read at arm time so a map remount that re-registered
    // layers is picked up on the next run (geometryVersion dep re-arms too).
    const layerFeatures =
      (activeLayerId === 'boundary' && boundaryQuery.data)
      || (activeLayerId === 'user_group' && userGroupQuery.data)
      || (activeLayerId === 'blocks' && blocksQuery.data)
      || (activeLayerId === 'sub_blocks' && subBlocksQuery.data)
      || (activeLayerId === 'compartments' && compartmentsQuery.data)
      || (activeLayerId === 'sub_compartments' && subCompartmentsQuery.data)
      || (activeLayerId === 'sub_areas' && subAreasQuery.data)
      || null;
    if (!layerFeatures || layerFeatures.length === 0) {
      mark('bail:no-features(layer=' + activeLayerId + ')');
      return;
    }

    // Scoped registry — ONLY this layer's features.  The global registry holds
    // every builtin + imported layer; arming it wholesale leaks Geoman markers
    // into unrelated layers (the "forest-boundary vertex markers during block
    // edit" bug) and a drag there commits the wrong feature.
    const globalReg = getFeatureLayerRegistry();
    const scopeIds: string[] = [];
    for (const f of layerFeatures) {
      const fid = featureIdOf(f);
      if (fid && globalReg.get(fid)) scopeIds.push(fid);
      else if (import.meta.env.DEV) console.warn(
        `[GeometryEdit] no registry layer for ${activeLayerId}::${fid ?? '<no-id>'} — skipped`,
      );
    }
    if (scopeIds.length === 0) {
      mark('bail:no-registry(layer=' + activeLayerId + ' regSize=' + globalReg.size + ')');
      const t = setTimeout(() => setVertexRetryTick((n) => n + 1), 400);
      return () => clearTimeout(t);
    }
    const scopedRegistry = {
      get: (fid: string): L.Layer | undefined => globalReg.get(fid),
      forEach: (cb: (fid: string, layer: L.Layer) => void): void => {
        for (const fid of scopeIds) {
          const l = globalReg.get(fid);
          if (l) cb(fid, l);
        }
      },
    };
    const primaryId = scopeIds[0];
    mark('armed count=' + scopeIds.length + ' layer=' + activeLayerId + ' primary=' + primaryId + ' regSize=' + globalReg.size);

    // R6 neighbour index — same-level features only (boundary has no siblings).
    const neighbourFeatures = activeLayerId === 'boundary' ? null : layerFeatures;
    const neighbourIndex = neighbourFeatures ? new SharedEdgeIndex(neighbourFeatures) : null;

    if (import.meta.env.DEV) console.log(
      `[GeometryEdit] vertex_edit armed: layer=${activeLayerId} features=${scopeIds.length}`,
    );

    // V-3 mask source of truth, shared by the Geoman mask callback, the
    // silent-lock guard below, and the VR-0 diagnostic probe, so none of the
    // three can ever disagree about which vertex is editable.
    // `null` = deliberately unmasked layer (sub_areas), NOT "nothing editable".
    const classifyFor = (
      geom: GeoJSON.Geometry | null | undefined,
      fid: string,
    ): VertexClassification | null => {
      // activity_features bailed above; sub_areas has no shell concept.
      if (activeLayerId === 'sub_areas') return null;
      const empty: VertexClassification = { shared: [], shell: [], editable: [], vertexCount: 0 };
      if (!geom) return empty;
      // Rule A: boundary markers only when NO structural layer exists.
      if (activeLayerId === 'boundary') {
        const base = classifyVertices(geom, { layerType: LAYER_TYPES.boundary });
        const hasStructure = !!(
          (blocksQuery.data && blocksQuery.data.length > 0) ||
          (subBlocksQuery.data && subBlocksQuery.data.length > 0) ||
          (compartmentsQuery.data && compartmentsQuery.data.length > 0) ||
          (subCompartmentsQuery.data && subCompartmentsQuery.data.length > 0)
        );
        // Locked by structure → report the vertices as shell (that IS the
        // reason they are locked) so the diagnostic dump stays honest.
        return hasStructure
          ? { shared: [], shell: base.editable, editable: [], vertexCount: base.vertexCount }
          : base;
      }
      const layerType = activeLayerId as ClassifiableLayerType;
      const others = (layerFeatures ?? []).filter((f) => featureIdOf(f as any) !== String(fid));
      const shells =
        activeLayerId === 'blocks' ? boundaryQuery.data
        : activeLayerId === 'sub_blocks' ? blocksQuery.data
        : activeLayerId === 'compartments' ? blocksQuery.data
        : compartmentsQuery.data; // sub_compartments
      const shell = shellGeometryFor(layerType, fid, layerFeatures, shells);
      return classifyVertices(geom, {
        layerType,
        sameLevelFeatures: others,
        parentShell: shell,
      });
    };

    const editableFor = (
      geom: GeoJSON.Geometry | null | undefined,
      fid: string,
    ): Array<[number, number]> | null => {
      const cls = classifyFor(geom, fid);
      if (cls === null) return null;
      const out: Array<[number, number]> = [];
      for (const index of cls.editable) {
        const c = coordAtIndex(geom, index);
        if (c) out.push([c[0], c[1]]);
      }
      return out;
    };

    // Silent-lock guard.  When the rules leave NOTHING editable the map renders
    // zero vertex markers, which is indistinguishable from a broken tool — the
    // user sees an armed toolbar and an empty map and cannot tell why.  Count
    // the editable vertices up front and say which rule is responsible.
    // (`null` = deliberately unmasked layer, e.g. sub_areas — not a lock.)
    let editableTotal = 0;
    let masked = false;
    for (const fid of scopeIds) {
      const e = editableFor(featureGeometryOf(layerFeatures, fid), fid);
      if (e === null) { masked = false; break; }
      masked = true;
      editableTotal += e.length;
    }
    if (masked && editableTotal === 0) {
      const hasStructure = !!(
        (blocksQuery.data && blocksQuery.data.length > 0) ||
        (subBlocksQuery.data && subBlocksQuery.data.length > 0) ||
        (compartmentsQuery.data && compartmentsQuery.data.length > 0) ||
        (subCompartmentsQuery.data && subCompartmentsQuery.data.length > 0)
      );
      // VR-4.1(d): the boundary-locked case is now surfaced BEFORE the click —
      // the toolbar greys the vertex button out with the same reason — so the
      // tool should not arm at all here.  The remaining two cases are not
      // locks; they are "this layer happens to have nothing shared", which can
      // only be known after classification, so they stay as a toast.
      if (activeLayerId === 'boundary' && hasStructure) {
        mark('no-editable-vertices(boundary-locked)');
      } else {
        message.info(
          scopeIds.length < 2
            ? t('workspace.edit.noEditableSingleFeature')
            : t('workspace.edit.noEditableAllShell'),
        );
        mark('no-editable-vertices(layer=' + activeLayerId + ')');
      }
    }
    mark('vertex_editable_count total=' + editableTotal + ' features=' + scopeIds.length
      + ' masked=' + masked);

    // ── VR-0 diagnostics ────────────────────────────────────────────────────
    // Live probe of what the vertex tool sees RIGHT NOW.  Recomputed on every
    // call (never cached at arm time) so the dump reflects current geometry
    // and the current Geoman marker set.  The whole point is to compare the
    // rule's `editable` count against the markers actually on screen — if they
    // disagree, the failure is in the masking layer, not the classifier.
    const markerStats = (layer: L.Layer | undefined) => {
      const pm = (layer as any)?.pm;
      if (!pm) return { total: 0, rendered: 0, pmEnabled: false };
      let markers: ReturnType<typeof collectVertexMarkers> = [];
      try {
        markers = collectVertexMarkers(pm._markers);
      } catch {
        return { total: 0, rendered: 0, pmEnabled: !!pm.enabled?.() };
      }
      let rendered = 0;
      for (const m of markers) {
        const icon = (m as any)._icon as HTMLElement | null | undefined;
        // A masked (locked) marker carries `.pm-locked` → display:none.
        if (!icon || !icon.classList.contains('pm-locked')) rendered += 1;
      }
      return { total: markers.length, rendered, pmEnabled: !!pm.enabled?.() };
    };

    vertexDebugRef.current = () => {
      const reg = getFeatureLayerRegistry();
      const features = scopeIds.map((fid) => {
        const layer = reg.get(fid);
        const serverGeom = featureGeometryOf(layerFeatures, fid);
        // Prefer LIVE geometry — after a drag the server copy is stale, and a
        // mismatch between the two is itself a finding worth seeing.
        const geom = (layer ? liveGeometryOf(layer) : null) ?? serverGeom;
        const cls = classifyFor(geom, fid);
        const m = markerStats(layer);
        // VR-0 root-cause probe: `maskVertexMarkers` matches a marker to the
        // editable set by an EXACT 9-dp coordinate key.  Compare the two key
        // spaces directly — if they never intersect, the mask hides every
        // marker regardless of what the classifier decided.
        let keyProbe: Record<string, unknown> | null = null;
        try {
          const key = (lng: number, lat: number) => lng.toFixed(9) + ',' + lat.toFixed(9);
          const editableKeys = new Set(
            (editableFor(geom, fid) ?? []).map(([lng, lat]) => key(lng, lat)),
          );
          const pmMarkers = collectVertexMarkers((layer as any)?.pm?._markers);
          const markerKeys = pmMarkers.map((mk) => {
            const ll = mk.getLatLng();
            return key(ll.lng, ll.lat);
          });
          keyProbe = {
            editableKeysSample: [...editableKeys].slice(0, 2),
            markerKeysSample: markerKeys.slice(0, 2),
            intersecting: markerKeys.filter((k) => editableKeys.has(k)).length,
          };
        } catch { /* probe only */ }
        const name = (layerFeatures ?? []).find(
          (f) => featureIdOf(f as any) === String(fid),
        )?.properties?.name ?? null;
        return {
          id: fid,
          name,
          verts: cls?.vertexCount ?? 0,
          shared: cls?.shared.length ?? 0,
          shell: cls?.shell.length ?? 0,
          editable: cls === null ? 'unmasked' : cls.editable.length,
          markersTotal: m.total,
          markersRendered: m.rendered,
          pmEnabled: m.pmEnabled,
          // The one assertion that matters for VR-0.
          match: cls === null ? null : cls.editable.length === m.rendered,
          inRegistry: !!layer,
          liveGeomDiffersFromServer: !!(layer && serverGeom
            && JSON.stringify(liveGeometryOf(layer)) !== JSON.stringify(serverGeom)),
          keyProbe,
        };
      });
      return {
        layer: activeLayerId,
        armedFeatures: scopeIds.length,
        registrySize: reg.size,
        toolbarMode: store.toolbarMode,
        expectedEditableTotal: editableTotal,
        renderedMarkerTotal: features.reduce((n, f) => n + f.markersRendered, 0),
        allMatch: features.every((f) => f.match !== false),
        features,
        breadcrumbs: dbg.slice(-30),
      };
    };

    const cleanup = enableGeometryEdit(map, scopedRegistry, primaryId, {
      topology: neighbourIndex,
      // V-2 atomic shared-vertex move: only structural built-in layers
      // propagate.  computeSharedMoves returns the SHARED partners (if the
      // dragged vertex was coincident-shared); the local pre-check then
      // validates against the propagated set so a shared drag passes.
      // Selectionless V-3: the dragged marker's OWN feature is propagated.
      sharedMove:
        activeLayerId === 'blocks'
        || activeLayerId === 'sub_blocks'
        || activeLayerId === 'compartments'
        || activeLayerId === 'sub_compartments'
        // user_group too: each polygon is its own row, so a vertex shared by two
        // of them is a shared vertex in exactly the block sense. Without this,
        // dragging it moved one polygon and tore the pair apart.
        || activeLayerId === 'user_group'
          ? (feature, snapshot, sharedId) => computeSharedMoves({
              featureId: sharedId,
              snapshot: snapshot.geometry,
              updated: feature.geometry,
              layerFeatures: layerFeatures ?? [],
            })
          : undefined,
      // V-4 (D4) shared-edge add/delete: a vertex inserted on a shared edge is
      // inserted on BOTH units, and a shared vertex deleted is deleted from
      // both — same atomic batch as the shared move, so the two sides never
      // stop sharing that vertex.  Structural layers only.
      sharedVertexChange:
        activeLayerId === 'blocks'
        || activeLayerId === 'sub_blocks'
        || activeLayerId === 'compartments'
        || activeLayerId === 'sub_compartments'
        // A vertex added on an edge shared by two user-group polygons must land on
        // both, and a deleted shared vertex must leave both - same as blocks.
        || activeLayerId === 'user_group'
          ? (feature, snapshot, sharedId) => computeSharedVertexChange({
              featureId: sharedId,
              snapshot: snapshot.geometry,
              updated: feature.geometry,
              layerFeatures: layerFeatures ?? [],
            })
          : undefined,
      // V-3 (D1) render-only-editable: locked (outer-shell / unshared) vertices
      // get NO marker — the user cannot grab what is not there.  The editable
      // set comes from the V-1 classifier, per armed layer (selected feature +
      // neighbours), against its own parent shell.
      mask: (layer, fid) => editableFor(
        liveGeometryOf(layer) ?? featureGeometryOf(layerFeatures, fid),
        fid,
      ),
      // VR-5 shared-edge midpoint rule.  A midpoint may be subdivided when it
      // lies on a same-level sibling's boundary (the edge is shared) and NOT
      // on the parent shell — regardless of whether its two corners are
      // locked.  Without this an auto-divided layer is completely uneditable:
      // an equal-area division cuts with straight segments, so every vertex is
      // a cut endpoint on the parent shell and every corner is locked
      // (measured on बृन्दाबन: shell == vertexCount for all 8 compartments).
      // Inserting here moves no locked vertex, and the new vertex is
      // shared-and-not-shell, i.e. immediately editable.
      midpointInsertable: (_layer, fid, lng, lat) => {
        if (activeLayerId === 'boundary' || activeLayerId === 'sub_areas') return false;
        const others = (layerFeatures ?? []).filter(
          (f) => featureIdOf(f as any) !== String(fid),
        );
        const onSibling = others.some((f) => {
          const g = (f as any)?.geometry as GeoJSON.Geometry | null;
          return !!g && isOnBoundary(lng, lat, g);
        });
        if (!onSibling) return false;
        const shells =
          activeLayerId === 'blocks' ? boundaryQuery.data
          : activeLayerId === 'sub_blocks' ? blocksQuery.data
          : activeLayerId === 'compartments' ? blocksQuery.data
          : compartmentsQuery.data; // sub_compartments
        const shell = shellGeometryFor(
          activeLayerId as ClassifiableLayerType, fid, layerFeatures, shells,
        );
        return !(shell && isOnBoundary(lng, lat, shell));
      },
      commit: async (feature, snapshot, sharedMove, draggedId) => {
        try {
          const draggedFeatureId = draggedId ?? primaryId;
          const prevGeom = (snapshot as GeoJSON.Feature | null)?.geometry;
          // Boundary has no edit-geometry route (backend rejects layer_type=
          // 'boundary') — persist through PUT /boundary exactly like the draw/
          // import flow, and recompute the geodesic area so result_data stays
          // accurate (the endpoint stores whatever area_hectares it is given).
          if (activeLayerId === 'boundary') {
            try {
              // A multipart boundary is shown as one feature PER PART. Editing
              // one part must re-assemble the whole MultiPolygon, or the save
              // would replace the boundary with just the edited piece.
              let geomToSave: GeoJSON.Geometry = feature.geometry;
              const allParts = boundaryQuery.data || [];
              if (allParts.length > 1) {
                const others = allParts.filter((f) => featureIdOf(f as any) !== draggedFeatureId);
                const toRings = (g: any): number[][][][] =>
                  g?.type === 'MultiPolygon' ? g.coordinates : g?.type === 'Polygon' ? [g.coordinates] : [];
                const rings = [
                  ...toRings(feature.geometry),
                  ...others.flatMap((f) => toRings((f as any).geometry)),
                ];
                geomToSave = { type: 'MultiPolygon', coordinates: rings } as GeoJSON.Geometry;
              }
              const bres: any = await forestApi.updateBoundaryGeometry(calculationId, {
                geometry: geomToSave,
                area_hectares: (turf.area(geomToSave as any) || 0) / 10000,
              });
              // PF-3: a reshaped boundary that now overlaps/gaps a neighbour is
              // NOT written — the backend returns a provisional. Surface the
              // preview so the user decides (Accept/Include/Dispute) before the
              // boundary is persisted; the edit is otherwise reverted.
              if (bres?.needs_overlap_review) {
                reviewBoundary({
                  geometry: bres.preview_geometry || geomToSave,
                  forestName: store.forestName || 'Forest',
                  method: 'digitize',
                  calculationId,
                  onResolved: () => store.bumpGeometryVersion(),
                });
                return { ok: true, status: 200 };
              }
              // VR-6 (D6): sub-areas past the new edge were re-clipped.  Say so
              // — silently shrinking a recorded sub-area changes every excluded
              // area figure downstream and must not pass unnoticed.
              const clipped: string[] = bres?.sub_areas_clipped ?? [];
              const dropped: string[] = bres?.sub_areas_dropped ?? [];
              if (clipped.length) {
                message.warning(t('workspace.geometry.subAreasClipped', { count: clipped.length }));
              }
              if (dropped.length) {
                message.warning(t('workspace.geometry.subAreasDropped', { count: dropped.length }));
              }
            } catch (err: any) {
              const prov = provisionalFromError(err);
              if (prov?.needs_overlap_review && prov?.preview_geometry) {
                reviewBoundary({
                  geometry: prov.preview_geometry,
                  forestName: store.forestName || 'Forest',
                  method: 'digitize',
                  calculationId,
                  onResolved: () => store.bumpGeometryVersion(),
                });
                return { ok: true, status: 200 };
              }
              const detail = (err as any)?.response?.data?.detail;
              const messageText = readDetail(detail) ?? (err as any)?.message;
              return {
                ok: false,
                status: (err as any)?.response?.status || 400,
                code: (detail as any)?.code || 'SAVE_FAILED',
                message: messageText || t('workspace.edit.saveFailed'),
              };
            }
            if (prevGeom) {
              pushOp(createVertexEditOperation(
                activeLayerId,
                draggedFeatureId,
                'drag',
                0,
                [0, 0],
                [0, 0],
                prevGeom,
                feature.geometry,
                'user',
              ));
            }
            return { ok: true, status: 200 };
          }
          // Structural / sub-area layers → the unified validated edit endpoint.
          const reqBody: Record<string, unknown> = {
            layer_type: activeLayerId === 'sub_areas' ? 'sub_areas' : activeLayerId,
            feature_id: draggedFeatureId,
            geometry: feature.geometry,
          };
          if (sharedMove?.moves.length) {
            reqBody.shared_moves = sharedMove.moves.map((m) => ({
              feature_id: m.feature_id,
              geometry: m.geometry,
            }));
          }
          const resp = await fetch(
            `/api/v1/calculations/${calculationId}/geometry/edit-geometry`,
            {
              method: 'POST',
              headers: authHeaders(),
              body: JSON.stringify(reqBody),
            },
          );
          const body = await resp.json().catch(() => null);
          const code = (body as any)?.detail?.code as string | undefined;
          const messageDetail = (body as any)?.detail?.message as string | undefined;
          // VR-0: the exact server verdict for this gesture.
          mark('vertex_commit_response status=' + resp.status + ' code=' + (code ?? '-')
            + ' feature=' + draggedFeatureId
            + ' sharedMoves=' + (sharedMove?.moves.length ?? 0)
            + ' warnings=' + JSON.stringify((body as any)?.warnings ?? []));
          if (resp.ok) {
            const warnings = (body as any)?.warnings as string[] | undefined;
            if (Array.isArray(warnings) && warnings.includes('CLIPPED_TO_BOUNDARY')) {
              message.warning(t('workspace.geometry.clippedToBoundary'));
            }
            // UE-3.2 — record the edit so Ctrl+Z re-POSTs the previous geometry.
            // V-2 — a shared move must record EVERY partner (their previous
            // AND new geometries) so undo/redo restores the whole batch in one
            // request instead of one side only (which would open a gap).
            if (prevGeom) {
              const partners = (sharedMove?.moves ?? []).map((m) => {
                const prev = (layerFeatures ?? []).find((f) =>
                  String((f as any)?.id ?? (f as any)?.properties?.id) === String(m.feature_id)
                );
                return {
                  featureId: m.feature_id,
                  previousGeometry: (prev as any)?.geometry as GeoJSON.Geometry,
                  newGeometry: m.geometry,
                };
              });
              pushOp(createVertexEditOperation(
                activeLayerId,
                draggedFeatureId,
                'drag',
                0,
                [0, 0],
                [0, 0],
                prevGeom,
                feature.geometry,
                'user',
                undefined,
                {
                  calcId: calculationId,
                  layerType: activeLayerId === 'sub_areas' ? 'sub_areas' : activeLayerId,
                  sharedMovePartners: partners,
                },
              ));
            }
            return { ok: true, status: resp.status };
          }
          if (resp.status === 409 && code === 'TOPOLOGY_REJECTED') {
            return { ok: false, status: 409, code, message: messageDetail };
          }
          // VR-3 — the server re-derives the rules and refuses a locked vertex
          // no matter what the client believed was editable.  Reaching this in
          // normal use means the client's classification drifted from the
          // server's, which is worth seeing rather than silently retrying.
          if (resp.status === 409
            && (code === 'VERTEX_LOCKED' || code === 'BOUNDARY_LOCKED_BY_STRUCTURE')) {
            return { ok: false, status: 409, code, message: messageDetail };
          }
          if (resp.status === 423 || code === 'structure_locked') {
            return { ok: false, status: 423, code: 'structure_locked', message: messageDetail };
          }
          return {
            ok: false,
            status: resp.status,
            code: code || 'SAVE_FAILED',
            message: messageDetail || t('workspace.edit.saveFailed'),
          };
        } catch (err: any) {
          throw err;
        }
      },
      onReject: (code, msg) => {
        // VR-0: why the gesture was reverted — distinguishes a LOCAL pre-check
        // rejection (TOPOLOGY_GAP/REJECTED raised before any POST) from a
        // server verdict, which `vertex_commit_response` records separately.
        mark('vertex_revert code=' + code + ' msg=' + String(msg).slice(0, 120));
        if (code === 'TOPOLOGY_REJECTED' || code === 'TOPOLOGY_GAP') {
          message.error(msg);
        } else if (code === 'structure_locked') {
          message.warning(t('workspace.edit.structureLocked'));
        } else if (code === 'map_lifecycle') {
          message.error(msg);
        } else if (code === 'VERTEX_CHANGE_BLOCKED') {
          // V-4: the add/delete would collapse the neighbouring unit's ring.
          message.warning(t('workspace.edit.sharedChangeBlocked'));
        } else if (code === 'VERTEX_LOCKED') {
          message.warning(t('workspace.edit.vertexLocked'));
        } else if (code === 'BOUNDARY_LOCKED_BY_STRUCTURE') {
          message.warning(t('workspace.edit.noEditableBoundaryLocked'));
        } else {
          message.error(msg);
        }
      },
      onCommitted: () => store.bumpGeometryVersion(),
    });

    // VR-0: Geoman has now instantiated its markers — record how many actually
    // reached the screen versus how many the rules said should.  A mismatch
    // here localises the bug to the masking layer in one line.
    {
      const reg = getFeatureLayerRegistry();
      let total = 0;
      let rendered = 0;
      for (const fid of scopeIds) {
        const s = markerStats(reg.get(fid));
        total += s.total;
        rendered += s.rendered;
      }
      mark('vertex_markers_created total=' + total + ' rendered=' + rendered
        + ' expected=' + editableTotal + (rendered === editableTotal ? ' MATCH' : ' MISMATCH'));
      // Mirror the dump onto the DOM as well as `window.__vertexDebug`.
      // Headless drivers (patchright/Playwright stealth) evaluate in an
      // ISOLATED world: they share the document but NOT window globals, so a
      // window-only probe is invisible to automation. The dataset copy is the
      // one an E2E test can actually read.
      if (isDev && typeof document !== 'undefined') {
        try {
          document.documentElement.dataset.vertexDump =
            JSON.stringify(vertexDebugRef.current?.() ?? null);
        } catch (err) {
          document.documentElement.dataset.vertexDump =
            JSON.stringify({ error: String(err) });
        }
      }
    }

    return () => {
      if (import.meta.env.DEV) console.log(`[E-2] vertex_edit teardown: layer=${activeLayerId} features=${scopeIds.length}`);
      vertexDebugRef.current = null;
      cleanup();
    };
  }, [map, store.activeLayerId, store.toolbarMode, store.bumpGeometryVersion, calculationId, boundaryQuery.data, userGroupQuery.data, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, subAreasQuery.data, vertexRetryTick, pushOp, t]);

  // ── UE-2.1 whole-feature MOVE (Geoman body drag → edit-geometry replace).
  // Mirrors the vertex lifecycle: snapshot on arm/dragstart, local R6 pre-check
  // + one POST on pm:dragend, revert+toast on rejection.
  useEffect(() => {
    const dbgMark = (s: string) => {
      if (typeof document !== 'undefined' && document.documentElement) {
        document.documentElement.dataset.moveDebug = s;
      }
    };
    dbgMark('run:' + store.toolbarMode);
    if (!map) { dbgMark('bail:no-map'); return; }
    if (store.toolbarMode !== 'move') return;
    const layerRef = activeLayerRef.current;
    const sel = store.selection;
    if (!layerRef || !sel || sel.featureIds.length !== 1) {
      dbgMark('bail:no-sel:' + (layerRef ? JSON.stringify(layerRef) : 'null'));
      return;
    }
    if (layerRef.kind === 'builtin' && layerRef.id === 'activity_features') { dbgMark('bail:activity'); return; }
    const featureId = String(sel.featureIds[0]);
    if (!moveLayer) {
      dbgMark('bail:no-layer:' + featureId + ':reg=' + getFeatureLayerRegistry().size);
      return; // awaiting registry (remount race) — retried by hook
    }
    // Move is a point-only tool (the toolbar button is already hidden on
    // polygon / line layers via geometryTypesForTool('move')). This is the
    // backstop: if the tool is somehow armed on a polygon or line, refuse it,
    // warn once and drop back to select — never drag a whole block / sub-area
    // body off its neighbours.
    const movingGeomType = (moveLayer as unknown as { feature?: GeoJSON.Feature }).feature?.geometry?.type;
    if (movingGeomType && movingGeomType !== 'Point' && movingGeomType !== 'MultiPoint') {
      dbgMark('bail:not-point:' + movingGeomType);
      store.setToolbarMode('select');
      message.warning(t('workspace.move.pointsOnly'));
      return;
    }
    dbgMark('armed:' + layerRef.layerType + ':' + featureId);

    if (import.meta.env.DEV) console.log(
      `[Move] armed: layer=${layerRef.layerType} feature=${featureId}`,
    );

    // R6 neighbour index — data-first, from the same GeoJSON the map renders.
    const layerFeatures =
      (layerRef.kind === 'imported' && layerRef.layerId != null && store.importedLayerFeatures[layerRef.layerId])
      || (layerRef.id === 'blocks' && blocksQuery.data)
      || (layerRef.id === 'sub_blocks' && subBlocksQuery.data)
      || (layerRef.id === 'compartments' && compartmentsQuery.data)
      || (layerRef.id === 'sub_compartments' && subCompartmentsQuery.data)
      || (layerRef.id === 'sub_areas' && subAreasQuery.data)
      || null;
    const neighbourIndex = layerFeatures ? new SharedEdgeIndex(layerFeatures) : null;

    const cleanup = enableMoveGesture(map, getFeatureLayerRegistry(), featureId, {
      topology: neighbourIndex,
      commit: async (feature) => {
        // V-3.2 — boundary has no edit-geometry route (the backend rejects
        // layer_type='boundary'); persist through PUT /boundary exactly like
        // the vertex path, otherwise a move-mode drag 400s and reverts.
        if (layerRef.kind === 'builtin' && layerRef.layerType === 'boundary') {
          try {
            const mres: any = await forestApi.updateBoundaryGeometry(calculationId, {
              geometry: feature.geometry,
              area_hectares: (turf.area(feature) || 0) / 10000,
            });
            if (mres?.needs_overlap_review) {
              reviewBoundary({
                geometry: mres.preview_geometry || feature.geometry,
                forestName: store.forestName || 'Forest',
                method: 'digitize',
                calculationId,
                onResolved: () => store.bumpGeometryVersion(),
              });
            }
          } catch (err: any) {
            const prov = provisionalFromError(err);
            if (prov?.needs_overlap_review && prov?.preview_geometry) {
              reviewBoundary({
                geometry: prov.preview_geometry,
                forestName: store.forestName || 'Forest',
                method: 'digitize',
                calculationId,
                onResolved: () => store.bumpGeometryVersion(),
              });
              return { ok: true, status: 200 };
            }
            const detail = (err as any)?.response?.data?.detail;
            const messageText = readDetail(detail) ?? (err as any)?.message;
            return {
              ok: false,
              status: (err as any)?.response?.status || 400,
              code: (detail as any)?.code || 'SAVE_FAILED',
              message: messageText || t('workspace.edit.saveFailed'),
            };
          }
          return { ok: true, status: 200 };
        }
        const resp = await fetch(
          `/api/v1/calculations/${calculationId}/geometry/edit-geometry`,
          {
            method: 'POST',
            // V-3.2 — JWT parity with the vertex path: without the Bearer
            // header the JWT-secured backend 401s and the gesture silently
            // snapshot-restores ("moved but not saved").
            headers: authHeaders(),
            body: JSON.stringify({
              layer_type: layerRef.layerType,
              layer_id: layerRef.kind === 'imported' ? layerRef.layerId : undefined,
              feature_id: featureId,
              geometry: feature.geometry,
            }),
          },
        );
        const body = await resp.json().catch(() => null);
        const code = (body as any)?.detail?.code as string | undefined;
        const messageDetail = (body as any)?.detail?.message as string | undefined;
        if (resp.ok) {
          if (layerRef.kind === 'imported' && layerRef.layerId != null) {
            const cur = store.importedLayerFeatures[layerRef.layerId] ?? [];
            const next = cur.map((f) =>
              String(f.properties?.featureId ?? f.properties?.id ?? f.id) === featureId
                ? { ...f, geometry: feature.geometry }
                : f,
            );
            store.setImportedLayerFeatures(layerRef.layerId, next);
          }
          const warnings = (body as any)?.warnings as string[] | undefined;
          if (Array.isArray(warnings) && warnings.includes('CLIPPED_TO_BOUNDARY')) {
            message.warning(t('workspace.geometry.clippedToBoundary'));
          }
          return { ok: true, status: resp.status };
        }
        if (resp.status === 409 && code === 'TOPOLOGY_REJECTED') {
          return { ok: false, status: 409, code, message: messageDetail };
        }
        if (resp.status === 423 || code === 'structure_locked') {
          return { ok: false, status: 423, code: 'structure_locked', message: messageDetail };
        }
        return {
          ok: false,
          status: resp.status,
          code: code || 'SAVE_FAILED',
          message: messageDetail || t('workspace.edit.saveFailed'),
        };
      },
      onReject: (code, msg) => {
        if (code === 'TOPOLOGY_REJECTED' || code === 'TOPOLOGY_GAP') {
          message.error(msg);
        } else if (code === 'structure_locked') {
          message.warning(t('workspace.move.structureLocked'));
        } else {
          message.error(msg);
        }
      },
      onCommitted: () => store.bumpGeometryVersion(),
    });

    return () => cleanup();
  }, [map, store.toolbarMode, store.selection, store.bumpGeometryVersion, calculationId, blocksQuery.data, subBlocksQuery.data, compartmentsQuery.data, subCompartmentsQuery.data, subAreasQuery.data, moveLayer, activeLayerRef, store.importedLayerFeatures, store.setImportedLayerFeatures, t]);

  // ── E-2.4 split mode: draw a cutting segment across the selected polygon →
  // POST /cut-polygon.  Works on any layer whose geometryTypes include
  // Polygon (blocks, compartments, sub_compartments, sub_areas).  LineString
  // split uses the click-splitter effect below (Approach A, E2.4).
  // UE-0.x: the split cut-line accumulator (`splitCutRef`) starts fresh each
  // time the user ENTERS split mode — not on every effect re-arm.  Keeping the
  // reset here (mode-transition based) means a mid-draw registry remount race
  // re-arms the draw effect without wiping the clicked points.
  const splitWasActive = useRef(false);
  useEffect(() => {
    const isSplit = store.toolbarMode === 'split';
    if (isSplit && !splitWasActive.current) {
      splitCutRef.current = [];
      setSplitCutCount(0);
    }
    splitWasActive.current = isSplit;
  }, [store.toolbarMode]);

  useEffect(() => {
    if (!map) return;
    if (store.toolbarMode !== 'split') return;
    const activeLayerId = store.activeLayerId;
    const sel = store.selection;
    if (!activeLayerId || !sel || sel.featureIds.length !== 1) return;
    if (activeLayerId === 'activity_features') return; // line split handled separately
    if (!splitLayer) return; // awaiting registry (remount race) — retried by hook

    const sourceGeom: GeoJSON.Geometry | undefined = (splitLayer as any)?.toGeoJSON?.()?.geometry;

    const cutLayer = L.featureGroup().addTo(map);
    const previewLayer = L.featureGroup().addTo(map);

    // UE-0.1 EXT: live area preview — recompute the cut_polygon mirror whenever
    // the cut changes (click adds a point / a vertex handle is dragged).
    const renderPreview = () => {
      previewLayer.clearLayers();
      const pts = splitCutRef.current;
      if (!sourceGeom || pts.length < 2) {
        splitPreviewElsRef.current.layers = [];
        splitPreviewElsRef.current.labels = [];
        setSplitPreview(null);
        return;
      }
      const result = computeSplitPreview(
        sourceGeom,
        pts.map((ll: L.LatLng) => [ll.lng, ll.lat] as [number, number]),
      );
      setSplitPreview(result);
      const geo = L.geoJSON(result.pieces as any, {
        style: { color: '#E67E22', weight: 2, opacity: 0.9, fillColor: '#F39C12', fillOpacity: 0.22 },
        interactive: false,
      });
      geo.addTo(previewLayer);
      const labels: L.Marker[] = [];
      result.pieces.forEach((p, i) => {
        try {
          const b = L.geoJSON(p).getBounds();
          const m = L.marker(b.getCenter(), {
            interactive: false,
            icon: L.divIcon({
              className: 'split-preview-label',
              iconSize: [0, 0],
              html:
                `<div class="split-part-label">` +
                `<span class="spl-name">${t('workspace.split.partOnly', { index: i + 1 })}</span>` +
                `<span class="spl-val">${result.partHa[i].toFixed(2)}<i>${t('units.hectare')}</i></span>` +
                `</div>`,
            }),
          });
          m.addTo(previewLayer);
          labels.push(m);
        } catch {
          /* degenerate piece — skip label */
        }
      });
      splitPreviewElsRef.current.layers = [geo as unknown as L.Layer];
      splitPreviewElsRef.current.labels = labels;
    };

    // UE-0.x: explicit-finish split draw.  No geoman draw here: geoman's Line
    // draw silently finishes the line when a click lands on a prior vertex
    // (~18px marker), which truncated zig-zag cuts to 1-3 points.  Instead we
    // accumulate every map click into splitCutRef (any number of points, zig-zag
    // included) and commit only via the "Finish & Split" button.  Backend
    // (`geometry_edit_service.cut_polygon`) extrapolates the ends + preserves
    // interior vertices, so the shared edge stays zig-zag.
    // Accumulation lives in `splitCutRef` (survives effect re-arms); it is only
    // reset when the user *enters* split mode (separate effect above).  If this
    // effect re-arms mid-draw (registry remount race), we redraw from the ref.
    const line = L.polyline([], { color: '#E74C3C', weight: 2 }).addTo(cutLayer);
    const vertexMarkers: L.Marker[] = [];
    const handleIcon = L.divIcon({
      className: 'split-vertex-handle',
      html: '<div class="split-vertex-dot"></div>',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
    });
    const redrawCut = () => {
      while (vertexMarkers.length) cutLayer.removeLayer(vertexMarkers.pop()!);
      line.setLatLngs(splitCutRef.current);
      const pts = splitCutRef.current;
      for (let i = 0; i < pts.length; i++) {
        const m = L.marker(pts[i], {
          icon: handleIcon,
          draggable: true,
          zIndexOffset: 2000,
        });
        m.on('drag', () => {
          line.setLatLngs(splitCutRef.current);
        });
        m.on('dragend', () => {
          const ll = m.getLatLng();
          splitCutRef.current[i] = ll;
          setSplitCutCount(splitCutRef.current.length);
          redrawCut();
          renderPreview();
        });
        // Right-click a cut-line vertex to remove just that point (the map's
        // own context menu / the browser menu must not also fire).
        m.on('contextmenu', (ev: L.LeafletMouseEvent) => {
          L.DomEvent.stop(ev);
          splitCutRef.current.splice(i, 1);
          setSplitCutCount(splitCutRef.current.length);
          redrawCut();
          renderPreview();
        });
        m.addTo(cutLayer);
        vertexMarkers.push(m);
      }
    };
    const onSplitClick = (e: L.LeafletMouseEvent) => {
      const pts = splitCutRef.current;
      const last = pts[pts.length - 1];
      if (last && Math.abs(last.lat - e.latlng.lat) < 1e-9 && Math.abs(last.lng - e.latlng.lng) < 1e-9) return;
      pts.push(e.latlng);
      setSplitCutCount(pts.length);
      redrawCut();
      renderPreview();
    };
    // Backspace / Delete removes the last-placed cut-line point (the standard
    // digitizing "undo last vertex"). Skipped while typing in a field.
    const onSplitKey = (e: KeyboardEvent) => {
      if (e.key !== 'Backspace' && e.key !== 'Delete') return;
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (splitCutRef.current.length === 0) return;
      e.preventDefault();
      splitCutRef.current.pop();
      setSplitCutCount(splitCutRef.current.length);
      redrawCut();
      renderPreview();
    };

    redrawCut();
    renderPreview();
    map.on('click', onSplitClick);
    window.addEventListener('keydown', onSplitKey);

    return () => {
      map.off('click', onSplitClick);
      window.removeEventListener('keydown', onSplitKey);
      if (map.hasLayer(cutLayer)) map.removeLayer(cutLayer);
      if (map.hasLayer(previewLayer)) map.removeLayer(previewLayer);
      splitPreviewElsRef.current.layers = [];
      splitPreviewElsRef.current.labels = [];
      setSplitPreview(null);
    };
  }, [map, store.activeLayerId, store.toolbarMode, store.selection, splitLayer, t]);

  // ── E2.4 cut line (Approach A): on `activity_features` lines, click near the
  // line within snap tolerance → POST /cut-line {layer_type, feature_id,
  // split_point}; backend slices at the nearest vertex.  Geoman has no native
  // line-cut, so this is a custom map-click handler (review-gap #5).
  useEffect(() => {
    if (!map) return;
    if (store.toolbarMode !== 'split') return;
    if (store.activeLayerId !== 'activity_features') return;
    const sel = store.selection;
    if (!sel || sel.featureIds.length !== 1) return;
    if (!cutLineLayer) return; // awaiting registry (remount race) — retried by hook
    const featureId = String(sel.featureIds[0]);
    const layer = cutLineLayer;
    const geom: GeoJSON.Geometry | undefined = (layer as any)?.toGeoJSON?.()?.geometry;
    if (!geom || (geom.type !== 'LineString' && geom.type !== 'MultiLineString')) return;

    const handleClick = async (e: L.LeafletMouseEvent) => {
      const splitPoint = nearestSplitPoint(geom, e.latlng);
      if (!splitPoint) {
        message.error(t('workspace.split.clickCloser'));
        return;
      }
      try {
        const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
        const token = localStorage.getItem('access_token');
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const resp = await fetch(
          `${baseUrl}/api/v1/calculations/${calculationId}/geometry/cut-line`,
          {
            method: 'POST',
            headers,
            body: JSON.stringify({
              layer_type: 'activity_features',
              feature_id: featureId,
              split_point: { type: 'Point', coordinates: [splitPoint.lng, splitPoint.lat] },
            }),
          },
        );
        if (resp.ok) {
          message.success(t('workspace.split.lineSuccess'));
          store.bumpGeometryVersion();
          store.setToolbarMode('select');
        } else {
          const body = await resp.json().catch(() => null);
          message.error(readDetail((body as any)?.detail) || t('workspace.split.failed'));
        }
      } catch {
        message.error(t('workspace.split.networkError'));
      }
    };

    map.on('click', handleClick);
    if (isTouchDevice()) map.doubleClickZoom.disable();

    return () => {
      map.off('click', handleClick);
      if (isTouchDevice()) map.doubleClickZoom.enable();
    };
  }, [map, store.activeLayerId, store.toolbarMode, store.selection, calculationId, store.bumpGeometryVersion, cutLineLayer, t]);

  useEffect(() => {
    performance.mark('workspace:mount-start');
  }, []);

  useEffect(() => {
    if (map) {
      performance.mark('workspace:map-ready');
      performance.measure('workspace:init-to-map',
        'workspace:mount-start', 'workspace:map-ready');
    }
  }, [map]);

  // UE-0.2: geometry-driven toolbar. Resolve the ACTIVE layer's geometry types
  // from the registry (built-in) or introspected from the imported feature list.
  const activeGeometryTypes = useMemo<string[]>(() => {
    if (store.activeLayerId) {
      return LAYER_REGISTRY[store.activeLayerId]?.geometryTypes ?? [];
    }
    if (store.activeImportedLayerId != null) {
      const features = store.importedLayerFeatures[store.activeImportedLayerId] ?? [];
      const types = new Set(features.map((f) => f.geometry?.type).filter(Boolean) as string[]);
      return types.size ? Array.from(types) : [];
    }
    return [];
  }, [store.activeLayerId, store.activeImportedLayerId, store.importedLayerFeatures]);

  // Toolbar Copy / Paste / Paste-as-layer / Delete (feature clipboard). Declared
  // before the `allFailed` early return so the hook order never changes.
  const workspaceRootRef = useRef<HTMLDivElement>(null);
  const clipboardTools = useFeatureClipboard({
    calculationId, getLayerFeatures, pushOp, pushAndExecute, rootRef: workspaceRootRef,
  });
  const reasonText = (issue: { code: string; params?: Record<string, string> } | null): string | null =>
    issue ? t(`editing.paste.reason.${issue.code}`, issue.params) : null;

  // What a layer's context menu and the attribute table's row menu need to offer
  // Copy / Paste / Paste as new layer. Same actions as the toolbar, any layer.
  const featureClipboardMenu = {
    clipboardCount: clipboardTools.clipboardCount,
    selectedCountFor: clipboardTools.selectedCountFor,
    pasteStateFor: clipboardTools.pasteStateFor,
    copy: (opts: { layerKey: string }) => clipboardTools.copy(opts),
    paste: (layerKey: string) => { void clipboardTools.paste(layerKey); },
    pasteAsLayer: () => { void clipboardTools.pasteAsLayer(); },
  };
  // A row's menu: a row that is part of a multi-selection copies the whole selection
  // (what the user sees highlighted); any other row copies just itself.
  const handleCopyRow = (feature: GeoJSON.Feature) => {
    const attrs = (feature.properties ?? {}) as Record<string, unknown>;
    const id = String(attrs.id || attrs.featureId || (feature as { id?: unknown }).id || '');
    const key = store.activeLayerId
      ?? (store.activeImportedLayerId != null ? `imported:${store.activeImportedLayerId}` : null);
    const selected = key && store.selection.layerId === key ? store.selection.featureIds : [];
    if (selected.length > 1 && selected.includes(id)) clipboardTools.copy();
    else clipboardTools.copy({ features: [feature] });
  };

  const allFailed = [boundaryQuery, blocksQuery, subBlocksQuery, compartmentsQuery, subCompartmentsQuery, subAreasQuery, activityQuery]
    .every(q => q.error);
  const layerLoading = boundaryQuery.loading || blocksQuery.loading || compartmentsQuery.loading;
  if (allFailed) {
    return <WorkspaceError onRetry={() => window.location.reload()} />;
  }

  return (
    <div ref={workspaceRootRef} className="map-workspace" data-testid="workspace-container" role="application" aria-label={t('workspace.mapAriaLabel', { name: shownForestName })}>
      <WorkspaceHeader
        forestName={shownForestName || t('workspace.calculationFallback', { id: calculationId.slice(0, 8) })}
        dimensionMode={store.dimensionMode}
        onDimensionToggle={store.toggleDimensionMode}
        panels={panelToggles}
        onTogglePanel={(id) => togglePanel(id as Parameters<typeof togglePanel>[0])}
        hasBoundary={hasBoundary}
        onOpenYearlyPlan={isYearlyPlanGuidanceEnabled() ? openPlanView : undefined}
      />

      <GeometryEditorToolbar
        geometryTypes={activeGeometryTypes}
        layerId={store.activeLayerId ?? (store.activeImportedLayerId != null ? `imported:${store.activeImportedLayerId}` : null)}
        toolbarMode={store.toolbarMode}
        onModeChange={store.setToolbarMode}
        canUndo={canUndo}
        canRedo={canRedo}
        onUndo={undo}
        onRedo={redo}
        // H-SUBMIT B4. `structureLocked` first: once the map is submitted for
        // analysis the whole structure is frozen, not one layer, and the
        // backend answers 423 on every geometry write. Without this the tools
        // stay enabled and the user discovers the freeze by having an edit
        // rejected — a disabled button with a reason is a better answer than
        // an error after the attempt.
        isLocked={store.structureLocked || (store.activeLayerId
          ? !!store.layerLocks[store.activeLayerId]
          : store.activeImportedLayerId != null
            ? !!store.layerLocks[`imported:${store.activeImportedLayerId}`]
            : false)}
        structureLockReason={store.structureLocked ? t('workspace.header.frozenGeneric') : undefined}
        onSnapToggle={() => setSnapEnabled(s => !s)}
        snapEnabled={snapEnabled}
        selectionCount={store.selection.featureIds.length}
        isDigitizeContext={digitizeCtx != null}
        activePurpose={digitizeCtx?.layer.purpose ?? null}
        isTouchDevice={isTouchDevice()}
        // Rule A — grey the vertex tool out on a boundary that any structural
        // layer has locked, instead of arming it onto an empty map and
        // explaining with a toast after the fact.
        vertexLockReason={
          store.activeLayerId === 'boundary' && (
            (blocksQuery.data?.length ?? 0) > 0
            || (subBlocksQuery.data?.length ?? 0) > 0
            || (compartmentsQuery.data?.length ?? 0) > 0
            || (subCompartmentsQuery.data?.length ?? 0) > 0
          ) ? 'boundary_locked' : null
        }
        onCopy={clipboardTools.copy}
        onPaste={clipboardTools.paste}
        onPasteAsLayer={clipboardTools.pasteAsLayer}
        onDeleteSelected={clipboardTools.deleteSelected}
        canCopy={clipboardTools.canCopy}
        copyTooltip={t(
          clipboardTools.copyIsWholeLayer ? 'editing.toolbar.copyTooltipAll' : 'editing.toolbar.copyTooltipSelected',
          { count: clipboardTools.copyCount },
        )}
        pasteDisabledReason={reasonText(clipboardTools.pasteIssue)}
        pasteAsLayerDisabledReason={reasonText(clipboardTools.pasteAsLayerIssue)}
        canDelete={clipboardTools.canDelete}
      >
      </GeometryEditorToolbar>
      <PasteCategoryModal
        prompt={clipboardTools.categoryPrompt}
        onResolve={clipboardTools.resolveCategoryPrompt}
      />

      {store.toolbarMode === 'split' && splitCutCount >= 2 && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('workspace.split.confirmBarAria')}>
          <span className="split-confirm-info">{t('workspace.split.pointsDrawnInfo', { count: splitCutCount })}</span>
          <span className="split-confirm-hint">{t('workspace.split.editHint')}</span>
          {(splitPreview?.pieces.length ?? 0) > 0 && (
            <span className="split-area-chips">
{splitPreview!.pieces.map((p, i) => (
                <span key={i} className="split-chip">
                  {t('workspace.split.partLabel', { index: i + 1, ha: (splitPreview!.partHa[i] ?? 0).toFixed(2) })}
                </span>
              ))}
            </span>
          )}
          {splitPreview && splitPreview.warnings.length > 0 && (
            <span className="split-warn">{splitPreview.warnings.join(' · ')}</span>
          )}
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={confirmSplitCut} aria-label={t('workspace.split.finishSplitAria')} title={t('workspace.split.finishSplit')}>✓</button>
            <button className="toolbar-btn confirm-cancel" onClick={() => store.setToolbarMode('select')} aria-label={t('workspace.split.cancelAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.toolbarMode === 'draw_polygon' && newDrawArmRef.current && newDrawCount >= 3 && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('workspace.draw.confirmBarAria')}>
          <span className="split-confirm-info">{t('workspace.draw.pointsDrawnInfo', {
            count: newDrawCount,
            type: newDrawArmRef.current === 'compartments' ? t('workspace.types.compartment') : t('workspace.types.block'),
          })}</span>
          {newDrawPreview && newDrawPreview.drawnHa > 0 && (
            <span className="split-area-chips">
              <span className="split-chip">{t('workspace.draw.drawnChip', { ha: newDrawPreview.drawnHa.toFixed(2) })}</span>
              {!newDrawPreview.outsideBoundary && (
                <span className="split-chip">{t('workspace.draw.blockChip', { ha: newDrawPreview.clippedHa.toFixed(2) })}</span>
              )}
            </span>
          )}
          {newDrawPreview && newDrawPreview.warnings.length > 0 && (
            <span className="split-warn">{newDrawPreview.warnings.join(' · ')}</span>
          )}
          <span className="confirm-btns">
            <button
              className="toolbar-btn confirm-go"
              onClick={confirmNewDraw}
              aria-label={t('workspace.draw.finishCreateAria')}
              title={t('workspace.draw.finishCreate')}
              disabled={!!newDrawPreview?.outsideBoundary}
            >
              ✓
            </button>
            <button className="toolbar-btn confirm-cancel" onClick={cancelNewDraw} aria-label={t('workspace.draw.cancelCreateAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.toolbarMode === 'draw_polygon' && store.activeLayerId === 'sub_areas' && subAreaDrawVertexCount >= 3 && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('workspace.draw.subAreaConfirmBarAria')}>
          <span className="split-confirm-info">{t('workspace.draw.subAreaPointsDrawnInfo', { count: subAreaDrawVertexCount })}</span>
          {subAreaDrawMeasurement?.areaHa != null && (
            <span className="split-area-chips">
              <span className="split-chip">{t('workspace.draw.subAreaDrawnChip', { ha: subAreaDrawMeasurement.areaHa.toFixed(2) })}</span>
            </span>
          )}
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={confirmSubAreaDraw} aria-label={t('workspace.draw.finishSubAreaAria')} title={t('workspace.draw.finishSubArea')}>✓</button>
            <button className="toolbar-btn confirm-cancel" onClick={cancelSubAreaDraw} aria-label={t('workspace.draw.cancelSubAreaAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.toolbarMode === 'draw_polygon' && store.activeLayerId === 'user_group' && userGroupDrawVertexCount >= 3 && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('workspace.userGroup.confirmBarAria')}>
          <span className="split-confirm-info">{t('workspace.userGroup.pointsDrawnInfo', { count: userGroupDrawVertexCount })}</span>
          {userGroupDrawMeasurement?.areaHa != null && (
            <span className="split-area-chips">
              <span className="split-chip">{t('workspace.draw.subAreaDrawnChip', { ha: userGroupDrawMeasurement.areaHa.toFixed(2) })}</span>
            </span>
          )}
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={finishUserGroupDraw} aria-label={t('workspace.userGroup.finishDrawAria')} title={t('workspace.userGroup.finishDraw')}>✓</button>
            <button className="toolbar-btn confirm-cancel" onClick={cancelUserGroupDraw} aria-label={t('workspace.userGroup.cancelDrawAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.activeLayerId === 'activity_features'
        && (store.toolbarMode === 'draw_line' || store.toolbarMode === 'draw_polygon')
        && activityDrawVertexCount >= (store.toolbarMode === 'draw_line' ? 2 : 3) && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('yearlyPlan.planTable.drawConfirmBarAria')}>
          <span className="split-confirm-info">{t('yearlyPlan.planTable.drawPointsDrawnInfo', { count: activityDrawVertexCount })}</span>
          {activityDrawMeasurement?.areaHa != null && (
            <span className="split-area-chips">
              <span className="split-chip">{t('yearlyPlan.planTable.drawAreaChip', { ha: activityDrawMeasurement.areaHa.toFixed(2) })}</span>
            </span>
          )}
          {activityDrawMeasurement?.lengthM != null && (
            <span className="split-area-chips">
              <span className="split-chip">{t('yearlyPlan.planTable.drawLengthChip', { m: activityDrawMeasurement.lengthM.toFixed(0) })}</span>
            </span>
          )}
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={finishActivityDraw} aria-label={t('yearlyPlan.planTable.drawFinishAria')} title={t('yearlyPlan.planTable.drawFinish')}>✓</button>
            <button className="toolbar-btn confirm-cancel" onClick={cancelActivityDraw} aria-label={t('yearlyPlan.planTable.drawCancelAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.toolbarMode === 'draw_polygon' && store.activeLayerId === 'boundary' && !newDrawArmRef.current && boundaryDrawVertexCount >= 3 && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('workspace.boundary.confirmBarAria')}>
          <span className="split-confirm-info">{t('workspace.boundary.piecePointsInfo', { count: boundaryDrawVertexCount })}</span>
          {boundaryDrawMeasurement?.areaHa != null && (
            <span className="split-area-chips">
              <span className="split-chip">{t('workspace.draw.subAreaDrawnChip', { ha: boundaryDrawMeasurement.areaHa.toFixed(2) })}</span>
            </span>
          )}
          {boundaryIslandCount >= 1 && (
            <span className="split-confirm-hint">{t('workspace.boundary.islandsDrawn', { count: boundaryIslandCount })}</span>
          )}
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={closeBoundaryPiece} aria-label={t('workspace.boundary.closePieceAria')} title={t('workspace.boundary.closePiece')}>{t('workspace.boundary.closePiece')}</button>
            <button className="toolbar-btn confirm-cancel" onClick={cancelBoundaryPiece} aria-label={t('workspace.boundary.cancelPieceAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.toolbarMode === 'draw_polygon' && store.activeLayerId === 'boundary' && !newDrawArmRef.current && boundaryDrawVertexCount < 3 && boundaryIslandCount >= 1 && (
        <div className="split-confirm-bar" role="toolbar" aria-label={t('workspace.boundary.confirmBarAria')}>
          <span className="split-confirm-info">{t('workspace.boundary.islandsDrawn', { count: boundaryIslandCount })}</span>
          <span className="split-confirm-hint">{t('workspace.boundary.islandsHint')}</span>
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={finishBoundaryDigitize} aria-label={t('workspace.boundary.finishAria')} title={t('workspace.boundary.finish')}>✓</button>
            <button className="toolbar-btn confirm-cancel" onClick={cancelBoundaryDigitize} aria-label={t('workspace.boundary.cancelAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      {store.toolbarMode === 'merge' && store.selection.featureIds.length >= 2 && activeLayerRef.current && (
        <div className="merge-confirm-bar" role="toolbar" aria-label={t('workspace.merge.confirmBarAria')}>
          <span className="merge-confirm-info">{t('workspace.merge.info', { count: store.selection.featureIds.length })}</span>
          <span className="confirm-btns">
            <button className="toolbar-btn confirm-go" onClick={() => confirmMerge(activeLayerRef.current!, [...store.selection.featureIds])} aria-label={t('workspace.merge.mergeSelectedAria')} title={t('workspace.merge.confirm')}>✓</button>
            <button className="toolbar-btn confirm-cancel" onClick={() => store.setToolbarMode('select')} aria-label={t('workspace.merge.cancelAria')} title={t('common.cancel')}>✕</button>
          </span>
        </div>
      )}

      <div className="workspace-main">
        <Group
          elementRef={horizontalGroupRef}
          id="workspace-horizontal"
          orientation="horizontal"
          className="workspace-group workspace-group-h"
          defaultLayout={{ left: 20, center: 60, right: 20 }}
          groupRef={registerGroup('workspace-horizontal')}
          onLayoutChanged={handleLayoutChanged}
        >
          <Panel id="left" className="workspace-column workspace-column-left" minSize={8} defaultSize={20}>
            <Group
              id="workspace-left"
              orientation="vertical"
              className="workspace-group workspace-group-left"
              defaultLayout={{ layers: 42, basemap: 16, imported: 24, raster: 18 }}
              groupRef={registerGroup('workspace-left')}
              onLayoutChanged={handleLayoutChanged}
            >
              <DockPanel
                ref={registerPanel('layers')}
                id="layers"
                title={t("workspace.layers") }
                icon="▤"
                minSize={8}
                defaultSize={42}
                onCollapseChange={setPanelCollapsed} onCollapseToggle={handleCollapseToggle}
              >
                <LayerPanel
                  map={map}
                  isLoading={boundaryQuery.loading || blocksQuery.loading || subBlocksQuery.loading || compartmentsQuery.loading || subCompartmentsQuery.loading || samplePlotsQuery.loading}
                  error={allFailed ? t('workspace.error.loadFailed') : null}
                  structureLocked={store.structureLocked}
                  zoomToLayer={zoomToLayer}
                  onLayerImported={handleLayerImported}
                  mode="layers"
                  featureClipboard={featureClipboardMenu}
                  hasGeometry={hasGeometry}
                  onAddSubArea={handleAddSubArea}
                  onPolygonFromPoints={handlePolygonFromPoints}
                  onAutoCreate={openAutoBlockDesigner}
                  onCreateSamplePlots={openSamplePlotModal}
                  onImportStemMapping={openStemMappingModal}
                  onUserGroupAnalysis={openUserGroupModal}
                  onImportBlockFromBoundary={handleImportBlockFromBoundary}
                  autoBlockActive={autoBlockLevel != null}
                  onNewDraw={handleNewDraw}
                  onDivide={handleDivide}
                  onAutoDivide={handleAutoDivide}
                  calculationId={calculationId}
                />
              </DockPanel>

              <Separator className="dock-separator-h" />

              <DockPanel
                ref={registerPanel('basemap')}
                id="basemap"
                title={t("workspace.basemap") }
                icon="▧"
                minSize={8}
                defaultSize={16}
                onCollapseChange={setPanelCollapsed} onCollapseToggle={handleCollapseToggle}
              >
                <LayerPanel
                  map={map}
                  isLoading={false}
                  error={null}
                  structureLocked={store.structureLocked}
                  zoomToLayer={zoomToLayer}
                  onLayerImported={handleLayerImported}
                  mode="basemap"
                />
              </DockPanel>

              <Separator className="dock-separator-h" />

              <DockPanel
                ref={registerPanel('imported')}
                id="imported"
                title={t("workspace.importedLayers") }
                icon="⬈"
                minSize={8}
                defaultSize={24}
                onCollapseChange={setPanelCollapsed} onCollapseToggle={handleCollapseToggle}
              >
                <LayerPanel
                  map={map}
                  isLoading={false}
                  error={null}
                  structureLocked={store.structureLocked}
                  zoomToLayer={zoomToLayer}
                  onLayerImported={handleLayerImported}
                  mode="imported"
                  featureClipboard={featureClipboardMenu}
                  hasGeometry={hasGeometry}
                />
              </DockPanel>

              <Separator className="dock-separator-h" />

              <DockPanel
                ref={registerPanel('raster')}
                id="raster"
                title={t("workspace.rasterLayers") }
                icon="▨"
                minSize={8}
                defaultSize={18}
                onCollapseChange={setPanelCollapsed} onCollapseToggle={handleCollapseToggle}
              >
                <LayerPanel
                  map={map}
                  isLoading={false}
                  error={null}
                  structureLocked={store.structureLocked}
                  zoomToLayer={zoomToLayer}
                  mode="raster"
                />
              </DockPanel>
            </Group>
          </Panel>

          <Separator className="dock-separator-v" />

          <Panel id="center" className="workspace-center-panel" minSize={25} defaultSize={60}>
            <div className="workspace-center">
              <div className="workspace-map-area" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, position: 'relative' }}>
                <MapCanvas
                  onMapReady={handleMapReady}
                  boundaryFeatures={mapFeatures.boundary}
                  userGroupFeatures={mapFeatures.user_group}
                  blockFeatures={mapFeatures.blocks}
                  subBlockFeatures={mapFeatures.sub_blocks}
                  compartmentFeatures={mapFeatures.compartments}
                  subCompartmentFeatures={mapFeatures.sub_compartments}
                  subAreaFeatures={mapFeatures.sub_areas}
                  activityFeatures={mapFeatures.activity_features}
                  samplePlotFeatures={mapFeatures.sample_plots}
                  fieldbookFeatures={mapFeatures.fieldbook}
                  onSubAreaCreated={handleSubAreaCreated}
                  onSamplePlotMoved={handleSamplePlotMoved}
                />
                <ForestSummaryPanel calculationId={calculationId} />
                {!hasGeometry && !layerLoading && (
                  <div
                    data-testid="no-geometry-banner"
                    style={{
                      position: 'absolute',
                      top: 12,
                      left: '50%',
                      transform: 'translateX(-50%)',
                      zIndex: 500,
                      maxWidth: 620,
                      width: '90%',
                      background: '#ffffff',
                      border: '1px solid #c6d8c8',
                      borderLeft: '4px solid #2f7d32',
                      borderRadius: 8,
                      boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
                      padding: '10px 14px',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                    }}
                  >
                    <span style={{ fontSize: 20 }} aria-hidden="true">🗺️</span>
                    <div style={{ fontSize: 13, lineHeight: 1.45, color: '#374151' }}>
                      <strong>{t('workspace.noGeometryYet.title')}</strong>{' '}
                      {t('workspace.noGeometryYet.body')}
                    </div>
                  </div>
                )}
                {/* The "Next step" bar belongs to the Activity Features layer: it shows only while that layer is the
                    active one and is ticked on. The guided card below stays mounted — it opens from the header,
                    the plan view and the bar, whichever layer is active. */}
                {hasGeometry && isYearlyPlanGuidanceEnabled() && canPlan
                  && store.activeLayerId === 'activity_features'
                  && store.layerVisibility.activity_features !== false && (
                  <>
                  <YearlyDoneBar calculationId={calculationId} quietWhenDone onAddMore={() => wizardHost.controller.openWizard()} />
                  <NextStepBar
                    calculationId={calculationId}
                    refreshKey={`${store.geometryVersion}:${planVersion}`}
                    onShowLayer={() => store.setActiveLayer('activity_features')}
                    onFixStep={(step) => { void wizardHost.openForStep(step); }}
                    onAddActivity={() => wizardHost.controller.openWizard()}
                    onOpenPlan={openPlanView}
                  />
                  </>
                )}
                {hasGeometry && isYearlyPlanGuidanceEnabled() && canPlan && (
                  <ActivityWizard
                    controller={wizardHost.controller}
                    calculationId={calculationId}
                    activities={wizardHost.activities}
                    lines={wizardHost.lines}
                    onSaved={() => {
                      wizardHost.reload();
                      setActivityRefreshKey((k) => k + 1);
                      store.bumpGeometryVersion();
                      if (returnToYearlyGridRef.current) {
                        returnToYearlyGridRef.current = false;
                        navigateToInventory(`/calculations/${calculationId}?surface=${toSurfaceId('plan', 'yearly')}`);
                      }
                    }}
                    onOpenPlan={openPlanView}
                  />
                )}
                {pointPick && (
                  <div
                    data-testid="polygon-from-points-overlay"
                    style={{
                      position: 'absolute',
                      bottom: 24,
                      left: '50%',
                      transform: 'translateX(-50%)',
                      zIndex: 600,
                      background: '#ffffff',
                      border: '1px solid #c6d8c8',
                      borderLeft: '4px solid #2f7d32',
                      borderRadius: 8,
                      boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
                      padding: '10px 14px',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 8,
                      minWidth: 280,
                      pointerEvents: 'none',
                    }}
                  >
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#1f2937' }}>
                      {t('workspace.polygon.title')}
                    </div>
                    <div style={{ fontSize: 12, lineHeight: 1.4, color: '#4b5563' }}>
                      {t('workspace.polygon.instructions', { count: pointPick.points.length })}
                    </div>
                    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', pointerEvents: 'auto' }}>
                      <button
                        type="button"
                        data-testid="clear-points"
                        onClick={handlePointPickClear}
                        style={{ ...miniBtn, color: '#4b5563' }}
                      >
                        {t('common.clear')}
                      </button>
                      <button
                        type="button"
                        data-testid="cancel-points"
                        onClick={handlePointPickCancel}
                        style={{ ...miniBtn, color: '#4b5563' }}
                      >
                        {t('common.cancel')}
                      </button>
                      <button
                        type="button"
                        data-testid="finish-points"
                        disabled={!pointPickCanFinish}
                        onClick={handlePointPickFinish}
                        style={{
                          ...miniBtn,
                          background: pointPickCanFinish ? '#2f7d32' : '#c6d8c8',
                          color: '#fff',
                          cursor: pointPickCanFinish ? 'pointer' : 'not-allowed',
                        }}
                      >
                        {t('common.finish')}
                      </button>
                    </div>
                  </div>
                )}
                <SubAreaPlanDialog
                  open={subAreaPlanDialog.open}
                  calculationId={calculationId}
                  focusId={subAreaPlanDialog.focusId}
                  onClose={() => setSubAreaPlanDialog({ open: false, focusId: null })}
                  onChanged={() => { setPlanVersion((v) => v + 1); subAreaPlan.reload(); }}
                />
                {showCategoryPicker && (
                  <div style={pickerOverlay}>
                    <div style={pickerPanel}>
                      <div style={pickerHeader}>
                        <span>{t('workspace.assignCategory')}</span>
                        <button onClick={handleCategoryCancel} style={closeBtn}>✕</button>
                      </div>
                      <SubAreaCategoryPicker
                        value={pendingCategory || undefined}
                        onChange={handleCategorySelected}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Panel>

          <Separator className="dock-separator-v" />

          <Panel id="right" className="workspace-column workspace-column-right" minSize={8} defaultSize={20}>
            <Group
              id="workspace-right"
              orientation="vertical"
              className="workspace-group workspace-group-right"
              defaultLayout={{ attributeTable: 62, legend: 38 }}
              groupRef={registerGroup('workspace-right')}
              onLayoutChanged={handleLayoutChanged}
            >
              <DockPanel
                ref={registerPanel('attributeTable')}
                id="attributeTable"
                title={t("workspace.attributeTable") }
                icon="☷"
                toolbarSlot
                minSize={10}
                defaultSize={62}
                bodyClassName="right-panel-table"
                onCollapseChange={setPanelCollapsed} onCollapseToggle={handleCollapseToggle}
              >
                {showTableSwitch && <TableViewSwitch value={planViewOn ? 'plan' : 'features'} onChange={setTableView} />}
                {planViewOn ? (
                  <PlanTable
                    calculationId={calculationId}
                    refreshKey={`${store.geometryVersion}:${activityRefreshKey}`}
                    onAddActivity={() => wizardHost.controller.openWizard()}
                    onSelectPlaces={handleSelectPlanPlaces}
                    onPlanChanged={() => setPlanVersion((v) => v + 1)}
                    onOpenFullPlan={() => window.open(`/calculations/${calculationId}?tab=reports-outputs&context=yearlyactivities`, '_blank', 'noopener')}
                    onShowOnMap={(line) => {
                      void wizardHost.openForStep({ key: 'NO_LOCATION', text: '', button: '', action: 'show_on_map', activityId: line.id, confirmable: false });
                    }}
                    extraToolbar={(
                      <>
                        <SubAreaPlanBadge
                          count={subAreaPlan.status?.needs_plan ?? 0}
                          onOpen={() => setSubAreaPlanDialog({ open: true, focusId: null })}
                        />
                        <PlanExportMenu calculationId={calculationId} size="small" onFixIssue={() => openPlanView()} />
                      </>
                    )}
                  />
                ) : (
                <AttributeTable
                  isLoading={boundaryQuery.loading || blocksQuery.loading || subBlocksQuery.loading || compartmentsQuery.loading || subCompartmentsQuery.loading || subAreasQuery.loading || activityQuery.loading}
                  error={null}
                  onRetry={() => {}}
                  features={
                    ({
                      boundary: boundaryQuery.data,
                      user_group: userGroupQuery.data,
                      blocks: blocksQuery.data,
                      sub_blocks: subBlocksQuery.data,
                      compartments: compartmentsQuery.data,
                      sub_compartments: subCompartmentsQuery.data,
                      sub_areas: subAreasQuery.data,
                      activity_features: activityQuery.data,
                      sample_plots: samplePlotsQuery.data,
                      stem_mapping: stemMappingQuery.data,
                      fieldbook: fieldbookQuery.data,
                    } as Record<string, GeoJSON.Feature[] | null>)[store.activeLayerId ?? ''] ??
                    (store.activeImportedLayerId != null
                      ? (store.importedLayers.find((l) => l.id === store.activeImportedLayerId)?.isDraft
                          ? (store.digitizeDraftFeatures[store.activeImportedLayerId] ?? null)
                          : (store.importedLayerFeatures[store.activeImportedLayerId] ?? null))
                      : store.activeRasterLayerId != null
                        ? (store.rasterLayerFeatures[store.activeRasterLayerId] ?? null)
                        : null)
                  }
                  onSaveProperty={
                    store.activeLayerId === 'sample_plots'
                      ? handleSaveSamplePlotCoordinate
                      : store.activeLayerId === 'sub_areas'
                      ? handleSaveSubAreaProperty
                      : store.activeLayerId === 'activity_features'
                        ? handleSaveActivityFeatureProperty
                      : (store.activeLayerId === 'blocks'
                        || store.activeLayerId === 'sub_blocks'
                        || store.activeLayerId === 'compartments'
                        || store.activeLayerId === 'sub_compartments')
                        ? handleSaveBlockProperty
                        : store.activeLayerId === 'boundary'
                          ? handleSaveBoundaryPieceProperty
                        : store.activeImportedLayerId != null
                          ? handleSaveImportedProperty
                          : store.activeRasterLayerId != null
                            ? handleSaveRasterProperty
                            : undefined
                  }
                  extraToolbar={
                    store.activeLayerId === 'activity_features' && canPlan
                      ? (
                        <>
                          <Button size="small" type="primary" data-testid="table-add-activity" onClick={() => wizardHost.controller.openWizard()}>
                            {t('yearlyPlan.wizard.addButton')}
                          </Button>
                          <PlanExportMenu calculationId={calculationId} size="small" onFixIssue={() => openPlanView()} />
                        </>
                      )
                      : undefined
                  }
                  onDeleteFeature={handleDeleteFeature}
                  onCopyFeature={handleCopyRow}
                  onPasteFeatures={() => { void clipboardTools.paste(); }}
                  onPasteAsLayer={() => { void clipboardTools.pasteAsLayer(); }}
                  pasteState={clipboardTools.activePasteState}
                  clipboardCount={clipboardTools.clipboardCount}
                  onZoomToFeature={handleZoomToFeature}
                  onZoomToSelection={handleZoomToSelection}
                  onSelectInView={handleSelectInView}
                />
                )}
              </DockPanel>

              <Separator className="dock-separator-h" />

              <DockPanel
                ref={registerPanel('legend')}
                id="legend"
                title={t("workspace.legend") }
                icon="◈"
                minSize={8}
                defaultSize={38}
                onCollapseChange={setPanelCollapsed} onCollapseToggle={handleCollapseToggle}
              >
                <LegendPanel />
              </DockPanel>
            </Group>
          </Panel>
        </Group>
      </div>

      <WorkspaceStatusBar map={map} />

      <CompletionModal
        open={completionModalOpen}
        onClose={() => setCompletionModalOpen(false)}
        status={store.mapLifecycleStatus}
        calculationId={calculationId}
      />
      {assignLayerModalInfo.visible && (
        <AssignLayerModal
          visible={assignLayerModalInfo.visible}
          onClose={() => setAssignLayerModalInfo({ visible: false, layerId: null, layerName: '' })}
          calculationId={calculationId}
          layerId={assignLayerModalInfo.layerId}
          layerName={assignLayerModalInfo.layerName}
        />
      )}
      {assignPurposeModalInfo.visible && (
        <AssignPurposeModal
          visible={assignPurposeModalInfo.visible}
          onClose={() => setAssignPurposeModalInfo({ visible: false, layerId: null, layerName: '' })}
          calculationId={calculationId}
          layerId={assignPurposeModalInfo.layerId}
          layerName={assignPurposeModalInfo.layerName}
        />
      )}
      <SamplePlotCreateModal
        open={samplePlotModalOpen}
        calculationId={calculationId}
        onClose={closeSamplePlotModal}
        onChanged={(change) => {
          // Every layer reads through the geometry version, so this re-fetches Sample Plots.
          store.bumpGeometryVersion();
          // A layer the user had hidden would otherwise "create nothing" as far as they can see.
          if (change === 'created' && store.layerVisibility.sample_plots === false) {
            store.toggleLayerVisibility('sample_plots');
          }
        }}
      />
      <StemMappingModal
        open={stemMappingModalOpen}
        calculationId={calculationId}
        onClose={closeStemMappingModal}
        onChanged={(change) => {
          // Every layer reads through the geometry version, so this re-fetches
          // the stem-mapping layer (StemMappingClusters + attribute table).
          store.bumpGeometryVersion();
          // A layer the user had hidden would otherwise "import nothing" as far
          // as they can see.
          if (change === 'created' && store.layerVisibility.stem_mapping === false) {
            store.toggleLayerVisibility('stem_mapping');
          }
        }}
      />
      <UserGroupDataModal
        open={userGroupData.open}
        calculationId={calculationId}
        section={userGroupData.section}
        onClose={() => {
          setUserGroupDataDialog((d) => ({ ...d, open: false }));
          void refreshUserGroupData();
        }}
      />
      <UserGroupModal
        open={userGroupModalOpen}
        calculationId={calculationId}
        forestName={forestName || store.forestName || undefined}
        onClose={closeUserGroupModal}
        onChanged={(change) => {
          // Every layer reads through the geometry version, so this re-fetches
          // the user-group extent features.
          store.bumpGeometryVersion();
          if (change === 'analyzed') {
            // A layer the user had hidden would otherwise "analyse nothing" as
            // far as they can see.
            if (store.layerVisibility.user_group === false) {
              store.toggleLayerVisibility('user_group');
            }
            // Defaults of the analyse flow (BG-4): surface the land-cover
            // raster + the Education POI overlay.
            if (!store.activeRasterLayers.includes('ug_landcover')) {
              store.toggleRasterLayer('ug_landcover');
            }
            if (store.userGroupPoiVisible.education !== true) {
              store.toggleUserGroupPoi('education');
            }
          }
          if (change === 'deleted') {
            const ugRasters = ['ug_landcover', 'ug_biomass'];
            const remaining = store.activeRasterLayers.filter((id) => !ugRasters.includes(id));
            if (remaining.length !== store.activeRasterLayers.length) {
              useWorkspaceStore.setState({ activeRasterLayers: remaining });
            }
            if (Object.keys(store.userGroupPoiVisible).length > 0) {
              store.clearUserGroupPoi();
            }
          }
        }}
      />
      {autoBlockLevel && (
        <AutoBlockDesigner
          map={map}
          calculationId={calculationId}
          initialLevel={autoBlockLevel}
          onClose={closeAutoBlockDesigner}
          onCommitted={() => {
            store.bumpGeometryVersion();
            // RS-2.16: the whole-forest commit now creates a new Auto-Block
            // layer rather than replacing the forest's blocks directly --
            // refresh the layer list so the panel shows it.
            store.refreshRasterLayers(calculationId);
          }}
        />
      )}
      {calculationId && (
        <UpdateAttributeDialog
          calculationId={calculationId}
          open={updateAttributeOpen}
          onClose={() => setUpdateAttributeOpen(false)}
        />
      )}
      {autoDivideParent && (
        <AutoBlockDesigner
          key={autoDivideParent.id}
          map={map}
          calculationId={calculationId}
          initialLevel="compartments"
          parent={autoDivideParent}
          onClose={() => setAutoDivideParent(null)}
          onCommitted={() => store.bumpGeometryVersion()}
        />
      )}
      {riverBanksOpen && (
        <FireLinePanel
          kind="river_bank"
          map={map}
          calculationId={calculationId}
          structureLocked={store.structureLocked}
          onClose={() => setRiverBanksOpen(false)}
          onChanged={() => store.bumpGeometryVersion()}
        />
      )}
      {fireLinesOpen && (
        <FireLinePanel
          map={map}
          calculationId={calculationId}
          structureLocked={store.structureLocked}
          onClose={() => setFireLinesOpen(false)}
          onChanged={() => store.bumpGeometryVersion()}
        />
      )}
      {divideTarget && (
        <EqualAreaDividePanel
          map={map}
          calculationId={calculationId}
          layerType={divideTarget.layerId}
          featureId={divideTarget.featureId}
          onClose={() => setDivideTarget(null)}
          onCommitted={() => {
            setDivideTarget(null);
            store.bumpGeometryVersion();
          }}
        />
      )}
    </div>
  );
}

/**
 * E2.4 (Approach A) — find the point on a LineString nearest to a map click,
 * within the edge snap tolerance.  Returns null when too far to split.
 */
function nearestSplitPoint(
  geom: GeoJSON.Geometry,
  click: L.LatLng,
): { lat: number; lng: number } | null {
  const coords: GeoJSON.Position[][] = geom.type === 'MultiLineString'
    ? (geom as GeoJSON.MultiLineString).coordinates
    : [((geom as GeoJSON.LineString).coordinates)];
  let best: { lat: number; lng: number } | null = null;
  let bestDist = Infinity;
  const tolDeg = 150 / 111_320; // ~SNAP_TOLERANCE_M in degrees

  for (const line of coords) {
    for (let i = 0; i < line.length - 1; i++) {
      const [lng1, lat1] = line[i];
      const [lng2, lat2] = line[i + 1];
      const near = projectPointToSegment(click.lng, click.lat, lng1, lat1, lng2, lat2);
      // only split at interior points, not at an existing vertex
      if (near.result > 1e-6 && near.result < 1 - 1e-6) {
        const d = Math.hypot(near.lng - click.lng, near.lat - click.lat);
        if (d < bestDist) {
          bestDist = d;
          best = { lat: near.lat, lng: near.lng };
        }
      }
    }
  }
  if (best && bestDist <= tolDeg) return best;
  return null;
}

/** Project a click onto a segment; returns the projected point + param t. */
function projectPointToSegment(
  px: number, py: number, x1: number, y1: number, x2: number, y2: number,
): { lat: number; lng: number; result: number } {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-12) return { lat: y1, lng: x1, result: 0 };
  let t = ((px - x1) * dx + (py - y1) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return { lat: y1 + t * dy, lng: x1 + t * dx, result: t };
}

function useLayerData(layerType: LayerTypeId, calculationId: string, enabled = true, refreshKey: number = 0) {
  const t = useT();
  const store = useWorkspaceStore();
  const [data, setData] = useState<GeoJSON.Feature[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Stem Mapping's full feature list (thousands of rows) is only ever read
    // by the attribute table / legend count, never the map (which renders via
    // StemMappingClusters' own viewport-tile fetches) — so it stays `enabled:
    // false` (see the call site) until the layer is actually selected, instead
    // of fetching every tree on every workspace mount regardless of whether
    // anyone looks at it.
    if (!enabled) { setLoading(false); return; }
    const layerConfig = getLayerConfig(layerType);
    if (!layerConfig) { setLoading(false); return; }
    let cancelled = false;

    store.setLoading(`features:${layerType}`, true);
    const perfMark = performance.mark(`layer:load-start-${layerType}`);

    layerConfig.dataSource.fetch(calculationId)
      .then((features) => {
        if (cancelled) return;
        setData(features);
        setError(null);
        store.setFeatureCount(layerType, features?.length || 0);
        // Track protection-working-circle units per unit layer so the legend can
        // show its row only when such a unit actually exists (P5-display).
        if (layerType === 'blocks' || layerType === 'sub_blocks' || layerType === 'compartments' || layerType === 'sub_compartments') {
          const prot = (features || []).filter(
            (f) => f.properties?.working_circle === 'protection',
          ).length;
          store.setFeatureCount(`${layerType}:protection`, prot);
        }
        // Activity Features: how many of each symbol kind, so the legend lists only those present.
        // Every known kind is set (to 0 if absent) so a kind that has gone does not linger.
        if (layerType === 'activity_features') {
          const perKind: Record<string, number> = {};
          for (const f of features || []) {
            const k = String(f.properties?.kind || '');
            if (k) perKind[k] = (perKind[k] ?? 0) + 1;
          }
          for (const k of ACTIVITY_KIND_IDS) store.setFeatureCount(activityKindCountKey(k), perKind[k] ?? 0);
        }
        store.noteLayerLoaded(layerType);
        performance.mark(`layer:load-end-${layerType}`);
        performance.measure(`layer:load-${layerType}`,
          `layer:load-start-${layerType}`, `layer:load-end-${layerType}`);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message || t('workspace.layerLoadFailed', { layer: layerType }));
        store.setError(`features:${layerType}`, err?.message || t('generalErrors.unknown'));
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
          store.setLoading(`features:${layerType}`, false);
        }
      });
    return () => { cancelled = true; };
    // geometryVersion lets purpose-first boundary set/merge refetch this
    // layer. `refreshKey` (owner report 2026-10-02) is a narrower trigger a
    // caller can bump on its own instead of the global geometryVersion --
    // sample-plot add/move/delete use it so one plot move doesn't refetch
    // every OTHER layer (blocks/compartments/sub_areas/activity_features/
    // boundary/...) too, which is what made a single drag feel slow: each
    // of those refetches runs its own query, and sample_plots' own fetch is
    // already the heaviest one here (elevation + nearest-topographic-
    // feature lookup per point, recomputed for the WHOLE design every time
    // its `points_data` cache is invalidated).
  }, [layerType, calculationId, store.geometryVersion, enabled, refreshKey]);

  // The SFM classification rides on the unit features' own properties, so colours, labels and the attribute table
  // share one source (see lib/sfmFeatureProps.ts).
  const isUnitLayer = layerType === 'blocks' || layerType === 'sub_blocks' || layerType === 'compartments' || layerType === 'sub_compartments';
  const sfmInfo = store.sfmBlockTypes;
  const hazardInfo = store.hazardUnits;
  const unitMapInfo = store.unitMap;
  const fiInfo = store.fieldInventoryUnits;
  const analysisInfo = store.unitAnalysis;
  const merged = useMemo(
    () => (isUnitLayer ? mergeUnitLayerProps(data, { sfmBlockTypes: sfmInfo, hazardUnits: hazardInfo, unitMap: unitMapInfo, fieldInventoryUnits: fiInfo, unitAnalysis: analysisInfo }) : data),
    [isUnitLayer, data, sfmInfo, hazardInfo, unitMapInfo, fiInfo, analysisInfo],
  );

  return { data: merged, loading, error };
}

const pickerOverlay: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  background: 'rgba(0,0,0,0.35)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1000,
};

const pickerPanel: React.CSSProperties = {
  background: '#fff',
  borderRadius: 8,
  boxShadow: '0 4px 24px rgba(0,0,0,0.25)',
  maxWidth: 640,
  width: '90%',
};

const pickerHeader: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  alignItems: 'center',
  padding: '12px 16px',
  borderBottom: '1px solid #eee',
  fontWeight: 600,
  fontSize: 14,
};

const closeBtn: React.CSSProperties = {
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  fontSize: 18,
  color: '#666',
};

const miniBtn: React.CSSProperties = {
  border: '1px solid #d1d5db',
  borderRadius: 6,
  padding: '5px 12px',
  fontSize: 12,
  fontWeight: 600,
  cursor: 'pointer',
  background: '#fff',
};

export default MapWorkspace;
