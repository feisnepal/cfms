import { useEffect, useLayoutEffect, useRef, useCallback, useState } from 'react';
import { createPortal } from 'react-dom';
import type L from 'leaflet';
import type { GeoJSON } from 'geojson';
import { message } from 'antd';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useContextMenuUndoRedo } from '../hooks/useContextMenuUndoRedo';
import { getLayerConfig } from '../lib/layerRegistry';
import type { LayerTypeId } from '../lib/layerRegistry';
import { geojsonToKml } from '../lib/geojsonToKml';
import { downloadFromApi } from '../utils/download';
import { buildExportFeatures, type ExportFeature } from '../lib/layerExportView';
import { purposeColumnsForFeatures } from '../lib/purposeColumns';
import { isUnitLayerType, mergeUnitLayerProps } from '../lib/unitLayerMerge';
import type { ColumnDef } from '../lib/layerRegistry';
import { geometryTypesForPurpose } from '../lib/purposeGeometryRules';
import { useT } from '../i18n/hooks';
import { fireLineApi, riverBankApi, type StripApi } from '../services/api';
import { errorMessage } from '../lib/fireLines';
import {
  createVisibilityOperation,
  createLabelsOperation,
  createRenameOperation,
  createDuplicateOperation,
  createDeleteOperation,
} from '../lib/operationFactories';
import { buildLayerMenu, groupLayerMenu, tuckAway, type LayerMenuItem, type LayerMenuContext } from '../lib/layerMenu';
import { OpacitySpinner } from './OpacitySpinner';
import { layerStyleKey } from '../lib/layerStyles';
import { ANALYSIS_MAPS, isSfmMap, isUnitLayerId, type AnalysisMapId } from '../lib/analysisMaps';

export interface ContextMenuPosition {
  x: number;
  y: number;
}

/** Which block of the Advanced fly-out a row belongs to (style, copy/paste, export, the rest). */
const advancedSection = (id: string) =>
  id.startsWith('style') ? 1 : id === 'copy_features' || id.startsWith('paste') ? 2 : id.startsWith('export') ? 3 : 4;

export interface ContextMenuAction {
  id: string;
  label: string;
  icon: string;
  shortcut?: string;
  disabled?: boolean;
  disabledReason?: string;
  danger?: boolean;
  divider?: boolean;
  /** Choice-style item (a label field), rendered as menuitemradio. */
  checked?: boolean;
  /** Mandatory data this command enters: done / missing (red) / optional. */
  status?: 'done' | 'missing' | 'optional';
  /**
   * Child actions shown in a fly-out rather than flattened into the column.
   * Style presets, label-by-field and export formats each become one row with a
   * ▸ instead of N inline rows — the menu was overflowing tall viewports.
   */
  submenu?: ContextMenuAction[];
  /** A number row (opacity %): rendered as a control, never closes the menu. */
  spinner?: { value: number; min: number; max: number; step: number };
  onSpin?: (value: number) => void;
  handler: () => void;
}

interface LayerContextMenuProps {
  layerId: string;
  layerType: 'builtin' | 'imported';
  layerName: string;
  visible: boolean;
  labelsShown: boolean;
  featureCount: number;
  editable: boolean;
  locked: boolean;
  position: ContextMenuPosition;
  onClose: () => void;
  map: L.Map | null;
  onStyleDialog?: (layerId: string, layerType: 'builtin' | 'imported') => void;
  /** P1.4 — copy / paste a custom style and apply a named preset. */
  onStyleCopy?: (layerId: string, layerType: 'builtin' | 'imported') => void;
  onStylePaste?: (layerId: string, layerType: 'builtin' | 'imported') => void;
  onStylePreset?: (layerId: string, layerType: 'builtin' | 'imported', preset: string) => void;
  hasCustomStyle?: boolean;
  hasStyleClipboard?: boolean;
  /**
   * The FEATURE clipboard, from this layer's point of view (selected count, what is on
   * the clipboard, whether a paste can land here). With the three handlers below it
   * adds Copy / Paste / Paste as new layer to the menu; without them the commands are
   * omitted.
   */
  clipboardMenu?: LayerMenuContext['clipboard'];
  onCopyFeatures?: (layerId: string, layerType: 'builtin' | 'imported') => void;
  onPasteFeatures?: (layerId: string, layerType: 'builtin' | 'imported') => void;
  onPasteAsLayer?: () => void;
  zoomToLayer?: (layerId: string) => void;
  /** GD 2.4 (review #4): purpose of an imported/digitized layer (append guard). */
  purpose?: string;
  /** GD 2.4: true when the imported layer is still an active draft (not appendable). */
  isDraft?: boolean;
  /** GD 2.4: fired when the user picks "Add Features to this Layer". */
  onAppend?: (layerId: string) => void;
  /** Fired when user picks "Import Layer" on a builtin layer (auto-purpose). */
  onImportLayer?: (layerId: string, purpose: string) => void;
  /** Fired when user picks "Delete Builtin Layer Data" on a builtin layer. */
  onDeleteBuiltin?: (layerId: string) => void;
  /** Fired when user picks "Add Sub-Area" on the builtin sub_areas layer (category-first draw, P6). */
  onAddSubArea?: (layerId: string) => void;
  /** User Group Boundary: auto-buffer from the forest boundary (P3). */
  onUserGroupAutoBuffer?: () => void;
  /** User Group Boundary: open the analysis + results in a modal over the map. */
  onUserGroupAnalysis?: () => void;
  /** Field Book: delete + regenerate (fieldbook_map_layer_plan.md P5). */
  onGenerateFieldbook?: () => void;
  /** Field Book: delete only (fieldbook_map_layer_plan.md P9). */
  onDeleteFieldbook?: () => void;
  /** Sample Plots: delete the whole layer -- owner report 2026-10-02,
   *  allowed only while no field inventory data exists for this forest yet. */
  onDeleteSamplePlots?: () => void;
  onDeleteStemMapping?: () => void;
  /** Sample Plots: add one new plot at the current map centre -- owner
   *  report 2026-10-02. */
  onAddSamplePlot?: () => void;
  /** U-4 (Task 4.1, case E): fired when user picks "Create Polygon from Points". */
  onPolygonFromPoints?: (layerId: string, purpose: string) => void;
  /** Sample Plots: open the sampling design form over the map. */
  onCreateSamplePlots?: () => void;
  /** Stem Mapping: open the Tree Mapping process in a modal over the map. */
  onImportStemMapping?: () => void;

  // --- M-3: everything below used to live only in the row menu's inline JSX.
  // The two menus now render the same list, so this component has to be able
  // to perform the commands that were previously the row menu's alone.
  /** Registry `alwaysReadOnly` — suppresses draw and lock entirely. */
  readOnly?: boolean;
  /** Backend structure lock (OP submitted) — blocks division. */
  structureLocked?: boolean;
  /** Attribute fields this layer can be labelled by. */
  labelFields?: string[];
  /** Which of them is active, so the choice can be announced. */
  currentLabelField?: string | null;
  /** Feature counts across layers; the divide commands need the source count. */
  counts?: Record<string, number>;
  isFirst?: boolean;
  isLast?: boolean;
  /** Ids this host cannot perform; omitted from the menu. */
  unavailableActions?: string[];
  /** Formats this host can produce; defaults to KML only. */
  exportFormats?: string[];
  onAutoCreate?: (level: 'blocks' | 'compartments') => void;
  /** BL-5: fired when user picks "Import Block from Forest Boundary" on the Blocks layer. */
  onImportBlockFromBoundary?: (layerId: string) => void;
  onNewDraw?: (level: 'blocks' | 'compartments') => void;
  onDivide?: (layerId: 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments') => void;
  /** Divide the selected block / compartment by a natural basis (river-ridge, slope, aspect, canopy). */
  onAutoDivide?: (layerId: 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments') => void;
  onToggleLock?: (layerId: string) => void;
  /** `delta` is -1 for up, +1 for down. */
  onMove?: (layerId: string, delta: number) => void;
  onSetLabelField?: (layerId: string, field: string) => void;
  /** Export in a format other than KML (M-8 wires the remaining three). */
  onExportFormat?: (layerId: string, format: string) => void;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(v, max));
}

export default function LayerContextMenu({
  layerId, layerType, layerName, visible, labelsShown,
  featureCount, editable, locked,
  position, onClose, map, onStyleDialog, onStyleCopy, onStylePaste, onStylePreset, hasCustomStyle, hasStyleClipboard, zoomToLayer,
  clipboardMenu, onCopyFeatures, onPasteFeatures, onPasteAsLayer,
  purpose, isDraft, onAppend, onImportLayer, onDeleteBuiltin, onAddSubArea,
onUserGroupAutoBuffer, onUserGroupAnalysis, onGenerateFieldbook, onDeleteFieldbook, onDeleteSamplePlots, onDeleteStemMapping, onAddSamplePlot,
  onPolygonFromPoints, onCreateSamplePlots, onImportStemMapping,
  readOnly, structureLocked, labelFields, currentLabelField, counts, isFirst, isLast, unavailableActions, exportFormats,
  onAutoCreate, onNewDraw, onDivide, onAutoDivide, onToggleLock, onMove, onSetLabelField,
  onExportFormat, onImportBlockFromBoundary,
}: LayerContextMenuProps) {
  const store = useWorkspaceStore();
  const t = useT();
  const { pushAndExecute } = useContextMenuUndoRedo();
  const menuRef = useRef<HTMLDivElement>(null);
  const submenuRef = useRef<HTMLDivElement>(null);
  const focusedIndexRef = useRef(-1);
  const actionsRef = useRef<ContextMenuAction[]>([]);
  /** DOM node of each submenu-parent row, so a fly-out can be anchored to it. */
  const anchorsRef = useRef<Record<string, HTMLButtonElement | null>>({});
  /** id of the parent whose fly-out is open, or null. One at a time. */
  const [openSubmenu, setOpenSubmenu] = useState<string | null>(null);
  const [submenuPos, setSubmenuPos] = useState<{ left: number; top: number } | null>(null);

  const closeSubmenu = useCallback((refocus: boolean) => {
    const anchorId = openSubmenu;
    setOpenSubmenu(null);
    setSubmenuPos(null);
    if (refocus && anchorId) anchorsRef.current[anchorId]?.focus();
  }, [openSubmenu]);

  const openSubmenuFor = useCallback((id: string) => {
    const anchor = anchorsRef.current[id];
    if (!anchor) return;
    const r = anchor.getBoundingClientRect();
    // First guess: hang it off the right edge, flip left if it would overflow.
    // A layout effect re-measures the real box once it has rendered.
    const guessW = 200;
    let left = r.right - 2;
    if (left + guessW > window.innerWidth - 4) left = Math.max(4, r.left - guessW + 2);
    setSubmenuPos({ left, top: r.top });
    setOpenSubmenu(id);
  }, []);

  // Correct the fly-out position against its real size (height especially).
  useLayoutEffect(() => {
    if (!openSubmenu || !submenuPos || !submenuRef.current) return;
    const box = submenuRef.current.getBoundingClientRect();
    const anchor = anchorsRef.current[openSubmenu]?.getBoundingClientRect();
    let { left, top } = submenuPos;
    if (anchor && left + box.width > window.innerWidth - 4) {
      left = Math.max(4, anchor.left - box.width + 2);
    }
    if (top + box.height > window.innerHeight - 4) {
      top = Math.max(4, window.innerHeight - box.height - 4);
    }
    if (left !== submenuPos.left || top !== submenuPos.top) setSubmenuPos({ left, top });
    // Move keyboard focus onto the first child of the fly-out.
    submenuRef.current.querySelector<HTMLButtonElement>('.context-menu-item')?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openSubmenu]);

  const handleZoom = useCallback(() => {
    if (zoomToLayer) {
      zoomToLayer(layerId);
    } else if (map && featureCount > 0) {
      map.fitBounds(map.getBounds());
    }
    onClose();
  }, [zoomToLayer, layerId, map, featureCount, onClose]);

  const handleToggleVis = useCallback(() => {
    const prevVisible = visible;
    const nextVisible = !prevVisible;
    const op = createVisibilityOperation(layerId, layerType, prevVisible, nextVisible, 'user');
    pushAndExecute(op, () => {
      if (layerType === 'builtin') {
        store.toggleLayerVisibility(layerId);
      } else {
        store.setImportedLayerVisibility(Number(layerId), nextVisible);
      }
    });
    onClose();
  }, [layerType, layerId, visible, store, onClose, pushAndExecute]);

  const handleToggleLabels = useCallback(() => {
    const cur = store.layerLabelsVisible[layerId] !== false;
    const next = !cur;
    const op = createLabelsOperation(layerId, cur, next, 'user');
    pushAndExecute(op, () => {
      store.setLayerLabelsVisible(layerId, next);
    });
    onClose();
  }, [store, layerId, onClose, pushAndExecute]);

  const handleStyle = useCallback(() => {
    onStyleDialog?.(layerId, layerType === 'imported' ? 'imported' : 'builtin');
    onClose();
  }, [onStyleDialog, layerId, layerType, onClose]);

  const handleRename = useCallback(() => {
    const newName = window.prompt(t('workspace.enterNewName'), layerName);
    if (!newName) { onClose(); return; }
    const trimmed = newName.trim();
    if (trimmed && trimmed !== layerName) {
      const prevName = layerName;
      const op = createRenameOperation(
        layerId, layerId, prevName, trimmed, 'user',
      );
      pushAndExecute(op, () => {
        store.renameImportedLayer(Number(layerId), trimmed);
      });
    }
    onClose();
  }, [layerName, layerId, store, onClose, pushAndExecute, t]);

  const handleDuplicate = useCallback(() => {
    const op = createDuplicateOperation(
      layerId, layerId, String(-Date.now()), null as any, {}, 'user',
    );
    pushAndExecute(op, () => {
      store.duplicateImportedLayer(Number(layerId));
    });
    onClose();
  }, [layerId, store, onClose, pushAndExecute]);

  /** Untick every strip of one kind in one go (the same decisions the Fire lines panel saves), then redraw the map. */
  const deleteAllStrips = useCallback(async (api: StripApi, confirmKey: string) => {
    const calcId = store.calculationId;
    onClose();
    if (!calcId || !window.confirm(t(confirmKey))) return;
    try {
      const summary = await api.list(calcId);
      const changes = summary.rows.filter((r) => r.ticked).map((r) => ({ unit_key: r.unit_key, included: false }));
      if (changes.length) await api.decide(calcId, changes);
      store.bumpGeometryVersion();
    } catch (err) {
      window.alert(errorMessage(err, t('fireLines.saveFailed')));
    }
  }, [store, onClose, t]);

  const handleRemove = useCallback(async () => {
    if (!window.confirm(t('workspace.confirmRemove', { name: layerName }))) {
      onClose();
      return;
    }
    const numericId = Number(layerId);
    const layerBefore = store.importedLayers.find((l) => l.id === numericId);
    if (!layerBefore) {
      store.removeImportedLayer(numericId);
      onClose();
      return;
    }
    const deletedFeature: GeoJSON.Feature = {
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [0, 0] },
      properties: { ...layerBefore, id: numericId } as unknown as Record<string, unknown>,
    };
    const op = createDeleteOperation(layerId, layerId, deletedFeature, 'user');
    pushAndExecute(op, () => {
      store.removeImportedLayer(numericId);
    });
    onClose();

    const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
    const calcId = store.calculationId;
    if (!calcId) return;

    const token = localStorage.getItem('access_token');
    const delHeaders: Record<string, string> = {};
    if (token) delHeaders['Authorization'] = `Bearer ${token}`;

    try {
      const res = await fetch(
        `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${numericId}`,
        { method: 'DELETE', headers: delHeaders, credentials: 'include' },
      );
      if (!res.ok && layerBefore) {
        store.addImportedLayer(layerBefore);
      }
    } catch {
      if (layerBefore) {
        store.addImportedLayer(layerBefore);
      }
    }
  }, [layerName, layerId, store, onClose, pushAndExecute]);

  const handleDigitizeBoundary = useCallback(() => {
    store.setActiveLayer('boundary');
    store.setToolbarMode('draw_polygon');
    onClose();
    message.success(t('layerPanel.digitizeBoundaryToastMulti'));
  }, [store, onClose]);

  const handleDigitizeUserGroup = useCallback(() => {
    // Arms the draw tool directly (same as "Add sub-area"): MapWorkspace's
    // user_group draw effect keys purely on activeLayer + toolbarMode.
    store.setActiveLayer('user_group');
    store.setToolbarMode('draw_polygon');
    onClose();
    message.success(t('layerPanel.digitizeBoundaryToast'));
  }, [store, onClose]);

  const handleAppend = useCallback(() => {
    if (onAppend) {
      onAppend(layerId);
      return;
    }
    store.setActiveImportedLayer(Number(layerId));
    onClose();
  }, [layerId, store, onClose, onAppend]);

  const handleShowAttr = useCallback(() => {
    store.setActiveLayer(layerId as any);
    onClose();
  }, [layerId, store, onClose]);

  /**
   * The layer as the attribute table shows it: every table column as a field (headed and valued as the table does), each feature with its look
   * from the map. What every export starts from.
   */
  const collectLayerFeatures = useCallback(async (calcId: string): Promise<ExportFeature[]> => {
      let features: GeoJSON.Feature[] = [];
      if (layerType === 'imported') {
        const numericId = Number(layerId);
        features = store.importedLayerFeatures[numericId] || [];
        if (features.length === 0) {
          const baseUrl = (import.meta as any).env?.VITE_API_URL ?? '';
          const token = localStorage.getItem('access_token');
          const headers: Record<string, string> = {};
          if (token) headers['Authorization'] = `Bearer ${token}`;
          const res = await fetch(
            `${baseUrl}/api/v1/workspace/${calcId}/import-layers/${numericId}/features`,
            { headers, credentials: 'include' },
          );
          if (res.ok) {
            const data = await res.json();
            features = data?.features || [];
          }
        }
      } else {
        const config = getLayerConfig(layerId as LayerTypeId);
        if (config) {
          features = (await config.dataSource.fetch(calcId)) || [];
        }
      }
      features = features || [];
      // the table shows a unit with its SFM / hazard / field-inventory / analysis overlays merged in: so does the export
      if (layerType !== 'imported' && isUnitLayerType(layerId)) {
        features = mergeUnitLayerProps(features, {
          sfmBlockTypes: store.sfmBlockTypes, hazardUnits: store.hazardUnits, unitMap: store.unitMap,
          fieldInventoryUnits: store.fieldInventoryUnits, unitAnalysis: store.unitAnalysis,
        }) || [];
      }
      if (features.length === 0) return [];
      const builtin = layerType === 'imported' ? undefined : getLayerConfig(layerId as LayerTypeId);
      let columns: ColumnDef[];
      if (builtin) {
        columns = builtin.columns;
      } else {
        const labels = store.columnLabels[Number(layerId)];
        if (purpose) {
          columns = purposeColumnsForFeatures(purpose, features, labels);
        } else {
          const keys: string[] = [];
          for (const f of features) for (const k of Object.keys(f.properties || {})) if (!k.startsWith('_') && !keys.includes(k)) keys.push(k);
          columns = keys.map((k) => ({ key: k, label: labels?.[k] || k, width: 100 }));
        }
      }
      return buildExportFeatures({
        columns,
        features,
        header: (c) => (c.labelKey ? t(c.labelKey) : c.label),
        layerKey: layerType === 'imported' ? `imported:${layerId}` : layerId,
        presetKey: builtin?.styleKey,
      });
  }, [layerId, layerType, purpose, store.importedLayerFeatures, store.columnLabels, store.sfmBlockTypes, store.hazardUnits, store.unitMap, store.fieldInventoryUnits, store.unitAnalysis, t]);

  const handleExportKml = useCallback(async () => {
    const calcId = store.calculationId;
    if (!calcId) { store.setError('export', t('workspace.noActiveCalculation')); onClose(); return; }
    try {
      const features = await collectLayerFeatures(calcId);
      if (!features || features.length === 0) {
        store.setError('export', t('layerPanel.noFeaturesToExport'));
        onClose();
        return;
      }

      const kml = geojsonToKml(features, layerName);
      const blob = new Blob([kml], { type: 'application/vnd.google-earth.kml+xml' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${layerName.replace(/\s+/g, '_')}.kml`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }, 2000);
    } catch (err: any) {
      store.setError('export', t('layerPanel.exportFailed', { detail: err?.message || 'unknown error' }));
    }
    onClose();
  }, [collectLayerFeatures, layerName, store, onClose, t]);

  /** GeoPackage: the same features, sent to the server, which writes the .gpkg (a layer of mixed kinds becomes one GeoPackage layer per kind). */
  const handleExportGpkg = useCallback(async () => {
    const calcId = store.calculationId;
    if (!calcId) { store.setError('export', t('workspace.noActiveCalculation')); onClose(); return; }
    try {
      const features = await collectLayerFeatures(calcId);
      if (!features || features.length === 0) {
        store.setError('export', t('layerPanel.noFeaturesToExport'));
        onClose();
        return;
      }
      await downloadFromApi(`/api/v1/workspace/${calcId}/export-geopackage`, `${layerName.replace(/\s+/g, '_')}.gpkg`, undefined, {
        method: 'POST',
        body: { layer_name: layerName, features },
      });
    } catch (err: any) {
      store.setError('export', t('layerPanel.exportFailed', { detail: err?.message || 'unknown error' }));
    }
    onClose();
  }, [collectLayerFeatures, layerName, store, onClose, t]);

  /**
   * M-2: the item list now comes from `buildLayerMenu` (lib/layerMenu.ts), the
   * same function the row menu uses. This component's remaining job is to
   * translate the keys and attach the handlers — it no longer decides *what*
   * appears, which is what let the two menus drift apart in the first place.
   */
  const isImported = layerType === 'imported';
  // Scopes the description ids to this menu instance.
  const menuId = `layer-menu-${layerType}-${layerId}`;

  const dispatch = useCallback((id: string) => {
    // Submenu ids carry their choice after a colon: `export:kml`.
    const [head, arg] = id.split(':');
    switch (head) {
      case 'zoom': return handleZoom();
      case 'visibility': return handleToggleVis();
      case 'style': return handleStyle();
      case 'style_copy': onStyleCopy?.(layerId, layerType); return onClose();
      case 'style_paste': onStylePaste?.(layerId, layerType); return onClose();
      case 'copy_features': onCopyFeatures?.(layerId, layerType); return onClose();
      case 'paste_features': onPasteFeatures?.(layerId, layerType); return onClose();
      case 'paste_as_layer': onPasteAsLayer?.(); return onClose();
      case 'style_preset': onStylePreset?.(layerId, layerType, arg); return onClose();
      case 'labels': return handleToggleLabels();
      case 'label_field': onSetLabelField?.(layerId, arg); return onClose();
      case 'analysis_map': store.setActiveAnalysisMap(arg === 'off' ? null : (arg as AnalysisMapId)); return onClose();
      case 'attributes': return handleShowAttr();
      case 'export':
        // GeoPackage is the same for every layer: the features on screen, written by the server.
        if (arg === 'gpkg') return handleExportGpkg();
        // A host that supplies `onExportFormat` owns every format it declared,
        // KML included — Sample Plots has its own exporter and must not be sent
        // through the generic GeoJSON-to-KML path. Only formats the host
        // declared reach here, so there is no silent no-op left.
        if (onExportFormat) {
          onExportFormat(layerId, arg || exportFormats?.[0] || 'kml');
          return onClose();
        }
        return handleExportKml();
      case 'import':
        if (isImported) return handleAppend();
        onImportLayer?.(layerId, purpose ?? '');
        // Deferred so the file dialog opens before the menu unmounts.
        return void setTimeout(() => onClose(), 0);
      case 'draw':
        // Only built for blocks / compartments (see layerMenu.ts).
        if (layerId === 'blocks' || layerId === 'compartments') onNewDraw?.(layerId);
        return onClose();
      case 'add_sub_area': onAddSubArea?.(layerId); return onClose();
      case 'user_group_auto_buffer': onUserGroupAutoBuffer?.(); return onClose();
      case 'user_group_analysis': onUserGroupAnalysis?.(); return onClose();
      case 'user_group_households':
      case 'user_group_executive':
      case 'user_group_other_committees':
        onClose();
        window.dispatchEvent(new CustomEvent('open-user-group-data', { detail: { section: id === 'user_group_households' ? 'households' : 'committee' } }));
        return;
      case 'generate_field_book': onGenerateFieldbook?.(); return onClose();
      case 'create_sample_plots': onCreateSamplePlots?.(); return onClose();
      case 'import_sample_plots': {
        onClose();
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.xlsx,.xls,.csv';
        input.onchange = () => {
          const files = Array.from(input.files ?? []);
          if (files.length) window.dispatchEvent(new CustomEvent('add-data-files', { detail: { files } }));
        };
        input.click();
        return;
      }
      case 'import_stem_mapping': onImportStemMapping?.(); return onClose();
      case 'delete_field_book': onDeleteFieldbook?.(); return onClose();
      case 'delete_sample_plots': onDeleteSamplePlots?.(); return onClose();
      case 'delete_stem_mapping': onDeleteStemMapping?.(); return onClose();
      case 'add_sample_plot': onAddSamplePlot?.(); return onClose();
      case 'auto_create':
        if (layerId === 'blocks' || layerId === 'compartments') onAutoCreate?.(layerId);
        return onClose();
      case 'import_from_boundary':
        onImportBlockFromBoundary?.(layerId);
        return onClose();
      case 'divide_equal_area':
        if (layerId === 'blocks' || layerId === 'sub_blocks' || layerId === 'compartments' || layerId === 'sub_compartments') onDivide?.(layerId);
        return onClose();
      case 'auto_divide':
        if (layerId === 'blocks' || layerId === 'sub_blocks' || layerId === 'compartments' || layerId === 'sub_compartments') onAutoDivide?.(layerId);
        return onClose();
      case 'import_field_inventory':
        onClose();
        window.dispatchEvent(new CustomEvent('open-field-inventory'));
        return;
      case 'update_attributes':
        onClose();
        window.dispatchEvent(new CustomEvent('open-update-attribute'));
        return;
      case 'fire_lines':
        onClose();
        window.dispatchEvent(new CustomEvent('open-fire-lines'));
        return;
      case 'delete_fire_lines': return void deleteAllStrips(fireLineApi, 'layerPanel.confirmDeleteFireLines');
      case 'delete_river_banks': return void deleteAllStrips(riverBankApi, 'layerPanel.confirmDeleteRiverBanks');
      case 'river_banks':
        onClose();
        window.dispatchEvent(new CustomEvent('open-river-banks'));
        return;
      case 'polygon_from_points': onPolygonFromPoints?.(layerId, layerId); return onClose();
      case 'digitize_boundary': return handleDigitizeBoundary();
      case 'digitize_user_group': return handleDigitizeUserGroup();
      case 'boundary_from_point_file': onImportLayer?.('boundary', 'boundary'); return onClose();
      case 'rename': return handleRename();
      case 'duplicate': return handleDuplicate();
      case 'assign_purpose':
        onClose();
        window.dispatchEvent(new CustomEvent('open-assign-purpose-modal', { detail: { layerId, layerName } }));
        return;
      case 'assign':
        onClose();
        window.dispatchEvent(new CustomEvent('open-assign-layer-modal', { detail: { layerId, layerName } }));
        return;
      case 'lock': onToggleLock?.(layerId); return onClose();
      case 'move_up': onMove?.(layerId, -1); return onClose();
      case 'move_down': onMove?.(layerId, 1); return onClose();
      case 'clear_data': onDeleteBuiltin?.(layerId); return onClose();
      case 'remove_layer': return handleRemove();
      default: return onClose();
    }
  }, [handleZoom, handleToggleVis, handleStyle, handleToggleLabels, handleShowAttr,
      handleExportKml, handleExportGpkg, handleAppend, handleDigitizeBoundary,
      handleDigitizeUserGroup,
      handleRename, handleDuplicate, handleRemove, deleteAllStrips, layerId, layerName, isImported,
      purpose, onClose, onImportLayer, onAddSubArea, onUserGroupAutoBuffer, onUserGroupAnalysis, onGenerateFieldbook, onDeleteFieldbook, onDeleteSamplePlots, onDeleteStemMapping, onAddSamplePlot,
      onStyleCopy, onStylePaste, onStylePreset, onCopyFeatures, onPasteFeatures, onPasteAsLayer,
      onPolygonFromPoints, onDeleteBuiltin, onCreateSamplePlots, onImportStemMapping,
      layerType,
      onAutoCreate, onNewDraw, onDivide, onAutoDivide, onToggleLock, onMove, onExportFormat, onSetLabelField,
      exportFormats, onImportBlockFromBoundary]);

  const buildMenuItems = useCallback((): ContextMenuAction[] => {
    const model = tuckAway(buildLayerMenu({
      layerId,
      kind: layerType,
      layerName,
      visible,
      userGroupData: store.userGroupData ?? undefined,
      labelsShown: store.layerLabelsVisible[layerId] !== false,
      featureCount,
      editable,
      readOnly: !!readOnly,
      locked,
      structureLocked,
      purpose,
      isDraft,
      labelFields,
      currentLabelField,
      counts,
      isFirst,
      isLast,
      // A command whose handler this host did not wire is omitted, not greyed.
      unavailableActions: [
        ...(unavailableActions ?? []),
        ...(onCopyFeatures ? [] : ['copy_features']),
        ...(onPasteFeatures ? [] : ['paste_features']),
        ...(onPasteAsLayer ? [] : ['paste_as_layer']),
        ...(onCreateSamplePlots ? [] : ['create_sample_plots']),
        ...(onImportStemMapping ? [] : ['import_stem_mapping']),
        ...(onDeleteStemMapping ? [] : ['delete_stem_mapping']),
        ...(onUserGroupAnalysis ? [] : ['user_group_analysis']),
      ],
      exportFormats,
      hasCustomStyle,
      hasStyleClipboard,
      clipboard: clipboardMenu,
      opacityPercent: layerType === 'builtin' ? Math.round((store.layerAlpha[layerStyleKey(layerId, 'builtin', store.calculationId)] ?? 1) * 100) : undefined,
      analysisMaps: isUnitLayerId(layerId) && layerType === 'builtin'
        ? [
            { id: null, labelKey: 'analysisMaps.off', checked: !isSfmMap(store.activeAnalysisMap) },
            ...ANALYSIS_MAPS.filter((m) => m.group === 'sfm').map((m) => ({ id: m.id, labelKey: m.labelKey, checked: store.activeAnalysisMap === m.id })),
          ]
        : undefined,
    }), counts);

    const toAction = (item: LayerMenuItem): ContextMenuAction => ({
      id: item.id,
      label: String(item.labelKey ? t(item.labelKey, item.labelParams) : ''),
      icon: item.icon,
      shortcut: item.shortcut,
      disabled: item.disabled,
      disabledReason: item.disabledReasonKey ? String(t(item.disabledReasonKey, item.disabledReasonParams)) : undefined,
      danger: item.danger,
      checked: item.checked,
      status: item.status,
      spinner: item.spinner,
      onSpin: item.spinner ? (v: number) => store.setLayerAlpha(layerId, v / 100) : undefined,
      handler: () => dispatch(item.id),
    });

    // Dividers are inserted BETWEEN groups, so the grouping the model already
    // carries is what draws them — no hand-placed `div1`/`div2` any more.
    const out: ContextMenuAction[] = [];
    for (const { group, items: groupItems } of groupLayerMenu(model)) {
      if (out.length) {
        out.push({ id: `div_${group}`, label: '', icon: '', divider: true, handler: () => {} });
      }
      for (const item of groupItems) {
        const action = toAction(item);
        // Children stay NESTED (a fly-out) instead of being appended to the
        // column — style presets + one-row-per-label-field could add 10+ rows
        // and push the bottom of the menu off screen.
        if (item.submenu && item.submenu.length) {
          action.submenu = item.submenu.flatMap((child, i, all) => {
            const row = { ...toAction(child), icon: child.icon || '', shortcut: undefined };
            // The Advanced fly-out is long: a rule between style, copy/paste, export and the rest.
            if (item.id === 'advanced' && i > 0 && advancedSection(child.id) !== advancedSection(all[i - 1].id)) {
              return [{ id: `div_adv_${i}`, label: '', icon: '', divider: true, handler: () => {} }, row];
            }
            return [row];
          });
        }
        out.push(action);
      }
    }
    return out;
  }, [layerId, layerType, layerName, visible, featureCount, editable, readOnly, locked,
      structureLocked, purpose, isDraft, labelFields, currentLabelField, counts, isFirst, isLast, unavailableActions, exportFormats,
      hasCustomStyle, hasStyleClipboard, clipboardMenu, onCopyFeatures, onPasteFeatures, onPasteAsLayer,
      onCreateSamplePlots, store.layerLabelsVisible, store.activeAnalysisMap, store.layerAlpha, store.calculationId, dispatch, t]);

  useEffect(() => {
    // M-12: remember who opened the menu so focus can go back there. Without
    // this, dismissing the menu drops focus to <body> and a keyboard user has
    // to tab in from the top of the page to get back to the layer they were on.
    const opener = document.activeElement as HTMLElement | null;
    focusedIndexRef.current = 0;
    const focusTimer = setTimeout(() => {
      const first = menuRef.current?.querySelector<HTMLButtonElement>('.context-menu-item');
      first?.focus();
    }, 50);
    return () => {
      clearTimeout(focusTimer);
      if (opener && document.contains(opener)) opener.focus();
    };
  }, []);

  useEffect(() => {
    const cycle = (container: HTMLElement | null, key: string) => {
      const items = container?.querySelectorAll<HTMLButtonElement>('.context-menu-item');
      if (!items || items.length === 0) return;
      if (key === 'Home') { items[0]?.focus(); return; }
      if (key === 'End') { items[items.length - 1]?.focus(); return; }
      const cur = Array.from(items).findIndex((el) => el === document.activeElement);
      const delta = key === 'ArrowDown' ? 1 : -1;
      items[(cur + delta + items.length) % items.length]?.focus();
    };

    const handleKeyDown = (e: KeyboardEvent) => {
      // A fly-out is open — arrows/Home/End walk it; Esc/Left step back to the
      // parent row without closing the whole menu.
      if (openSubmenu) {
        if (e.key === 'Escape' || e.key === 'ArrowLeft') {
          e.preventDefault();
          e.stopPropagation();
          closeSubmenu(true);
          return;
        }
        if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
          e.preventDefault();
          cycle(submenuRef.current, e.key);
        }
        return;
      }

      if (e.key === 'Escape') { onClose(); return; }
      // Right arrow on a submenu-parent opens its fly-out.
      if (e.key === 'ArrowRight') {
        const active = document.activeElement as HTMLElement | null;
        const id = active?.getAttribute('data-submenu-parent');
        if (id) { e.preventDefault(); openSubmenuFor(id); }
        return;
      }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
        e.preventDefault();
        cycle(menuRef.current, e.key);
      }
    };

    // Click outside to close — the fly-out is a portal sibling, not a child of
    // menuRef, so it needs its own containment check.
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node;
      const inMenu = menuRef.current?.contains(target);
      const inSub = submenuRef.current?.contains(target);
      if (!inMenu && !inSub) onClose();
    };

    window.addEventListener('keydown', handleKeyDown);
    // Deferred so the same click that opened the menu doesn't immediately close
    // it. The timer id MUST be cleared in cleanup: without it, an effect
    // re-run (React 18/19 StrictMode double-invokes every effect in dev) runs
    // this cleanup before the timer fires, then the orphaned timer still adds a
    // `mousedown` listener that nothing will ever remove. Each stale listener
    // keeps a `menuRef` that is null once its menu closed, so on the *next*
    // menu open it fires on the opening mousedown, calls `onClose()`, and the
    // menu shuts before the click reaches an item — the item's handler never
    // runs and the action silently does nothing until a full page reload.
    const outsideTimer = window.setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
    }, 0);

    return () => {
      window.clearTimeout(outsideTimer);
      window.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose, openSubmenu, closeSubmenu, openSubmenuFor]);

  const actions = buildMenuItems();
  actionsRef.current = actions;

  const menuWidth = 240;
  const rowCount = actions.filter((a) => !a.divider).length;
  const dividerCount = actions.filter((a) => a.divider).length;
  // Overestimate a row at 36px for the open-position math; the real menu is
  // capped by CSS `max-height` + scroll, so being a little high here only
  // affects where it anchors, never whether a row is reachable.
  const menuHeight = Math.min(rowCount * 36 + dividerCount + 8, window.innerHeight - 8);

  const clampedX = clamp(position.x, 4, window.innerWidth - menuWidth - 4);
  const clampedY = clamp(position.y, 4, window.innerHeight - menuHeight - 4);

  const renderItem = (action: ContextMenuAction, inSubmenu: boolean) => {
    if (action.spinner && !inSubmenu) {
      return (
        <div key={action.id} className="context-menu-spinner-row" role="group" aria-label={action.label} data-menu-spinner>
          <span className="context-menu-icon" aria-hidden="true">{action.icon}</span>
          <span className="context-menu-label">{action.label}</span>
          <OpacitySpinner value={action.spinner.value} onChange={(v) => action.onSpin?.(v)} ariaLabel={action.label} step={action.spinner.step} min={action.spinner.min} max={action.spinner.max} />
        </div>
      );
    }
    const hasSub = !inSubmenu && !!action.submenu?.length;
    return (
      <button
        key={action.id}
        ref={hasSub ? (el) => { anchorsRef.current[action.id] = el; } : undefined}
        data-submenu-parent={hasSub ? action.id : undefined}
        className={`context-menu-item${action.danger ? ' danger' : ''}${action.disabled ? ' disabled' : ''}${hasSub ? ' has-submenu' : ''}`}
        // A label field is a CHOICE among several; everything else is an
        // action. The distinction is what lets a screen reader say "3 of 5,
        // selected" rather than reading five identical-sounding commands.
        role={action.checked === undefined ? 'menuitem' : 'menuitemradio'}
        aria-checked={action.checked}
        aria-haspopup={hasSub ? 'menu' : undefined}
        aria-expanded={hasSub ? openSubmenu === action.id : undefined}
        // The shortcut hint is visible text, so without this the accessible
        // name became "New block N" — the command plus its keystroke. Naming
        // the button explicitly keeps the shortcut visual and out of what a
        // screen reader announces as the command.
        aria-label={action.label}
        // M-12: the reason an item is unavailable used to live only in
        // `title`, a mouse-only tooltip — so every explanation M-7 added was
        // invisible to exactly the users least able to guess it. It is a
        // DESCRIPTION rather than part of the name: the command is still
        // called "Divide equal-area", and a name that changed with
        // availability would be a moving target for anyone finding items by
        // name, assistive technology and tests alike.
        aria-describedby={
          action.disabled && action.disabledReason ? `${menuId}-why-${action.id}` : undefined
        }
        // `aria-disabled`, NOT the `disabled` attribute. A disabled button is
        // removed from the tab order entirely, so a keyboard user could never
        // land on it and never hear why it is unavailable. This keeps it
        // reachable and inert.
        aria-disabled={action.disabled || undefined}
        title={action.disabledReason || ''}
        onMouseEnter={
          hasSub
            ? () => openSubmenuFor(action.id)
            : inSubmenu
              ? undefined
              : () => { if (openSubmenu) closeSubmenu(false); }
        }
        onClick={() => {
          if (action.disabled) return;
          if (action.id === 'advanced') { openSubmenuFor(action.id); return; } // a container only: a tap opens it, as hover does
          // A submenu-parent that also has its own action (Style → dialog,
          // Labels → toggle) still runs it on click; hover / → opens the
          // fly-out. `style` has no direct effect worth running twice, but the
          // handler is harmless and closes the menu, which is the expected
          // outcome of clicking a row.
          action.handler();
        }}
        tabIndex={-1}
      >
        {!inSubmenu && <span className="context-menu-icon" aria-hidden="true">{action.icon}</span>}
        <span className="context-menu-label">{action.label}</span>
        {action.status === 'done' && <span className="context-menu-shortcut" style={{ color: '#15803d' }} data-testid={`status-${action.id}`} aria-label={t('workspace.userGroup.statusDone')} title={t('workspace.userGroup.statusDone')}>✓</span>}
        {action.status === 'missing' && <span className="context-menu-shortcut" style={{ color: '#b91c1c', fontWeight: 700 }} data-testid={`status-${action.id}`} aria-label={t('workspace.userGroup.statusMissing')} title={t('workspace.userGroup.statusMissing')}>{t('workspace.userGroup.statusMissingShort')}</span>}
        {action.status === 'optional' && <span className="context-menu-shortcut" data-testid={`status-${action.id}`} aria-label={t('workspace.userGroup.statusOptional')} title={t('workspace.userGroup.statusOptional')}>{t('workspace.userGroup.statusOptionalShort')}</span>}
        {action.checked && inSubmenu && (
          <span className="context-menu-shortcut" aria-hidden="true">✓</span>
        )}
        {action.shortcut && (
          <span className="context-menu-shortcut" aria-hidden="true">{action.shortcut}</span>
        )}
        {hasSub && <span className="context-menu-caret" aria-hidden="true">▸</span>}
        {action.disabled && action.disabledReason && (
          <span id={`${menuId}-why-${action.id}`} className="sr-only">
            {t('layerPanel.unavailableBecause', { reason: action.disabledReason })}
          </span>
        )}
      </button>
    );
  };

  const openParent = openSubmenu ? actions.find((a) => a.id === openSubmenu) : undefined;

  const menu = (
    <>
      <div
        ref={menuRef}
        className="layer-context-menu"
        role="menu"
        aria-label={t('layerPanel.contextMenuFor', { name: layerName })}
        style={{ left: clampedX, top: clampedY }}
      >
        {actions.map((action) =>
          action.divider
            ? <div key={action.id} className="context-menu-divider" role="separator" />
            : renderItem(action, false),
        )}
      </div>
      {openParent?.submenu && submenuPos && (
        <div
          ref={submenuRef}
          className="context-menu-submenu"
          role="menu"
          aria-label={openParent.label}
          style={{ left: submenuPos.left, top: submenuPos.top }}
          onMouseLeave={() => closeSubmenu(false)}
        >
          {openParent.submenu.map((child) => (child.divider
            ? <div key={child.id} className="context-menu-divider" role="separator" />
            : renderItem(child, true)))}
        </div>
      )}
    </>
  );

  return createPortal(menu, document.body);
}