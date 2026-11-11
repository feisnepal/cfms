/** TreeMappingTab — tab for tree mapping data management and export. */
import React, { useState, useEffect } from 'react';
import { onDataImported } from '../lib/uploadEvents';
import StemMappingSuggestion from './StemMappingSuggestion';
import { JOB_STATUS_KEY, statusLabel } from '../lib/statusLabels';
import { inventoryApi } from '../services/api';
import { CorrectionPreviewDialog } from './CorrectionPreviewDialog';
import ColumnMappingPreview from './ColumnMappingPreview';
import { Pie, Bar } from 'react-chartjs-2';
import '../utils/chartSetup';
import { downloadFromApi } from '../utils/download';
import { TreeMappingAnalysis } from './TreeMappingAnalysis';
import { UploadReport } from './UploadReport';
import { findingsFromBody, findingsFromError, type UploadFinding } from '../lib/uploadFindings';
import { UploadPointsPreview } from './UploadPointsPreview';
import { UploadStateLine } from './UploadStateLine';
import { useT } from '../i18n/hooks';
import { formatDecimal, parseLocaleNumber } from '../i18n/numberFormat';
import { readDetail } from '../hooks/useErrorHandler';

const COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

interface TreeMappingTabProps {
  calculationId: string;
  /**
     * Which pane of the step's Data / Results split to render. The step's host
     * mounts only the active pane, so this is the split point, not a prop both
     * copies receive.
     *
     * Data is the file, its status, the actions that change it, and the raw
     * uploaded rows. Results is everything derived from those rows: totals,
     * charts, tables, the analysis. The `view` guards below are
     * `view !== 'results'` / `view !== 'data'` rather than equality so the
     * component keeps working unmounted-split for its other callers.
     */
    view?: 'data' | 'results';
    /**
     * Called whenever the tree-mapping data changes (uploaded/processed, corrections
     * applied, block/sub-area reassigned, or deleted) so a host (e.g. the map
     * workspace stem-mapping layer) can refresh and re-render.
     */
    onChanged?: (change: 'created' | 'deleted' | 'processed' | 'updated') => void;
  }


/** Display-label keys for persisted tree-remark data values. */
const REMARK_LABEL_KEY: Record<string, string> = {
  'Mother': 'treeMapping.remark.mother',
  'Felling': 'treeMapping.remark.felling',
  'Seedling': 'treeMapping.remark.seedling',
  'Normal': 'treeMapping.remark.normal',
};

export function TreeMappingTab({ calculationId, view, onChanged }: TreeMappingTabProps) {
  const t = useT();
  const [treeMapping, setTreeMapping] = useState<any>(null);
  const [summary, setSummary] = useState<any>(null);
  const [trees, setTrees] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [gridSpacing, setGridSpacing] = useState(20);
  const [projectionEpsg, setProjectionEpsg] = useState<string>('');
  const [uploading, setUploading] = useState(false);
  const [validationResult, setValidationResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorFindings, setErrorFindings] = useState<UploadFinding[] | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [updatingBlockSubarea, setUpdatingBlockSubarea] = useState(false);

  // Column mapping state
  const [showColumnMapping, setShowColumnMapping] = useState(false);
  const [columnMappingData, setColumnMappingData] = useState<any>(null);

  // Boundary correction state
  const [showCorrectionDialog, setShowCorrectionDialog] = useState(false);
  const [correctionData, setCorrectionData] = useState<any>(null);
  const [applyingCorrections, setApplyingCorrections] = useState(false);

  // Check if tree mapping exists for this calculation
  useEffect(() => {
    checkTreeMapping();
  }, [calculationId]);

  // A stem mapping imported from "Add data" arrives from outside this tab: read it again.
  const reloadRef = React.useRef<() => void>(() => {});
  reloadRef.current = () => { void checkTreeMapping(); };
  useEffect(
    () => onDataImported(({ purposes }) => {
      if (purposes.includes('trees')) reloadRef.current();
    }),
    [],
  );

  const checkTreeMapping = async () => {
    try {
      setLoading(true);
      
      // First check if ANY tree mapping exists (regardless of owner)
      const existingCheck = await inventoryApi.checkTreeMappingExists(calculationId).catch(() => null);
      
      if (existingCheck?.exists) {
        // Show existing data 
        setTreeMapping({
          id: existingCheck.inventory_id,
          uploaded_filename: existingCheck.filename,
          status: existingCheck.status
        });
        
        // Load summary for existing data
        loadTreeData(existingCheck.inventory_id);
        
        setError(`Tree mapping already exists: ${existingCheck.filename}. Delete it first to upload new data.`);
        setLoading(false);
        return;
      }
      
      // No tree mapping exists - check for current user's data
      const mapping = await inventoryApi.getTreeMappingByCalculation(calculationId);
      setTreeMapping(mapping);

      if (mapping?.id) {
        loadTreeData(mapping.id);
      }
    } catch (err: any) {
      if (err.response?.status === 404) {
        setTreeMapping(null);
        setSummary(null);
        setTrees([]);
      } else {
        console.log('checkTreeMapping error:', err);
        setTreeMapping(null);
      }
    } finally {
      setLoading(false);
    }
  };

  // Force delete tree mapping from another user
  const forceDeletePrevious = async () => {
    if (!treeMapping?.id) return;
    
    try {
      setDeleting(true);
      await inventoryApi.forceDeleteByCalculation(calculationId);
      setTreeMapping(null);
      setSummary(null);
      setTrees([]);
      setError(null);
      setFile(null);
      setValidationResult(null);
      alert(t('treeMapping.tab.msgDeleted'));
      onChanged?.('deleted');
    } catch (err: any) {
      console.log('Force delete error:', err);
      // Force delete should still work - reload
      await checkTreeMapping();
    } finally {
      setDeleting(false);
    }
  };

  const loadTreeData = async (mappingId: string) => {
    try {
      setLoadingData(true);
      const [summaryData, treesData] = await Promise.all([
        inventoryApi.getInventorySummary(mappingId).catch(() => null),
        inventoryApi.listInventoryTrees(mappingId, { page: 1, page_size: 50 }).catch(() => ({ trees: [] }))
      ]);
      setSummary(summaryData);
      setTrees(treesData.trees || []);
    } catch (err: any) {
      console.error('Error loading tree data:', err);
    } finally {
      setLoadingData(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setValidationResult(null);
      setError(null);
    }
  };

  // Handle clearing current tree mapping to re-upload
  const handleClearAndReupload = async () => {
    if (!treeMapping?.id) return;
    
    if (!confirm(t('treeMapping.tab.confirmClear'))) {
      return;
    }

    try {
      setDeleting(true);
      await inventoryApi.deleteInventory(treeMapping.id);
      setTreeMapping(null);
      setSummary(null);
      setTrees([]);
      setFile(null);
      setValidationResult(null);
      setError(null);
      onChanged?.('deleted');
    } catch (err: any) {
      setError(readDetail(err.response?.data?.detail) ?? t('treeMapping.tab.msgClearFailed'));
    } finally {
      setDeleting(false);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      await downloadFromApi('/api/inventory/template', 'TreeMapping_Template.csv');
    } catch (err: any) {
      setError(t('treeMapping.tab.msgTemplateFailed'));
    }
  };

  const handleUpload = async () => {
    if (!file) {
      setError(t('treeMapping.tab.msgSelectFile'));
      return;
    }

    try {
      setUploading(true);
      setError(null);

      // Step 1: Preview column mapping
      const previewData = await inventoryApi.previewColumnMapping(file);
      setUploading(false);
      // Every required column was recognised with confidence and nothing is ambiguous (the server decides: `needs_user_input`), so there is
      // nothing for the user to confirm: go straight on instead of showing a dialog that only repeats what we already know.
      if (previewData.needs_user_input === false && previewData.mapping && Object.keys(previewData.mapping).length > 0) {
        await handleConfirmMapping(previewData.mapping, false);
        return;
      }
      setColumnMappingData(previewData);
      setShowColumnMapping(true);

    } catch (err: any) {
      console.error('Preview error:', err);
      const findings = findingsFromError(err);
      setErrorFindings(findings);
      const errorMessage = readDetail(err.response?.data?.detail) ?? err.message ?? t('treeMapping.tab.msgPreviewFailed');
      setError(findings ? null : errorMessage);
      setUploading(false);
    }
  };

  const handleConfirmMapping = async (
    mapping: Record<string, string>,
    savePreference: boolean
  ) => {
    if (!file) return;

    try {
      setUploading(true);
      setShowColumnMapping(false);
      setError(null);

      const epsg = projectionEpsg ? parseInt(projectionEpsg) : undefined;

      // Step 2: Confirm mapping and upload
      const result = await inventoryApi.confirmColumnMapping(
        file,
        mapping,
        savePreference,
        gridSpacing,
        calculationId,
        epsg
      );
      
      // If data already exists, show it and don't replace
      if (result.exists) {
        // Show existing data info
        setTreeMapping({
          id: result.inventory_id,
          uploaded_filename: result.filename,
          status: result.status
        });
        setError(`Tree mapping already exists: ${result.filename}. Delete it first to upload new data.`);
        setUploading(false);
        return;
      }
      
      setValidationResult(result);


      // Step 2: Check if boundary corrections are needed
      if (result.summary?.ready_for_processing && result.inventory_id) {
        // Check for boundary issues
        if (result.boundary_check?.needs_correction) {
          // Show correction dialog
          setCorrectionData({
            inventoryId: result.inventory_id,
            boundaryCheck: result.boundary_check,
            result: result
          });
          setShowCorrectionDialog(true);
          setUploading(false);
          return;
        }

        // No corrections needed - proceed with normal processing
        // Update status to show processing
        setValidationResult({
          ...result,
          summary: {
            ...result.summary,
            status: t('treeMapping.tab.statusProcessing')
          }
        });

        try {
          // Process the inventory (re-upload file)
          await inventoryApi.processInventory(result.inventory_id, file);

          // Reload tree mapping data
          await checkTreeMapping();
          setFile(null);
          setValidationResult(null);
          onChanged?.('created');
        } catch (processErr: any) {
          console.error('[TREE MAPPING] Processing error:', processErr);
          console.error('Error response:', processErr.response);
          console.error('Error data:', processErr.response?.data);

          const errorMessage = readDetail(processErr.response?.data?.detail) ?? processErr.message ?? t('treeMapping.tab.msgProcessingFailed');
          setError(errorMessage);
          setValidationResult(null); // Clear validation result to show error
        }
      } else {
        // CRITICAL FIX: If not ready for processing (e.g., boundary error),
        // stop loading immediately so user can see the error
        setUploading(false);
      }
    } catch (err: any) {
      console.error('Upload error:', err);
      const findings = findingsFromError(err);
      setErrorFindings(findings);
      const errorMessage = readDetail(err.response?.data?.detail) ?? err.message ?? t('treeMapping.tab.msgUploadFailed');
      setError(findings ? null : errorMessage);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (confirmText?: string) => {
    if (!treeMapping?.id) return;

    if (!confirm(confirmText ?? t('treeMapping.tab.confirmDelete'))) {
      return;
    }

    try {
      setDeleting(true);
      await inventoryApi.deleteInventory(treeMapping.id);
      setTreeMapping(null);
      setError(null);
      onChanged?.('deleted');
    } catch (err: any) {
      setError(readDetail(err.response?.data?.detail) ?? t('treeMapping.tab.msgDeleteFailed'));
    } finally {
      setDeleting(false);
    }
  };

  const handleUpdateBlockSubarea = async () => {
    if (!treeMapping?.id) return;

    try {
      setUpdatingBlockSubarea(true);
      setError(null);
      const result = await inventoryApi.updateTreeBlockSubarea(treeMapping.id);
      alert(result.message || t('treeMapping.msgBlockUpdated'));
      // Reload tree data to see updated values
      loadTreeData(treeMapping.id);
      onChanged?.('updated');
    } catch (err: any) {
      setError(readDetail(err.response?.data?.detail) ?? t('treeMapping.blockUpdateFailed'));
    } finally {
      setUpdatingBlockSubarea(false);
    }
  };

  const handleAcceptCorrections = async () => {
    if (!correctionData || !file) return;

    try {
      setApplyingCorrections(true);
      setError(null);

      // Apply corrections
      console.log('Applying corrections for inventory:', correctionData.inventoryId);
      const result = await inventoryApi.acceptCorrections(correctionData.inventoryId, file);
      console.log('Corrections applied successfully:', result);

      // Close dialog
      setShowCorrectionDialog(false);
      setCorrectionData(null);

      // Show success message
      setValidationResult({
        ...correctionData.result,
        summary: {
          ...correctionData.result.summary,
          status: `Corrections applied (${result.corrections_count} trees). Processing tree mapping...`
        }
      });

// Process the inventory with corrected data
      await inventoryApi.processInventory(correctionData.inventoryId, file);

      // Reload tree mapping data
      await checkTreeMapping();
      setFile(null);
      setValidationResult(null);
      onChanged?.('processed');
    } catch (err: any) {
      console.error('Correction error:', err);
      console.error('Error response:', err.response);

      // Extract detailed error message. The backend can send a structured
      // {code, message, message_np} detail (i18n_error) rather than a plain
      // string — readDetail() picks the right language out of it; assigning
      // the raw object here crashed the whole tab ("Objects are not valid as
      // a React child") the one time accept-corrections actually failed.
      const errorMessage = readDetail(err.response?.data?.detail) ?? err.message ?? t('treeMapping.tab.msgCorrectionsFailed');

      setError(errorMessage);
      setShowCorrectionDialog(false);
    } finally {
      setApplyingCorrections(false);
    }
  };

  const handleCancelCorrections = () => {
    setShowCorrectionDialog(false);
    setCorrectionData(null);
    setFile(null);
    setValidationResult(null);
    setError(t('treeMapping.tab.msgUploadCancelled'));
  };

  const handleCancelMapping = () => {
    setShowColumnMapping(false);
    setColumnMappingData(null);
  };

  const handleExport = async (format: 'csv' | 'geojson') => {
    if (!treeMapping?.id) return;

    try {
      await downloadFromApi(
        `/api/inventory/${treeMapping.id}/export`,
        `TreeMapping_Data.${format}`,
        { format, module: 'TreeMapping' }
      );
    } catch (err: any) {
      setError(`Failed to export ${format.toUpperCase()}`);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600"></div>
      </div>
    );
  }

  // If tree mapping exists, show summary and delete option
  if (treeMapping) {
    return (
      <div className="space-y-6">
        {view !== 'results' && (
          <>
        {/* Header with Actions */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-1">{t('treeMapping.tab.title')}</h3>
              <p className="text-sm text-gray-600">{treeMapping.uploaded_filename}</p>
              <UploadStateLine present detail={treeMapping.uploaded_filename} className="mt-1" />
              <span className={`inline-block mt-2 px-3 py-1 rounded-full text-sm font-semibold ${
                treeMapping.status === 'completed' ? 'bg-green-100 text-green-800' :
                treeMapping.status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                'bg-gray-100 text-gray-800'
              }`}>
                {statusLabel(JOB_STATUS_KEY, treeMapping.status, t)}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => handleExport('csv')}
                className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm"
              >
                {t('treeMapping.tab.exportCsv')}
              </button>
              <button
                onClick={() => handleExport('geojson')}
                className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 text-sm"
              >
                {t('treeMapping.tab.exportGeojson')}
              </button>
              <button
                onClick={handleUpdateBlockSubarea}
                disabled={updatingBlockSubarea}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm disabled:bg-gray-400"
              >
                {updatingBlockSubarea ? t('treeMapping.tab.updating') : t('treeMapping.tab.updateBlockSubarea')}
              </button>
              <button
                onClick={() => handleDelete(t('uploadState.replaceConfirm', { file: treeMapping.uploaded_filename ?? '', date: treeMapping.created_at ? new Date(treeMapping.created_at).toLocaleDateString() : '' }))}
                disabled={deleting}
                data-testid="replace-data"
                className="px-4 py-2 bg-amber-600 text-white rounded-md hover:bg-amber-700 text-sm disabled:bg-gray-400"
              >
                {t('uploadState.replace')}
              </button>
              <button
                onClick={() => handleDelete()}
                disabled={deleting}
                className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm disabled:bg-gray-400"
              >
                {deleting ? t('treeMapping.tab.deleting') : t('common.delete')}
              </button>
            </div>
          </div>
        </div>
          </>
        )}

        {view !== 'data' && (
          <>
        {/* Summary Statistics */}
        {summary && (
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('treeMapping.tab.summaryStats')}</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-6">
              <div>
                <p className="text-sm text-gray-500">{t('treeMapping.col.totalTrees')}</p>
                <p className="mt-1 text-3xl font-bold text-gray-900">{summary.total_trees || 0}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">{t('treeMapping.col.motherTrees')}</p>
                <p className="mt-1 text-3xl font-bold text-green-600">{summary.mother_trees_count || 0}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">{t('treeMapping.col.fellingTrees')}</p>
                <p className="mt-1 text-3xl font-bold text-orange-600">{summary.felling_trees_count || 0}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">{t('treeMapping.tab.seedlings')}</p>
                <p className="mt-1 text-3xl font-bold text-blue-600">{summary.seedling_count || 0}</p>
              </div>
            </div>

            {/* Rows the import could not use (e.g. blank coordinates) -- previously dropped without a word */}
            {Array.isArray(treeMapping?.row_errors) && treeMapping.row_errors.length > 0 && (
              <div className="mb-6 p-3 bg-amber-50 border border-amber-300 rounded-md text-sm text-amber-900" data-testid="skipped-rows-note">
                <p className="font-medium">
                  {t('treeMapping.tab.skippedRows', { count: treeMapping.row_errors.length })}
                </p>
                <ul className="mt-1 list-disc list-inside">
                  {treeMapping.row_errors.slice(0, 5).map((e: { row_number: number; reason: string }) => (
                    <li key={e.row_number}>
                      {t('treeMapping.tab.skippedRowLine', { row: e.row_number, reason: e.reason })}
                    </li>
                  ))}
                </ul>
                {treeMapping.row_errors.length > 5 && (
                  <p className="mt-1">{t('treeMapping.tab.skippedRowsMore', { count: treeMapping.row_errors.length - 5 })}</p>
                )}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-gray-50 rounded-md">
                <p className="text-sm text-gray-500">{t('treeMapping.tab.totalVolume')}</p>
                <p className="mt-1 text-2xl font-bold text-gray-900">{formatDecimal((summary.total_volume_m3 || 0), 2)} m³</p>
              </div>
              <div className="p-4 bg-gray-50 rounded-md">
                <p className="text-sm text-gray-500">{t('treeMapping.tab.netVolume')}</p>
                <p className="mt-1 text-2xl font-bold text-gray-900">{formatDecimal((summary.total_net_volume_m3 || 0), 2)} m³</p>
                <p className="text-xs text-gray-500 mt-1">{formatDecimal((summary.total_net_volume_cft || 0), 2)} cft</p>
              </div>
              <div className="p-4 bg-gray-50 rounded-md">
                <p className="text-sm text-gray-500">{t('treeMapping.tab.firewood')}</p>
                <p className="mt-1 text-2xl font-bold text-gray-900">{formatDecimal((summary.total_firewood_m3 || 0), 2)} m³</p>
                <p className="text-xs text-gray-500 mt-1">{formatDecimal((summary.total_firewood_chatta || 0), 0)} chatta</p>
              </div>
            </div>
          </div>
        )}

        {/* Species and DBH Analysis Charts */}
        {summary && (summary.species_distribution || summary.dbh_classes) && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Species Distribution Pie Chart */}
            {summary.species_distribution && Object.keys(summary.species_distribution).length > 0 && (
              <div className="bg-white rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold mb-4">{t('treeMapping.tab.speciesDistribution')}</h3>
                <div style={{ width: '100%', height: 300 }}>
                  <Pie
                    height={300}
                    data={{
                      labels: Object.keys(summary.species_distribution),
                      datasets: [{
                        data: Object.values(summary.species_distribution).map((v) => Number(v)),
                        backgroundColor: Object.keys(summary.species_distribution).map((_, index) => COLORS[index % COLORS.length]),
                        borderColor: '#fff',
                        borderWidth: 1,
                      }],
                    }}
                    options={{
                      plugins: {
                        legend: { display: false },
                        tooltip: {
                          callbacks: {
                            label: (ctx) => {
                              const value = Number(ctx.parsed);
                              const total = Number(Object.values(summary.species_distribution).reduce((s: number, v: any) => s + Number(v), 0)) || 1;
                              const percent = ((value / total) * 100).toFixed(0);
                              return `${ctx.label}: ${value} (${percent}%)`;
                            },
                          },
                        },
                      },
                    }}
                  />
                </div>
              </div>
            )}

            {/* DBH Classes Bar Chart */}
            {summary.dbh_classes && Object.keys(summary.dbh_classes).length > 0 && (
              <div className="bg-white rounded-lg shadow p-6">
                <h3 className="text-lg font-semibold mb-4">{t('treeMapping.tab.dbhDistribution')}</h3>
                <div style={{ width: '100%', height: 300 }}>
                  <Bar
                    height={300}
                    data={{
                      labels: Object.keys(summary.dbh_classes),
                      datasets: [{
                        label: 'Trees',
                        data: Object.values(summary.dbh_classes).map((v) => Number(v)),
                        backgroundColor: '#22c55e',
                      }],
                    }}
                    options={{
                      plugins: { legend: { display: false } },
                      scales: {
                        x: { grid: { display: true } },
                        y: { beginAtZero: true },
                      },
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tabular Species and DBH Summary */}
        {summary && (summary.species_distribution || summary.dbh_classes) && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Species Table */}
            {summary.species_distribution && Object.keys(summary.species_distribution).length > 0 && (
              <div className="bg-white rounded-lg shadow overflow-hidden">
                <h3 className="text-lg font-semibold px-6 py-4 border-b">{t('treeMapping.tab.speciesSummary')}</h3>
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.species')}</th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.count')}</th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">%</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {Object.entries(summary.species_distribution).map(([species, count]: [string, any], idx: number) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-4 py-2 text-sm">{species}</td>
                        <td className="px-4 py-2 text-sm text-right font-medium">{Number(count)}</td>
                        <td className="px-4 py-2 text-sm text-right text-gray-500">{formatDecimal(((Number(count) / summary.total_trees) * 100), 1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* DBH Classes Table */}
            {summary.dbh_classes && Object.keys(summary.dbh_classes).length > 0 && (
              <div className="bg-white rounded-lg shadow overflow-hidden">
                <h3 className="text-lg font-semibold px-6 py-4 border-b">{t('treeMapping.tab.dbhSummary')}</h3>
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.dbhClass')}</th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.count')}</th>
                      <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 uppercase">%</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {Object.entries(summary.dbh_classes).map(([dbhClass, count]: [string, any], idx: number) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-4 py-2 text-sm">{dbhClass}</td>
                        <td className="px-4 py-2 text-sm text-right font-medium">{Number(count)}</td>
                        <td className="px-4 py-2 text-sm text-right text-gray-500">{formatDecimal(((Number(count) / summary.total_trees) * 100), 1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tree Mapping Analysis */}
        {summary && summary.total_trees > 0 && treeMapping?.id && (
          <TreeMappingAnalysis mappingId={treeMapping.id} />
        )}
          </>
        )}

        {view !== 'results' && (
          <>
        {/* Tree Data Preview */}
        {trees && trees.length > 0 && (
          <div className="bg-white rounded-lg shadow overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold">Tree Data Preview ({trees.length} of {summary?.total_trees || 0})</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.species')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.dbhCm')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.heightM')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.volumeM3')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.block')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.subArea')}</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('treeMapping.col.remark')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {trees.map((tree: any, idx: number) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-4 py-2 text-sm">{tree.species || '-'}</td>
                      <td className="px-4 py-2 text-sm">{tree.dia_cm ? formatDecimal(tree.dia_cm, 1) : '-'}</td>
                      <td className="px-4 py-2 text-sm">{tree.height_m ? formatDecimal(tree.height_m, 1) : '-'}</td>
                      <td className="px-4 py-2 text-sm">{tree.tree_volume ? formatDecimal(tree.tree_volume, 3) : '-'}</td>
                      <td className="px-4 py-2 text-sm text-blue-600">{tree.block_name || '-'}</td>
                      <td className="px-4 py-2 text-sm text-purple-600">{tree.sub_area_name || '-'}</td>
                      <td className="px-4 py-2 text-sm">
                        <span className={`px-2 py-1 rounded text-xs ${
                          tree.remark === 'Mother' ? 'bg-green-100 text-green-800' :
                          tree.remark === 'Felling' ? 'bg-orange-100 text-orange-800' :
                          tree.remark === 'Seedling' ? 'bg-blue-100 text-blue-800' :
                          'bg-gray-100 text-gray-800'
                        }`}>
                          {t(REMARK_LABEL_KEY[tree.remark || 'Normal'] ?? 'treeMapping.remark.normal')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
          </>
        )}

        {loadingData && (
          <div className="bg-white rounded-lg shadow p-8 text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mx-auto"></div>
            <p className="mt-4 text-gray-600">{t('treeMapping.tab.loadingTreeData')}</p>
          </div>
        )}
      </div>
    );
  }

  // If no tree mapping exists, show upload form
  //
  // Data-only. The host locks the Results pane while the step has no data, so
  // this should be unreachable from there; the guard makes that a fact rather
  // than a hope, because the alternative is a Results tab offering to upload a
  // file the moment readiness and the file disagree.
  if (view === 'results') {
    return (
      <div className="bg-white rounded-lg shadow p-6 text-sm text-gray-600" data-testid="treemapping-results-empty">
        {t('treeMapping.tab.noDataForResults')}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}
      {errorFindings && <UploadReport findings={errorFindings} />}

      {validationResult && (
        <div className={`border rounded-lg p-6 ${
          validationResult.summary?.ready_for_processing
            ? 'bg-green-50 border-green-200'
            : 'bg-red-50 border-red-200'
        }`}>
          <h3 className="font-semibold mb-2 text-lg">
            {validationResult.summary?.ready_for_processing ? t('treeMapping.tab.validationSuccess') : t('treeMapping.tab.validationFailed')}
          </h3>

          {/* What is wrong and how to fix it, in plain words; and where the points fall (UP-2 / UP-3) */}
          {!validationResult.summary?.ready_for_processing && findingsFromBody(validationResult).length > 0 && (
            <UploadReport findings={findingsFromBody(validationResult)} />
          )}
          {validationResult.preview && <UploadPointsPreview preview={validationResult.preview} />}

          {/* Show errors if validation failed */}
          {!validationResult.summary?.ready_for_processing && findingsFromBody(validationResult).length === 0 && validationResult.errors && validationResult.errors.length > 0 && (
            <div className="space-y-2">
              {validationResult.errors.map((err: any, idx: number) => (
                <div key={idx} className="bg-red-100 border border-red-300 rounded-md p-3">
                  <p className="text-sm font-medium text-red-800">{err.type || 'Error'}</p>
                  <p className="text-sm text-red-700 mt-1">{err.message}</p>
                </div>
              ))}

              {/* Boundary check details */}
              {validationResult.boundary_check && (
                <div className="mt-4 p-3 bg-white rounded-md border border-red-200">
                  <h4 className="text-sm font-semibold text-gray-900 mb-2">{t('treeMapping.tab.boundaryCheckDetails')}</h4>
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <span className="text-gray-600">{t('treeMapping.tab.totalPoints')}</span>
                      <span className="ml-2 font-semibold">{validationResult.boundary_check.total_points}</span>
                    </div>
                    <div>
                      <span className="text-gray-600">{t('treeMapping.tab.outsideBoundary')}</span>
                      <span className="ml-2 font-semibold text-red-600">
                        {validationResult.boundary_check.out_of_boundary_count} ({validationResult.boundary_check.out_of_boundary_percentage}%)
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-600">{t('treeMapping.tab.withinTolerance')}</span>
                      <span className="ml-2 font-semibold">
                        {validationResult.boundary_check.within_tolerance ? 'Yes' : 'No'}
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Show status if ready for processing */}
          {validationResult.summary?.ready_for_processing && (
            <p className="text-sm text-green-700">
              {validationResult.summary?.status || t('treeMapping.tab.readyForProcessing')}
            </p>
          )}
        </div>
      )}

      {/* Under shelterwood: which block / compartment has the most growing stock of trees of 40 cm and above (renders nothing otherwise) */}
      <StemMappingSuggestion calculationId={calculationId} />

      {/* Step 1: Download Template */}
      <div className="bg-white border rounded-lg p-6">
        <div className="flex items-start">
          <div className="flex-shrink-0">
            <div className="flex items-center justify-center h-10 w-10 rounded-full bg-green-100 text-green-600 font-bold">
              1
            </div>
          </div>
          <div className="ml-4 flex-1">
            <h3 className="text-lg font-semibold text-gray-900">{t('treeMapping.tab.downloadTemplate')}</h3>
            <p className="mt-1 text-sm text-gray-600">
              {t('treeMapping.tab.downloadTemplateHint')}
            </p>
            <button
              onClick={handleDownloadTemplate}
              className="mt-3 inline-flex items-center px-4 py-2 border border-green-600 text-sm font-medium rounded-md text-green-600 bg-white hover:bg-green-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500"
            >
              <svg className="w-4 h-4 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              {t('treeMapping.tab.downloadTemplate')}
            </button>
          </div>
        </div>
      </div>

      {/* Step 2: Upload File */}
      <div className="bg-white border rounded-lg p-6">
        <div className="flex items-start">
          <div className="flex-shrink-0">
            <div className="flex items-center justify-center h-10 w-10 rounded-full bg-green-100 text-green-600 font-bold">
              2
            </div>
          </div>
          <div className="ml-4 flex-1">
            <h3 className="text-lg font-semibold text-gray-900">{t('treeMapping.tab.uploadCsvFile')}</h3>
            <UploadStateLine present={false} className="mt-1" />
            <p className="mt-1 text-sm text-gray-600">
              {t('treeMapping.tab.uploadCsvHint')}
            </p>

            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  {t('treeMapping.tab.csvExcelFile')}
                </label>
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,.gpkg"
                  onChange={handleFileChange}
                  className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold file:bg-green-50 file:text-green-700 hover:file:bg-green-100"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('treeMapping.tab.gridSpacing')}
                  </label>
                  <input
                    type="text" inputMode="decimal"
                    value={gridSpacing}
                    onChange={(e) => setGridSpacing(parseLocaleNumber(e.target.value))}
                    min="10"
                    max="100"
                    className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-green-500 focus:border-green-500"
                  />
                  <p className="mt-1 text-xs text-gray-500">{t('treeMapping.tab.gridSpacingHint')}</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('treeMapping.tab.projectionEpsg')}
                  </label>
                  <input
                    type="text"
                    value={projectionEpsg}
                    onChange={(e) => setProjectionEpsg(e.target.value)}
                    placeholder={t('treeMapping.tab.epsgPlaceholder')}
                    className="block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-green-500 focus:border-green-500"
                  />
                  <p className="mt-1 text-xs text-gray-500">{t('treeMapping.tab.projectionHint')}</p>
                </div>
              </div>

              <button
                onClick={handleUpload}
                disabled={!file || uploading}
                className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:bg-gray-400 disabled:cursor-not-allowed"
              >
                {uploading ? (
                  <span className="flex items-center">
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    {t('treeMapping.tab.processing')}
                  </span>
                ) : (
                  t('treeMapping.tab.uploadAndProcess')
                )}
              </button>
              
              {/* Show delete option if tree mapping exists - use force delete to remove any user's data */}
              {(treeMapping?.id) && (
                <button
                  onClick={forceDeletePrevious}
                  disabled={deleting}
                  className="mt-3 w-full flex justify-center py-2 px-4 border border-red-300 rounded-md shadow-sm text-sm font-medium text-red-600 bg-white hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:bg-gray-100"
                >
                  {deleting ? t('treeMapping.tab.deleting') : t('treeMapping.tab.deletePrevious')}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <h4 className="text-sm font-semibold text-blue-900 mb-2">{t('treeMapping.tab.requiredColumns')}</h4>
        <ul className="text-sm text-blue-800 space-y-1 list-disc list-inside">
          <li>{t('treeMapping.tab.colSpeciesHint')}</li>
          <li>{t('treeMapping.tab.colDbhHint')}</li>
          <li>{t('treeMapping.tab.colHeightHint')}</li>
          <li>{t('treeMapping.tab.colCoordsHint')}</li>
        </ul>
      </div>

      {/* Correction Preview Dialog */}
      {showCorrectionDialog && correctionData?.boundaryCheck && (
        <CorrectionPreviewDialog
          boundaryCheck={correctionData.boundaryCheck}
          corrections={correctionData.boundaryCheck.corrections || []}
          summary={correctionData.boundaryCheck.correction_summary || {
            total_corrections: 0,
            max_distance: 0,
            min_distance: 0,
            avg_distance: 0
          }}
          onAccept={handleAcceptCorrections}
          onCancel={handleCancelCorrections}
          isProcessing={applyingCorrections}
        />
      )}

      {/* Column Mapping Modal */}
      {showColumnMapping && columnMappingData && (
        <ColumnMappingPreview
          previewData={columnMappingData}
          onConfirm={handleConfirmMapping}
          onCancel={handleCancelMapping}
        />
      )}
    </div>
  );
}
