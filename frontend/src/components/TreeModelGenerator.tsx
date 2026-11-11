/** TreeModelGenerator — tree model generation with export controls and status tracking. */
import React, { useState, useEffect } from 'react';
import { ChevronDown, ChevronUp, Download, Trash2, AlertCircle, CheckCircle, Clock, Loader, FileSpreadsheet, Map } from 'lucide-react';
import api, { allTreeExportApi, exportCleanupApi } from '../services/api';
import { downloadFromApi } from '../utils/download';
import { useDimensionLabels } from '../hooks/useDimensionLabels';
import { useT } from '../i18n/hooks';
import { formatDecimal, formatNumber, parseLocaleNumber } from '../i18n/numberFormat';
import { useWorkspaceStore } from '../store/workspaceStore';
import { apiErrorText } from '../lib/apiErrorText';

// Layers whose features are forest_blocks rows (feature id = forest_blocks.id)
const UNIT_LAYER_IDS = ['blocks', 'sub_blocks', 'compartments', 'sub_compartments'];

interface TreeModelConfig {
  min_dbh_cm: number;
  min_height_m: number;
  max_trees_per_ha: number;
  spatial_distribution: string;
  plot_buffer_meters: number;
  algorithm_version: string;
}

interface TreeModel {
  id: string;
  calculation_id: string;
  model_version: string;
  algorithm_config?: any;
  status: 'processing' | 'completed' | 'failed';
  progress_percent: number;
  current_step: string;
  total_trees: number | null;
  area_hectares: number | null;
  trees_per_hectare: number | null;
  min_dbh_cm: number | null;
  max_dbh_cm: number | null;
  min_height_m: number | null;
  max_height_m: number | null;
  gpkg_filename: string | null;
  file_size_mb: number | null;
  excel_filename: string | null;
  excel_size_mb: number | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  processing_time_seconds: number | null;
}

interface TreeModelGeneratorProps {
  calculationId: string;
  forestName?: string;
  onRefresh?: () => void | Promise<void>;
  hasCompartments?: boolean;
}

const TreeModelGenerator: React.FC<TreeModelGeneratorProps> = ({ calculationId, forestName, onRefresh, hasCompartments }) => {
  const t = useT();
  const labels = useDimensionLabels({ hasCompartments: hasCompartments || false });
  const [expanded, setExpanded] = useState(false);
  const [models, setModels] = useState<TreeModel[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Configuration state
  const [config, setConfig] = useState<TreeModelConfig>({
    min_dbh_cm: 10.0,
    min_height_m: 5.0,
    max_trees_per_ha: 500,
    spatial_distribution: 'random',
    plot_buffer_meters: 12.62,
    algorithm_version: 'v1.0'
  });

  // Polling for progress updates
  const [pollingId, setPollingId] = useState<string | null>(null);

  // Load existing models
  const loadModels = async () => {
    try {
      setLoading(true);
      const response = await api.get(`/api/calculations/${calculationId}/tree-models`);  // Fixed: Added /api prefix
      setModels(response.data.models || []);
    } catch (err: any) {
      console.error('Error loading tree models:', err);
    } finally {
      setLoading(false);
    }
  };

  // Initial load when expanded
  useEffect(() => {
    if (expanded) {
      loadModels();
    }
  }, [expanded, calculationId]);

  // Polling for progress
  useEffect(() => {
    if (!pollingId) return;

    const interval = setInterval(async () => {
      try {
        const response = await api.get(`/api/tree-models/${pollingId}`);  // Fixed: Added /api prefix
        const model = response.data;

        // Update model in list
        setModels(prev =>
          prev.map(m => m.id === model.id ? model : m)
        );

        // Stop polling if completed or failed
        if (model.status === 'completed' || model.status === 'failed') {
          setPollingId(null);
          setGenerating(false);
          onRefresh?.();
        }
      } catch (err) {
        console.error('Error polling model status:', err);
      }
    }, 3000); // Poll every 3 seconds

    return () => clearInterval(interval);
  }, [pollingId, onRefresh]);

  // Generate tree model
  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);

      const response = await api.post(
        `/api/calculations/${calculationId}/generate-tree-model`,  // Fixed: Added /api prefix
        { config }
      );

      const newModel = response.data;
      setModels(prev => [newModel, ...prev]);
      setPollingId(newModel.id);

    } catch (err: any) {
      setError(apiErrorText(err, t('treeMapping.model.msgGenerateFailed')));
      setGenerating(false);
    }
  };

  // Download model (GPKG)
  const handleDownload = async (modelId: string) => {
    try {
      await downloadFromApi(`/api/tree-models/${modelId}/download`, 'tree_model.gpkg');
    } catch (err: any) {
      alert('Failed to download file: ' + (err.response?.data?.detail || err.message));
    }
  };

  // Download Excel
  const handleDownloadExcel = async (modelId: string) => {
    try {
      await downloadFromApi(`/api/tree-models/${modelId}/download-excel`, 'tree_model.xlsx');
    } catch (err: any) {
      alert('Failed to download Excel file: ' + (err.response?.data?.detail || err.message));
    }
  };

  // Delete model
  const handleDelete = async (modelId: string) => {
    if (!confirm(t('treeMapping.model.confirmDeleteModel'))) return;

    try {
      await api.delete(`/api/tree-models/${modelId}`);  // Fixed: Added /api prefix
      setModels(prev => prev.filter(m => m.id !== modelId));
    } catch (err: any) {
      alert('Failed to delete model: ' + (err.response?.data?.detail || err.message));
    }
  };

  // Format file size
  const formatFileSize = (mb: number) => {
    if (mb < 1) return `${formatDecimal((mb * 1024), 0)} KB`;
    return `${formatDecimal(mb, 2)} MB`;
  };

  // Format duration
  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}m ${secs}s`;
  };

  return (
    <div className="mt-6 border border-gray-200 rounded-lg bg-white">
      {/* Header - Always Visible */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-green-100 flex items-center justify-center">
            <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
            </svg>
          </div>
          <div className="text-left">
            <h3 className="text-lg font-semibold text-gray-900">
              {t('treeMapping.model.title')}
            </h3>
            <p className="text-sm text-gray-500">
              {t('treeMapping.model.subtitle')}
            </p>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="w-5 h-5 text-gray-400" />
        ) : (
          <ChevronDown className="w-5 h-5 text-gray-400" />
        )}
      </button>

      {/* Expanded Content */}
      {expanded && (
        <div className="px-6 pb-6 border-t border-gray-200">
          {/* Description */}
          <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <div className="flex gap-3">
              <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
              <div className="text-sm text-blue-900">
                <p className="font-medium mb-1">{t('treeMapping.model.whatIsThis')}</p>
                <p className="mb-2">
                  {t('treeMapping.model.intro')}
                </p>
                <p className="font-medium text-orange-700 mb-1">📋 Requirement:</p>
                <p className="mb-2 text-orange-900">
                  {t('treeMapping.model.requirement')}
                </p>
                <p className="font-medium text-red-700 mb-1">⚠️ Important Disclaimer:</p>
                <ul className="list-disc list-inside space-y-1 text-red-900">
                  <li>{t('treeMapping.model.disclaimer1')}</li>
                  <li>{t('treeMapping.model.disclaimer2')}</li>
                  <li>{t('treeMapping.model.disclaimer3')}</li>
                  <li>{t('treeMapping.model.disclaimer4')}</li>
                </ul>
              </div>
            </div>
          </div>

          {/* Configuration Form */}
          <div className="mt-6">
            <h4 className="text-md font-semibold text-gray-900 mb-3">{t('treeMapping.model.configuration')}</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('treeMapping.model.minDbh')}
                </label>
                <input
                  type="text" inputMode="decimal"
                  value={config.min_dbh_cm}
                  onChange={(e) => setConfig({ ...config, min_dbh_cm: parseLocaleNumber(e.target.value) })}
                  min="5"
                  max="50"
                  step="0.1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
                  disabled={generating}
                />
                <p className="text-xs text-gray-500 mt-1">{t('treeMapping.model.minDbhHint')}</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('treeMapping.model.minHeight')}
                </label>
                <input
                  type="text" inputMode="decimal"
                  value={config.min_height_m}
                  onChange={(e) => setConfig({ ...config, min_height_m: parseLocaleNumber(e.target.value) })}
                  min="2"
                  max="20"
                  step="0.1"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
                  disabled={generating}
                />
                <p className="text-xs text-gray-500 mt-1">{t('treeMapping.model.minHeightHint')}</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('treeMapping.model.maxTreesHa')}
                </label>
                <input
                  type="text" inputMode="decimal"
                  value={config.max_trees_per_ha}
                  onChange={(e) => setConfig({ ...config, max_trees_per_ha: Math.trunc(parseLocaleNumber(e.target.value)) })}
                  min="50"
                  max="5000"
                  step="50"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
                  disabled={generating}
                />
                <p className="text-xs text-gray-500 mt-1">{t('treeMapping.model.maxTreesHaHint')}</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('treeMapping.model.plotBuffer')}
                </label>
                <input
                  type="text" inputMode="decimal"
                  value={config.plot_buffer_meters}
                  onChange={(e) => setConfig({ ...config, plot_buffer_meters: parseLocaleNumber(e.target.value) })}
                  min="5"
                  max="100"
                  step="0.01"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
                  disabled={generating}
                />
                <p className="text-xs text-gray-500 mt-1">{t('treeMapping.model.plotBufferHint')}</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('treeMapping.model.spatialDistribution')}
                </label>
                <select
                  value={config.spatial_distribution}
                  onChange={(e) => setConfig({ ...config, spatial_distribution: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-green-500 focus:border-green-500"
                  disabled={generating}
                >
                  <option value="random">{t('treeMapping.model.random')}</option>
                  <option value="clustered" disabled>{t('treeMapping.model.clustered')}</option>
                  <option value="regular" disabled>{t('treeMapping.model.regular')}</option>
                </select>
                <p className="text-xs text-gray-500 mt-1">{t('treeMapping.model.spatialHint')}</p>
              </div>
            </div>

            {/* Error Display */}
            {error && (
              <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
                <p className="text-sm text-red-800">{error}</p>
              </div>
            )}

            {/* Generate Button */}
            <div className="mt-6">
              <button
                onClick={handleGenerate}
                disabled={generating}
                className={`w-full md:w-auto px-6 py-3 rounded-md font-medium transition-colors ${
                  generating
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-green-600 text-white hover:bg-green-700'
                }`}
              >
                {generating ? (
                  <span className="flex items-center gap-2">
                    <Loader className="w-5 h-5 animate-spin" />
                    {t('treeMapping.model.generating')}
                  </span>
                ) : (
                  t('treeMapping.model.generate')
                )}
              </button>
              {generating && (
                <p className="mt-2 text-sm text-gray-600">
                  This may take 5-10 minutes depending on forest size. You can close this and check back later.
                </p>
              )}
            </div>
          </div>

          {/* Models List */}
          <div className="mt-8">
            <h4 className="text-md font-semibold text-gray-900 mb-3">
              Generated Models ({models.length})
            </h4>

            {loading ? (
              <div className="text-center py-8 text-gray-500">
                <Loader className="w-6 h-6 animate-spin mx-auto mb-2" />
                {t('treeMapping.model.loadingModels')}
              </div>
            ) : models.length === 0 ? (
              <div className="text-center py-8 text-gray-500">
                <p>{t('treeMapping.model.noModels')}</p>
                <p className="text-sm mt-1">Click "Generate Tree Model" above to create your first model.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {models.map((model) => (
                  <div
                    key={model.id}
                    className="border border-gray-200 rounded-lg p-4 bg-gray-50"
                  >
                    {/* Status Header */}
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2">
                        {model.status === 'completed' && (
                          <CheckCircle className="w-5 h-5 text-green-600" />
                        )}
                        {model.status === 'processing' && (
                          <Loader className="w-5 h-5 text-blue-600 animate-spin" />
                        )}
                        {model.status === 'failed' && (
                          <AlertCircle className="w-5 h-5 text-red-600" />
                        )}
                        <span className={`font-medium ${
                          model.status === 'completed' ? 'text-green-700' :
                          model.status === 'processing' ? 'text-blue-700' :
                          'text-red-700'
                        }`}>
                          {model.status.toUpperCase()}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Clock className="w-4 h-4 text-gray-400" />
                        <span className="text-sm text-gray-500">
                          {new Date(model.created_at).toLocaleString()}
                        </span>
                      </div>
                    </div>

                    {/* Progress Bar (if processing) */}
                    {model.status === 'processing' && (
                      <div className="mb-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm text-gray-600">{model.current_step}</span>
                          <span className="text-sm font-medium text-gray-700">{model.progress_percent}%</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-2">
                          <div
                            className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                            style={{ width: `${model.progress_percent}%` }}
                          />
                        </div>
                      </div>
                    )}


                    {/* Statistics (if completed) */}
                    {model.status === 'completed' && model.total_trees && (
                      <>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                          <div>
                            <p className="text-xs text-gray-500">{t('treeMapping.col.totalTrees')}</p>
                            <p className="text-sm font-semibold text-gray-900">
                              {formatNumber(model.total_trees)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-gray-500">{t('treeMapping.col.treesPerHa')}</p>
                            <p className="text-sm font-semibold text-gray-900">
                              {formatDecimal(model.trees_per_hectare, 1)}
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-gray-500">{t('treeMapping.model.dbhRange')}</p>
                            <p className="text-sm font-semibold text-gray-900">
                              {formatDecimal(model.min_dbh_cm, 1)} - {formatDecimal(model.max_dbh_cm, 1)} cm
                            </p>
                          </div>
                          <div>
                            <p className="text-xs text-gray-500">{t('treeMapping.model.fileSize')}</p>
                            <p className="text-sm font-semibold text-gray-900">
                              {model.file_size_mb ? formatFileSize(model.file_size_mb) : 'N/A'}
                            </p>
                          </div>
                        </div>

                        {/* Overall DBH Class Density per Hectare */}
                        {model.algorithm_config?.dbh_per_ha && (
                          <>
                          <p className="text-xs font-medium text-green-700 mb-2">
                            {forestName} ({model.algorithm_config.total_sample_plots} plots): Overall Stand Summary (per hectare)
                          </p>
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3 p-3 bg-green-50 rounded-lg border border-green-200">
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.seedlingHa')}</p>
                              <p className="text-sm font-bold text-green-800">
                                {model.algorithm_config.dbh_per_ha.regeneration_1_4cm?.toLocaleString() || '0'}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.saplingHa')}</p>
                              <p className="text-sm font-bold text-green-700">
                                {model.algorithm_config.dbh_per_ha.sapling_4_10cm?.toLocaleString() || '0'}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.poleHa')}</p>
                              <p className="text-sm font-bold text-blue-800">
                                {model.algorithm_config.dbh_per_ha.pole_10_30cm?.toLocaleString() || '0'}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">Tree (&gt;30cm)/ha</p>
                              <p className="text-sm font-bold text-purple-800">
                                {model.algorithm_config.dbh_per_ha.tree_above_30cm?.toLocaleString() || '0'}
                              </p>
                            </div>
                          </div>
                        </>
                        )}

                        {/* Overall Volume Summary */}
                        {model.algorithm_config && (
                          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3 p-3 bg-amber-50 rounded-lg border border-amber-200">
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.poleTimberHa')}</p>
                              <p className="text-sm font-bold text-amber-800">
                                {model.algorithm_config.pole_timber_m3_per_ha != null ? formatDecimal(model.algorithm_config.pole_timber_m3_per_ha, 1) : '0'} m³/ha
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.poleFuelHa')}</p>
                              <p className="text-sm font-bold text-orange-700">
                                {model.algorithm_config.pole_firewood_m3_per_ha != null ? formatDecimal(model.algorithm_config.pole_firewood_m3_per_ha, 1) : '0'} m³/ha
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.treeTimberHa')}</p>
                              <p className="text-sm font-bold text-amber-900">
                                {model.algorithm_config.tree_timber_m3_per_ha != null ? formatDecimal(model.algorithm_config.tree_timber_m3_per_ha, 1) : '0'} m³/ha
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">{t('treeMapping.model.treeFuelHa')}</p>
                              <p className="text-sm font-bold text-orange-800">
                                {model.algorithm_config.tree_firewood_m3_per_ha != null ? formatDecimal(model.algorithm_config.tree_firewood_m3_per_ha, 1) : '0'} m³/ha
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-gray-600">pole & tree net timber and firewood volume (m³)/ha</p>
                              <p className="text-sm font-bold text-red-800">
                                {model.algorithm_config.volume_per_ha != null ? formatDecimal(model.algorithm_config.volume_per_ha, 1) : '0'} m³/ha
                              </p>
                            </div>
                          </div>
                        )}

                        {/* Block/Compartment-wise DBH Class Distribution (Per Hectare) - hide in compartment mode since the overall summary covers it */}
                        {!hasCompartments && model.algorithm_config?.block_dbh_distribution && (
                          <div className="mb-3">
                            <p className="text-xs text-gray-500 mb-2">Stand Density & Volume by {labels.unitLabelPlural} (per hectare):</p>
                            <div className="space-y-2">
                              {Object.entries(model.algorithm_config.block_dbh_distribution).map(([blockName, blockData]: [string, any]) => (
                                <div key={blockName} className="bg-gray-50 p-2 rounded">
                                  <p className="text-xs font-medium text-gray-700 mb-1">{blockName} ({blockData.num_plots} plots):</p>
                                  <div className="flex flex-wrap gap-1.5">
                                    {/* Volume breakdown per hectare */}
                                    {blockData.pole_timber_m3_per_ha > 0 && (
                                      <span className="px-2 py-0.5 bg-amber-100 text-amber-800 text-xs rounded-full">
                                        Pole Net Timber Volume (m³)/ha: {formatDecimal(blockData.pole_timber_m3_per_ha, 1)}
                                      </span>
                                    )}
                                    {blockData.pole_firewood_m3_per_ha > 0 && (
                                      <span className="px-2 py-0.5 bg-orange-100 text-orange-800 text-xs rounded-full">
                                        Pole Fuelwood Volume (m³)/ha: {formatDecimal(blockData.pole_firewood_m3_per_ha, 1)}
                                      </span>
                                    )}
                                    {blockData.tree_timber_m3_per_ha > 0 && (
                                      <span className="px-2 py-0.5 bg-amber-200 text-amber-900 text-xs rounded-full">
                                        Tree Net Timber Volume (m³)/ha: {formatDecimal(blockData.tree_timber_m3_per_ha, 1)}
                                      </span>
                                    )}
                                    {blockData.tree_firewood_m3_per_ha > 0 && (
                                      <span className="px-2 py-0.5 bg-orange-200 text-orange-900 text-xs rounded-full">
                                        Tree Fuelwood Volume (m³)/ha: {formatDecimal(blockData.tree_firewood_m3_per_ha, 1)}
                                      </span>
                                    )}
                                    {/* Total volume per hectare - prominent display */}
                                    {blockData.volume_per_ha !== undefined && blockData.volume_per_ha > 0 && (
                                      <span className="px-2 py-0.5 bg-red-100 text-red-900 text-xs rounded-full font-semibold">
                                        pole & tree net timber and firewood volume (m³)/ha: {formatDecimal(blockData.volume_per_ha, 1)}
                                      </span>
                                    )}
                                    {blockData.dbh_per_ha?.regeneration_1_4cm > 0 && (
                                      <span className="px-2 py-0.5 bg-green-100 text-green-800 text-xs rounded-full">
                                        Seedling (1-4cm): {formatNumber(blockData.dbh_per_ha.regeneration_1_4cm)}
                                      </span>
                                    )}
                                    {blockData.dbh_per_ha?.sapling_4_10cm > 0 && (
                                      <span className="px-2 py-0.5 bg-green-200 text-green-900 text-xs rounded-full">
                                        Sapling (4-10cm): {formatNumber(blockData.dbh_per_ha.sapling_4_10cm)}
                                      </span>
                                    )}
                                    {blockData.dbh_per_ha?.pole_10_30cm > 0 && (
                                      <span className="px-2 py-0.5 bg-blue-100 text-blue-800 text-xs rounded-full">
                                        Pole (10-30cm): {formatNumber(blockData.dbh_per_ha.pole_10_30cm)}
                                      </span>
                                    )}
                                    {blockData.dbh_per_ha?.tree_above_30cm > 0 && (
                                      <span className="px-2 py-0.5 bg-purple-100 text-purple-800 text-xs rounded-full">
                                        Tree (&gt;30cm): {formatNumber(blockData.dbh_per_ha.tree_above_30cm)}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </>
                    )}

                    {/* Error Message (if failed) */}
                    {model.status === 'failed' && model.error_message && (
                      <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-800">
                        {model.error_message}
                          </div>
                        )}

                    {/* Actions */}
                    <div className="flex items-center gap-2 flex-wrap">
                      {model.status === 'completed' && model.gpkg_filename && (
                        <button
                          onClick={() => handleDownload(model.id)}
                          className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors flex items-center gap-2 text-sm"
                        >
                          <Download className="w-4 h-4" />
                          {t('treeMapping.model.downloadGpkg')}
                          {model.file_size_mb && <span className="text-xs opacity-80">({formatFileSize(model.file_size_mb)})</span>}
                        </button>
                      )}
                      {model.status === 'completed' && model.excel_filename && (
                        <button
                          onClick={() => handleDownloadExcel(model.id)}
                          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors flex items-center gap-2 text-sm"
                        >
                          <FileSpreadsheet className="w-4 h-4" />
                          {t('treeMapping.model.downloadExcel')}
                          {model.excel_size_mb && <span className="text-xs opacity-80">({formatFileSize(model.excel_size_mb)})</span>}
                        </button>
                      )}

                      <button
                        onClick={() => handleDelete(model.id)}
                        className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors flex items-center gap-2 text-sm"
                      >
                        <Trash2 className="w-4 h-4" />
                        Delete
                      </button>
                      {model.processing_time_seconds && (
                        <span className="ml-auto text-sm text-gray-500">
                          Processing time: {formatDuration(model.processing_time_seconds)}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};


// ═══════════════════════════════════════════════════════════════════════════
// Total Tree Export Accordion — separate collapsible section
// ═══════════════════════════════════════════════════════════════════════════

export const TotalTreeExportAccordion: React.FC<{ calculationId: string }> = ({ calculationId }) => {
  const t = useT();
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mt-4 border border-gray-200 rounded-lg bg-white">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-full bg-purple-100 flex items-center justify-center">
            <FileSpreadsheet className="w-6 h-6 text-purple-600" />
          </div>
          <div className="text-left">
            <h3 className="text-lg font-semibold text-gray-900">
              {t('treeMapping.model.allTreesTitle')}
            </h3>
            <p className="text-sm text-gray-500">
              {t('treeMapping.model.allTreesSubtitle')}
            </p>
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="w-5 h-5 text-gray-400" />
        ) : (
          <ChevronDown className="w-5 h-5 text-gray-400" />
        )}
      </button>

      {expanded && (
        <div className="px-6 pb-6 border-t border-gray-200">
          {/* Description */}
          <div className="mt-4 p-4 bg-purple-50 border border-purple-200 rounded-lg">
            <div className="flex gap-3">
              <AlertCircle className="w-5 h-5 text-purple-600 flex-shrink-0 mt-0.5" />
              <div className="text-sm text-purple-900">
                <p className="font-medium mb-1">{t('treeMapping.model.whatIsThis')}</p>
                <p className="mb-2">
                  {t('treeMapping.model.allTreesIntro')}
                </p>
                <ul className="list-disc list-inside space-y-1">
                  <li>{t('treeMapping.model.allTreesFormat')}</li>
                  <li>{t('treeMapping.model.allTreesOutput')}</li>
                  <li>{t('treeMapping.model.allTreesNoPlots')}</li>
                </ul>
              </div>
            </div>
          </div>

          <div className="mt-6">
            <AllTreeExportSection calculationId={calculationId} />
          </div>
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// All Tree Export Section — internal component (used by TotalTreeExportAccordion)
// ═══════════════════════════════════════════════════════════════════════════

interface AllTreeExportItem {
  id: string;
  calculation_id: string;
  model_type: string;
  model_version: string;
  algorithm_config?: any;
  status: 'processing' | 'completed' | 'failed';
  progress_percent: number;
  current_step: string;
  total_trees: number | null;
  area_hectares: number | null;
  trees_per_hectare: number | null;
  min_dbh_cm: number | null;
  max_dbh_cm: number | null;
  min_height_m: number | null;
  max_height_m: number | null;
  gpkg_filename: string | null;
  gpkg_size_mb: number | null;
  excel_filename: string | null;
  excel_size_mb: number | null;
  csv_filename: string | null;
  csv_size_mb: number | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
  processing_time_seconds: number | null;
  /** Server deletes the export at this time (1 hour after it finishes); null while running */
  expires_at?: string | null;
}

const AllTreeExportSection: React.FC<{ calculationId: string }> = ({ calculationId }) => {
  const t = useT();
  const [exports, setExports] = useState<AllTreeExportItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useRatioOverride, setUseRatioOverride] = useState(false);
  const [pollingId, setPollingId] = useState<string | null>(null);
  const [cleaningUp, setCleaningUp] = useState(false);

  // Selected blocks limit the export; nothing selected = the whole boundary.
  const selectionLayerId = useWorkspaceStore((s) => s.selection.layerId);
  const selectionFeatureIds = useWorkspaceStore((s) => s.selection.featureIds);
  const selectedUnitIds =
    selectionLayerId && UNIT_LAYER_IDS.includes(selectionLayerId)
      ? selectionFeatureIds.map(String)
      : [];

  // Config
  const [config, setConfig] = useState({
    min_dbh_cm: 10.0,
    max_dbh_cm: '' as number | '',
    min_height_m: 5.0,
    max_trees_per_ha: 500,
    algorithm_version: 'v1.0',
    species_role_target_ratio: null as Record<string, number> | null,
  });

  const [ratio, setRatio] = useState({
    dominant: 0.50,
    'co-dominant': 0.30,
    associate: 0.15,
    occasional: 0.04,
    rare: 0.01,
  });

  const loadExports = async () => {
    try {
      setLoading(true);
      const data = await allTreeExportApi.listExports(calculationId);
      setExports(data.exports || []);
    } catch (err: any) {
      console.error('Error loading all-tree exports:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadExports();
  }, [calculationId]);

  // Exports are deleted by the server an hour after they finish. Tick once a
  // minute so the countdown stays honest, and re-read the list when one lapses
  // so the user never keeps a row whose file is already gone.
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const anyLapsed = exports.some(
    (e) => e.expires_at && new Date(e.expires_at).getTime() <= nowMs,
  );
  useEffect(() => {
    if (anyLapsed) loadExports();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyLapsed]);

  useEffect(() => {
    if (!pollingId) return;
    const interval = setInterval(async () => {
      try {
        const item = await allTreeExportApi.getExport(pollingId);
        setExports(prev => prev.map(e => e.id === item.id ? item : e));
        if (item.status === 'completed' || item.status === 'failed') {
          setPollingId(null);
          setGenerating(false);
        }
      } catch (err) {
        console.error('Error polling:', err);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [pollingId]);

  const handleGenerate = async () => {
    try {
      setGenerating(true);
      setError(null);

      const reqConfig: any = { ...config };
      if (reqConfig.max_dbh_cm === '' || reqConfig.max_dbh_cm === null) {
        delete reqConfig.max_dbh_cm;
      }
      if (useRatioOverride) {
        reqConfig.species_role_target_ratio = { ...ratio };
      } else {
        reqConfig.species_role_target_ratio = null;
      }

      const newExport = await allTreeExportApi.generate(calculationId, reqConfig, selectedUnitIds);
      setExports(prev => [newExport, ...prev]);
      setPollingId(newExport.id);
    } catch (err: any) {
      setError(apiErrorText(err, err.message || t('treeMapping.model.msgExportFailed')));
      setGenerating(false);
    }
  };

  // One export carries three formats; the server names the file, this is only the fallback.
  const DOWNLOADS = {
    gpkg: { path: 'download', fallback: 'all_trees.gpkg' },
    excel: { path: 'download-excel', fallback: 'all_trees.xlsx' },
    csv: { path: 'download-csv', fallback: 'all_trees.csv' },
  } as const;

  const handleDownload = async (exportId: string, kind: keyof typeof DOWNLOADS) => {
    try {
      const { path, fallback } = DOWNLOADS[kind];
      await downloadFromApi(`/api/all-tree-exports/${exportId}/${path}`, fallback);
    } catch (err: any) {
      alert('Download failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleDelete = async (exportId: string) => {
    if (!confirm(t('treeMapping.model.confirmDeleteExport'))) return;
    try {
      await allTreeExportApi.delete(exportId);
      setExports(prev => prev.filter(e => e.id !== exportId));
    } catch (err: any) {
      alert('Delete failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleCleanupOldExports = async () => {
    if (!confirm('Delete all export files older than 7 days? This cannot be undone.')) return;
    try {
      setCleaningUp(true);
      const result = await exportCleanupApi.cleanup(7);
      alert(result.message || t('treeMapping.model.msgCleanupComplete'));
      loadExports();
    } catch (err: any) {
      alert('Cleanup failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setCleaningUp(false);
    }
  };

  const formatFileSize = (mb: number) => {
    if (mb < 1) return `${formatDecimal((mb * 1024), 0)} KB`;
    return `${formatDecimal(mb, 2)} MB`;
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  };

  const updateRatio = (key: string, value: number) => {
    const newRatio = { ...ratio, [key]: value };
    const total = Object.values(newRatio).reduce((s, v) => s + v, 0);
    if (Math.abs(total - 1.0) > 0.001) {
      const normalized: Record<string, number> = {};
      for (const k of Object.keys(newRatio) as (keyof typeof ratio)[]) {
        normalized[k] = total > 0 ? Math.round((newRatio[k] / total) * 100) / 100 : 0;
      }
      setRatio(normalized as { dominant: number; 'co-dominant': number; associate: number; occasional: number; rare: number; });
    } else {
      setRatio(newRatio);
    }
  };

  return (
    <div>
      {/* Configuration */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t('treeMapping.model.minDbhShort')}</label>
          <input type="text" inputMode="decimal" value={config.min_dbh_cm}
            onChange={e => setConfig({ ...config, min_dbh_cm: parseLocaleNumber(e.target.value) })}
            min={5} max={50} step={0.1} disabled={generating}
            className="w-full px-3 py-2 border border-gray-300 rounded-md" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t('treeMapping.model.maxDbhShort')}</label>
          <input type="text" inputMode="decimal" value={config.max_dbh_cm}
            onChange={e => setConfig({ ...config, max_dbh_cm: e.target.value ? parseLocaleNumber(e.target.value) : '' })}
            min={10} max={200} step={0.1} disabled={generating} placeholder="No limit"
            className="w-full px-3 py-2 border border-gray-300 rounded-md" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t('treeMapping.model.minHeightShort')}</label>
          <input type="text" inputMode="decimal" value={config.min_height_m}
            onChange={e => setConfig({ ...config, min_height_m: parseLocaleNumber(e.target.value) })}
            min={2} max={20} step={0.1} disabled={generating}
            className="w-full px-3 py-2 border border-gray-300 rounded-md" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">{t('treeMapping.model.maxTreesHaShort')}</label>
          <input type="text" inputMode="decimal" value={config.max_trees_per_ha}
            onChange={e => setConfig({ ...config, max_trees_per_ha: Math.trunc(parseLocaleNumber(e.target.value)) })}
            min={50} max={5000} step={50} disabled={generating}
            className="w-full px-3 py-2 border border-gray-300 rounded-md" />
        </div>
      </div>

      {/* Species Role Ratio Toggle */}
      <div className="mb-4">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={useRatioOverride}
            onChange={e => setUseRatioOverride(e.target.checked)}
            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500" />
          <span className="text-sm font-medium text-gray-700">{t('treeMapping.model.overrideRatios')}</span>
        </label>
        <p className="text-xs text-gray-500 mt-1 ml-6">
          {t('treeMapping.model.ratioHint1')}
          {t('treeMapping.model.ratioHint2')}
        </p>
      </div>

      {useRatioOverride && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4 p-4 bg-purple-50 rounded-lg border border-purple-200">
          {Object.entries(ratio).map(([key, val]) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-700 mb-1 capitalize">{key}</label>
              <div className="flex items-center gap-1">
                <input type="text" inputMode="decimal" value={val}
                  onChange={e => updateRatio(key, Math.max(0, Math.min(1, parseLocaleNumber(e.target.value) || 0)))}
                  min={0} max={1} step={0.01} disabled={generating}
                  className="w-full px-2 py-1.5 border border-gray-300 rounded-md text-sm" />
              </div>
            </div>
          ))}
          <div className="col-span-full flex justify-end">
            <span className="text-xs text-gray-500">
              Total: {formatDecimal(Object.values(ratio).reduce((s, v) => s + v, 0), 2)}
            </span>
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-800">{error}</p>
        </div>
      )}

      <p className="mb-3 text-sm text-gray-600" data-testid="all-tree-export-scope">
        {selectedUnitIds.length > 0
          ? t('treeMapping.model.allTreesScopeSelected', { count: selectedUnitIds.length })
          : t('treeMapping.model.allTreesScopeAll')}
      </p>

      <div className="flex items-center gap-3">
        <button onClick={handleGenerate} disabled={generating}
          className={`px-6 py-3 rounded-md font-medium transition-colors ${
            generating
              ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
              : 'bg-purple-600 text-white hover:bg-purple-700'
          }`}>
          {generating ? (
            <span className="flex items-center gap-2">
              <Loader className="w-5 h-5 animate-spin" />
              {t('treeMapping.model.exportingAll')}
            </span>
          ) : (
            t('treeMapping.model.allTreesTitle')
          )}
        </button>
        {exports.length > 0 && (
          <button onClick={handleCleanupOldExports} disabled={cleaningUp}
            className="px-4 py-3 rounded-md font-medium text-sm bg-gray-200 text-gray-700 hover:bg-gray-300 transition-colors">
            {cleaningUp ? (
              <span className="flex items-center gap-2">
                <Loader className="w-4 h-4 animate-spin" />
                {t('treeMapping.model.cleaning')}
              </span>
            ) : (
              t('treeMapping.model.cleanOld')
            )}
          </button>
        )}
      </div>
      {generating && (
        <p className="mt-2 text-sm text-gray-600">
          {t('treeMapping.model.mayTakeMinutes')}
        </p>
      )}

      {/* Exports List */}
      <div className="mt-6">
        <h4 className="text-md font-semibold text-gray-900 mb-3">
          All-Tree Exports ({exports.length})
        </h4>

        {loading ? (
          <div className="text-center py-4 text-gray-500">
            <Loader className="w-5 h-5 animate-spin mx-auto mb-1" />
            {t('treeMapping.model.loading')}
          </div>
        ) : exports.length === 0 ? (
          <div className="text-center py-4 text-gray-500">
            <p className="text-sm">{t('treeMapping.model.noExports')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {exports.map((item) => (
              <div key={item.id} className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                {/* Status */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {item.status === 'completed' && <CheckCircle className="w-4 h-4 text-green-600" />}
                    {item.status === 'processing' && <Loader className="w-4 h-4 text-blue-600 animate-spin" />}
                    {item.status === 'failed' && <AlertCircle className="w-4 h-4 text-red-600" />}
                    <span className={`font-medium text-sm ${
                      item.status === 'completed' ? 'text-green-700' :
                      item.status === 'processing' ? 'text-blue-700' : 'text-red-700'
                    }`}>{item.status.toUpperCase()}</span>
                    <span className="text-xs text-gray-500">{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                </div>

                {/* Scope + expiry */}
                <p className="text-xs text-gray-500 mb-2">
                  {Array.isArray(item.algorithm_config?.unit_ids) && item.algorithm_config.unit_ids.length > 0
                    ? t('treeMapping.model.allTreesScopeSelected', { count: item.algorithm_config.unit_ids.length })
                    : t('treeMapping.model.allTreesScopeAllShort')}
                  {item.expires_at && (
                    <>
                      {' '}
                      {t('treeMapping.model.allTreesExpiresIn', {
                        minutes: Math.max(1, Math.ceil((new Date(item.expires_at).getTime() - nowMs) / 60000)),
                      })}
                    </>
                  )}
                </p>

                {/* Progress */}
                {item.status === 'processing' && (
                  <div className="mb-2">
                    <div className="flex justify-between text-xs mb-1">
                      <span>{item.current_step}</span>
                      <span>{item.progress_percent}%</span>
                    </div>
                    <div className="w-full bg-gray-200 rounded-full h-1.5">
                      <div className="bg-blue-600 h-1.5 rounded-full" style={{ width: `${item.progress_percent}%` }} />
                    </div>
                  </div>
                )}

                {/* Stats */}
                {item.status === 'completed' && item.total_trees && (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-2">
                    <div>
                      <p className="text-xs text-gray-500">{t('treeMapping.col.totalTrees')}</p>
                      <p className="text-sm font-semibold">{formatNumber(item.total_trees)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500">{t('treeMapping.col.treesPerHa')}</p>
                      <p className="text-sm font-semibold">{formatDecimal(item.trees_per_hectare, 1)}</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500">{t('treeMapping.model.dbhRange')}</p>
                      <p className="text-sm font-semibold">{formatDecimal(item.min_dbh_cm, 1)} - {formatDecimal(item.max_dbh_cm, 1)} cm</p>
                    </div>
                    <div>
                      <p className="text-xs text-gray-500">{t('treeMapping.model.area')}</p>
                      <p className="text-sm font-semibold">{formatDecimal(item.area_hectares, 1)} ha</p>
                    </div>
                  </div>
                )}

                {/* Error */}
                {item.status === 'failed' && item.error_message && (
                  <div className="mb-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-800">
                    {item.error_message}
                  </div>
                )}

                {/* Why a format is missing, instead of a button that silently isn't there */}
                {item.status === 'completed' && !item.csv_filename && (
                  <p className="text-xs text-amber-700 mb-2">{t('treeMapping.model.allTreesNoTabular')}</p>
                )}
                {item.status === 'completed' && item.csv_filename && !item.excel_filename && (
                  <p className="text-xs text-amber-700 mb-2">{t('treeMapping.model.allTreesNoExcel')}</p>
                )}

                {/* Download Buttons */}
                <div className="flex items-center gap-2 flex-wrap">
                  {item.status === 'completed' && item.gpkg_filename && (
                    <button onClick={() => handleDownload(item.id, 'gpkg')}
                      className="px-3 py-1.5 bg-green-600 text-white rounded hover:bg-green-700 flex items-center gap-1.5 text-xs">
                      <Map className="w-3.5 h-3.5" /> GPKG {item.gpkg_size_mb && <span>({formatFileSize(item.gpkg_size_mb)})</span>}
                    </button>
                  )}
                  {item.status === 'completed' && item.excel_filename && (
                    <button onClick={() => handleDownload(item.id, 'excel')}
                      className="px-3 py-1.5 bg-emerald-700 text-white rounded hover:bg-emerald-800 flex items-center gap-1.5 text-xs">
                      <FileSpreadsheet className="w-3.5 h-3.5" /> Excel {item.excel_size_mb && <span>({formatFileSize(item.excel_size_mb)})</span>}
                    </button>
                  )}
                  {item.status === 'completed' && item.csv_filename && (
                    <button onClick={() => handleDownload(item.id, 'csv')}
                      className="px-3 py-1.5 bg-sky-700 text-white rounded hover:bg-sky-800 flex items-center gap-1.5 text-xs">
                      <FileSpreadsheet className="w-3.5 h-3.5" /> CSV {item.csv_size_mb && <span>({formatFileSize(item.csv_size_mb)})</span>}
                    </button>
                  )}

                  <button onClick={() => handleDelete(item.id)}
                    className="px-3 py-1.5 bg-red-600 text-white rounded hover:bg-red-700 flex items-center gap-1.5 text-xs">
                    <Trash2 className="w-3.5 h-3.5" /> Delete
                  </button>
                  {item.processing_time_seconds && (
                    <span className="text-xs text-gray-500 ml-auto">Time: {formatDuration(item.processing_time_seconds)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default TreeModelGenerator;
