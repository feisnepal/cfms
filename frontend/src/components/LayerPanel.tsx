import { useState, useCallback, useRef, useEffect, Fragment } from 'react';
import { planLinesDetail, chooseWhatHappensToPlanLines } from '../lib/planLinesChoice';
import L from 'leaflet';
import JSZip from 'jszip';
import { message, Modal, Dropdown, Select, Tag as AntTag, Tooltip } from 'antd';
import {
  ArrowDown, ArrowUp, FileJson, FileSpreadsheet, FileText, Focus, Lock, LockOpen,
  Map, MoreVertical, Plus, RefreshCw, Route, Scissors, Sparkles, Tag,
} from 'lucide-react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { buildLayerMenu, type PasteState } from '../lib/layerMenu';
import { layerStyleKey, getStyleClipboard, setStyleClipboard, NAMED_STYLE_PRESETS, defaultImportedLabelField, type CustomLayerStyle } from '../lib/layerStyles';
import { zoomToLayerBounds } from '../lib/mapZoom';
import type { LayerTypeId } from '../lib/layerRegistry';
import { useBoundaryPreview } from '../contexts/BoundaryPreviewContext';
import { provisionalFromError } from '../lib/boundaryPreviewPending';
import LayerGlyph from './LayerGlyph';
import { getLayerConfig, resolveLayerOrder, isLayerVisibleByDefault } from '../lib/layerRegistry';
import { useContextMenuUndoRedo } from '../hooks/useContextMenuUndoRedo';
import { createLabelFieldOperation } from '../lib/operationFactories';
import ImportPurposeDialog from './ImportPurposeDialog';
import type { ImportResult } from '../hooks/useImportLayer';
import LayerContextMenu from './LayerContextMenu';
import type { ContextMenuPosition } from './LayerContextMenu';
import { UserGroupAnalysisSection } from './UserGroupAnalysisSection';
import { StemMappingLegendSection } from './StemMappingLegendSection';
import { AnalysisMapsGroup } from './AnalysisMapsGroup';
import { ReferenceLayersGroup } from './ReferenceLayersGroup';
import { NtfpPlotsGroup } from './NtfpPlotsGroup';
import { MoreLayersBand } from './MoreLayersBand';
import { ForestSummaryButton } from './ForestSummaryButton';
import { useNtfpHasDesign } from '../hooks/useNtfpHasDesign';
import { SubLayerSymbol } from './SubLayerSymbol';
import LayerStyleDialog from './LayerStyleDialog';
import AddLayerMenu from './AddLayerMenu';
import PurposePickerDialog from './PurposePickerDialog';
import { flushDigitizeBufferWithRetry } from '../hooks/useDraftSync';
import { geometryTypesForPurpose } from '../lib/purposeGeometryRules';
import type { ToolbarMode } from '../lib/layerRegistry';
import { inventoryApi, forestApi, samplingApi, userGroupApi, fieldbookApi, fieldInventoryApi } from '../services/api';
import { useT } from '../i18n/hooks';
import { UserGroupAnalysisChip } from './UserGroupAnalysisChip';
import { readDetail } from '../hooks/useErrorHandler';
import { downloadFromApi } from '../utils/download';
import i18n from '../i18n';

function firstDrawModeForPurpose(purpose: string): ToolbarMode {
  const first = geometryTypesForPurpose(purpose)[0];
  return first === 'point' ? 'draw_point' : first === 'line' ? 'draw_line' : 'draw_polygon';
}

const SHAPEFILE_EXTS = new Set(['.dbf', '.shx', '.prj', '.cpg', '.sbn', '.sbx', '.xml']);

function findShapefileSet(files: File[]): { shp: File; companions: File[]; missingCpg: boolean } | null {
  const shp = files.find(f => f.name.toLowerCase().endsWith('.shp'));
  if (!shp) return null;
  const base = shp.name.slice(0, -4).toLowerCase();
  const companions = files.filter(f => {
    if (f === shp) return false;
    const n = f.name.toLowerCase();
    return n.startsWith(base) && SHAPEFILE_EXTS.has(n.slice(n.lastIndexOf('.')));
  });
  const missingCpg = !companions.some(f => f.name.toLowerCase().endsWith('.cpg'));
  return { shp, companions, missingCpg };
}

async function zipShapefileFiles(shp: File, companions: File[]): Promise<File> {
  const zip = new JSZip();
  zip.file(shp.name, shp);
  for (const f of companions) zip.file(f.name, f);
  const blob = await zip.generateAsync({ type: 'blob' });
  return new File([blob], shp.name.replace(/\.shp$/i, '.zip'), { type: 'application/zip' });
}

interface LayerPanelProps {
  map: L.Map | null;
  isLoading: boolean;
  error: string | null;
  onRetry?: () => void;
  structureLocked?: boolean;
  zoomToLayer?: (id: string) => void;
  onLayerImported?: (layerId?: number, purpose?: string) => void;
  mode?: 'layers' | 'basemap' | 'imported' | 'raster';
  /** True once any geometry (boundary / blocks / compartments) exists. When false,
   *  the first "Add Geometry" must pick a geometry purpose (Forest boundary / Block). */
  hasGeometry?: boolean;
  /** Fired when user picks "Add Sub-Area" on the builtin sub_areas layer (P6 category-first draw). */
  onAddSubArea?: (layerId: string) => void;
  /** U-4 (Task 4.1, case E): fired when user picks "Create Polygon from Points". */
  onPolygonFromPoints?: (layerId: string, purpose: string) => void;
  /** Auto-Block MMU (Phase B): fired when user picks "Auto-create" on the
   *  Blocks/Compartments builtin row or the zero-blocks banner. */
  onAutoCreate?: (level: 'blocks' | 'compartments') => void;
  /** Sample Plots layer menu: open the sampling design form over the map. */
  onCreateSamplePlots?: () => void;
  /** Stem Mapping layer menu: open the Tree Mapping process in a modal over the map. */
  onImportStemMapping?: () => void;
  /** User Group Boundary layer menu: open the analysis + results in a modal over the map. */
  onUserGroupAnalysis?: () => void;
  /** BL-5 (block lifecycle decoupling): fired when user picks "Import Block
   *  from Forest Boundary" on the Blocks builtin row. */
  onImportBlockFromBoundary?: (layerId: string) => void;
  /** Auto-Block MMU (Phase B): true when any auto-block preview is active. */
  autoBlockActive?: boolean;
  /** Block-boundary invariant (E.8): fired when user picks "New Block" /
   *  "New Compartment" on the Blocks/Compartments builtin row — arms the
   *  polygon-draw tool which posts to POST /calculations/{id}/blocks/draw. */
  onNewDraw?: (level: 'blocks' | 'compartments') => void;
  /** Compartment rewire (D5/D6): fired when user picks "Divide Equal-Area" on
   *  the Compartments / Sub-Compartments builtin row. Button is always shown but
   *  disabled when the prerequisite data is missing or the layer is locked. */
  onDivide?: (layerId: 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments') => void;
  /** Divide the selected block / compartment by a natural basis (river-ridge, slope, aspect, canopy). */
  onAutoDivide?: (layerId: 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments') => void;
  /** Phase G (rule G): current calculation id — enables Sample Plots export. */
  calculationId?: string;
  /**
   * The FEATURE clipboard (Copy / Paste / Paste as new layer) for a layer's context
   * menu. Layers are keyed like the selection: a built-in id, or `imported:<id>`.
   * Absent = the three commands are not offered.
   */
  featureClipboard?: FeatureClipboardMenuApi;
}

/** What the workspace hands the layer menu so it can offer Copy / Paste on any layer. */
export interface FeatureClipboardMenuApi {
  /** Features waiting on the clipboard. */
  clipboardCount: number;
  /** Features selected in a layer (0 = Copy would take the whole layer). */
  selectedCountFor: (layerKey: string) => number;
  /** Can a paste land in a layer right now? null = yes; 'never' = it never can; else why not. */
  pasteStateFor: (layerKey: string) => PasteState;
  copy: (opts: { layerKey: string }) => void;
  paste: (layerKey: string) => void;
  pasteAsLayer: () => void;
}

/** A layer's key in the feature clipboard / selection: a built-in id, or `imported:<id>`. */
function clipKeyOf(layerId: string, layerType: 'builtin' | 'imported'): string {
  return layerType === 'imported' ? `imported:${layerId}` : layerId;
}

interface CtxMenuState {
  layerId: string;
  layerType: 'builtin' | 'imported';
  layerName: string;
  visible: boolean;
  featureCount: number;
  editable: boolean;
  locked: boolean;
  position: { x: number; y: number };
  purpose?: string;
  isDraft?: boolean;
  // M-3: state the row menu used to hold privately, now shared with right-click.
  readOnly?: boolean;
  structureLocked?: boolean;
  labelFields?: string[];
  currentLabelField?: string | null;
  counts?: Record<string, number>;
  isFirst?: boolean;
  isLast?: boolean;
  unavailableActions?: string[];
  exportFormats?: string[];
}

interface LayerItemConfig {
  id: string;
  label: string;
  icon: string;
  locked: boolean;
  hasSubLayers: boolean;
  subLayers?: Array<{ id: string; label: string }>;
}

function resolveLock(manualLocked = false): boolean {
  // Per-layer UI lock is user-controlled: a layer is locked ONLY when the user
  // explicitly toggles it. Wire/DFO lifecycle and structure locks are enforced
  // server-side (403), so they do not disable the layer in this workspace.
  return manualLocked;
}

export function LayerPanel({ map, isLoading, error, onRetry, zoomToLayer, onLayerImported, mode = 'layers', hasGeometry = false, onAddSubArea, onPolygonFromPoints, onAutoCreate, onCreateSamplePlots, onImportStemMapping, onUserGroupAnalysis, onImportBlockFromBoundary, autoBlockActive = false, onNewDraw, structureLocked = false, onDivide, onAutoDivide, calculationId, featureClipboard }: LayerPanelProps) {
  const store = useWorkspaceStore();
  const ntfpHasDesign = useNtfpHasDesign(calculationId);
  const t = useT();
  const { reviewBoundary } = useBoundaryPreview();
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importWarning, setImportWarning] = useState<string | null>(null);
  const [fixedImportPurpose, setFixedImportPurpose] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [addLayerMenu, setAddLayerMenu] = useState<{ x: number; y: number } | null>(null);
  const [purposePickerOpen, setPurposePickerOpen] = useState(false);
  const addLayerBtnRef = useRef<HTMLButtonElement>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);

  const openAddLayerMenu = useCallback(() => {
    const rect = addLayerBtnRef.current?.getBoundingClientRect();
    if (!rect) return;
    setAddLayerMenu({ x: rect.left, y: rect.bottom + 4 });
  }, []);

  const closeAddLayerMenu = useCallback(() => setAddLayerMenu(null), []);

  const handleDrawOnMap = useCallback(() => {
    setPurposePickerOpen(true);
  }, []);

  const closePurposePicker = useCallback(() => setPurposePickerOpen(false), []);

  // ── GD 2.2.2 / 2.2.4: Finish & Save + Cancel & Discard for draft layers ──
  const pollFinalize = useCallback(async (layerId: number, calcId: string): Promise<Record<string, unknown>> => {
    const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const res = await fetch(
        `${baseUrl}/api/v1/workspace/${calcId}/digitize-layers/${layerId}/finalize-status`,
        { headers, credentials: 'include' },
      );
      if (!res.ok) continue;
      const data = await res.json().catch(() => null);
      if (!data) continue;
      const status = (data as Record<string, unknown>).status as string | undefined;
      if (status === 'succeeded' || status === 'validation_failed' || status === 'failed') {
        return data as Record<string, unknown>;
      }
    }
    throw new Error(i18n.t('layerPanel.finalizeTimeout'));
  }, []);

  // Purpose-first (policy B): merge finalized Block/Compartment geometry pieces into
  // the single derived forest boundary (boundary_geom). Additive (unary_union) and
  // re-runnable. The Block layer itself is preserved so the user can still edit /
  // cut / split it afterwards (policy A is out of scope — see layer_consolidation.md).
  const mergeLayerToBoundary = useCallback(async (layer: { id: number; name: string }) => {
    const calcId = store.calculationId;
    if (!calcId) return;
    setMergingLayerId(layer.id);
    try {
      const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
      const token = localStorage.getItem('access_token');
      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;
      let features = store.importedLayerFeatures[layer.id];
      if (!features || features.length === 0) {
        const res = await fetch(
          `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${layer.id}/features`,
          { headers, credentials: 'include' },
        );
        if (res.ok) {
          const data = await res.json();
          features = data.features || [];
          store.setImportedLayerFeatures(layer.id, features);
        }
      }
      const geometries = (features || []).map((f) => f.geometry).filter(Boolean);
      if (geometries.length === 0) {
        message.warning(t('workspace.noGeometryToMerge', { name: layer.name }));
        return;
      }
      // PF-3: merge into the boundary may create overlap/gap with a neighbour.
      // mergeForestBoundary has no provisional gate, so pre-flight the preview.
      if (calcId && typeof forestApi.previewBoundaryOverlap === 'function') {
        try {
          const merged: any = await (async () => {
            // union all geometries to a single proposed boundary for the preview
            const fc = geometries as any[];
            let acc = fc[0];
            for (let i = 1; i < fc.length; i++) {
              const u = await (import('@turf/turf')).then((turf) => turf.union(acc, fc[i]));
              if (u) acc = u;
            }
            return acc;
          })();
          const rel = await forestApi.previewBoundaryOverlap({
            geometry: merged,
            method: 'digitize',
            forest_id: calcId,
          });
          if (rel?.overlapping_forests?.length || rel?.gaps?.length) {
            reviewBoundary({
              geometry: merged,
              forestName: store.forestName || layer.name,
              method: 'digitize',
              calculationId: calcId,
              onResolved: () => {
                store.bumpGeometryVersion();
                message.success(t('workspace.mergedIntoBoundary', { name: layer.name, count: geometries.length }));
              },
            });
            return;
          }
        } catch {
          /* preview unavailable — fall through to direct merge */
        }
      }
      await forestApi.mergeForestBoundary(calcId, geometries);
      store.bumpGeometryVersion();
      message.success(t('workspace.mergedIntoBoundary', { name: layer.name, count: geometries.length }));
    } catch (err) {
      const prov = provisionalFromError(err);
      if (prov?.needs_overlap_review && prov?.preview_geometry) {
        reviewBoundary({
          geometry: prov.preview_geometry,
          forestName: store.forestName || layer.name,
          method: 'digitize',
          calculationId: store.calculationId ?? undefined,
          onResolved: () => store.bumpGeometryVersion(),
        });
        return;
      }
      message.error(err instanceof Error ? err.message : t('workspace.mergeFailed'));
    } finally {
      setMergingLayerId(null);
    }
  }, [store, reviewBoundary, t]);

  const handleFinishSave = useCallback(async (layer: { id: number; name: string; featureCount: number; purpose?: string }) => {
    const calcId = store.calculationId;
    if (!calcId) return;
    // Forest-boundary purpose: drawn piece becomes the derivation of boundary_geom
    // (single source of truth), not an auxiliary layer. Route to updateBoundaryGeometry /
    // mergeForestBoundary instead of finalizeDigitizeLayer.
    if (layer.purpose === 'boundary') {
      const buffered = store.digitizeDraftFeatures[layer.id] ?? [];
      if (buffered.length === 0) {
        message.warning(t('workspace.noDrawnGeometry', { name: layer.name }));
        return;
      }
      store.setDigitizeSyncState('syncing');
      try {
        if (buffered.length === 1) {
          const resp: any = await forestApi.updateBoundaryGeometry(calcId, { geometry: buffered[0], area_hectares: 0 });
          if (resp?.needs_overlap_review) {
            reviewBoundary({
              geometry: resp.preview_geometry || buffered[0],
              forestName: store.forestName || layer.name,
              method: 'digitize',
              calculationId: calcId,
              onResolved: () => {
                message.success(t('workspace.forestBoundarySet', { count: buffered.length }));
                store.bumpGeometryVersion();
              },
            });
          } else {
            message.success(t('workspace.forestBoundarySet', { count: buffered.length }));
            store.bumpGeometryVersion();
          }
        } else {
          // PF-3: pre-flight preview before merging (merge has no provisional gate)
          if (typeof forestApi.previewBoundaryOverlap === 'function') {
            try {
              const turf = await import('@turf/turf');
              let acc2: any = buffered[0]?.geometry;
              if (acc2) {
                for (let i = 1; i < buffered.length; i++) {
                  const u = (turf as any).union(acc2, buffered[i]?.geometry);
                  if (u) acc2 = u;
                }
                const rel = await forestApi.previewBoundaryOverlap({
                  geometry: acc2,
                  method: 'digitize',
                  forest_id: calcId,
                });
                if (rel?.overlapping_forests?.length || rel?.gaps?.length) {
                  reviewBoundary({
                    geometry: acc2,
                    forestName: store.forestName || layer.name,
                    method: 'digitize',
                    calculationId: calcId,
                    onResolved: () => {
                      message.success(t('workspace.forestBoundaryMerged', { count: buffered.length }));
                      store.bumpGeometryVersion();
                    },
                  });
                  return;
                }
              }
            } catch {
              /* preview unavailable — fall through to direct merge */
            }
          }
          await forestApi.mergeForestBoundary(calcId, buffered.map((f) => f.geometry));
          message.success(t('workspace.forestBoundaryMerged', { count: buffered.length }));
          store.bumpGeometryVersion();
        }
        await store.discardDigitizeLayer(calcId, layer.id).catch(() => {});
      } catch (err) {
        const prov = provisionalFromError(err);
        if (prov?.needs_overlap_review && prov?.preview_geometry) {
          reviewBoundary({
            geometry: prov.preview_geometry,
            forestName: store.forestName || layer.name,
            method: 'digitize',
            calculationId: calcId,
            onResolved: () => store.bumpGeometryVersion(),
          });
          return;
        }
        message.error(err instanceof Error ? err.message : t('workspace.failedSetBoundary'));
      } finally {
        store.setDigitizeSyncState('idle');
      }
      return;
    }
    const buffered = store.digitizeDraftFeatures[layer.id] ?? [];
    const hasFeatures = buffered.length > 0 || layer.featureCount > 0;
    if (!hasFeatures) {
      Modal.confirm({
        title: t('workspace.discardEmptyDraftTitle'),
        content: t('workspace.discardEmptyDraftContent', { name: layer.name }),
        okText: t('workspace.discard'),
        okType: 'danger',
        cancelText: t('workspace.keepEditing'),
        onOk: async () => {
          try {
            await store.discardDigitizeLayer(calcId, layer.id);
            message.success(t('workspace.discardedLayer', { name: layer.name }));
          } catch (err) {
            message.error(err instanceof Error ? err.message : t('workspace.discardFailed'));
          }
        },
      });
      return;
    }
    store.setDigitizeSyncState('syncing');
    try {
      if (buffered.length > 0) {
        const ok = await flushDigitizeBufferWithRetry(calcId, layer.id, buffered);
        if (!ok) throw new Error(i18n.t('layerPanel.syncFailed'));
      }
      const result = await store.finalizeDigitizeLayer(calcId, layer.id);
      const queued = (result as Record<string, unknown>)?.status === 'queued';
      const status = queued
        ? await pollFinalize(layer.id, calcId)
        : result as Record<string, unknown>;
      const finalStatus = (status as Record<string, unknown>).status as string | undefined;
      if (finalStatus === 'succeeded' || finalStatus === 'finalized') {
        message.success(t('workspace.layerSaved', { name: layer.name, count: (status as Record<string, unknown>).feature_count ?? layer.featureCount }));
        // Purpose-first: a Block/Compartment that is the FIRST geometry added to
        // a boundary-less draft is automatically unioned into the derived forest
        // boundary (boundary_geom). The Block layer itself is preserved so the
        // user can still edit / cut / split it. A Boundary-purpose first add
        // becomes the boundary directly and is NOT auto-merged.
        if (layer.purpose === 'blocks' && !hasGeometry) {
          mergeLayerToBoundary(layer);
        }
      } else if (finalStatus === 'validation_failed') {
        const raw = (status as Record<string, unknown>).last_validation_error;
        const errText = typeof raw === 'string'
          ? raw
          : typeof raw === 'object' && raw != null && 'message' in raw
            ? String((raw as { message?: unknown }).message ?? '')
            : '';
        message.error(t('workspace.validationFailedWithDetail', { detail: errText || t('workspace.reviewAndFix') }));
        Modal.info({
          title: t('workspace.validationFailedTitle'),
          content: errText || t('workspace.validationFailedContent'),
          okText: t('workspace.reviewAndFix'),
          onOk: () => {
            store.setActiveImportedLayer(layer.id);
            store.setActiveDigitizeContext({ mode: 'draft', layer: store.importedLayers.find((l) => l.id === layer.id) as any });
            store.setToolbarMode(firstDrawModeForPurpose(layer.purpose as string));
          },
        });
      } else {
        message.error(t('workspace.finalizeFailed'));
      }
    } catch (err) {
      const detail = err instanceof Error && 'detail' in err ? (err as any).detail : null;
      message.error(detail || (err instanceof Error ? err.message : t('workspace.finalizeFailed')));
    } finally {
      store.setDigitizeSyncState('idle');
    }
  }, [store, pollFinalize, hasGeometry, mergeLayerToBoundary, reviewBoundary]);

  const handleDiscard = useCallback((layer: { id: number; name: string }) => {
    const calcId = store.calculationId;
    if (!calcId) return;
    const count = (store.digitizeDraftFeatures[layer.id] ?? []).length;
    Modal.confirm({
      title: t('layerPanel.discardDraftTitle'),
      content: t('layerPanel.discardDraftContent', { count, name: layer.name }),
      okText: t('workspace.discard'),
      okType: 'danger',
      cancelText: t('workspace.keepEditing'),
      onOk: async () => {
        try {
          await store.discardDigitizeLayer(calcId, layer.id);
          message.success(t('layerPanel.discarded', { name: layer.name }));
        } catch (err) {
          message.error(err instanceof Error ? err.message : t('workspace.discardFailed'));
        }
      },
    });
  }, [store]);

  const handleImportComplete = useCallback((result: ImportResult) => {
    setImportFile(null);
    setImportWarning(null);
    setFixedImportPurpose(null);
    if (result.success) {
      store.setLoading(`import:${result.layerId}`, false);
      message.success(t('workspace.importedLayerSuccess', { name: result.layerName, count: result.featureCount }));
      // Zoom the map to the freshly imported layer once its geometry is available
      // (custom layers load async; builtin conversions refetch their query).
      onLayerImported?.(result.layerId, result.purpose);
      // Purpose-first (policy B): a Block/Compartment that is the FIRST geometry
      // added to a boundary-less draft is automatically unioned into the derived
      // forest boundary (boundary_geom). The Block layer itself is preserved so
      // the user can still edit / cut / split it afterwards.
      if (result.purpose === 'blocks' && !hasGeometry && result.layerId) {
        void mergeLayerToBoundary({ id: result.layerId, name: result.layerName ?? '' });
      }
    }
  }, [store, hasGeometry, mergeLayerToBoundary, onLayerImported]);

  // GD 2.4 (review #4): enter append mode — target an existing finalized layer.
  const handleAppend = useCallback((layerId: string) => {
    const id = Number(layerId);
    const layer = store.importedLayers.find((l) => l.id === id);
    if (!layer) return;
    if (layer.isDraft) return;
    const firstMode = firstDrawModeForPurpose(layer.purpose);
    if (!firstMode) return;
    store.setActiveImportedLayer(id);
    store.setActiveDigitizeContext({ mode: 'append', layer, sourceLayerId: id });
    store.setToolbarMode(firstMode);
    message.info(t('workspace.addingFeatures', { name: layer.name }), 3);
  }, [store]);

  const handleMergeIntoBoundary = useCallback(async (layer: { id: number; name: string; purpose?: string }) => {
    const calcId = store.calculationId;
    if (!calcId) return;
    Modal.confirm({
      title: t('layerPanel.mergeTitle'),
      content: t('layerPanel.mergeContent', { name: layer.name }),
      okText: t('layerPanel.mergeOk'),
      cancelText: t('workspace.cancel'),
       onOk: async () => {
        await mergeLayerToBoundary(layer);
      },
    });
}, [store, mergeLayerToBoundary]);
  

  useEffect(() => {
    const preventWindowDrop = (e: DragEvent) => {
    };
  }, []);

  const openFilePicker = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleContextImport = useCallback((layerId: string, purpose: string) => {
    console.log('[LayerPanel] handleContextImport called:', { layerId, purpose });
    // The builtin layer id is its import purpose everywhere except the user
    // group boundary, whose purpose string is `user_group_boundary`.
    const resolved = layerId === 'user_group' ? 'user_group_boundary' : purpose;
    setFixedImportPurpose(resolved);
    // Ensure state is flushed before opening file dialog
    setTimeout(() => {
      fileInputRef.current?.click();
    }, 0);
  }, []);

  const handleMenuImport = useCallback((purpose: string) => {
    setFixedImportPurpose(purpose);
    fileInputRef.current?.click();
  }, []);

  // User Group Boundary — auto-buffer from the forest boundary (P3).
  const handleUserGroupAutoBuffer = useCallback(async () => {
    const calcId = store.calculationId;
    if (!calcId) return;
    const raw = window.prompt(t('workspace.userGroup.autoBufferPrompt'), '1000');
    if (raw == null) return;
    const distance = Math.round(Number(raw));
    if (!Number.isFinite(distance) || distance < 100 || distance > 5000) {
      message.error(t('workspace.userGroup.autoBufferFailed'));
      return;
    }
    try {
      const res = await userGroupApi.createAutoBuffer(calcId, distance);
      if (/Analysis (skipped|could not)/.test(res?.message ?? '')) message.warning(res.message, 8);
      else message.success(t('workspace.userGroup.autoBuffered', { distance }));
      store.bumpGeometryVersion();
    } catch (err: unknown) {
      const detail = readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail);
      message.error(detail || t('workspace.userGroup.autoBufferFailed'), 8);
    }
  }, [store, t]);

  const onFileSelected = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    console.log('[LayerPanel] onFileSelected called');
    if (!store.calculationId) {
      console.log('[LayerPanel] No calculationId');
      message.error(t('workspace.noActiveCalculation'));
      e.target.value = '';
      return;
    }
    console.log('[LayerPanel] calculationId:', store.calculationId);
    setImportWarning(null);
    const files = Array.from(e.target.files ?? []);
    console.log('[LayerPanel] Files selected:', files.length, files.map(f => f.name));
    if (files.length === 0) return;
    
    // Handle .zip files directly (shapefile archives)
    const zipFile = files.find(f => f.name.toLowerCase().endsWith('.zip'));
    if (zipFile && files.length === 1) {
      console.log('[LayerPanel] Detected single .zip file, treating as shapefile archive');
      setImportFile(zipFile);
      return;
    }
    
    const set_ = findShapefileSet(files);
    if (set_) {
      const warnings: string[] = [];
      if (set_.missingCpg) {
        warnings.push(t('workspace.missingCpgWarning'));
      }
      if (warnings.length > 0) setImportWarning(warnings.join(' '));
      const zipped = await zipShapefileFiles(set_.shp, set_.companions);
      console.log('[LayerPanel] Setting importFile (zipped shapefile)');
      setImportFile(zipped);
    } else {
      if (files.length === 1 && files[0].name.toLowerCase().endsWith('.shp')) {
        setImportWarning(t('workspace.standaloneShpWarning'));
        
        e.target.value = '';
        return;
      }
      console.log('[LayerPanel] Setting importFile (regular file)');
      setImportFile(files[0]);
    }
       e.target.value = '';
  }, [store.calculationId]);

  const [ctxMenu, setCtxMenu] = useState<CtxMenuState | null>(null);

  // Delete builtin layer data (e.g., clear all Blocks)
  const handleDeleteBuiltin = useCallback(async (layerId: string) => {
    const calcId = store.calculationId;
    if (!calcId) return;
    const layerName = ctxMenu?.layerName || layerId;
    const isBoundary = layerId === 'boundary';
    if (isBoundary) {
      const dependentCount = ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas']
        .reduce((sum, id) => sum + (store.featureCounts[id] ?? 0), 0);
      if (dependentCount > 0) {
        message.warning(t('workspace.cannotDeleteBoundaryWithChildren'));
        return;
        return;
      }
    }
    Modal.confirm({
      title: t('workspace.deleteLayerDataTitle', { name: layerName }),
      content: isBoundary
        ? t('workspace.deleteBoundaryContent')
        : t('workspace.deleteLayerDataContent', { name: layerName }),
      okText: t('common.delete'),
      cancelText: t('workspace.cancel'),
      okType: 'danger',
      onOk: async () => {
        try {
          const action =
            layerId === 'sub_areas'
              ? forestApi.clearSubAreas(calcId).catch(async (e: unknown) => {
                  const detail = planLinesDetail(e);
                  if (!detail) throw e;
                  const choice = await chooseWhatHappensToPlanLines(detail, t);
                  if (!choice) throw Object.assign(new Error('cancelled'), { name: 'PlanLinesCancelled' });
                  return forestApi.clearSubAreas(calcId, choice);
                })
              : layerId === 'user_group'
                ? userGroupApi.deleteExtent(calcId)
                : layerId === 'boundary'
                  ? forestApi.deleteBoundary(calcId)
                  : forestApi.deleteBlocks(calcId);
          await action;
          message.success(t('workspace.deletedAllData', { name: layerName }));
          store.bumpGeometryVersion();
        } catch (err: any) {
          if (err?.name === 'PlanLinesCancelled') return;
          const detail = err?.response?.data?.detail;
          message.error(
            typeof detail === 'string'
              ? detail
              : detail?.message || err?.response?.data?.message || t('workspace.failedDeleteData')
          );
        }
      },
    });
  }, [store, ctxMenu?.layerName]);

  const [styleDialogLayerId, setStyleDialogLayerId] = useState<string | null>(null);
  const [styleDialogLayerType, setStyleDialogLayerType] = useState<'builtin' | 'imported' | 'raster'>('builtin');
  const [styleDialogPos, setStyleDialogPos] = useState<ContextMenuPosition>({ x: 0, y: 0 });
  const [mergingLayerId, setMergingLayerId] = useState<number | null>(null);
  const undoRedo = useContextMenuUndoRedo();

  const [rasterSearch, setRasterSearch] = useState('');

  useEffect(() => {
    let cancelled = false;
    const calcId = store.calculationId;
    if (!calcId) {
      store.setRasterCatalog([]);
      return;
    }
    const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
    const token = localStorage.getItem('access_token');
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    fetch(`${baseUrl}/api/calculations/${calcId}/raster-layers`, { headers })
      .then((res) => (res.ok ? res.json() : { layers: [] }))
      .then((data) => {
        if (cancelled) return;
        // BG-1: the user-group land-cover / biomass rasters are not part of the
        // global raster catalog — they are per-calculation tiles served from
        // `user-group-tiles/{landcover|biomass}` with trees excluded. Register
        // them on top of the catalog so LayerPanel + LegendPanel treat them
        // exactly like any other overlay.
        store.setRasterCatalog([
          ...(data.layers || []),
          {
            id: 'ug_landcover',
            name: t('workspace.userGroup.landcoverOverlay'),
            description: t('workspace.userGroup.landcoverOverlayDesc'),
            tilesPath: 'user-group-tiles',
            tileKey: 'landcover',
            extraParams: { exclude_forest: 'true' },
          },
          {
            id: 'ug_biomass',
            name: t('workspace.userGroup.biomassOverlay'),
            description: t('workspace.userGroup.biomassOverlayDesc'),
            tilesPath: 'user-group-tiles',
            tileKey: 'biomass',
            extraParams: { exclude_forest: 'true' },
          },
        ]);
      })
      .catch(() => { if (!cancelled) store.setRasterCatalog([]); });
    return () => { cancelled = true; };
  }, [store.calculationId, t]);

  type CtxMenuConfig = {
    id: string; itemType: 'builtin' | 'imported'; name: string;
    visible: boolean; count: number; locked: boolean; editable: boolean;
    purpose?: string; isDraft?: boolean;
    readOnly?: boolean; structureLocked?: boolean; labelFields?: string[];
    currentLabelField?: string | null;
    counts?: Record<string, number>; isFirst?: boolean; isLast?: boolean;
    unavailableActions?: string[];
    exportFormats?: string[];
  };

  /** M-3: the one place the menu is opened. Right-click and the row button
   *  both come through here, so neither can show a different list. */
  const openCtxMenuAt = useCallback((x: number, y: number, config: CtxMenuConfig) => {
    setCtxMenu({
      layerId: config.id,
      layerType: config.itemType,
      layerName: config.name,
      visible: config.visible,
      featureCount: config.count,
      editable: config.editable,
      locked: config.locked,
      position: { x, y },
      purpose: config.purpose,
      isDraft: config.isDraft,
      readOnly: config.readOnly,
      structureLocked: config.structureLocked,
      labelFields: config.labelFields,
      currentLabelField: config.currentLabelField,
      counts: config.counts,
      isFirst: config.isFirst,
      isLast: config.isLast,
      unavailableActions: config.unavailableActions,
      exportFormats: config.exportFormats,
    });
  }, []);

  const openCtxMenu = useCallback((e: React.MouseEvent | React.TouchEvent, config: CtxMenuConfig) => {
    e.preventDefault();
    const x = 'clientX' in e ? e.clientX : e.touches[0].clientX;
    const y = 'clientY' in e ? e.clientY : e.touches[0].clientY;
    openCtxMenuAt(x, y, config);
  }, [openCtxMenuAt]);

  const closeCtxMenu = useCallback(() => setCtxMenu(null), []);

  /** Attribute keys an imported layer can be labelled by, from its first feature. */
  const importedLabelFields = useCallback((layerId: number): string[] => {
    const features = store.importedLayerFeatures[layerId] ?? [];
    return features.length > 0 ? Object.keys(features[0].properties || {}).sort() : [];
  }, [store.importedLayerFeatures]);

  /** M-4: what an imported row cannot do. The structural commands belong to
   *  built-in layers only, and the builder omits them for `kind: 'imported'`
   *  anyway — this covers the handlers this host may not have been given. */
  const importedUnavailable = useCallback((): string[] => (
    onPolygonFromPoints ? [] : ['polygon_from_points']
  ), [onPolygonFromPoints]);
  const touchTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const touchTargetRef = useRef<{ id: string; itemType: 'builtin' | 'imported'; name: string; visible: boolean; count: number; locked: boolean; editable: boolean; purpose?: string; isDraft?: boolean }>(undefined);

  const onLayerTouchStart = useCallback((e: React.TouchEvent, cfg: CtxMenuState) => {
    touchTimerRef.current = setTimeout(() => {
      const pos = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      setCtxMenu({ ...cfg, position: pos });
    }, 500);
  }, []);

  const onLayerTouchMove = useCallback(() => {
    clearTimeout(touchTimerRef.current);
  }, []);

  const onLayerTouchEnd = useCallback(() => {
    clearTimeout(touchTimerRef.current);
  }, []);

  // RS-2.16/P2.5 — promote/demote an Auto-Block layer. Promotion can be
  // refused (409 blocks.promoted_layer_exists) when a different layer is
  // already the forest's real structure; that is D51's "offers to switch",
  // so a refused promote asks to confirm and retries with force=true.
  const promoteRasterLayer = useCallback(async (
    layerId: string, layerName: string, asLevel: 'blocks' | 'compartments', force = false,
  ) => {
    if (!store.calculationId) return;
    try {
      await forestApi.promoteRasterLayer(store.calculationId, layerId, asLevel, force);
      message.success(t('layerPanel.autoBlockPromoteSuccess', { name: layerName }));
      store.refreshRasterLayers(store.calculationId);
      store.bumpGeometryVersion();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const code = detail && typeof detail === 'object' ? detail.code : undefined;
      if (code === 'blocks.promoted_layer_exists' && !force) {
        Modal.confirm({
          title: t('layerPanel.autoBlockPromoteConflict'),
          okText: t('layerPanel.autoBlockPromoteSwitch'),
          onOk: () => promoteRasterLayer(layerId, layerName, asLevel, true),
        });
        return;
      }
      message.error(readDetail(detail) || t('layerPanel.autoBlockPromoteFailed'));
    }
  }, [store.calculationId, t]);

  const demoteRasterLayer = useCallback(async (layerId: string, layerName: string) => {
    if (!store.calculationId) return;
    try {
      await forestApi.demoteRasterLayer(store.calculationId, layerId);
      message.success(t('layerPanel.autoBlockDemoteSuccess', { name: layerName }));
      store.refreshRasterLayers(store.calculationId);
      store.bumpGeometryVersion();
    } catch (err: any) {
      message.error(readDetail(err?.response?.data?.detail) || t('layerPanel.autoBlockDemoteFailed'));
    }
  }, [store.calculationId, t]);

  const deleteRasterLayer = useCallback((layerId: string, layerName: string) => {
    if (!store.calculationId) return;
    const calcId = store.calculationId;
    const count = store.rasterLayerFeatures[layerId]?.length ?? 0;
    Modal.confirm({
      title: t('layerPanel.autoBlockDeleteConfirmTitle', { name: layerName }),
      content: t('layerPanel.autoBlockDeleteConfirmBody', { count }),
      okText: t('common.delete'),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await forestApi.deleteRasterLayer(calcId, layerId);
          message.success(t('layerPanel.autoBlockDeleteSuccess', { name: layerName }));
          if (store.activeRasterLayerId === layerId) store.setActiveRasterLayer(null);
          store.refreshRasterLayers(calcId);
          store.bumpGeometryVersion();
        } catch (err: any) {
          message.error(readDetail(err?.response?.data?.detail) || t('layerPanel.autoBlockDeleteFailed'));
        }
      },
    });
  }, [store.calculationId, store.activeRasterLayerId, store.rasterLayerFeatures, t]);

  // RS-2.17 sub-unit assignment: "Assign to existing block/compartment…"
  // opens a small parent-picker rather than a submenu, since the candidate
  // list is per-forest data fetched on demand, not a fixed choice set.
  const [assignParentFor, setAssignParentFor] = useState<{ id: string; name: string } | null>(null);
  const [assignParentOptions, setAssignParentOptions] = useState<
    { id: string; name: string; is_compartment: boolean; area_hectares: number }[]
  >([]);
  const [assignParentChoice, setAssignParentChoice] = useState<string | null>(null);
  const [assignParentBusy, setAssignParentBusy] = useState(false);
  // null = either kind (the generic "Assign to existing…" command); otherwise
  // restrict the picker to blocks (sub-blocks) or compartments (sub-compartments).
  const [assignParentBranch, setAssignParentBranch] = useState<'block' | 'compartment' | null>(null);

  const openAssignToParent = useCallback(async (
    layerId: string, layerName: string, branch: 'block' | 'compartment' | null = null,
  ) => {
    if (!store.calculationId) return;
    setAssignParentBranch(branch);
    setAssignParentFor({ id: layerId, name: layerName });
    setAssignParentChoice(null);
    try {
      const { parents } = await forestApi.listEligibleParentsForLayer(store.calculationId, layerId);
      setAssignParentOptions(parents);
    } catch {
      setAssignParentOptions([]);
    }
  }, [store.calculationId]);

  const confirmAssignToParent = useCallback(async () => {
    if (!store.calculationId || !assignParentFor || !assignParentChoice) return;
    setAssignParentBusy(true);
    try {
      const result = await forestApi.assignRasterLayerToParent(
        store.calculationId, assignParentFor.id, assignParentChoice,
      );
      message.success(t('layerPanel.autoBlockAssignSuccess', { name: assignParentFor.name, count: result.n_children }));
      store.bumpGeometryVersion();
      setAssignParentFor(null);
    } catch (err: any) {
      message.error(readDetail(err?.response?.data?.detail) || t('layerPanel.autoBlockAssignFailed'));
    } finally {
      setAssignParentBusy(false);
    }
  }, [store.calculationId, assignParentFor, assignParentChoice, t]);

  const openStyleDialog = useCallback((layerId: string, layerType: 'builtin' | 'imported' | 'raster' = 'builtin') => {
    setStyleDialogLayerId(layerId);
    setStyleDialogLayerType(layerType);
    setStyleDialogPos(ctxMenu?.position || { x: 200, y: 200 });
  }, [ctxMenu]);

  const closeStyleDialog = useCallback(() => setStyleDialogLayerId(null), []);

  // P1.4 — copy / paste a custom style between layers, and apply a named preset.
  const keyFor = useCallback(
    (layerId: string, layerType: 'builtin' | 'imported') => layerStyleKey(layerId, layerType, store.calculationId),
    [store.calculationId],
  );
  const handleStyleCopy = useCallback((layerId: string, layerType: 'builtin' | 'imported') => {
    const s = store.customLayerStyles[keyFor(layerId, layerType)] as CustomLayerStyle | undefined;
    if (!s) return;
    setStyleClipboard(s);
    message.success(t('layerPanel.styleCopied'));
  }, [store.customLayerStyles, keyFor, t]);
  const handleStylePaste = useCallback((layerId: string, layerType: 'builtin' | 'imported') => {
    const s = getStyleClipboard();
    if (!s) return;
    store.setCustomLayerStyle(keyFor(layerId, layerType), s);
    message.success(t('layerPanel.stylePasted'));
  }, [store, keyFor, t]);
  const handleStylePreset = useCallback((layerId: string, layerType: 'builtin' | 'imported', preset: string) => {
    const p = NAMED_STYLE_PRESETS[preset];
    if (p) store.setCustomLayerStyle(keyFor(layerId, layerType), p);
  }, [store, keyFor]);

  useEffect(() => {
    if (!openMenuId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpenMenuId(null);
    };
    const onDocDown = (e: MouseEvent) => {
      if (e.target instanceof Element && !e.target.closest('.layer-row-menu-wrap')) {
        setOpenMenuId(null);
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDocDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDocDown);
    };
  }, [openMenuId]);

  // Phase G (rule G): export sample plots (resolves design id → /sampling/{id}/points).
  const exportSamplePlots = async (format: 'csv' | 'gpx' | 'geojson' | 'kml') => {
    if (!calculationId) return;
    try {
      const designs = await samplingApi.list(calculationId);
      if (!designs || designs.length === 0) {
        message.info(t('layerPanel.noSampleDesign'));
        return;
      }
      const designId = designs[0].id;
      await downloadFromApi(
        `/api/sampling/${designId}/points`,
        `sampling_plots_${designId.substring(0, 8)}.${format}`,
        { format }
      );
    } catch (err: any) {
      message.error(err?.message || t('layerPanel.exportFormatFailed', { format: format.toUpperCase() }));
    }
  };

  // fieldbook_map_layer_plan.md P4: export the Field Book layer in its own
  // 4 real formats (no KML builder exists for it, unlike Sample Plots).
  const exportFieldbook = async (format: 'csv' | 'excel' | 'gpx' | 'geojson') => {
    if (!calculationId) return;
    try {
      await downloadFromApi(
        `/api/calculations/${calculationId}/fieldbook`,
        `fieldbook_${calculationId.substring(0, 8)}.${format === 'excel' ? 'xlsx' : format}`,
        { format }
      );
    } catch (err: any) {
      if (err?.response?.status === 404 || err?.status === 404) {
        message.info(t('layerPanel.noFieldbookToExport'));
        return;
      }
      message.error(err?.message || t('layerPanel.exportFormatFailed', { format: format.toUpperCase() }));
    }
  };

  // fieldbook_map_layer_plan.md P5: "Generate Field Book" -- same delete-then-
  // regenerate behaviour as FieldbookTab.handleGenerate, same defaults (50m
  // interpolation, elevation on) since a context-menu click has no settings
  // form (E6/E7). Refreshes every layer via bumpGeometryVersion (E6) since
  // that's the one dependency every useLayerData hook shares. Modal.confirm
  // (not window.confirm) to match handleDeleteBuiltin's established pattern.
  const generateFieldbook = async () => {
    if (!calculationId) return;
    const runGenerate = async () => {
      try {
        await fieldbookApi.delete(calculationId).catch(() => {});
        const result = await fieldbookApi.generate(calculationId, {
          interpolation_distance_meters: 50,
          extract_elevation: true,
        } as any);
        message.success(t('layerPanel.fieldbookGenerated', { count: result.total_points }));
        store.bumpGeometryVersion();
      } catch (err: any) {
        message.error(err?.response?.data?.detail || err?.message || t('layerPanel.fieldbookGenerateFailed'));
      }
    };
    const existing = await fieldbookApi.list(calculationId).catch(() => null);
    if (existing && existing.total_count > 0) {
      Modal.confirm({
        title: t('layerPanel.regenerateFieldbook'),
        content: t('fieldbook.confirmGenerate'),
        okText: t('common.confirm'),
        cancelText: t('common.cancel'),
        okType: 'danger',
        onOk: runGenerate,
      });
      return;
    }
    await runGenerate();
  };

  // fieldbook_map_layer_plan.md P9: "Delete Field Book" -- unlike Generate,
  // this does not recreate anything. Reuses the same generic
  // deleteLayerDataTitle/Content/deletedAllData/failedDeleteData keys
  // handleDeleteBuiltin uses for blocks/sub_areas/etc, parametrised with
  // Field Book's own name -- no new Modal copy needed.
  const deleteFieldbook = () => {
    if (!calculationId) return;
    const layerName = t('layer.fieldbook');
    Modal.confirm({
      title: t('workspace.deleteLayerDataTitle', { name: layerName }),
      content: t('workspace.deleteLayerDataContent', { name: layerName }),
      okText: t('common.delete'),
      cancelText: t('workspace.cancel'),
      okType: 'danger',
      onOk: async () => {
        try {
          await fieldbookApi.delete(calculationId);
          message.success(t('workspace.deletedAllData', { name: layerName }));
          store.bumpGeometryVersion();
        } catch (err: any) {
          const detail = err?.response?.data?.detail;
          message.error(
            typeof detail === 'string'
              ? detail
              : detail?.message || err?.response?.data?.message || t('workspace.failedDeleteData')
          );
        }
      },
    });
  };

  // Owner report 2026-10-02: "Delete [Sample Plots]" from the layer's own ⋮
  // context menu -- allowed only while this forest has no field inventory
  // data uploaded yet (same rule, and same reasoning, as the per-plot row
  // delete in MapWorkspace.tsx's handleDeleteSamplePlot: a crew's uploaded
  // rows match by block_name + a plot number from their own file, with no
  // FK back to the design, so deleting/renumbering plots after that data
  // exists would silently desync it). Deletes the whole design (one design
  // per calculation today, same assumption `exportSamplePlots` above and
  // the sample_plots `dataSource.fetch` in layerRegistry.ts already make).
  // Same act as the legacy Tree Mapping page's Delete (force-delete by calculation).
  const deleteStemMapping = () => {
    if (!calculationId) return;
    const layerName = t('layer.stemMapping');
    Modal.confirm({
      title: t('workspace.deleteLayerDataTitle', { name: layerName }),
      content: t('treeMapping.tab.confirmDelete'),
      okText: t('common.delete'),
      cancelText: t('workspace.cancel'),
      okType: 'danger',
      onOk: async () => {
        try {
          await inventoryApi.forceDeleteByCalculation(calculationId);
          message.success(t('workspace.deletedAllData', { name: layerName }));
          store.bumpGeometryVersion();
        } catch (err: any) {
          const detail = err?.response?.data?.detail;
          message.error(typeof detail === 'string' ? detail : detail?.message || t('workspace.failedDeleteData'));
        }
      },
    });
  };

  const deleteSamplePlots = async () => {
    if (!calculationId) return;
    let hasFieldData = false;
    try {
      await fieldInventoryApi.getByCalculation(calculationId);
      hasFieldData = true;
    } catch {
      hasFieldData = false;
    }
    if (hasFieldData) {
      Modal.error({
        title: t('workspace.deleteLayerDataTitle', { name: t('layer.samplePlots') }),
        content: t('sampling.cannotDeletePlotFieldDataExists'),
      });
      return;
    }

    const layerName = t('layer.samplePlots');
    Modal.confirm({
      title: t('workspace.deleteLayerDataTitle', { name: layerName }),
      content: t('workspace.deleteLayerDataContent', { name: layerName }),
      okText: t('common.delete'),
      cancelText: t('workspace.cancel'),
      okType: 'danger',
      onOk: async () => {
        try {
          const designs = await samplingApi.list(calculationId);
          for (const d of designs || []) {
            await samplingApi.delete(d.id);
          }
          message.success(t('workspace.deletedAllData', { name: layerName }));
          store.bumpGeometryVersion();
        } catch (err: any) {
          const detail = err?.response?.data?.detail;
          message.error(
            typeof detail === 'string'
              ? detail
              : detail?.message || err?.response?.data?.message || t('workspace.failedDeleteData')
          );
        }
      },
    });
  };

  // Owner report 2026-10-02 (rule 1, refined after follow-up: "no clickable,
  // no point will be generated" outside the boundary): "Add Sample Plot"
  // from the layer's own ⋮ menu arms click-to-place on the map (handled in
  // MapWorkspace.tsx's sample-plot draw_point effect) rather than always
  // dropping the new plot at the map centre -- the click's own lat/lng is
  // sent straight to the backend, which is the one authority on "inside the
  // boundary" (same `ST_Contains` check `handleSamplePlotMoved` relies on
  // for a drag); a click outside it is refused and no point ever appears.
  const addSamplePlot = () => {
    if (!calculationId) return;
    store.setActiveLayer('sample_plots');
    store.setToolbarMode('draw_point');
  };

  if (mode === 'layers' && isLoading) {
    return (
      <div className="layer-panel" data-testid="layer-panel" role="tree" aria-label={t('layerPanel.loadingAria')}>
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="layer-skeleton" aria-busy="true">
            <div className="skeleton-checkbox" />
            <div className="skeleton-text" style={{ width: `${60 + i * 10}px` }} />
          </div>
        ))}
      </div>
    );
  }

  if (mode === 'layers' && error) {
    return (
      <div className="layer-panel layer-panel-error" data-testid="layer-panel" role="alert">
        <p className="error-message">{error}</p>
        {onRetry && (
          <button onClick={onRetry} className="retry-btn" aria-label={t('attributeTable.retry')}>
            {t('attributeTable.retry')}
          </button>
        )}
      </div>
    );
  }

const layerConfigs: LayerItemConfig[] = [
    { id: 'boundary', label: t('layer.forestBoundary'), icon: '═', locked: resolveLock(!!store.layerLocks.boundary), hasSubLayers: false },
    { id: 'user_group', label: t('layer.userGroupBoundary'), icon: '⬡', locked: resolveLock(!!store.layerLocks.user_group), hasSubLayers: false },
    { id: 'blocks', label: t('layer.blocks'), icon: '▦', locked: resolveLock(!!store.layerLocks.blocks), hasSubLayers: false },
    { id: 'sub_blocks', label: t('layer.subBlocks'), icon: '▦', locked: resolveLock(!!store.layerLocks.sub_blocks), hasSubLayers: false },
    { id: 'compartments', label: t('layer.compartments'), icon: '▦', locked: resolveLock(!!store.layerLocks.compartments), hasSubLayers: false },
    { id: 'sub_compartments', label: t('layer.subCompartments'), icon: '▦', locked: resolveLock(!!store.layerLocks.sub_compartments), hasSubLayers: false },
    { id: 'sub_areas', label: t('layer.subAreas'), icon: '▓', locked: resolveLock(!!store.layerLocks.sub_areas), hasSubLayers: false },
    { id: 'sample_plots', label: t('layer.samplePlots'), icon: '✚', locked: false, hasSubLayers: false },
    { id: 'stem_mapping', label: t('layer.stemMapping'), icon: '♣', locked: false, hasSubLayers: false },
    {
      id: 'activity_features', label: t('layer.activityFeatures'),
      icon: '◉', locked: resolveLock(!!store.layerLocks.activity_features), hasSubLayers: true,
      subLayers: [
        { id: 'point', label: t('layer.points') },
        { id: 'line', label: t('layer.lines') },
        { id: 'polygon', label: t('layer.polygons') },
      ],
    },
    { id: 'fieldbook', label: t('layer.fieldbook'), icon: '🧭', locked: false, hasSubLayers: false },
  ];

  const layers = layerConfigs;

  // Sort on the CANONICAL registry order, not on `layerOrder[id] ?? 0`. The `?? 0`
  // fallback is what made the panel's order arbitrary: only 4 of the 11 layers
  // were ever seeded with an index, so 7 of them tied at 0 and their real
  // position came from the array literal above rather than from anywhere the
  // user could see or change. A user's move up/down still wins — it writes an
  // explicit numeric entry for the layer.
  const sortedLayers = [...layers].sort(
    (a, b) => resolveLayerOrder(store.layerOrder, a.id) - resolveLayerOrder(store.layerOrder, b.id),
  );

  return (
    <div
      className="layer-panel"
      data-testid={mode === 'layers' ? 'layer-panel' : `layer-panel-${mode}`}
      role="tree"
      aria-label={t('layerPanel.layersAria')}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept=".geojson,.json,.kml,.kmz,.gpx,.csv,.xlsx,.shp,.zip,.gpkg"
        style={{ position: 'absolute', opacity: 0, pointerEvents: 'none', width: '0.1px', height: '0.1px' }}
        onChange={onFileSelected}
        multiple
        aria-hidden="true"
      />
      {mode === 'layers' && (
        <>
          <div className="layer-panel-header">
            <div className="layer-actions">
              <button onClick={() => store.showAllLayers()} aria-label={t('layerPanel.showAllAria')} title={t('layerPanel.showAll')}>⊞</button>
              <button onClick={() => store.hideAllLayers()} aria-label={t('layerPanel.hideAllAria')} title={t('layerPanel.hideAll')}>⊟</button>
              <ForestSummaryButton />
              {/* RS-2.16/P9, owner directive 2026-10-01: ONE neutral entry
                  point, not anchored to the Blocks or Compartments row —
                  replaces the removed per-row "Auto Create" commands (see
                  layerMenu.ts). `onAutoCreate`'s `level` argument is cosmetic
                  here (the real choice happens later via "Assign layer
                  as…"/"Assign to existing block/compartment…" on the layer
                  itself), so this always passes 'blocks'. */}
              {onAutoCreate && (
                <Tooltip title={!hasGeometry ? t('layerPanel.autoBlockLayerButtonNeedsBoundary') : t('layerPanel.autoBlockLayerButton')}>
                  <button
                    className="layer-auto-block-btn"
                    onClick={() => onAutoCreate('blocks')}
                    disabled={!hasGeometry}
                    aria-label={t('layerPanel.autoBlockLayerButtonAria')}
                  >
                    <Sparkles size={14} />
                  </button>
                </Tooltip>
              )}
              <label className="label-toggle" title={t('layerPanel.toggleLabelsTitle')}>
                <input
                  type="checkbox"
                  checked={store.showLabels}
                  onChange={(e) => store.setShowLabels(e.target.checked)}
                  aria-label={t('layerPanel.labelsAria')}
                />
                <span className="label-toggle-text">{t('layerPanel.labels')}</span>
              </label>
              <label className="label-toggle" title={t('layerPanel.toggleHoverInfoTitle', { defaultValue: 'Show the forest-type card when the pointer is over a block or compartment' })}>
                <input
                  type="checkbox"
                  checked={store.showHoverInfo}
                  onChange={(e) => store.setShowHoverInfo(e.target.checked)}
                  aria-label={t('layerPanel.hoverInfoAria', { defaultValue: 'Hover info' })}
                />
                <span className="label-toggle-text">{t('layerPanel.hoverInfo', { defaultValue: 'Hover info' })}</span>
              </label>
              <button
                className="layer-refresh-btn"
                onClick={() => void store.refreshAll()}
                disabled={store.syncStatus === 'syncing' || store.dirty}
                aria-label={t('layerPanel.refreshMapData')}
                title={
                  store.syncStatus === 'syncing'
                    ? t('layerPanel.refreshSyncing')
                    : store.dirty
                      ? t('layerPanel.refreshCommitFirst')
                      : Object.keys(store.lastRefreshErrors).length > 0
                        ? t('layerPanel.refreshHadWarnings')
                        : t('layerPanel.refreshServer')
                }
              >
                <RefreshCw size={14} className={store.syncStatus === 'syncing' ? 'refresh-spin' : ''} />
              </button>
            </div>
          </div>

          {ntfpHasDesign === true && <NtfpPlotsGroup calculationId={calculationId} map={map} />}
          <MoreLayersBand calculationId={calculationId} ntfpInside={ntfpHasDesign !== true}>
            <AnalysisMapsGroup calculationId={calculationId} map={map} />
            {ntfpHasDesign !== true && <NtfpPlotsGroup calculationId={calculationId} map={map} />}
            <ReferenceLayersGroup calculationId={calculationId} map={map} />
          </MoreLayersBand>
          <div className="layer-list" role="group" aria-label={t('layerPanel.layersAria')}>
        {sortedLayers.map((config) => {
          const isActive = store.activeLayerId === config.id;
          const isVisible = store.layerVisibility[config.id] ?? isLayerVisibleByDefault(undefined, config.id);
          const isLocked = config.locked || false;
          const registryConfig = getLayerConfig(config.id as LayerTypeId);
          // Derived from the registry (not a one-off id check) so a layer
          // declared `alwaysReadOnly` — e.g. Sample Plots, Stem Mapping — never
          // needs a matching hardcoded id here to actually behave read-only.
          const isReadOnly = !!registryConfig?.alwaysReadOnly;
          const count = store.featureCounts[config.id] ?? 0;
          const subVis = store.subLayerVisibility[config.id];
          const labelFields = registryConfig?.labelFields ?? [];
          const autoLevel: 'blocks' | 'compartments' | null =
            config.id === 'blocks' || config.id === 'compartments' ? config.id : null;
          const isDivideRow = config.id === 'compartments' || config.id === 'sub_compartments';
          const blocksCount = store.featureCounts['blocks'] ?? 0;
          const compartmentsCount = store.featureCounts['compartments'] ?? 0;
          const divideSourceMissing =
            config.id === 'compartments' ? blocksCount === 0 : compartmentsCount === 0;
          const divideDisabled =
            isDivideRow &&
            (!!structureLocked || isLocked || divideSourceMissing || !onDivide);
          const divideReason = isDivideRow
            ? structureLocked
              ? t('workspace.divideReasonLocked')
              : isLocked
                ? t('workspace.divideReasonLayerLocked')
                : config.id === 'compartments'
                  ? t('workspace.divideReasonNoBlocks')
                  : t('workspace.divideReasonNoCompartments')
            : '';

          return (
            <Fragment key={config.id}>
            <div
              key={config.id}
              className={`layer-item ${isActive ? 'active' : ''}`}
              data-testid="layer-item"
              role="treeitem"
              aria-selected={isActive}
              aria-expanded={config.hasSubLayers}
              tabIndex={0}
              onKeyDown={(e) => handleLayerKeyDown(e, config.id, store, ctxMenu, setCtxMenu)}
              onContextMenu={(e) => openCtxMenu(e, {
                id: config.id, itemType: 'builtin', name: config.label,
                visible: isVisible, count, locked: isLocked, editable: isReadOnly ? false : !isLocked,
                purpose: config.id,
                readOnly: isReadOnly, structureLocked, labelFields,
                counts: store.featureCounts,
                isFirst: sortedLayers[0]?.id === config.id,
                isLast: sortedLayers[sortedLayers.length - 1]?.id === config.id,
                  currentLabelField: store.builtinLabelField[config.id] ?? null,
                  exportFormats: config.id === 'sample_plots'
                    ? ['csv', 'geojson', 'gpx', 'kml']
                    : config.id === 'fieldbook'
                      ? ['csv', 'excel', 'gpx', 'geojson']
                      : ['kml', 'gpkg'],
                unavailableActions: [
                  ...(onAddSubArea ? [] : ['add_sub_area']),
                  ...(onNewDraw ? [] : ['draw']),
                  ...(onAutoCreate ? [] : ['auto_create']),
                  ...(onImportBlockFromBoundary ? [] : ['import_from_boundary']),
                  ...(onDivide ? [] : ['divide_equal_area']),
                  ...(onAutoDivide ? [] : ['auto_divide']),
                  ...(onPolygonFromPoints ? [] : ['polygon_from_points']),
                ],

              })}
              onTouchStart={(e) => onLayerTouchStart(e, {
                layerId: config.id, layerType: 'builtin', layerName: config.label,
                visible: isVisible, featureCount: count, editable: !isLocked,
                locked: isLocked, position: { x: 0, y: 0 },
              })}
              onTouchMove={onLayerTouchMove}
              onTouchEnd={onLayerTouchEnd}
            >
              <button
                className="layer-visibility-toggle"
                onClick={() => store.toggleLayerVisibility(config.id)}
                aria-label={isVisible ? t('layerPanel.hideName', { name: config.label }) : t('layerPanel.showName', { name: config.label })}
                aria-pressed={isVisible}
              >
                <span className={`checkbox ${isVisible ? 'checked' : ''}`} aria-hidden="true">
                  {isVisible ? '☑' : '☐'}
                </span>
              </button>

              <button
                className="layer-name-btn"
                onClick={() => store.setActiveLayer(config.id as LayerTypeId)}
                aria-label={t('layerPanel.activate', { name: config.label })}
              >
                <span className="layer-icon" aria-hidden="true">
                  <LayerGlyph type={config.id as LayerTypeId} size={16} />
                </span>
                <span className="layer-name-text">
                  <span className="layer-name">{config.label}</span>
                  {count > 0 && <span className="layer-count">({count})</span>}
                  {config.id === 'user_group' && <UserGroupAnalysisChip />}
                  {(() => {
                    // the opacity control lives in the ⋮ menu; a faded layer says so here, so it never looks like a bug
                    const a = store.layerAlpha[layerStyleKey(config.id, 'builtin', store.calculationId)] ?? 1;
                    return a < 1 ? (
                      <span className="layer-alpha-badge" title={t('layerPanel.opacityBadge', { pct: Math.round(a * 100) })} data-testid={`layer-alpha-badge-${config.id}`}>
                        {Math.round(a * 100)}%
                      </span>
                    ) : null;
                  })()}
                </span>
              </button>

              <div className="layer-row-menu-wrap">
                <button
                  className={`layer-more-btn ${ctxMenu?.layerId === config.id ? 'open' : ''}`}
                  onClick={(e) => {
                    // M-3: the button no longer owns a menu of its own. It opens
                    // the SAME menu right-click does, anchored under the row —
                    // which is what makes the two openers impossible to drift.
                    e.stopPropagation();
                    if (ctxMenu?.layerId === config.id) { closeCtxMenu(); return; }
                    const row = (e.currentTarget as HTMLElement).closest('.layer-item') as HTMLElement | null;
                    const rect = (row ?? (e.currentTarget as HTMLElement)).getBoundingClientRect();
                    openCtxMenuAt(Math.round(rect.left), Math.round(rect.bottom) + 4, {
                      id: config.id, itemType: 'builtin', name: config.label,
                      visible: isVisible, count, locked: isLocked,
                      editable: isReadOnly ? false : !isLocked,
                      purpose: config.id,
                      readOnly: isReadOnly, structureLocked, labelFields,
                      counts: store.featureCounts,
                      isFirst: sortedLayers[0]?.id === config.id,
                      isLast: sortedLayers[sortedLayers.length - 1]?.id === config.id,
                      currentLabelField: store.builtinLabelField[config.id] ?? null,
                      exportFormats: config.id === 'sample_plots'
                        ? ['csv', 'geojson', 'gpx', 'kml']
                        : config.id === 'fieldbook'
                          ? ['csv', 'excel', 'gpx', 'geojson']
                          : ['kml', 'gpkg'],
                    unavailableActions: [
                      ...(onAddSubArea ? [] : ['add_sub_area']),
                      ...(onNewDraw ? [] : ['draw']),
                      ...(onAutoCreate ? [] : ['auto_create']),
                      ...(onImportBlockFromBoundary ? [] : ['import_from_boundary']),
                      ...(onDivide ? [] : ['divide_equal_area']),
                      ...(onAutoDivide ? [] : ['auto_divide']),
                      ...(onPolygonFromPoints ? [] : ['polygon_from_points']),
                    ],
                    });
                  }}
                  aria-label={t('layerPanel.actionsFor', { name: config.label })}
                  aria-haspopup="menu"
                  aria-expanded={ctxMenu?.layerId === config.id}
                >
                  <MoreVertical size={15} />
                </button>

              </div>

              {config.hasSubLayers && config.subLayers && (
                <div className="sub-layers" role="group" aria-label={t('layerPanel.subLayers', { name: config.label })}>
                  {config.subLayers.map((sl) => {
                    const slVisible = subVis?.[sl.id] ?? true;
                    return (
                      <div key={sl.id} className="sub-layer-item" role="treeitem">
                        <button
                          className={`sub-layer-toggle${slVisible ? ' on' : ''}`}
                          onClick={() => store.toggleSubLayer(config.id, sl.id)}
                          aria-pressed={slVisible}
                          aria-label={slVisible ? t('layerPanel.hideName', { name: sl.label }) : t('layerPanel.showName', { name: sl.label })}
                          title={slVisible ? t('layerPanel.hideName', { name: sl.label }) : t('layerPanel.showName', { name: sl.label })}
                        >
                          <SubLayerSymbol kind={sl.id} />
                          <span className="sub-layer-name">{sl.label}</span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
              </div>

              {config.id === 'user_group' && (
                <UserGroupAnalysisSection calculationId={store.calculationId} />
              )}

              {config.id === 'stem_mapping' && <StemMappingLegendSection />}
            </Fragment>
          );
        })}
        {/* Auto-Block layers (RS-2.16/P9, owner directive 2026-10-01): same
            row markup and position as a built-in layer — own name, own
            geometry, own attribute column — not a separate section. A raster
            layer's id is a UUID, not a `LayerTypeId`, so it keeps its own
            active-layer state (`activeRasterLayerId`) and a lightweight menu
            (Promote/Demote/Export) rather than going through
            `LayerContextMenu`, which is typed to the closed builtin id set. */}
        {store.rasterLayers.map((l) => {
          const isActive = store.activeRasterLayerId === l.id;
          const badge = l.promoted_as === 'blocks'
            ? t('layerPanel.autoBlockLayerPromoted')
            : l.promoted_as === 'compartments'
              ? t('layerPanel.autoBlockLayerPromotedCompartments')
              : t('layerPanel.autoBlockLayerTrial');
          const count = store.rasterLayerFeatures[l.id]?.length ?? 0;
          const rasterLocked = !!store.layerLocks[`raster:${l.id}`];
          const rasterMenuHandlers: Record<string, () => void> = {
            zoom: () => {
              const feats = store.rasterLayerFeatures[l.id];
              if (!map || !feats || feats.length === 0) return;
              try {
                const bounds = L.geoJSON(feats as any).getBounds();
                zoomToLayerBounds(map, bounds);
              } catch { /* same best-effort shape as the builtin zoom handler */ }
            },
            visibility: () => store.toggleLayerVisibility(`raster:${l.id}`),
            attributes: () => {
              store.setActiveRasterLayer(l.id);
              if (store.calculationId && !store.rasterLayerFeatures[l.id]) {
                store.fetchRasterLayerFeatures(store.calculationId, l.id);
              }
            },
            export: () => {
              const fc = { type: 'FeatureCollection', features: store.rasterLayerFeatures[l.id] ?? [] };
              const blob = new Blob([JSON.stringify(fc, null, 2)], { type: 'application/geo+json' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = `${l.name.replace(/[^a-z0-9_-]+/gi, '_')}.geojson`;
              a.click();
              URL.revokeObjectURL(url);
            },
            'assign:blocks': () => promoteRasterLayer(l.id, l.name, 'blocks'),
            'assign:compartments': () => promoteRasterLayer(l.id, l.name, 'compartments'),
            'assign:sub_blocks': () => openAssignToParent(l.id, l.name, 'block'),
            'assign:sub_compartments': () => openAssignToParent(l.id, l.name, 'compartment'),
            assign_to_parent: () => openAssignToParent(l.id, l.name),
            demote: () => demoteRasterLayer(l.id, l.name),
            remove_layer: () => deleteRasterLayer(l.id, l.name),
            lock: () => store.setLayerLock(`raster:${l.id}`, !rasterLocked),
            // Owner reminder 2026-10-01: raster layers were missing "Style…".
            // Owner report 2026-10-02: passing 'builtin' here (reusing
            // `layerStyleKey`'s storage key unchanged, which was fine) ALSO
            // made `LayerStyleDialog`'s feature-loading effect try to look
            // this UUID up in the static `LAYER_REGISTRY` via
            // `getLayerConfig` -- always a miss, so the Categorical/
            // Graduated field dropdown was permanently empty for every
            // raster layer. Now passes the dedicated 'raster' type so the
            // dialog reads `store.rasterLayerFeatures` instead.
            style: () => openStyleDialog(l.id, 'raster'),
          };
          const menuItems = buildLayerMenu({
            layerId: l.id,
            kind: 'raster',
            layerName: l.name,
            visible: store.layerVisibility[`raster:${l.id}`] ?? true,
            labelsShown: false,
            featureCount: count,
            editable: true,
            readOnly: false,
            locked: rasterLocked,
            promotedAs: l.promoted_as,
          }).map((item) => ({
            key: item.id,
            label: t(item.labelKey, item.labelParams),
            disabled: item.disabled,
            title: item.disabledReasonKey ? t(item.disabledReasonKey, item.disabledReasonParams) : undefined,
            danger: item.danger,
            onClick: rasterMenuHandlers[item.id] ? () => rasterMenuHandlers[item.id]() : undefined,
            children: item.submenu?.map((sub) => ({
              key: sub.id,
              label: t(sub.labelKey, sub.labelParams),
              disabled: sub.disabled,
              onClick: rasterMenuHandlers[sub.id] ? () => rasterMenuHandlers[sub.id]() : undefined,
            })),
          }));
          const rasterVisKey = `raster:${l.id}`;
          const isVisible = store.layerVisibility[rasterVisKey] ?? true;
          return (
            <div
              key={l.id}
              className={`layer-item ${isActive ? 'active' : ''}`}
              data-testid="layer-item"
              role="treeitem"
              aria-selected={isActive}
              tabIndex={0}
            >
              <button
                className="layer-visibility-toggle"
                onClick={() => store.toggleLayerVisibility(rasterVisKey)}
                aria-label={isVisible ? t('layerPanel.hideName', { name: l.name }) : t('layerPanel.showName', { name: l.name })}
                aria-pressed={isVisible}
              >
                <span className={`checkbox ${isVisible ? 'checked' : ''}`} aria-hidden="true">
                  {isVisible ? '☑' : '☐'}
                </span>
              </button>
              <button
                className="layer-name-btn"
                onClick={() => {
                  store.setActiveRasterLayer(l.id);
                  if (store.calculationId && !store.rasterLayerFeatures[l.id]) {
                    store.fetchRasterLayerFeatures(store.calculationId, l.id);
                  }
                }}
                aria-label={t('layerPanel.activate', { name: l.name })}
              >
                <span className="layer-icon" aria-hidden="true">🧩</span>
                <span className="layer-name-text">
                  <span className="layer-name">{l.name}</span>
                  {count > 0 && <span className="layer-count">({count})</span>}
                </span>
              </button>
              <AntTag color={l.promoted_as ? 'green' : 'default'} style={{ marginLeft: 4, marginRight: 4 }}>
                {badge}
              </AntTag>
              <div className="layer-row-menu-wrap">
                <Dropdown menu={{ items: menuItems }} trigger={['click']}>
                  <button
                    type="button"
                    className="layer-more-btn"
                    aria-label={t('layerPanel.autoBlockLayerActionsAria', { name: l.name })}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <MoreVertical size={15} />
                  </button>
                </Dropdown>
              </div>
            </div>
          );
        })}
      </div>
    </>
  )}

      {mode === 'basemap' && (
        <BaseMapSelector
          options={store.baseMapOptions}
          active={store.activeBaseMap}
          onSelect={store.setActiveBaseMap}
        />
      )}

      {mode === 'imported' && (
        <div className="imported-layers-header">
          <button
            ref={addLayerBtnRef}
            type="button"
            className="add-layer-btn"
            onClick={openAddLayerMenu}
            aria-haspopup="menu"
            aria-expanded={addLayerMenu != null}
            aria-label={t('layerPanel.addLayerAria')}
            title={t('layerPanel.addLayerTitle')}
          >
            {t('layerPanel.addLayer')}
          </button>
          {addLayerMenu && (
            <AddLayerMenu
              position={addLayerMenu}
              onImportFile={() => { setFixedImportPurpose(null); openFilePicker(); }}
              onImportWithPurpose={handleMenuImport}
              onDrawOnMap={handleDrawOnMap}
              onClose={closeAddLayerMenu}
            />
          )}
          {purposePickerOpen && store.calculationId && (
            <PurposePickerDialog
              calculationId={store.calculationId}
              restrictToGeometry={!hasGeometry}
              onCreated={closePurposePicker}
              onCancel={closePurposePicker}
            />
          )}
        </div>
      )}

      {mode === 'imported' && store.importedLayers.length > 0 && (
        <div className="imported-layers-section" role="group" aria-label={t('layerPanel.importedLayers')}>
          <h3 className="imported-layers-title">{t('layerPanel.importedCount', { count: store.importedLayers.length })}</h3>
          {store.importedLayers.map((l) => {
            const isActive = store.activeImportedLayerId === l.id;
            const isLocked = !!store.layerLocks[`imported:${l.id}`];
            return (
              <div
                key={l.id}
                className={`layer-item imported-layer-item ${isActive ? 'active' : ''} ${l.isDraft ? 'draft-active-row' : ''}`}
                role="treeitem"
                aria-selected={isActive}
                onContextMenu={(e) => openCtxMenu(e, {
                  id: String(l.id), itemType: 'imported', name: l.name,
                  visible: l.visible, count: l.featureCount,
                  locked: isLocked, editable: !isLocked,
                  purpose: l.purpose, isDraft: l.isDraft,
                  labelFields: importedLabelFields(l.id),
                  currentLabelField: store.labelField[l.id] ?? defaultImportedLabelField(store.importedLayerFeatures[l.id] ?? []),
                  counts: store.featureCounts,
                  unavailableActions: importedUnavailable(),
                })}
                onTouchStart={(e) => onLayerTouchStart(e, {
                  layerId: String(l.id), layerType: 'imported', layerName: l.name,
                  visible: l.visible, featureCount: l.featureCount,
                  editable: !isLocked, locked: isLocked,
                  position: { x: 0, y: 0 },
                  purpose: l.purpose, isDraft: l.isDraft,
                })}
                onTouchMove={onLayerTouchMove}
                onTouchEnd={onLayerTouchEnd}
              >
                <button
                  className="layer-visibility-toggle"
                  onClick={() => store.setImportedLayerVisibility(l.id, !l.visible)}
                  aria-label={l.visible ? t('layerPanel.hideName', { name: l.name }) : t('layerPanel.showName', { name: l.name })}
                >
                  <span className={`checkbox ${l.visible ? 'checked' : ''}`} aria-hidden="true">
                    {l.visible ? '☑' : '☐'}
                  </span>
                </button>
                <button
                  className="layer-name-btn imported-layer-name"
                  onClick={() => {
                    if (isActive) {
                      store.setActiveImportedLayer(null);
                    } else {
                      store.setActiveImportedLayer(l.id);
                    }
                  }}
                  aria-label={t('layerPanel.activate', { name: l.name })}
                  title={l.name}
                >
                  <span className="layer-name">{l.name}</span>
                  {l.isDraft && <span className="draft-label" aria-label={t('layerPanel.draft')}>{t('layerPanel.draft')}</span>}
                  {isActive && <span className="active-indicator" aria-label={t('layerPanel.activeLayer')}>◉</span>}
                  {l.isDraft && l.draftStatus === 'validation_failed' && (
                    <span className="layer-draft-badge badge-error" title={t('layerPanel.validationFailed')}>⚠</span>
                  )}
                  {l.isDraft && l.draftStatus === 'active' && store.digitizeSyncState === 'error' && (
                    <span className="layer-draft-badge badge-warn" title={t('layerPanel.syncPending')}>⟳</span>
                  )}
                </button>
                <LabelFieldPicker
                  layerLabel={l.name}
                  currentField={store.labelField[l.id] ?? null}
                  fields={(() => {
                    const features = store.importedLayerFeatures[l.id] ?? [];
                    return features.length > 0
                      ? Object.keys(features[0].properties || {}).sort()
                      : [];
                  })()}
                  onSelect={(field) => {
                    const current = store.labelField[l.id] ?? null;
                    if (current === field) return;
                    const op = createLabelFieldOperation(String(l.id), current, field, 'user');
                    undoRedo.pushAndExecute(op, () => {
                      store.setLabelField(l.id, field);
                    });
                  }}
                />
                <span className="layer-count">({l.featureCount})</span>

                {/* M-4: imported rows had no ⋮ at all, so a user who learned
                    "the actions live under the three dots" found nothing here.
                    Same button, same menu, same list as a built-in row. */}
                <div className="layer-row-menu-wrap">
                  <button
                    className={`layer-more-btn ${ctxMenu?.layerId === String(l.id) ? 'open' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (ctxMenu?.layerId === String(l.id)) { closeCtxMenu(); return; }
                      const row = (e.currentTarget as HTMLElement).closest('.layer-item') as HTMLElement | null;
                      const rect = (row ?? (e.currentTarget as HTMLElement)).getBoundingClientRect();
                      openCtxMenuAt(Math.round(rect.left), Math.round(rect.bottom) + 4, {
                        id: String(l.id), itemType: 'imported', name: l.name,
                        visible: l.visible, count: l.featureCount,
                        locked: isLocked, editable: !isLocked,
                        purpose: l.purpose, isDraft: l.isDraft,
                        labelFields: importedLabelFields(l.id),
                        currentLabelField: store.labelField[l.id] ?? defaultImportedLabelField(store.importedLayerFeatures[l.id] ?? []),
                        counts: store.featureCounts,
                        unavailableActions: importedUnavailable(),
                      });
                    }}
                    aria-label={t('layerPanel.actionsFor', { name: l.name })}
                    aria-haspopup="menu"
                    aria-expanded={ctxMenu?.layerId === String(l.id)}
                  >
                    <MoreVertical size={15} />
                  </button>
                </div>
                {!l.purpose && (
                  <span className="layer-unassigned-badge" aria-label={t('layerPanel.unassignedLayer')}>
                    {t('layerPanel.unassignedLayer')}
                  </span>
                )}
                <button
                  className={`layer-lock-btn ${isLocked ? 'locked' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    store.toggleLayerLock(`imported:${l.id}`);
                  }}
                  aria-label={isLocked ? t('layerPanel.unlockName', { name: l.name }) : t('layerPanel.lockName', { name: l.name })}
                  title={isLocked ? t('layerPanel.unlockLayerTitle') : t('layerPanel.lockLayerTitle')}
                >
                  {isLocked ? '🔒' : '🔓'}
                </button>
                {!l.isDraft && l.purpose === 'blocks' && (
                  <button
                    className="draft-action-btn layer-merge-btn"
                    onClick={(e) => { e.stopPropagation(); handleMergeIntoBoundary(l); }}
                    disabled={mergingLayerId === l.id}
                    aria-label={t('layerPanel.mergeToBoundaryAria', { name: l.name })}
                    title={t('layerPanel.mergeToBoundaryTitle')}
                  >
                    {mergingLayerId === l.id ? t('layerPanel.merging') : t('layerPanel.mergeToBoundary')}
                  </button>
                )}
                {l.isDraft && (
                  <div className="draft-layer-actions">
                    {l.draftStatus === 'validation_failed' && (
                      <button
                        className="draft-action-btn draft-fix-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          store.setActiveImportedLayer(l.id);
                          store.setActiveDigitizeContext({ mode: 'draft', layer: l });
                          store.setToolbarMode(firstDrawModeForPurpose(l.purpose));
                        }}
                        aria-label={t('layerPanel.reviewFixAria', { name: l.name })}
                        title={t('layerPanel.reviewFixTitle')}
                      >
                        {t('layerPanel.reviewFix')}
                      </button>
                    )}
                    <button
                      className="draft-action-btn draft-finish-btn"
                      onClick={(e) => { e.stopPropagation(); handleFinishSave(l); }}
                      disabled={store.digitizeSyncState === 'syncing'}
                      aria-label={t('layerPanel.finishSaveAria', { name: l.name })}
                      title={t('layerPanel.finishSaveTitle')}
                    >
                      {store.digitizeSyncState === 'syncing' ? t('layerPanel.saving') : t('layerPanel.finishSave')}
                    </button>
                    <button
                      className="draft-action-btn draft-discard-btn"
                      onClick={(e) => { e.stopPropagation(); handleDiscard(l); }}
                      disabled={store.digitizeSyncState === 'syncing'}
                      aria-label={t('layerPanel.discardAria', { name: l.name })}
                      title={t('layerPanel.discardTitle')}
                    >
                      {t('layerPanel.discard')}
                    </button>
                  </div>
                )}
                <div className="layer-reorder">
                  <button onClick={() => store.reorderImportedLayer(l.id, 'up')} className="reorder-btn" aria-label={t('layerPanel.moveUpSmall')}>▲</button>
                  <button onClick={() => store.reorderImportedLayer(l.id, 'down')} className="reorder-btn" aria-label={t('layerPanel.moveDownSmall')}>▼</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {mode === 'imported' && store.importedLayers.length === 0 && (
        hasGeometry ? (
          <div className="imported-empty">{t('layerPanel.noImportedLayers')}</div>
        ) : (
          <div className="imported-empty imported-empty-purpose" role="note" data-testid="imported-empty-purpose">
            <span className="imported-empty-title">{t('layerPanel.addGeometryWithPurpose')}</span>
            <span className="imported-empty-text">{t('layerPanel.addGeometryEmptyText')}</span>
          </div>
        )
      )}

      {mode === 'raster' && (
      <div className="raster-layers-section" role="group" aria-label={t('layerPanel.rasterLayers')}>
        <input
          type="text"
          className="raster-search"
          placeholder={t('layerPanel.searchRaster')}
          value={rasterSearch}
          onChange={(e) => setRasterSearch(e.target.value)}
          aria-label={t('layerPanel.searchRasterAria')}
        />
        <div className="raster-layer-list">
          {store.rasterCatalog
            .filter((r) =>
              rasterSearch.trim()
                ? `${r.name} ${r.description || ''}`.toLowerCase().includes(rasterSearch.trim().toLowerCase())
                : true,
            )
            .map((r) => {
              const active = store.activeRasterLayers.includes(r.id);
              return (
                <div key={r.id} className="raster-layer-item">
                  <button
                    className="raster-toggle"
                    onClick={() => store.toggleRasterLayer(r.id)}
                    aria-pressed={active}
                    title={r.description}
                  >
                    <span className={`checkbox ${active ? 'checked' : ''}`} aria-hidden="true">
                      {active ? '☑' : '☐'}
                    </span>
                    <span className="raster-name">{r.name}</span>
                    <span className="raster-meta">
                      {[r.resolution, r.year].filter(Boolean).join(' · ')}
                    </span>
                  </button>
                </div>
              );
            })}
          {store.rasterCatalog.length > 0 && rasterSearch.trim() && (
            <div className="raster-no-results">{t('layerPanel.rasterNoMatch', { query: rasterSearch })}</div>
          )}
          {store.rasterCatalog.length === 0 && (
            <div className="raster-no-results">{t('layerPanel.rasterNone')}</div>
          )}
        </div>
        <div className="raster-opacity-row">
          <span className="raster-opacity-label">{t('layerPanel.opacity')}</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={store.rasterOpacity}
            onChange={(e) => store.setRasterOpacity(Number(e.target.value))}
            className="raster-opacity-slider"
            aria-label={t('layerPanel.rasterOpacityAria')}
          />
        </div>
</div>
      )}

      {importWarning && (
        <div className="import-warning" role="alert" style={{ padding: '8px', margin: '4px 8px', background: '#fff3cd', border: '1px solid #ffc107', borderRadius: '4px', fontSize: '12px', color: '#856404' }}>
          <span>{importWarning}</span>
          <button onClick={() => setImportWarning(null)} style={{ float: 'right', border: 'none', background: 'none', cursor: 'pointer', fontWeight: 'bold' }} aria-label={t('layerPanel.dismissWarning')}>&times;</button>
        </div>
      )}

      {importFile && store.calculationId && (
        <ImportPurposeDialog
          file={importFile}
          calculationId={store.calculationId}
          restrictToGeometry={!hasGeometry}
          onBoundarySaved={() => store.bumpGeometryVersion()}
          onComplete={handleImportComplete}
          onCancel={() => { setImportFile(null); setFixedImportPurpose(null); }}
          fixedPurpose={fixedImportPurpose ?? undefined}
        />
      )}

      {ctxMenu && (
        <LayerContextMenu
          layerId={ctxMenu.layerId}
          layerType={ctxMenu.layerType}
          layerName={ctxMenu.layerName}
          visible={ctxMenu.visible}
          labelsShown={store.showLabels}
          featureCount={ctxMenu.featureCount}
          editable={ctxMenu.editable}
          locked={ctxMenu.locked}
          position={ctxMenu.position}
          onClose={closeCtxMenu}
          map={map}
          onStyleDialog={openStyleDialog}
          onStyleCopy={handleStyleCopy}
          onStylePaste={handleStylePaste}
          onStylePreset={handleStylePreset}
          hasCustomStyle={!!store.customLayerStyles[keyFor(ctxMenu.layerId, ctxMenu.layerType)]}
          hasStyleClipboard={getStyleClipboard() != null}
          clipboardMenu={featureClipboard ? {
            selectedCount: featureClipboard.selectedCountFor(clipKeyOf(ctxMenu.layerId, ctxMenu.layerType)),
            clipboardCount: featureClipboard.clipboardCount,
            paste: featureClipboard.pasteStateFor(clipKeyOf(ctxMenu.layerId, ctxMenu.layerType)),
          } : undefined}
          onCopyFeatures={featureClipboard
            ? (id, type) => featureClipboard.copy({ layerKey: clipKeyOf(id, type) })
            : undefined}
          onPasteFeatures={featureClipboard
            ? (id, type) => featureClipboard.paste(clipKeyOf(id, type))
            : undefined}
          onPasteAsLayer={featureClipboard?.pasteAsLayer}
          zoomToLayer={zoomToLayer}
          purpose={ctxMenu.purpose}
          isDraft={ctxMenu.isDraft}
          onAppend={handleAppend}
          onImportLayer={handleContextImport}
          onDeleteBuiltin={handleDeleteBuiltin}
          onAddSubArea={onAddSubArea}
          onUserGroupAutoBuffer={handleUserGroupAutoBuffer}
          onUserGroupAnalysis={onUserGroupAnalysis}
          onGenerateFieldbook={generateFieldbook}
          onDeleteFieldbook={deleteFieldbook}
          onDeleteSamplePlots={deleteSamplePlots}
          onDeleteStemMapping={deleteStemMapping}
          onAddSamplePlot={addSamplePlot}
          onPolygonFromPoints={onPolygonFromPoints}
          readOnly={ctxMenu.readOnly}
          structureLocked={ctxMenu.structureLocked}
          labelFields={ctxMenu.labelFields}
          currentLabelField={ctxMenu.currentLabelField}
          counts={ctxMenu.counts}
          isFirst={ctxMenu.isFirst}
          isLast={ctxMenu.isLast}
          unavailableActions={ctxMenu.unavailableActions}
          exportFormats={ctxMenu.exportFormats}
          onExportFormat={
            // Only Sample Plots and Field Book have a real multi-format
            // exporter. Every other layer declares KML alone and falls
            // through to the generic path, so no menu item can silently do
            // nothing. M-8 generalises this.
            ctxMenu.layerId === 'sample_plots'
              ? (_id, format) => exportSamplePlots(format as 'csv' | 'gpx' | 'geojson' | 'kml')
              : ctxMenu.layerId === 'fieldbook'
                ? (_id, format) => exportFieldbook(format as 'csv' | 'excel' | 'gpx' | 'geojson')
                : undefined
          }
          onAutoCreate={onAutoCreate}
          onCreateSamplePlots={onCreateSamplePlots}
          onImportStemMapping={onImportStemMapping}
          onImportBlockFromBoundary={onImportBlockFromBoundary}
          onNewDraw={onNewDraw}
          onDivide={onDivide}
          onAutoDivide={onAutoDivide}
          onToggleLock={(id) => store.toggleLayerLock(id)}
          onMove={(id, delta) => (delta < 0 ? store.moveLayerUp(id) : store.moveLayerDown(id))}
          onSetLabelField={(id, field) => {
            // Preserved from the deleted row menu: changing the label field is
            // an undoable operation, not a plain setter. Built-in and imported
            // layers keep separate label-field state and separate setters, so
            // the menu has to route to the right one.
            const imported = ctxMenu.layerType === 'imported';
            const current = imported
              ? (store.labelField[Number(id)] ?? null)
              : (store.builtinLabelField[id] ?? null);
            if (current === field) return;
            const op = createLabelFieldOperation(id, current, field, 'user');
            undoRedo.pushAndExecute(op, () => {
              if (imported) store.setLabelField(Number(id), field);
              else store.setBuiltinLabelField(id, field);
            });
          }}
        />
      )}

      {styleDialogLayerId && (
        <LayerStyleDialog
          visible
          layerId={styleDialogLayerId}
          layerType={styleDialogLayerType}
          position={styleDialogPos}
          onClose={closeStyleDialog}
        />
      )}

      {/* RS-2.17 sub-unit assignment: "Assign to existing block/compartment…" */}
      <Modal
        open={!!assignParentFor}
        title={assignParentFor ? t('layerPanel.autoBlockAssignParentModalTitle', { name: assignParentFor.name }) : ''}
        onCancel={() => setAssignParentFor(null)}
        onOk={confirmAssignToParent}
        okText={t('layerPanel.autoBlockAssignParentConfirm')}
        okButtonProps={{ disabled: !assignParentChoice, loading: assignParentBusy }}
      >
        <Select
          style={{ width: '100%' }}
          placeholder={t('layerPanel.autoBlockAssignParentPlaceholder')}
          value={assignParentChoice ?? undefined}
          onChange={(v) => setAssignParentChoice(v)}
          notFoundContent={t('layerPanel.autoBlockAssignParentNone')}
          options={assignParentOptions
            .filter((p) => assignParentBranch === null || p.is_compartment === (assignParentBranch === 'compartment'))
            .map((p) => ({
            value: p.id,
            label: `${p.name} (${p.is_compartment ? t('layerPanel.autoBlockLayerPromotedCompartments') : t('layerPanel.autoBlockLayerPromoted')}, ${p.area_hectares.toFixed(2)} ha)`,
          }))}
        />
      </Modal>

    </div>
  );
}

function LabelFieldPicker({
  currentField, fields, layerLabel, onSelect,
}: {
  currentField: string | null;
  fields: string[];
  layerLabel: string;
  onSelect: (field: string | null) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const active = currentField != null;

  return (
    <div className="layer-label-picker" ref={ref} onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        className={`layer-label-btn ${active ? 'active' : ''}`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        aria-label={t('layerPanel.labelFieldAria', { name: layerLabel })}
        title={active ? t('layerPanel.labelFieldTitle', { field: currentField }) : t('layerPanel.labelFieldTitleDefault')}
        aria-expanded={open}
        aria-haspopup="listbox"
      >
        🏷
      </button>
      {open && (
        <div className="layer-label-popup" role="listbox" aria-label={t('layerPanel.labelFieldAria', { name: layerLabel })}>
          <button
            type="button"
            className={`layer-label-option ${currentField == null ? 'selected' : ''}`}
            onClick={() => {
              onSelect(null);
              setOpen(false);
            }}
            role="option"
            aria-selected={currentField == null}
          >
            <span className="opt-check">{currentField == null ? '✓' : ''}</span>
            {t('layerPanel.labelDefault')}
          </button>
          {fields.map((f) => (
            <button
              type="button"
              key={f}
              className={`layer-label-option ${currentField === f ? 'selected' : ''}`}
              onClick={() => {
                onSelect(f);
                setOpen(false);
              }}
              role="option"
              aria-selected={currentField === f}
            >
              <span className="opt-check">{currentField === f ? '✓' : ''}</span>
              {f}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function handleLayerKeyDown(
  e: React.KeyboardEvent,
  layerId: string,
  store: any,
  ctxMenu: any,
  setCtxMenu: any,
) {
  switch (e.key) {
    case 'Enter':
    case ' ':
      e.preventDefault();
      store.setActiveLayer(layerId);
      break;
    case 'ArrowUp':
      e.preventDefault();
      store.moveLayerUp(layerId);
      break;
    case 'ArrowDown':
      e.preventDefault();
      store.moveLayerDown(layerId);
      break;
    case 'ContextMenu':
    case 'F10':
      e.preventDefault();
      if (e.shiftKey || e.key === 'ContextMenu') {
        const rect = (e.target as HTMLElement).getBoundingClientRect();
        setCtxMenu({
          layerId,
          layerType: 'builtin',
          layerName: layerId,
          visible: store.layerVisibility[layerId] ?? true,
          featureCount: store.featureCounts[layerId] ?? 0,
          editable: true,
          locked: false,
          position: { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 },
        });
      }
      break;
  }
}

function BaseMapSelector({
  options, active, onSelect,
}: {
  options: { id: string; label: string; labelKey?: string }[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const t = useT();
  return (
    <div className="base-map-selector" role="radiogroup" aria-label={t('layerPanel.baseMapAria')}>
      <div className="base-map-options">
        {options.map((opt) => (
          <button
            key={opt.id}
            className={`base-map-btn ${active === opt.id ? 'active' : ''}`}
            onClick={() => onSelect(opt.id)}
            role="radio"
            aria-checked={active === opt.id}
            aria-label={t(opt.labelKey ?? opt.label)}
          >
            <span className="bm-indicator" aria-hidden="true">
              {active === opt.id ? '▪' : '·'}
            </span>
            <span className="bm-label">{t(opt.labelKey ?? opt.label)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}


