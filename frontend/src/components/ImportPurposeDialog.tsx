import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import CrsSelector from './CrsSelector';
import GpxTypeSelector from './GpxTypeSelector';
import type { CrsEpsg } from './CrsSelector';
import { Modal, message } from 'antd';
import { useImportLayer } from '../hooks/useImportLayer';
import type { ImportResult } from '../hooks/useImportLayer';
import { useWorkspaceStore } from '../store/workspaceStore';
import { PURPOSES, autoNameForPurpose, nextPurposeName, purposeLabelKey } from '../lib/purposeGeometryRules';
import { useT } from '../i18n/hooks';
import { formatDecimal, formatNumber } from '../i18n/numberFormat';
import { parseBoundaryFile } from '../lib/parseBoundaryFile';
import { forestApi, compartmentApi, userGroupApi, uploadApi } from '../services/api';
import { CsvColumnPicker } from './CsvColumnPicker';
import { UploadReport } from './UploadReport';
import { findingsFromError, findingText as uploadFindingText, type AcceptedCorrection, type UploadFinding } from '../lib/uploadFindings';
import i18n from '../i18n';
import { readDetail } from '../hooks/useErrorHandler';
import BoundaryPointFlowModal from './BoundaryPointFlowModal';
import BoundaryOverlapPreviewPanel from './BoundaryOverlapPreviewPanel';
import BoundaryValidationNotice from './BoundaryValidationNotice';
import { useTranslation } from 'react-i18next';
import {
  readBoundaryValidation,
  findingText,
  type BoundaryValidationReport,
} from '../lib/boundaryValidation';
import { apiErrorText } from '../lib/apiErrorText';
import { applyStemBoundaryCorrections, discardStemMappingDraft, importTabular, NeedsTheDedicatedTab, type StemBoundaryFix } from '../lib/tabularImportPipelines';
import { CorrectionPreviewDialog } from './CorrectionPreviewDialog';

interface ImportPurposeDialogProps {
  file: File;
  calculationId: string;
  onComplete: (result: ImportResult) => void;
  onCancel: () => void;
  /** Restrict the offered purposes to geometry-typed ones (Forest boundary / Block).
   *  Used for the first add on a boundary-less draft. */
  restrictToGeometry?: boolean;
  /** Called after a Forest-boundary import sets the calculation boundary. */
  onBoundarySaved?: () => void;
  /** If provided, locks the purpose to this value (context-menu import on builtin layers). */
  fixedPurpose?: string;
  /**
   * Findings this file produced (what is wrong and how to fix it). When given,
   * the caller collects them into one report (UP-4.3, "Add data"); when absent
   * we fall back to a toast, so the dialog still works standalone (LayerPanel).
   */
  onFindings?: (findings: UploadFinding[]) => void;
  /** The coordinate system chosen in Add data for a tabular file (degrees / UTM zone); omitted = the file as it is. */
  tabularCrsEpsg?: number | null;
  /** The proposed replacements the user accepted for a refused file (Add data, "apply the proposed values"). */
  tabularCorrections?: AcceptedCorrection[] | null;
  /** Renumber sample plots 1..N in order (Add data, "renumber the plots"). */
  tabularRenumber?: boolean;
}

/** Builtin layer purposes that can receive direct imports. */
const BUILTIN_PURPOSES = ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas', 'activity_features'];

/**
 * Builtin purposes that ALWAYS append — never overwrite existing data.
 * Sub-areas are append-only: a re-import adds new areas alongside existing
 * ones (FCFS overlap trimming happens at conversion), never deleting them.
 */
const APPEND_ONLY_PURPOSES = new Set(['sub_areas']);

/** Geometry-typed purposes allowed for the first add on a boundary-less draft. */
const GEOMETRY_PURPOSES = ['boundary', 'blocks'];

const EXTENSION_PURPOSE_MAP: Record<string, string> = {
  gpx: 'inventory',
  kml: 'boundary',
  kmz: 'boundary',
  csv: 'inventory',
  xlsx: 'inventory',
  geojson: 'boundary',
  json: 'boundary',
  shp: 'blocks',
  zip: 'blocks',
};

function suggestPurpose(file: File): string {
  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  return EXTENSION_PURPOSE_MAP[ext] || 'other';
}

/** Spreadsheet-only purposes: they run the same pipeline as their own tab (lib/tabularImportPipelines). */
const TABULAR_PURPOSES = [
  { id: 'field_inventory', labelKey: 'purpose.field_inventory', descKey: 'purposeDesc.field_inventory' },
  { id: 'households', labelKey: 'purpose.households', descKey: 'purposeDesc.households' },
  { id: 'forest_metadata', labelKey: 'purpose.forest_metadata', descKey: 'purposeDesc.forest_metadata' },
] as const;

const FORMATS_REQUIRING_CRS = new Set(['csv', 'xlsx', 'txt']);
const FORMAT_IS_GPX = new Set(['gpx']);

export default function ImportPurposeDialog({
  file,
  calculationId,
  onComplete,
  onCancel,
  restrictToGeometry = false,
  onBoundarySaved,
  fixedPurpose,
  onFindings,
  tabularCrsEpsg,
  tabularCorrections,
  tabularRenumber,
}: ImportPurposeDialogProps) {
  const t = useT();
  // Tables that are not map layers (a field inventory, a household list) are offered whenever the file is a spreadsheet, so a file the
  // system recognised as one of them has a button to land on.
  const isSpreadsheet = ['csv', 'xlsx', 'xls'].includes((file.name.split('.').pop() || '').toLowerCase());
  const availablePurposes: ReadonlyArray<{ id: string; labelKey: string; descKey: string }> = restrictToGeometry
    ? PURPOSES.filter((p) => GEOMETRY_PURPOSES.includes(p.id))
    : isSpreadsheet
      ? [...PURPOSES, ...TABULAR_PURPOSES]
      : PURPOSES;
  const suggestedInitial = suggestPurpose(file);
  const initialPurpose = fixedPurpose ?? (restrictToGeometry && !GEOMETRY_PURPOSES.includes(suggestedInitial) ? 'boundary' : suggestedInitial);
  const [purpose, setPurpose] = useState<string | null>(initialPurpose);
  // fixedPurpose is just a default pre-selection, not a lock — user can still change or skip
  // Purpose-driven naming (layer_consolidation.md §3.3): for geometry purposes we
  // auto-name by purpose and let the user override. The exact unique name
  // ("Block 1", "Block 2", ...) is resolved at import time.
  const autoDefault = autoNameForPurpose(suggestedInitial);
  const [customName, setCustomName] = useState('');
  const [crsEpsg, setCrsEpsg] = useState<number>(4326);
  const [gpxTypes, setGpxTypes] = useState<string[]>(['waypoints', 'tracks', 'routes']);
  const [error, setError] = useState<string | null>(null);
  const [errorFindings, setErrorFindings] = useState<UploadFinding[] | null>(null);
  const [boundaryReport, setBoundaryReport] = useState<BoundaryValidationReport | null>(null);
  const { i18n } = useTranslation();
  /** Send this file's findings to the caller's report; fall back to a toast when
   *  there is no collector (the dialog used on its own, e.g. from LayerPanel). */
  const emitFindings = (list: UploadFinding[] | null | undefined) => {
    if (!list || !list.length) return;
    if (onFindings) {
      onFindings(list);
      return;
    }
    const lang = i18n.language === 'ne' ? 'ne' : 'en';
    for (const note of list) message.info(uploadFindingText(note, lang).title, 8);
  };
  /** Show the backend's reason for refusing / adjusting a boundary. Returns true
   *  when it handled the case (caller should stop). */
  const showBoundaryValidation = (src: unknown): boolean => {
    const rep = readBoundaryValidation(src);
    if (rep && (rep.errors.length || rep.warnings.length)) {
      setBoundaryReport(rep);
      return rep.errors.length > 0;
    }
    return false;
  };
  /** Point-file boundary flow state: preview data while the modal is open. */
  const [boundaryFlow, setBoundaryFlow] = useState<{ preview: any; file: File } | null>(null);
  /** Boundary overlap/gap preview for KML/GeoJSON direct boundary imports (PF-3). */
  const [boundaryPreview, setBoundaryPreview] = useState<{ geometry: any; forestName: string; method: string } | null>(null);

  const { importLayer, isImporting, progress, progressMessage, reset } = useImportLayer();
  const addImportedLayer = useWorkspaceStore((s) => s.addImportedLayer);
  const importedLayers = useWorkspaceStore((s) => s.importedLayers);
  const existingLayerNames = useMemo(
    () => importedLayers.map((l) => l.name),
    [importedLayers],
  );

  const ext = file.name.split('.').pop()?.toLowerCase() || '';
  const needsCrs = FORMATS_REQUIRING_CRS.has(ext);
  const isGpx = FORMAT_IS_GPX.has(ext);

  const [overwriteConfirmOpen, setOverwriteConfirmOpen] = useState(false);
  const [pendingConversion, setPendingConversion] = useState<{ layerId: number; purpose: string; finalName: string } | null>(null);
  const [csvColumnPickerOpen, setCsvColumnPickerOpen] = useState(false);
  // a tree file with points outside the boundary: the same correction preview the Tree mapping tab shows (accept -> move them, then process)
  const [treeFix, setTreeFix] = useState<{ fix: StemBoundaryFix } | null>(null);
  const [treeFixBusy, setTreeFixBusy] = useState(false);
  const overwritePurposeLabel = pendingConversion?.purpose
    ? (purposeLabelKey(pendingConversion.purpose)
        ? t(purposeLabelKey(pendingConversion.purpose))
        : pendingConversion.purpose)
    : '';

  const checkExistingBlocks = async (): Promise<boolean> => {
    if (purpose === 'blocks') {
      try {
        const blocks = await forestApi.getBlocks(calculationId);
        return (blocks?.blocks || []).length > 0;
      } catch {
        return false;
      }
    }
    if (purpose === 'sub_blocks') {
      try {
        const tree = await compartmentApi.getCompartmentTree(calculationId);
        return (tree?.total_sub_blocks ?? 0) > 0;
      } catch {
        return false;
      }
    }
    if (purpose === 'compartments' || purpose === 'sub_compartments') {
      try {
        const tree = await compartmentApi.getCompartmentTree(calculationId);
        if (purpose === 'sub_compartments') {
          return (tree?.total_sub_compartments ?? 0) > 0;
        }
        return (tree?.total_compartments ?? 0) > 0;
      } catch {
        return false;
      }
    }
    return false;
  };

  const handleImport = async () => {
    setError(null);
    setBoundaryReport(null);
    if (import.meta.env.DEV) console.log(
      '[Import] submit',
      { file: file.name, purpose, skipped: purpose === null, fixedPurpose, calculationId },
    );

    const finalName = purpose === null && customName.trim()  // the typed name only applies to an unassigned layer
      ? customName
      : (purpose ? (autoNameForPurpose(purpose) ? nextPurposeName(purpose, existingLayerNames) : file.name.replace(/\.[^.]+$/, '')) : file.name.replace(/\.[^.]+$/, ''));

    // Forest-boundary purpose: set the calculation boundary directly (no auxiliary
    // layer). Parse client-side, then PUT boundary_geom (server computes geodesic area).
    if (
      purpose === 'boundary' &&
      ['csv', 'xlsx', 'txt'].includes((file.name.split('.').pop() || '').toLowerCase())
    ) {
      try {
        const preview = await forestApi.previewBoundaryMapping(calculationId, file);
        setBoundaryFlow({ preview, file });
        return;
      } catch (err) {
        if (showBoundaryValidation(err)) return;
        setError(
          err instanceof Error
            ? `${t('import.dialog.boundaryPreviewFailed')}: ${err.message}`
            : t('import.dialog.boundaryPreviewFailed'),
        );
        return;
      }
    }
    if (purpose === 'boundary') {
      try {
        const feature = await parseBoundaryFile(file);
        const geom = (feature as any).geometry ?? feature;
        const resp: any = await forestApi.updateBoundaryGeometry(calculationId, {
          geometry: feature as unknown as any,
          area_hectares: 0,
        });
        if (resp?.needs_overlap_review) {
          setBoundaryPreview({ geometry: geom as unknown as any, forestName: finalName, method: 'upload' });
          return;
        }
        // Success — but the boundary may have been clipped to Nepal; tell the user.
        const okReport = readBoundaryValidation(resp);
        if (okReport?.warnings.length) {
          message.warning(
            okReport.warnings.map((w) => findingText(w, i18n.language)).join(' '),
          );
        }
        onBoundarySaved?.();
        onComplete({
          success: true,
          layerName: finalName,
          featureCount: 1,
          geometryTypes: [(feature as any).geometry?.type || (geom as any)?.type || 'Polygon'],
        });
        return;
      } catch (err: any) {
        // If the server returned provisional as an error (409 etc.), try to surface preview if present
        const data = err?.response?.data;
        if (data?.needs_overlap_review) {
          try {
            const feature = await parseBoundaryFile(file);
            const geom = (feature as any).geometry ?? feature;
            setBoundaryPreview({ geometry: geom, forestName: finalName, method: 'upload' });
            return;
          } catch {
            // best-effort parse; fall through to the standard boundary error path
          }
        }
        if (showBoundaryValidation(err)) return;
        setError(
          err instanceof Error
            ? `${t('import.dialog.boundarySetFailed')}: ${err.message}`
            : t('import.dialog.boundarySetFailed'),
        );
        return;
      }
    }

    // User Group Boundary: set the extent directly (no auxiliary layer), the
    // same way `boundary` does. The backend `/user-group/import` reuses the
    // Forest-Boundary engine — any format, any geometry type.
    // USER_GROUP_BOUNDARY_PLAN.md D2a.
    if (purpose === 'user_group_boundary') {
      // CSV/Excel files: if auto-detection didn't find lat/lon, ask the user to pick columns (UP-3.2)
      const fileExt = (file.name.split('.').pop() || '').toLowerCase();
      if (['csv', 'xlsx', 'xls'].includes(fileExt)) {
        try {
          const colInfo = await uploadApi.getCsvColumns(file);
          if (!colInfo.lat_col || !colInfo.lon_col) {
            setCsvColumnPickerOpen(true);
            return;
          }
        } catch {
          // if reading columns fails, let the import try anyway
        }
      }
      // Importing REPLACES the current user group boundary (owner decision D3): when there is one, say so and ask first.
      const existing = useWorkspaceStore.getState().featureCounts.user_group ?? 0;
      if (existing > 0 && !window.confirm(t('import.dialog.replaceUserGroup', { count: existing }))) {
        return; // the user chose not to replace: nothing was sent
      }
      try {
        const res = await userGroupApi.importExtent(calculationId, file);
        // what we noticed and fixed while reading the file (UTM metres converted, columns swapped): tell the user, in their language
        emitFindings(res.findings);
        onComplete({
          success: true,
          layerName: finalName,
          featureCount: 1,
          geometryTypes: ['MultiPolygon'],
          purpose: 'user_group_boundary',
          converted: true,
          extentId: res.extent_id,
        } as unknown as ImportResult);
        return;
      } catch (err: unknown) {
        // The detail may be a coded, bilingual object (e.g. user_group.too_large), so read it with the language-aware reader.
        // A refused upload carries plain-language findings (what is wrong, where, how to fix): show those instead of a bare message.
        const findings = findingsFromError(err);
        if (findings) onFindings?.(findings);
        setErrorFindings(findings);
        const detail = findings ? null : readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail);
        setError(
          findings ? null : detail ||
            (err instanceof Error
              ? `${t('workspace.userGroup.importFailed')}: ${err.message}`
              : t('workspace.userGroup.importFailed')),
        );
        return;
      }
    }

    // Tabular uploads: the SAME pipeline each dedicated tab runs (UP-4.1 / UP-4.3).
    // `households` and `field_inventory` are always tabular; `inventory` (Tree
    // Inventory / stem mapping) is tabular only for spreadsheets — a spatial tree
    // layer still takes the normal geometry path below.
    const isTabularExt = ['csv', 'xlsx', 'xls'].includes(ext);
    const tabularPipeline =
      purpose === 'households'
        ? 'households'
        : purpose === 'field_inventory'
          ? 'field_inventory'
          : purpose === 'inventory' && isTabularExt
            ? 'stem_mapping'
            : purpose === 'sample_plot' && isTabularExt
              ? 'sample_plots'
              : purpose === 'forest_metadata'
                ? 'forest_metadata'
                : null;
    if (tabularPipeline) {
      try {
        const res = await importTabular(tabularPipeline, calculationId, file, { crsEpsg: tabularCrsEpsg, corrections: tabularCorrections, renumber: tabularRenumber });
        emitFindings(res.findings);
        onComplete({
          success: res.failed !== true,
          layerName: finalName,
          featureCount: res.records_imported ?? 0,
          purpose,
        } as unknown as ImportResult);
        return;
      } catch (err: unknown) {
        // The pipeline hit a question Add data cannot ask (which column is which,
        // what to do about a boundary correction). Say so and name the tab.
        if (err instanceof NeedsTheDedicatedTab) {
          if (err.reason === 'boundary' && err.fix) {
            setTreeFix({ fix: err.fix });
            return;
          }
          const type = t(`purpose.${err.message}`);
          setError(
            err.reason === 'exists'
              ? t('import.dialog.tabularExists', { type, file: err.detail || '' })
              : err.reason === 'boundary'
                ? t('import.dialog.tabularNeedsBoundary', { type })
                : t('import.dialog.tabularNeedsColumns', { type }),
          );
          return;
        }
        // Finding-shaped refusals carry what is wrong and how to fix it: show those.
        const findings = findingsFromError(err);
        if (findings) onFindings?.(findings);
        setErrorFindings(findings);
        setError(
          findings ? null : readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail) ||
            (err instanceof Error ? err.message : null) ||
            t('import.dialog.unknownError'),
        );
        return;
      }
    }

    const result = await importLayer({
      calculationId,
      file,
      crsEpsg: needsCrs ? crsEpsg : undefined,
      purpose: purpose || undefined,
      customName: finalName,
      gpxTypes: isGpx ? gpxTypes : undefined,
      // When importing into a builtin layer type, replace existing (except append-only sub_areas)
      replaceExisting: BUILTIN_PURPOSES.includes(purpose || '') && !APPEND_ONLY_PURPOSES.has(purpose || ''),
    });

    if (!result.success || !result.layerId) {
      setError(result.error || t('import.dialog.unknownError'));
      return;
    }

    // For builtin layer purposes, check for existing data and confirm overwrite.
    // Append-only purposes (sub_areas) bypass the overwrite dialog and convert directly.
    if (purpose !== null && BUILTIN_PURPOSES.includes(purpose)) {
      if (APPEND_ONLY_PURPOSES.has(purpose)) {
        await doConversion(result.layerId, purpose, finalName, undefined, result.swappedFixed);
        return;
      }
      const hasExisting = await checkExistingBlocks();
      if (hasExisting) {
        setPendingConversion({ layerId: result.layerId, purpose, finalName });
        setOverwriteConfirmOpen(true);
        return;
      }
      // No existing data, proceed with conversion
      await doConversion(result.layerId, purpose, finalName, undefined, result.swappedFixed);
      return;
    }

    // Normal imported layer path
    addImportedLayer({
      id: result.layerId,
      name: result.layerName || finalName,
      purpose: purpose ?? 'other',
      format: ext,
      featureCount: result.featureCount || 0,
      geometryTypes: result.geometryTypes || [],
      visible: true,
      order: 0,
    });
    if (result.swappedFixed) {
      message.info(t('import.dialog.swappedFixed'));
    }
    onComplete({ ...result, purpose: purpose ?? 'other' });
  };

  const doConversion = async (layerId: number, purpose: string, finalName: string, confirm?: boolean, swappedFixed?: boolean) => {
    try {
      const conversion: any = await forestApi.convertImportedToBuiltin(calculationId, layerId, purpose, confirm ? { confirm: true } : undefined);
      if (conversion?.needs_overlap_review) {
        const geom = conversion.preview_geometry
        if (geom) {
          setBoundaryPreview({ geometry: geom, forestName: finalName, method: 'upload' })
        } else {
          setError(conversion.detail || conversion.message || t('import.dialog.conversionFailed'))
        }
        return
      }
      if (conversion.success) {
        useWorkspaceStore.getState().bumpGeometryVersion();
        message.success(buildImportSummaryMessage(conversion, purpose, t));
        if (swappedFixed) {
          message.info(t('import.dialog.swappedFixed'));
        }
        const result: ImportResult = { ...{ layerId, layerName: finalName }, purpose, converted: true, success: true };
        onComplete(result);
        return;
      }
      setError(conversion.detail || conversion.message || t('import.dialog.conversionFailed'));
    } catch (err: any) {
      const data = err?.response?.data
      if (data?.needs_overlap_review && data?.preview_geometry) {
        setBoundaryPreview({ geometry: data.preview_geometry, forestName: finalName, method: 'upload' })
        return
      }
      setError(apiErrorText(err, err.message || t('import.dialog.conversionFailedShort')));
    }
  };

  const handleOverwriteConfirm = async () => {
    setOverwriteConfirmOpen(false);
    if (pendingConversion) {
      await doConversion(pendingConversion.layerId, pendingConversion.purpose, pendingConversion.finalName, true);
      setPendingConversion(null);
    }
  };

  const acceptTreeFix = async () => {
    if (!treeFix) return;
    setTreeFixBusy(true);
    try {
      await applyStemBoundaryCorrections(treeFix.fix, file);
      const total = Number(treeFix.fix.boundaryCheck?.total_points ?? 0);
      setTreeFix(null);
      onComplete({ success: true, layerName: customName.trim() || file.name, featureCount: total, purpose } as unknown as ImportResult);
    } catch (err: unknown) {
      setTreeFix(null);
      setError(readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail) || (err instanceof Error ? err.message : null) || t('import.dialog.unknownError'));
    } finally {
      setTreeFixBusy(false);
    }
  };

  const declineTreeFix = async () => {
    if (!treeFix) return;
    const { inventoryId } = treeFix.fix;
    setTreeFix(null);
    await discardStemMappingDraft(inventoryId);
    setError(t('treeMapping.tab.msgUploadCancelled'));
  };

  if (treeFix?.fix.boundaryCheck) {
    const bc = treeFix.fix.boundaryCheck;
    // the dialog is a plain fixed overlay (z-50), made for the Tree mapping tab where nothing else is open; here the Add data window (z 1000)
    // and the map's own layers are on screen, so it gets a stacking context of its own above them
    return createPortal(
      <div style={{ position: 'relative', zIndex: 2000 }} data-testid="tree-correction-layer">
        <CorrectionPreviewDialog
          boundaryCheck={bc}
          corrections={bc.corrections || []}
          summary={bc.correction_summary || { total_corrections: 0, max_distance: 0, min_distance: 0, avg_distance: 0 }}
          onAccept={() => void acceptTreeFix()}
          onCancel={() => void declineTreeFix()}
          isProcessing={treeFixBusy}
        />
      </div>,
      document.body,
    );
  }

  if (boundaryPreview) {
    return createPortal(
      <Modal
        open
        onCancel={() => setBoundaryPreview(null)}
        footer={null}
        width={1100}
        title={t('boundaryPreview.title')}
        centered
        destroyOnHidden
      >
        <BoundaryOverlapPreviewPanel
          geometry={boundaryPreview.geometry}
          forestName={boundaryPreview.forestName}
          method={boundaryPreview.method}
          calculationId={calculationId}
          onCancel={() => setBoundaryPreview(null)}
          onDone={() => {
            // Clear our own modal state BEFORE handing off — otherwise this
            // `if (boundaryPreview)` branch keeps rendering the panel and it
            // looks like Accept re-opens the same window.
            const name = boundaryPreview.forestName
            setBoundaryPreview(null)
            onBoundarySaved?.()
            onComplete({ success: true, layerName: name, featureCount: 1, geometryTypes: ['Polygon'], purpose: 'boundary', converted: true } as unknown as ImportResult)
          }}
          onEdit={() => setBoundaryPreview(null)}
        />
      </Modal>,
      document.body,
    )
  }

  return createPortal(
    boundaryFlow ? (
      <BoundaryPointFlowModal
        file={boundaryFlow.file}
        preview={boundaryFlow.preview}
        calculationId={calculationId}
        onBoundarySaved={onBoundarySaved}
        onComplete={onComplete}
        onCancel={() => setBoundaryFlow(null)}
      />
    ) : (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-[9999] p-4">
      <div className="bg-white rounded-lg max-w-lg w-full max-h-[90vh] overflow-y-auto p-6 space-y-5">
        <h2 className="text-xl font-bold text-gray-900">{t('import.dialog.title')}</h2>
        <p className="text-sm text-gray-600">
          {t('import.dialog.file')} <span className="font-mono font-medium">{file.name}</span> ({t('import.dialog.fileSize', { size: formatDecimal(file.size / 1024, 1) })})
        </p>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm">
            {error}
          </div>
        )}
        {errorFindings && <UploadReport findings={errorFindings} />}

        <BoundaryValidationNotice report={boundaryReport} />

        <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">{t('import.dialog.purpose')}</label>
            <div className="grid grid-cols-2 gap-2">
              {availablePurposes.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  disabled={isImporting}
                  onClick={() => setPurpose(p.id)}
                  className={`px-3 py-2 text-sm rounded-md border text-left transition-colors
                    ${purpose === p.id
                      ? 'border-green-500 bg-green-50 text-green-800'
                      : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}
                    ${isImporting ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                >
                  <span className="block font-medium">{t(p.labelKey)}</span>
                  <span className="block text-xs text-gray-500">{t(p.descKey)}</span>
                </button>
              ))}
            </div>
            <div className="mt-3 pt-3 border-t border-gray-200">
              <button
                type="button"
                onClick={() => setPurpose(null)}
                disabled={isImporting}
                className={`w-full px-3 py-2 text-sm rounded-md border transition-colors disabled:opacity-50
                  ${purpose === null
                    ? 'border-green-500 bg-green-50 text-green-800 font-medium'
                    : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'}
                  ${isImporting ? 'cursor-not-allowed' : 'cursor-pointer'}`}
              >
                {t('import.dialog.skipPurpose')}
              </button>
            </div>
          </div>

        {/* A layer with a purpose is named by the system (Forest Boundary 1, Block 1 ...), so there is nothing to type. The name is only
            asked for when the file is kept as an unassigned layer. */}
        {purpose === null && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{t('import.dialog.layerName')}</label>
            <input
              type="text"
              value={customName}
              disabled={isImporting}
              onChange={(e) => setCustomName(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
            />
          </div>
        )}

        {needsCrs && (
          <CrsSelector value={crsEpsg} onChange={setCrsEpsg} disabled={isImporting} />
        )}

        {isGpx && (
          <GpxTypeSelector value={gpxTypes} onChange={setGpxTypes} disabled={isImporting} />
        )}

        {isImporting && (
          <div className="space-y-2">
            <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-green-600 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-xs text-gray-500 text-center">{progressMessage}</p>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onCancel}
            disabled={isImporting}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleImport}
            disabled={isImporting}
            className="px-4 py-2 border border-transparent rounded-md text-sm font-medium text-white bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isImporting ? t('import.dialog.importing') : t('import.dialog.import')}
          </button>
        </div>

        {overwriteConfirmOpen && (
          <Modal
            open={overwriteConfirmOpen}
            onOk={handleOverwriteConfirm}
            onCancel={() => setOverwriteConfirmOpen(false)}
            title={t('import.dialog.overwriteTitle')}
            centered
            okText={t('import.dialog.overwrite')}
            cancelText={t('common.cancel')}
          >
            <p>{t('import.dialog.overwriteHas', { purpose: overwritePurposeLabel })}</p>
            <p className="text-orange-600 font-medium">
              {t('import.dialog.overwriteReplace', { purpose: overwritePurposeLabel })}
            </p>
            <p className="text-sm text-gray-500">{t('import.dialog.overwriteBackup')}</p>
            <p className="text-sm text-gray-500">{t('import.dialog.overwriteConfirm')}</p>
          </Modal>
        )}

        <CsvColumnPicker
          open={csvColumnPickerOpen}
          file={file}
          onConfirm={(latCol, lonCol) => {
            setCsvColumnPickerOpen(false);
            userGroupApi.importExtent(calculationId, file, { lat_col: latCol, lon_col: lonCol })
              .then((res) => {
                emitFindings(res.findings);
                onComplete({
                  success: true,
                  layerName: customName.trim() || file.name.replace(/\.[^.]+$/, ''),
                  featureCount: 1,
                  geometryTypes: ['MultiPolygon'],
                  purpose: 'user_group_boundary',
                  converted: true,
                  extentId: res.extent_id,
                } as unknown as ImportResult);
              })
              .catch((err: unknown) => {
                const findings = findingsFromError(err);
                if (findings) onFindings?.(findings);
                setErrorFindings(findings);
                setError(findings ? null : readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail) || t('workspace.userGroup.importFailed'));
              });
          }}
          onCancel={() => setCsvColumnPickerOpen(false)}
        />
        </div>
      </div>
    ),
    document.body,
  );
}

/** Build a human-readable import toast, surfacing clip/removal/overlap counts (R4/P7). */
function buildImportSummaryMessage(
  conversion: any,
  purpose: string,
  t: (k: string, opts?: Record<string, unknown>) => string,
): string {
  const created = conversion?.created ?? 0;
  const area = conversion?.total_area_hectares;
  const label = purposeLabelKey(purpose) ? t(purposeLabelKey(purpose)) : purpose.replace('_', ' ');
  const base = area != null
    ? t('import.dialog.msgCreatedWithArea', {
        count: formatNumber(created),
        purpose: label,
        area: formatDecimal(area),
      })
    : t('import.dialog.msgCreated', { count: formatNumber(created), purpose: label });
  const s = conversion?.import_summary;
  if (!s) return base;
  const parts: string[] = [];
  if (s.imported != null) parts.push(t('import.dialog.sumImported', { count: formatNumber(s.imported) }));
  if ((s.clipped ?? 0) > 0) parts.push(t('import.dialog.sumClipped', { count: formatNumber(s.clipped) }));
  if ((s.removed ?? 0) > 0) parts.push(t('import.dialog.sumRemoved', { count: formatNumber(s.removed) }));
  if ((s.overlapped ?? 0) > 0) parts.push(t('import.dialog.sumOverlapped', { count: formatNumber(s.overlapped) }));
  if ((s.dropped_unclosed ?? 0) > 0) parts.push(t('import.dialog.sumDropped', { count: formatNumber(s.dropped_unclosed) }));
  return parts.length ? `${base}. ${parts.join(', ')}.` : base;
}