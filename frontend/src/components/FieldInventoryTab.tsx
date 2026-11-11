/** FieldInventoryTab — tab for field inventory data upload, review, and export. */
import React, { useState } from 'react';
import { fieldInventoryApi } from '../services/api';
import { toNepaliDigit } from '../constants/nepaliLabels';
import HelpTooltip from './HelpTooltip';
import CopyTag from './DetailDescription/CopyTag';
import { useFieldInventoryData } from './fieldInventory/useFieldInventoryData';
import {
  FieldInventoryResultsTables,
  FieldInventoryTotalsSummary,
} from './fieldInventory/FieldInventoryResultsTables';
import { UnsampledUnitsNote } from './fieldInventory/UnsampledUnitsNote';
import i18n from '../i18n';
import { UploadReport } from './UploadReport';
import { UploadPointsPreview } from './UploadPointsPreview';
import { UploadStateLine } from './UploadStateLine';
import { useT } from '../i18n/hooks';
import { parseLocaleNumber } from '../i18n/numberFormat';
import { useDbhClassConfig } from '../hooks/useDbhClasses';

/**
 * CFMG's regeneration group ends at 10 cm, and a class inside it carries no
 * harvestable volume -- P0 established that seedling and sapling report 0.00
 * m3/ha, so the table greys those columns and prints `-` for timber and firewood
 * rather than showing a zero that looks like a measurement.
 *
 * The old code wrote this as `i < 2`: "the first two classes". That is index
 * arithmetic standing in for a domain rule, and it fails twice over. Add a class
 * below 10 cm and the greying moves onto the wrong column; remove one and it
 * stops covering the second. Deriving it from each class's own upper bound
 * against this constant survives both, and the constant is pinned to
 * `harvesting_cfmg.regeneration.upper` by
 * `frontend/src/constants/__tests__/dbhLabelJoin.test.ts`, so it cannot drift
 * away from the database either.
 */
const CFMG_REGENERATION_UPPER_CM = 10;

interface FieldInventoryTabProps {
  calculationId: string;
  blocks?: any[];
  forestName?: string;
  /**
   * Which pane of the step's split to render. `data` is the upload, `results` is
   * everything derived from a processed inventory.
   *
   * Both panes read their state from `FieldInventoryDataProvider`, which the
   * step's host mounts above the tab bar — so switching panes does not refetch
   * and does not lose a half-configured upload. `undefined` keeps the old
   * "whichever the data supports" behaviour for any caller that is not split.
   */
  view?: 'data' | 'results';
}

/** Display keys for the persisted forest_condition data values. */
const CONDITION_LABEL_KEY: Record<string, string> = {
  Good: 'fieldInventory.condGood',
  Moderate: 'fieldInventory.condModerate',
  Weak: 'fieldInventory.condWeak',
};

/** Narrative digits: Devanagari in Nepali per D6, ASCII in English. */
function narrativeNum(n: number, decimals = 2): string {
  return i18n.language === 'ne' ? toNepaliDigit(n, decimals) : Number(n).toFixed(decimals);
}

export function FieldInventoryTab({ calculationId, view }: FieldInventoryTabProps) {
    const t = useT();

    // P4: the class list is the database's, so a class added there appears here
    // without a second edit. This table used to carry a hardcoded eight-key
    // literal and three assumptions built on its indexes -- `i < 2` for the
    // classes with no harvestable volume, and `i === 7` for the last column.
    const dbhClasses = useDbhClassConfig('guideline_2061');
    const dbhKeys = dbhClasses.map((c) => c.key);
    /** Classes at or below the CFMG regeneration bound: no timber, no firewood. */
    const noTimberKeys = new Set(
        dbhClasses
            .filter((c) => c.upper !== null && c.upper <= CFMG_REGENERATION_UPPER_CM)
            .map((c) => c.key),
    );

  // All of the state, the loading effects and the handlers now live in the
  // provider above the tab bar (WORKSPACE_FLOW_NAV_PLAN P5d). Reading it here
  // rather than owning it is the point: the host mounts one pane at a time, so
  // state declared in a pane is destroyed by switching away from it.
  const {
    fieldInventory, summary, speciesBreakdown, maiAahData, loading, initialized,
    file, uploading, processing, deleting, validationResult, error, uploadFindings, componentError,
    sampleSizes, setSampleSizes, aahMultipliers, setAahMultipliers, customMultipliers,
    editingBlock, editingValue, handleStartInlineEdit, handleSaveInlineEdit,
    handleCancelInlineEdit, modalBlock, handleOpenModal, handleCloseModal,
    handleSaveModal, checkFieldInventory, handleFileChange, handleUpload,
    handleProcess, handleExportExcel, handleDfoExport, handleDelete,
    setComponentError, setFieldInventory, setInitialized, labels, displayBlockName,
    setError, setMaiAahData, setCustomMultipliers, setEditingValue, forestName,
    ensureLoaded,
  } = useFieldInventoryData();

  // Both views need the record, so both ask for it. The provider is mounted for
  // the whole step while this pane is mounted only while it is the active tab,
  // and the third pane in this group does not need the record at all -- so the
  // load is requested here rather than performed on provider mount. The guard
  // lives in the provider, so Data -> Results still fetches once.
  React.useEffect(() => {
    ensureLoaded();
  }, [ensureLoaded]);

  // Validation check
  if (!calculationId) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-yellow-900 mb-2">{t('fieldInventory.invalidCalc')}</h3>
          <p className="text-sm text-yellow-800">{t('fieldInventory.noCalcId')}</p>
        </div>
      </div>
    );
  }

  // Component-level error display
  if (componentError) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-red-900 mb-2">{t('fieldInventory.errorLoading')}</h3>
          <p className="text-sm text-red-800 mb-4">{componentError}</p>
          <div className="space-x-2">
            <button
              onClick={() => {
                setComponentError(null);
                setInitialized(false);
                checkFieldInventory();
              }}
              className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm"
            >
              {t('fieldInventory.retry')}
            </button>
            <button
              onClick={() => {
                setComponentError(null);
                setFieldInventory(null);
                setInitialized(true);
              }}
              className="px-4 py-2 bg-gray-500 text-white rounded-md hover:bg-gray-600 text-sm"
            >
              {t('fieldInventory.clearError')}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (loading && !initialized) {
    return (
      <div className="flex flex-col justify-center items-center py-12">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mb-4"></div>
        <p className="text-sm text-gray-600">{t('fieldInventory.loading')}</p>
      </div>
    );
  }

  // If field inventory exists, show summary
  //
  // The `view` guards: `data` is where the file is chosen and validated, so the
  // summary is not shown there; `results` is the summary, and the upload UI is
  // not shown there. Omitting `view` keeps the original behaviour — whichever
  // the loaded data supports — so an unsplit caller is unaffected.
  if (fieldInventory && view !== 'data') {
    return (
      <div className="space-y-6">
        {/* Header with Actions */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-start mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-900 mb-1">{t('fieldInventory.title')}</h3>
              <p className="text-sm text-gray-600">{fieldInventory.uploaded_filename}</p>
              <UploadStateLine present detail={fieldInventory.uploaded_filename} className="mt-1" />
              <span className={`inline-block mt-2 px-3 py-1 rounded-full text-sm font-semibold ${
                fieldInventory.status === 'completed' ? 'bg-green-100 text-green-800' :
                fieldInventory.status === 'processing' ? 'bg-yellow-100 text-yellow-800' :
                'bg-gray-100 text-gray-800'
              }`}>
                {fieldInventory.status}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleExportExcel}
                className="px-4 py-2 bg-emerald-600 text-white rounded-md hover:bg-emerald-700 text-sm flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                {t('fieldInventory.downloadExcel')}
              </button>
              <button
                onClick={handleDfoExport}
                className="px-4 py-2 bg-blue-800 text-white rounded-md hover:bg-blue-900 text-sm flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
                {t('fieldInventory.dfoSummary')}
              </button>
              <button
                onClick={() => handleDelete(t('uploadState.replaceConfirm', { file: fieldInventory.uploaded_filename ?? '', date: fieldInventory.created_at ? new Date(fieldInventory.created_at).toLocaleDateString() : '' }))}
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
                {deleting ? t('common.deleting') : t('common.delete')}
              </button>
            </div>
          </div>
        </div>

        {/* Effective areas + forest-wide grand total */}
        {/*
          First, because every per-hectare and absolute figure further down is
          derived from the effective areas shown here. Carried over from the old
          `TotalInventoryTab` (P5d); see `FieldInventoryResultsTables`.
        */}
        {view === 'results' && <FieldInventoryTotalsSummary />}

{/*
P8: the units a summary row is missing for. A block is summarised only if it was
sampled, so an unsampled unit silently vanishes and the totals above read 21 of 24
with nothing explaining the gap. This names them, and only renders when there is
something missing - an always-present empty card would be noise.
*/}
{view === 'results' && fieldInventory?.id && (
<UnsampledUnitsNote fieldInventoryId={fieldInventory.id} />
)}

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{error}</p>
            <button onClick={() => setError(null)} className="mt-1 text-xs text-red-500 hover:text-red-700">{t('fieldInventory.dismiss')}</button>
          </div>
        )}

        {/* Summary Statistics */}
        {summary && (
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">{t('fieldInventory.overallSummary')}</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-6">
              <div>
                <p className="text-sm text-gray-500">{t('fieldInventory.totalSamplePlots')}</p>
                <p className="mt-1 text-3xl font-bold text-gray-900">{toNepaliDigit(summary.total_sample_plots || 0, 0)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">{labels.unitLabelPlural}</p>
                <p className="mt-1 text-3xl font-bold text-gray-900">{toNepaliDigit(summary.total_blocks || 0, 0)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">{t('fieldInventory.status')}</p>
                <p className="mt-1 text-lg font-semibold text-green-600">{summary.status}</p>
              </div>
              <div>
                <p className="text-sm text-gray-500">{t('fieldInventory.processingTime')}</p>
                <p className="mt-1 text-lg font-semibold text-gray-900">
                  {summary.processing_time_seconds ? `${toNepaliDigit(Number(summary.processing_time_seconds), 2)}s` : 'N/A'}
                </p>
              </div>
            </div>

            {/* Forest-Wide Summary */}
            {summary && summary.total_blocks > 0 && (
              <div className="mt-6 mb-6 bg-gradient-to-r from-green-50 to-teal-50 rounded-lg border-2 border-green-400 p-6 shadow-lg">
                <h3 className="text-xl font-bold text-green-800 mb-4 flex items-center flex-wrap gap-2">
                  <svg className="w-6 h-6 mr-2" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M3 12v3c0 1.657 3.134 3 7 3s7-1.343 7-3v-3c0 1.657-3.134 3-7 3s-7-1.343-7-3z"/>
                    <path d="M3 7v3c0 1.657 3.134 3 7 3s7-1.343 7-3V7c0 1.657-3.134 3-7 3S3 8.657 3 7z"/>
                    <path d="M17 5c0 1.657-3.134 3-7 3S3 6.657 3 5s3.134-3 7-3 7 1.343 7 3z"/>
                  </svg>
                  {t('fieldInventory.overallHeading', { name: forestName })}
                  <CopyTag
                    label="{{section:field_inventory_narration}}"
                    value="{{section:field_inventory_narration}}"
                    variant="section"
                  />
                </h3>

                {/* Nepali Narration Paragraph */}
                <div className="mb-6 p-4 bg-white/70 rounded-lg border border-green-200">
                  <p className="text-sm text-gray-700 leading-relaxed">
                    {t('fieldInventory.narr1', {
                      plots: narrativeNum(summary.total_sample_plots || 0, 0),
                      blocks: narrativeNum(summary.total_blocks || 0, 0),
                      unit: labels.unitLabelNp,
                      seedling: narrativeNum(summary.total_regeneration_per_ha || 0, 0),
                      sapling: narrativeNum(summary.total_sapling_per_ha || 0, 0),
                      pole: narrativeNum(summary.total_pole_per_ha || 0, 0),
                      tree: narrativeNum(summary.total_tree_per_ha || 0, 0),
                    })}{' '}
                    {t('fieldInventory.narr2', {
                      growingStock: narrativeNum(Number(summary.total_growing_stock_m3_per_ha || 0), 2),
                      basalArea: narrativeNum(Number(summary.average_basal_area_m2_per_ha || 0), 2),
                    })}{' '}
                    {t('fieldInventory.narr3', {
                      agb: narrativeNum(Number(summary.average_agb_t_per_ha || 0), 2),
                      bgb: narrativeNum(Number(summary.average_bgb_t_per_ha || 0), 2),
                      total: narrativeNum(Number(summary.average_total_biomass_t_per_ha || 0), 2),
                    })}{' '}
                    {t('fieldInventory.narr4', {
                      carbon: narrativeNum(Number(summary.average_carbon_stock_tc_per_ha || 0), 2),
                      co2: narrativeNum(Number(summary.average_co2_equivalent_tco2_per_ha || 0), 2),
                    })}{' '}
                    {t('fieldInventory.narr5', {
                      condition: summary.overall_forest_condition || '—',
                      mai: narrativeNum(Number(summary.average_mai_percent || 0), 1),
                      woodDensity: narrativeNum(Number(summary.average_wood_density || 0), 3),
                    })}
                  </p>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                  {/* Basic Stats */}
                  <div className="bg-white rounded-lg p-4 shadow-md border border-green-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{labels.unitLabelPlural}</div>
                    <div className="text-3xl font-bold text-green-700">{toNepaliDigit(summary.total_blocks || 0, 0)}</div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-green-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.samplePlots')}</div>
                    <div className="text-3xl font-bold text-green-700">{toNepaliDigit(summary.total_sample_plots || 0, 0)}</div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-blue-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.seedlingHa')}</div>
                    <div className="text-2xl font-bold text-blue-700">
                      {summary.total_regeneration_per_ha ? toNepaliDigit(summary.total_regeneration_per_ha, 0) : 0}
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-blue-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.saplingHa')}</div>
                    <div className="text-2xl font-bold text-blue-700">
                      {summary.total_sapling_per_ha ? toNepaliDigit(summary.total_sapling_per_ha, 0) : 0}
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-blue-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.poleHa')}</div>
                    <div className="text-2xl font-bold text-blue-700">
                      {summary.total_pole_per_ha ? toNepaliDigit(summary.total_pole_per_ha, 0) : 0}
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-blue-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.treeHa')}</div>
                    <div className="text-2xl font-bold text-blue-700">
                      {summary.total_tree_per_ha ? toNepaliDigit(summary.total_tree_per_ha, 0) : 0}
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-amber-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.growingStock')}</div>
                    <div className="text-xl font-bold text-amber-700">
                      {summary.total_growing_stock_m3_per_ha ? toNepaliDigit(Number(summary.total_growing_stock_m3_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> m³/ha</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-emerald-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.basalArea')}</div>
                    <div className="text-xl font-bold text-emerald-700">
                      {summary.average_basal_area_m2_per_ha ? toNepaliDigit(Number(summary.average_basal_area_m2_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> m²/ha</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-purple-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">MAI</div>
                    <div className="text-2xl font-bold text-purple-700">
                      {summary.average_mai_percent ? toNepaliDigit(Number(summary.average_mai_percent), 1) : '0.0'}%
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-red-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.forestCondition')}</div>
                    <div className={`text-lg font-bold ${
                      summary.overall_forest_condition === 'Good' ? 'text-green-600' :
                      summary.overall_forest_condition === 'Moderate' ? 'text-yellow-600' :
                      summary.overall_forest_condition === 'Weak' ? 'text-red-600' : 'text-gray-400'
                    }`}>
                      {summary.overall_forest_condition || '-'}
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-teal-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.woodDensity')}</div>
                    <div className="text-xl font-bold text-teal-700">
                      {summary.average_wood_density ? toNepaliDigit(Number(summary.average_wood_density), 3) : '0.000'}
                      <span className="text-sm font-normal"> t/m³</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-teal-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">AGB</div>
                    <div className="text-xl font-bold text-teal-700">
                      {summary.average_agb_t_per_ha ? toNepaliDigit(Number(summary.average_agb_t_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> t/ha</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-teal-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">BGB</div>
                    <div className="text-xl font-bold text-teal-700">
                      {summary.average_bgb_t_per_ha ? toNepaliDigit(Number(summary.average_bgb_t_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> t/ha</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-teal-200">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.totalBiomass')}</div>
                    <div className="text-xl font-bold text-teal-700">
                      {summary.average_total_biomass_t_per_ha ? toNepaliDigit(Number(summary.average_total_biomass_t_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> t/ha</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-teal-200 col-span-2 md:col-span-1">
                    <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.carbonStock')}</div>
                    <div className="text-xl font-bold text-teal-700">
                      {summary.average_carbon_stock_tc_per_ha ? toNepaliDigit(Number(summary.average_carbon_stock_tc_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> tC/ha</span>
                    </div>
                  </div>

                  <div className="bg-white rounded-lg p-4 shadow-md border border-teal-300 col-span-2 md:col-span-1 bg-teal-50">
                    <div className="text-xs text-gray-600 mb-1 font-medium">{t('fieldInventory.co2Equivalent')}</div>
                    <div className="text-2xl font-bold text-teal-800">
                      {summary.average_co2_equivalent_tco2_per_ha ? toNepaliDigit(Number(summary.average_co2_equivalent_tco2_per_ha), 2) : '0.00'}
                      <span className="text-sm font-normal"> tCO₂/ha</span>
                    </div>
                  </div>

                  {/* MAI and AAH Summary */}
                  {maiAahData && (
                    <>
                      <div className="bg-white rounded-lg p-4 shadow-md border border-purple-200 col-span-2 md:col-span-1">
                        <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.maiTotalVolume')}</div>
                        <div className="text-xl font-bold text-purple-700">
                          {maiAahData.mai_overall?.total_mai_m3_per_ha ? toNepaliDigit(Number(maiAahData.mai_overall.total_mai_m3_per_ha), 2) : '0.00'}
                          <span className="text-sm font-normal"> m³/ha/yr</span>
                        </div>
                        <div className="text-xs text-gray-500 mt-1">
                          Pole: {toNepaliDigit(maiAahData.mai_overall?.pole_per_ha || 0, 0)} |
                          Tree: {toNepaliDigit(maiAahData.mai_overall?.tree_per_ha || 0, 0)}
                        </div>
                      </div>

                      <div className="bg-white rounded-lg p-4 shadow-md border border-amber-300 col-span-2 md:col-span-1 bg-amber-50">
                        <div className="text-xs text-gray-600 mb-1 font-medium">{t('fieldInventory.aahTotalVolume')}</div>
                        <div className="text-2xl font-bold text-amber-800">
                          {maiAahData.aah_overall?.total_aah_m3_per_ha ? toNepaliDigit(Number(maiAahData.aah_overall.total_aah_m3_per_ha), 2) : '0.00'}
                          <span className="text-sm font-normal"> m³/ha/yr</span>
                        </div>
                        <div className="text-xs text-gray-600 mt-1">
                          Pole: {toNepaliDigit(maiAahData.aah_overall?.pole_per_ha || 0, 0)} |
                          Tree: {toNepaliDigit(maiAahData.aah_overall?.tree_per_ha || 0, 0)}
                        </div>
                      </div>

                      <div className="bg-white rounded-lg p-4 shadow-md border border-red-200">
                        <div className="text-xs text-gray-500 mb-1 font-medium">{t('fieldInventory.aahMultiplier')}</div>
                        <div className="text-2xl font-bold text-red-700">
                          {maiAahData.aah_overall?.aah_multiplier_percent ? toNepaliDigit(Number(maiAahData.aah_overall.aah_multiplier_percent), 0) : '0'}%
                        </div>
                        <div className={`text-xs mt-1 font-medium ${
                          maiAahData.aah_overall?.forest_condition === 'Good' ? 'text-green-600' :
                          maiAahData.aah_overall?.forest_condition === 'Moderate' ? 'text-yellow-600' :
                          'text-red-600'
                        }`}>
                          {maiAahData.aah_overall?.forest_condition || '-'}
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}

            {/* OP Document Variables */}
            {fieldInventory && (
              <div className="mt-6 bg-white border border-emerald-200 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-emerald-800 text-sm">
                    📋 OP Document Variables — Field Inventory Data Table
                  </h4>
                </div>
                <p className="text-xs text-gray-500 mb-2">
                  {t('fieldInventory.rawDataTitle')}
                </p>
                <div className="flex flex-wrap gap-2">
                  <CopyTag label="{{table:fieldinventory}}" value="{{table:fieldinventory}}" variant="section" />
                </div>
              </div>
            )}

            {/* Block-wise Results */}
            {summary?.blocks && Array.isArray(summary.blocks) && summary.blocks.length > 0 && (
              <div className="mt-6">
                <h4 className="text-md font-semibold text-gray-900 mb-1 flex items-center gap-2">
                    {labels.unitLabel}-wise Results
                    <span className="flex flex-wrap gap-1">
                      <CopyTag label="{{fi_block_tree_count_per_ha}}" value="{{fi_block_tree_count_per_ha}}" variant="section" />
                      <CopyTag label="{{fi_block_pole_tree_volume}}" value="{{fi_block_pole_tree_volume}}" variant="section" />
                      <CopyTag label="{{fi_block_growing_stock}}" value="{{fi_block_growing_stock}}" variant="section" />
                      <CopyTag label="{{fi_block_basal_area}}" value="{{fi_block_basal_area}}" variant="section" />
                      <CopyTag label="{{fi_block_satellite_volume}}" value="{{fi_block_satellite_volume}}" variant="section" />
                      <CopyTag label="{{fi_block_condition_growth}}" value="{{fi_block_condition_growth}}" variant="section" />
                      <CopyTag label="{{fi_block_biomass_carbon}}" value="{{fi_block_biomass_carbon}}" variant="section" />
                    </span>
                  </h4>
                <p className="text-xs text-gray-500 mb-3 leading-relaxed">
                  <strong>{t('fieldInventory.regenStatusColon')}</strong> {t('fieldInventory.regenStatusDef')}
                  <br />
                  <strong>{t('fieldInventory.forestStatusColon')}</strong> {t('fieldInventory.forestStatusDef')}
                  <br />
                  <strong>{t('fieldInventory.maiPercentColon')}</strong> {t('fieldInventory.maiPercentDef', { unit: labels.unitNameHeaderNp })}
                </p>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitNameHeaderNp}</th>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.samplePlotCount')}</th>
                        <th colSpan={4} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-blue-50">{t('fieldInventory.treesPerHa')}</th>
                        <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-green-50">{t('fieldInventory.poleVolume')}</th>
                        <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-amber-50">{t('fieldInventory.treeVolume')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-purple-50">{t('fieldInventory.gsTimber')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-indigo-50">{t('fieldInventory.gsTotal')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-emerald-50">{t('fieldInventory.basalAreaNp')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-bold italic text-blue-800 uppercase border-r-2 border-blue-400 bg-blue-100 shadow-sm">{t('fieldInventory.satelliteVolume')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.regenStatus')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.forestStatus')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.maiPercent')}</th>
                        <th colSpan={6} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-teal-50">
                          <HelpTooltip helpText="IPCC Tier 2 Methodology: AGB = VOB × WD × BEF. VOB (gross merchantable stem volume, NOT net_volume), BEF=1.3, R/S=0.24, CF=0.47 (IPCC 2006 GL Vol 4 Tables 4.3, 4.4).">
                            <span>{t('fieldInventory.carbonBiomass')}</span>
                          </HelpTooltip>
                        </th>
                      </tr>
                      <tr>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50">{t('fieldInventory.seedling')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50">{t('fieldInventory.sapling')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50">{t('fieldInventory.pole')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50 border-r border-gray-300">{t('fieldInventory.tree')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-green-50">{t('fieldInventory.timber')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-green-50">{t('fieldInventory.firewood')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-green-50 border-r border-gray-300">{t('fieldInventory.total')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-amber-50">{t('fieldInventory.timber')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-amber-50">{t('fieldInventory.firewood')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-amber-50 border-r border-gray-300">{t('fieldInventory.total')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.woodDensityNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.agbNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.bgbNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.totalBiomassNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.carbonNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.co2Np')}</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {summary.blocks.map((block: any, idx: number) => {
                        const poleTimber = Number(block.pole_timber_m3_per_ha || 0);
                        const poleFirewood = Number(block.pole_firewood_m3_per_ha || 0);
                        const poleTotal = poleTimber + poleFirewood;
                        const treeTimber = Number(block.tree_timber_m3_per_ha || 0);
                        const treeFirewood = Number(block.tree_firewood_m3_per_ha || 0);
                        const treeTotal = treeTimber + treeFirewood;

                        return (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="px-3 py-3 text-sm font-medium text-gray-900 border-r border-gray-200">{displayBlockName(block.block_name)}</td>
                            <td className="px-3 py-3 text-sm text-gray-700 border-r border-gray-200">{toNepaliDigit(block.total_sample_plots, 0)}</td>

                            {/* Trees per hectare */}
                            <td className="px-2 py-3 text-sm text-right text-gray-700">
                              {toNepaliDigit(Number(block.regeneration_per_ha || 0), 0)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-gray-700">
                              {toNepaliDigit(Number(block.sapling_per_ha || 0), 0)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-gray-700">
                              {toNepaliDigit(Number(block.pole_per_ha || 0), 0)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-gray-700 border-r border-gray-200">
                              {toNepaliDigit(Number(block.tree_per_ha || 0), 0)}
                            </td>

                            {/* Pole volumes */}
                            <td className="px-2 py-3 text-sm text-right text-green-700 bg-green-50">
                              {toNepaliDigit(poleTimber, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-green-600 bg-green-50">
                              {toNepaliDigit(poleFirewood, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-green-900 font-semibold bg-green-50 border-r border-gray-200">
                              {toNepaliDigit(poleTotal, 2)}
                            </td>

                            {/* Tree volumes */}
                            <td className="px-2 py-3 text-sm text-right text-amber-700 bg-amber-50">
                              {toNepaliDigit(treeTimber, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-amber-600 bg-amber-50">
                              {toNepaliDigit(treeFirewood, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-amber-900 font-semibold bg-amber-50 border-r border-gray-200">
                              {toNepaliDigit(treeTotal, 2)}
                            </td>

                            {/* Growing stock (timber only) */}
                            <td className="px-3 py-3 text-sm text-right text-purple-700 font-bold border-r border-gray-200 bg-purple-50">
                              {toNepaliDigit(Number(block.total_growing_stock_m3_per_ha || 0), 2)}
                            </td>

                            {/* Total volume (timber + firewood) */}
                            <td className="px-3 py-3 text-sm text-right text-indigo-700 font-bold border-r border-gray-200 bg-indigo-50">
                              {toNepaliDigit((poleTotal + treeTotal), 2)}
                            </td>

                            {/* Basal area */}
                            <td className="px-3 py-3 text-sm text-right text-emerald-700 font-bold border-r border-gray-200 bg-emerald-50">
                              {block.basal_area_m2_per_ha ? toNepaliDigit(Number(block.basal_area_m2_per_ha), 2) : '-'}
                            </td>

                            {/* Satellite-derived volume */}
                            <td className="px-3 py-3 text-sm text-right text-blue-900 font-bold italic border-r-2 border-blue-400 bg-blue-100 shadow-sm">
                              {block.satellite_volume_m3_per_ha ? toNepaliDigit(Number(block.satellite_volume_m3_per_ha), 2) : '-'}
                            </td>

                            {/* Conditions */}
                            <td className="px-3 py-3 text-sm border-r border-gray-200">
                              <span className={`px-2 py-1 rounded-full text-xs font-semibold ${
                                block.regeneration_condition === 'Good' ? 'bg-green-100 text-green-800' :
                                block.regeneration_condition === 'Moderate' ? 'bg-yellow-100 text-yellow-800' :
                                'bg-red-100 text-red-800'
                              }`}>
                                {block.regeneration_condition || 'N/A'}
                              </span>
                            </td>
                            <td className="px-3 py-3 text-sm border-r border-gray-200">
                              <span className={`px-2 py-1 rounded-full text-xs font-semibold ${
                                block.forest_condition === 'Good' ? 'bg-green-100 text-green-800' :
                                block.forest_condition === 'Moderate' ? 'bg-yellow-100 text-yellow-800' :
                                'bg-red-100 text-red-800'
                              }`}>
                                {block.forest_condition || 'N/A'}
                              </span>
                            </td>

                            {/* MAI */}
                            <td className="px-3 py-3 text-sm text-right font-semibold text-gray-900 border-r border-gray-200">
                              {toNepaliDigit(Number(block.mai_percent || 0), 1)}%
                            </td>

                            {/* Carbon & Biomass (IPCC/REDD+) */}
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{block.weighted_wood_density ? toNepaliDigit(Number(block.weighted_wood_density), 3) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{block.agb_t_per_ha ? toNepaliDigit(Number(block.agb_t_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{block.bgb_t_per_ha ? toNepaliDigit(Number(block.bgb_t_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{block.total_biomass_t_per_ha ? toNepaliDigit(Number(block.total_biomass_t_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{block.carbon_stock_tc_per_ha ? toNepaliDigit(Number(block.carbon_stock_tc_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50 font-semibold text-teal-900">{block.co2_equivalent_tco2_per_ha ? toNepaliDigit(Number(block.co2_equivalent_tco2_per_ha), 2) : '-'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* DBH Class Breakdown Section */}
            {summary?.blocks && Array.isArray(summary.blocks) && summary.blocks.length > 0 && (
              <div className="mt-8">
                <h4 className="text-md font-semibold text-gray-900 mb-3 flex items-center gap-2">
                    {t('fieldInventory.dbhClassStock')}
                    <span className="flex flex-wrap gap-1">
                      <CopyTag label="{{fi_block_dbh_class_growing_stock_np}}" value="{{fi_block_dbh_class_growing_stock_np}}" variant="section" />
                      <CopyTag label="{{fi_block_dbh_class_ag_np}}" value="{{fi_block_dbh_class_ag_np}}" variant="section" />
                      <CopyTag label="{{fi_block_dbh_class_advance_np}}" value="{{fi_block_dbh_class_advance_np}}" variant="section" />
                      <CopyTag label="{{fi_block_dbh_class_mature_np}}" value="{{fi_block_dbh_class_mature_np}}" variant="section" />
                      <CopyTag label="{{chart:dbh_class_bar}}" value="{{chart:dbh_class_bar}}" variant="section" />
                      <CopyTag label="{{chart:dbh_class_count_bar}}" value="{{chart:dbh_class_count_bar}}" variant="section" />
                    </span>
                  </h4>
                <div className="overflow-x-auto" style={{ maxWidth: '100%' }}>
                  <table className="min-w-full divide-y divide-gray-200 text-sm" style={{ minWidth: '1600px' }}>
                    <thead className="bg-gray-50">
                      <tr>
                        <th rowSpan={2} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-gray-100 sticky left-0" style={{position:'sticky',left:0,background:'#f9fafb',zIndex:2}}>{labels.unitNameHeaderNp}</th>
                        <th rowSpan={2} className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-gray-100">{t('fieldInventory.plotCount')}</th>
                        {[
                          {range:'0-4', nameKey:'dbhClass.seedling'},
                          {range:'4-10', nameKey:'dbhClass.sapling'},
                          {range:'10-20', nameKey:'dbhClass.smallPole'},
                          {range:'20-30', nameKey:'dbhClass.largePole'},
                          {range:'30-40', nameKey:'dbhClass.smallTree'},
                          {range:'40-50', nameKey:'dbhClass.mediumTree'},
                          {range:'50-60', nameKey:'dbhClass.largeTree'},
                          {range:'≥60', nameKey:'dbhClass.veryLargeTree'},
                        ].map((item, i) => (
                          <th key={i} colSpan={3} className={`px-1 py-1 text-center text-xs font-medium border-r border-gray-300 ${i < 2 ? 'bg-orange-50' : i < 4 ? 'bg-yellow-50' : 'bg-green-50'}`}>
                            {item.range} ({t(item.nameKey)})
                          </th>
                        ))}
                      </tr>
                      <tr>
                        {Array(8).fill(0).flatMap((_, i) => [
                          <th key={`cnt_${i}`} className={`px-1 py-1 text-right text-[10px] font-medium ${i < 2 ? 'bg-orange-50' : i < 4 ? 'bg-yellow-50' : 'bg-green-50'} border-r border-gray-200`}>{t('fieldInventory.count')}</th>,
                          <th key={`tim_${i}`} className={`px-1 py-1 text-right text-[10px] font-medium ${i < 2 ? 'bg-orange-50' : i < 4 ? 'bg-yellow-50' : 'bg-green-50'} border-r border-gray-200`}>{t('fieldInventory.timber')}</th>,
                          <th key={`fw_${i}`} className={`px-1 py-1 text-right text-[10px] font-medium ${i < 2 ? 'bg-orange-50' : i < 4 ? 'bg-yellow-50' : 'bg-green-50'} ${i === 7 ? '' : 'border-r border-gray-300'}`}>{t('fieldInventory.firewood')}</th>
                        ])}
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                        {summary.blocks.map((block: any, idx: number) => {
                          const bd = block.dbh_class_breakdown || {};
                          return (
                            <tr key={idx} className="hover:bg-gray-50">
                              <td className="px-3 py-2 text-sm font-medium text-gray-900 border-r border-gray-200 sticky left-0 bg-white" style={{position:'sticky',left:0,zIndex:1}}>{displayBlockName(block.block_name)}</td>
                              <td className="px-3 py-2 text-sm text-gray-700 border-r border-gray-200">{toNepaliDigit(block.total_sample_plots, 0)}</td>
                              {dbhKeys.flatMap((k, i) => {
                                const d = bd[k];
                                const cnt = d?.count_per_ha ?? '-';
                                const tim = d?.timber_m3_per_ha ?? '-';
                                const fw = d?.firewood_m3_per_ha ?? '-';
                                // By name, not by index: a class inserted at the
                                // front of the system must not inherit or lose
                                // the greying.
                                const noTimber = noTimberKeys.has(k);
                                // And "last" is the end of the list that was
                                // actually fetched, not the number 7.
                                const isLast = i === dbhKeys.length - 1;
                                return [
                                  <td key={`${k}_cnt`} className={`px-1 py-2 text-sm text-right border-r border-gray-200 ${noTimber ? '' : 'font-medium'}`}>{cnt}</td>,
                                  <td key={`${k}_tim`} className={`px-1 py-2 text-sm text-right border-r border-gray-200 ${noTimber ? 'text-gray-300' : ''}`}>{noTimber ? '-' : tim}</td>,
                                  <td key={`${k}_fw`} className={`px-1 py-2 text-sm text-right ${noTimber ? 'text-gray-300' : ''} ${isLast ? '' : 'border-r border-gray-300'}`}>{noTimber ? '-' : fw}</td>,
                                ];
                              })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <p className="text-[10px] text-gray-400 mt-1">{t('fieldInventory.countNote')}</p>
              </div>
            )}

            {/* Species-wise Breakdown */}
            {speciesBreakdown && speciesBreakdown.species_breakdown && Array.isArray(speciesBreakdown.species_breakdown) && speciesBreakdown.species_breakdown.length > 0 && (
              <div className="mt-8">
                <h4 className="text-md font-semibold text-gray-900 mb-3 flex items-center gap-2">
                    {t('fieldInventory.speciesBreakdown', { unit: labels.unitWiseNpShort })}
                    <CopyTag label="{{fi_species_block_growing_stock}}" value="{{fi_species_block_growing_stock}}" variant="section" />
                  </h4>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitNameHeaderNp}</th>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.speciesSci')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.localName')}</th>
                        <th colSpan={4} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-blue-50">{t('fieldInventory.treesPerHa')}</th>
                        <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-green-50">{t('fieldInventory.poleVolume')}</th>
                        <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-amber-50">{t('fieldInventory.treeVolume')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-purple-50">{t('fieldInventory.gsTimberShort')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-indigo-50">{t('fieldInventory.totalVolume')}</th>
                        <th rowSpan={2} className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-emerald-50">{t('fieldInventory.basalAreaNp')}</th>
                        <th colSpan={6} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-teal-50">
                          <HelpTooltip helpText="IPCC Tier 2 Methodology: AGB = VOB × WD × BEF. VOB (gross merchantable stem volume, NOT net_volume), BEF=1.3, R/S=0.24, CF=0.47 (IPCC 2006 GL Vol 4 Tables 4.3, 4.4).">
                            <span>{t('fieldInventory.carbonBiomass')}</span>
                          </HelpTooltip>
                        </th>
                      </tr>
                      <tr>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50">{t('fieldInventory.seedling')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50">{t('fieldInventory.sapling')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50">{t('fieldInventory.pole')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-blue-50 border-r border-gray-300">{t('fieldInventory.tree')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-green-50">{t('fieldInventory.timber')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-green-50">{t('fieldInventory.firewood')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-green-50 border-r border-gray-300">{t('fieldInventory.total')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-amber-50">{t('fieldInventory.timber')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-amber-50">{t('fieldInventory.firewood')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-amber-50 border-r border-gray-300">{t('fieldInventory.total')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.woodDensityNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.agbNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.bgbNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.totalBiomassNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.carbonNp')}</th>
                        <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('fieldInventory.co2Np')}</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {speciesBreakdown.species_breakdown.map((species: any, idx: number) => {
                        const poleTimber = Number(species.pole_timber_m3_per_ha || 0);
                        const poleFirewood = Number(species.pole_firewood_m3_per_ha || 0);
                        const poleTotal = poleTimber + poleFirewood;
                        const treeTimber = Number(species.tree_timber_m3_per_ha || 0);
                        const treeFirewood = Number(species.tree_firewood_m3_per_ha || 0);
                        const treeTotal = treeTimber + treeFirewood;

                        return (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="px-3 py-3 text-sm text-gray-700 border-r border-gray-200">{displayBlockName(species.block_name)}</td>
                            <td className="px-3 py-3 text-sm font-medium text-gray-900 border-r border-gray-200 italic">{species.species_scientific}</td>
                            <td className="px-3 py-3 text-sm text-gray-700 border-r border-gray-200">{species.species_local || '-'}</td>

                            {/* Trees per hectare */}
                            <td className="px-2 py-3 text-sm text-right text-gray-700">
                              {toNepaliDigit(Number(species.regeneration_per_ha || 0), 0)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-gray-700">
                              {toNepaliDigit(Number(species.sapling_per_ha || 0), 0)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-gray-700">
                              {toNepaliDigit(Number(species.pole_per_ha || 0), 0)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-gray-700 border-r border-gray-200">
                              {toNepaliDigit(Number(species.tree_per_ha || 0), 0)}
                            </td>

                            {/* Pole volumes */}
                            <td className="px-2 py-3 text-sm text-right text-green-700 bg-green-50">
                              {toNepaliDigit(poleTimber, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-green-600 bg-green-50">
                              {toNepaliDigit(poleFirewood, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-green-900 font-semibold bg-green-50 border-r border-gray-200">
                              {toNepaliDigit(poleTotal, 2)}
                            </td>

                            {/* Tree volumes */}
                            <td className="px-2 py-3 text-sm text-right text-amber-700 bg-amber-50">
                              {toNepaliDigit(treeTimber, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-amber-600 bg-amber-50">
                              {toNepaliDigit(treeFirewood, 2)}
                            </td>
                            <td className="px-2 py-3 text-sm text-right text-amber-900 font-semibold bg-amber-50 border-r border-gray-200">
                              {toNepaliDigit(treeTotal, 2)}
                            </td>

                            {/* Growing stock and total volume */}
                            <td className="px-3 py-3 text-sm text-right text-purple-700 font-bold border-r border-gray-200 bg-purple-50">
                              {toNepaliDigit(Number(species.growing_stock_m3_per_ha || 0), 2)}
                            </td>
                            <td className="px-3 py-3 text-sm text-right text-indigo-700 font-bold border-r border-gray-200 bg-indigo-50">
                              {toNepaliDigit(Number(species.total_volume_m3_per_ha || 0), 2)}
                            </td>

                            {/* Basal area */}
                            <td className="px-3 py-3 text-sm text-right text-emerald-700 font-bold border-r border-gray-200 bg-emerald-50">
                              {species.basal_area_m2_per_ha ? toNepaliDigit(Number(species.basal_area_m2_per_ha), 2) : '-'}
                            </td>

                            {/* Carbon & Biomass (IPCC/REDD+) */}
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{species.wood_density_t_m3 ? toNepaliDigit(Number(species.wood_density_t_m3), 3) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{species.agb_t_per_ha ? toNepaliDigit(Number(species.agb_t_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{species.bgb_t_per_ha ? toNepaliDigit(Number(species.bgb_t_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{species.total_biomass_t_per_ha ? toNepaliDigit(Number(species.total_biomass_t_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50">{species.carbon_stock_tc_per_ha ? toNepaliDigit(Number(species.carbon_stock_tc_per_ha), 2) : '-'}</td>
                            <td className="px-2 py-3 text-sm text-right whitespace-nowrap bg-teal-50 font-semibold text-teal-900">{species.co2_equivalent_tco2_per_ha ? toNepaliDigit(Number(species.co2_equivalent_tco2_per_ha), 2) : '-'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* MAI and AAH Tables */}
            {maiAahData && (
              <>
                {/* AAH Multiplier Controls */}
                <div className="mt-8 bg-yellow-50 rounded-lg border border-yellow-200 p-4">
                  <h4 className="text-sm font-semibold text-gray-900 mb-3">{t('fieldInventory.aahSettings')}</h4>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.goodForest')}</label>
                      <input
                        type="text" inputMode="decimal"
                        value={aahMultipliers.good}
                        onChange={(e) => {
                          const v = parseLocaleNumber(e.target.value);
                          setAahMultipliers({ ...aahMultipliers, good: Number.isNaN(v) ? 0 : v });
                        }}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md"
                        min="0"
                        max="100"
                        step="5"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.moderateForest')}</label>
                      <input
                        type="text" inputMode="decimal"
                        value={aahMultipliers.moderate}
                        onChange={(e) => {
                          const v = parseLocaleNumber(e.target.value);
                          setAahMultipliers({ ...aahMultipliers, moderate: Number.isNaN(v) ? 0 : v });
                        }}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md"
                        min="0"
                        max="100"
                        step="5"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.weakForest')}</label>
                      <input
                        type="text" inputMode="decimal"
                        value={aahMultipliers.weak}
                        onChange={(e) => {
                          const v = parseLocaleNumber(e.target.value);
                          setAahMultipliers({ ...aahMultipliers, weak: Number.isNaN(v) ? 0 : v });
                        }}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md"
                        min="0"
                        max="100"
                        step="5"
                      />
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      if (fieldInventory?.id) {
                        const result = await fieldInventoryApi.getMaiAah(
                          fieldInventory.id,
                          aahMultipliers.good,
                          aahMultipliers.moderate,
                          aahMultipliers.weak,
                          customMultipliers
                        );
                        setMaiAahData(result);
                      }
                    }}
                    className="mt-3 px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700 text-sm"
                  >
                    {t('fieldInventory.recalcAah')}
                  </button>
                  <button
                    onClick={() => {
                      setCustomMultipliers({});
                      // Recalculate will happen automatically via useEffect
                      if (fieldInventory?.id) {
                        fieldInventoryApi.getMaiAah(
                          fieldInventory.id,
                          aahMultipliers.good,
                          aahMultipliers.moderate,
                          aahMultipliers.weak,
                          {}
                        ).then(setMaiAahData);
                      }
                    }}
                    className="mt-3 ml-2 px-4 py-2 bg-gray-500 text-white rounded-md hover:bg-gray-600 text-sm"
                  >
                    {t('fieldInventory.resetDefaults')}
                  </button>
                </div>

                {/* MAI Table */}
                <div className="mt-8">
                  <h4 className="text-md font-semibold text-gray-900 mb-3 flex items-center gap-2">
                    {t('fieldInventory.maiTable')}
                    <CopyTag label="{{fi_mai_table}}" value="{{fi_mai_table}}" variant="section" />
                  </h4>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-purple-50">
                        <tr>
                          <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitNameHeaderNp}</th>
                          <th colSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.treesPerHa')}</th>
                          <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.poleMai')}</th>
                          <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.treeMai')}</th>
                          <th rowSpan={2} className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase bg-purple-100">{t('fieldInventory.totalMai')}</th>
                        </tr>
                        <tr>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.pole')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.tree')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.timber')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.firewood')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.total')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.timber')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.firewood')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.total')}</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {maiAahData?.mai_blocks && Array.isArray(maiAahData.mai_blocks) && maiAahData.mai_blocks.map((mai: any, index: number) => (
                          <tr key={index} className="hover:bg-gray-50">
                            <td className="px-3 py-3 text-sm font-medium text-gray-900 border-r border-gray-200">{displayBlockName(mai.block_name)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(mai.pole_per_ha || 0, 0)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(mai.tree_per_ha || 0, 0)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(mai.pole_timber_m3_per_ha, 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(mai.pole_firewood_m3_per_ha, 2)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(mai.pole_total_m3_per_ha, 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(mai.tree_timber_m3_per_ha, 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(mai.tree_firewood_m3_per_ha, 2)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(mai.tree_total_m3_per_ha, 2)}</td>
                            <td className="px-2 py-3 text-sm text-right font-bold text-purple-700 bg-purple-50">{toNepaliDigit(mai.total_mai_m3_per_ha, 2)}</td>
                          </tr>
                        ))}
                        {/* Overall Row */}
                        {maiAahData?.mai_overall && (
                          <tr className="bg-purple-100 font-bold">
                            <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('fieldInventory.totalForest')}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(maiAahData.mai_overall.pole_per_ha || 0, 0)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(maiAahData.mai_overall.tree_per_ha || 0, 0)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.mai_overall.pole_timber_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.mai_overall.pole_firewood_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(Number(maiAahData.mai_overall.pole_total_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.mai_overall.tree_timber_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.mai_overall.tree_firewood_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(Number(maiAahData.mai_overall.tree_total_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right font-bold text-purple-900">{toNepaliDigit(Number(maiAahData.mai_overall.total_mai_m3_per_ha || 0), 2)}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* AAH Table */}
                <div className="mt-8">
                  <h4 className="text-md font-semibold text-gray-900 mb-1 flex items-center gap-2">
                    {t('fieldInventory.aahTable')}
                    <CopyTag label="{{fi_aah_table}}" value="{{fi_aah_table}}" variant="section" />
                  </h4>
                  <p className="text-xs text-gray-500 mb-3 leading-relaxed">
                    <strong>{t('fieldInventory.maiDefColon')}</strong> {t('fieldInventory.maiDefText')}
                    <br />
                    <strong>{t('fieldInventory.aahDefColon')}</strong> {t('fieldInventory.aahDefText')}
                  </p>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200 text-sm">
                      <thead className="bg-amber-50">
                        <tr>
                          <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitNameHeaderNp}</th>
                          <th colSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.treesPerHa')}</th>
                          <th rowSpan={2} className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.condition')}</th>
                          <th rowSpan={2} className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.harvestPercent')}</th>
                          <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.poleAah')}</th>
                          <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.treeAah')}</th>
                          <th rowSpan={2} className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase bg-amber-100">{t('fieldInventory.totalAah')}</th>
                        </tr>
                        <tr>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.pole')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.tree')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.timber')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.firewood')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.total')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.timber')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('fieldInventory.firewood')}</th>
                          <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('fieldInventory.total')}</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {maiAahData?.aah_blocks && Array.isArray(maiAahData.aah_blocks) && maiAahData.aah_blocks.map((aah: any, index: number) => {
                          const block = summary?.blocks?.find((b: any) => b.block_name === aah.block_name);
                          return (
                            <tr key={index} className="hover:bg-gray-50">
                              <td className="px-3 py-3 text-sm font-medium text-gray-900 border-r border-gray-200">{displayBlockName(aah.block_name)}</td>
                              <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(aah.pole_per_ha || 0, 0)}</td>
                              <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(aah.tree_per_ha || 0, 0)}</td>
                              <td className={`px-3 py-3 text-sm text-center font-semibold border-r border-gray-200 ${
                                aah.forest_condition === 'Good' ? 'text-green-600' :
                                aah.forest_condition === 'Moderate' ? 'text-yellow-600' :
                                'text-red-600'
                              }`}>{aah.forest_condition}</td>
                              <td className="px-3 py-3 text-sm text-center border-r border-gray-200">
                                <div className="flex items-center justify-center gap-1">
                                  {editingBlock === aah.block_name ? (
                                    // Inline editing mode
                                    <div className="flex items-center gap-1">
                                      <input
                                        type="text" inputMode="decimal"
                                        value={editingValue}
                                        onChange={(e) => setEditingValue(e.target.value)}
                                        onBlur={() => handleSaveInlineEdit(aah.block_name)}
                                        onKeyDown={(e) => {
                                          if (e.key === 'Enter') handleSaveInlineEdit(aah.block_name);
                                          if (e.key === 'Escape') handleCancelInlineEdit();
                                        }}
                                        autoFocus
                                        className="w-16 px-2 py-1 border border-blue-500 rounded text-center focus:outline-none focus:ring-2 focus:ring-blue-500"
                                        min="0"
                                        max="100"
                                        step="1"
                                      />
                                      <span className="text-xs">%</span>
                                    </div>
                                  ) : (
                                    // Display mode
                                    <>
                                      <span
                                        onClick={() => handleStartInlineEdit(aah.block_name, aah.aah_multiplier_percent)}
                                        className={`cursor-pointer hover:bg-gray-100 px-2 py-1 rounded ${
                                          aah.is_custom ? 'text-orange-600 font-semibold' : 'text-gray-900'
                                        }`}
                                        title={aah.is_custom ? t('fieldInventory.customWithDefault', { percent: aah.default_multiplier_percent }) : t('fieldInventory.clickToEdit')}
                                      >
                                        {toNepaliDigit(aah.aah_multiplier_percent, 0)}%
                                      </span>
                                      {aah.is_custom && (
                                        <span className="text-orange-500 text-xs font-bold" title={t('fieldInventory.customPercent')}>⚠️</span>
                                      )}
                                      <button
                                        onClick={() => handleOpenModal(aah)}
                                        className="text-blue-500 hover:text-blue-700 text-xs"
                                        title={t('fieldInventory.openEditor')}
                                      >
                                        ℹ️
                                      </button>
                                    </>
                                  )}
                                </div>
                              </td>
                              <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(aah.pole_timber_m3_per_ha, 2)}</td>
                              <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(aah.pole_firewood_m3_per_ha, 2)}</td>
                              <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(aah.pole_total_m3_per_ha, 2)}</td>
                              <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(aah.tree_timber_m3_per_ha, 2)}</td>
                              <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(aah.tree_firewood_m3_per_ha, 2)}</td>
                              <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(aah.tree_total_m3_per_ha, 2)}</td>
                              <td className="px-2 py-3 text-sm text-right font-bold text-amber-700 bg-amber-50">{toNepaliDigit(aah.total_aah_m3_per_ha, 2)}</td>
                            </tr>
                          );
                        })}
                        {/* Overall Row */}
                        {maiAahData?.aah_overall && (
                          <tr className="bg-amber-100 font-bold">
                            <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('fieldInventory.totalForest')}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(maiAahData.aah_overall.pole_per_ha || 0, 0)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(maiAahData.aah_overall.tree_per_ha || 0, 0)}</td>
                            <td className={`px-3 py-3 text-sm text-center font-bold border-r border-gray-200 ${
                              maiAahData.aah_overall.forest_condition === 'Good' ? 'text-green-700' :
                              maiAahData.aah_overall.forest_condition === 'Moderate' ? 'text-yellow-700' :
                              'text-red-700'
                            }`}>{maiAahData.aah_overall.forest_condition || 'N/A'}</td>
                            <td className="px-3 py-3 text-sm text-center border-r border-gray-200">{toNepaliDigit(Number(maiAahData.aah_overall.aah_multiplier_percent || 0), 0)}%</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.aah_overall.pole_timber_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.aah_overall.pole_firewood_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(Number(maiAahData.aah_overall.pole_total_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.aah_overall.tree_timber_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right">{toNepaliDigit(Number(maiAahData.aah_overall.tree_firewood_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{toNepaliDigit(Number(maiAahData.aah_overall.tree_total_m3_per_ha || 0), 2)}</td>
                            <td className="px-2 py-3 text-sm text-right font-bold text-amber-900">{toNepaliDigit(Number(maiAahData.aah_overall.total_aah_m3_per_ha || 0), 2)}</td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* AAH Multiplier Editing Modal */}
        {modalBlock && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
              <h3 className="text-lg font-bold text-gray-900 mb-4">
                {t('fieldInventory.modalTitle', { name: displayBlockName(modalBlock.block_name) })}
              </h3>

              <div className="space-y-4">
                {/* Forest Condition */}
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="text-sm text-gray-600">{t('fieldInventory.forestStatus')}</div>
                  <div className={`text-xl font-bold ${
                    modalBlock.forest_condition === 'Good' ? 'text-green-600' :
                    modalBlock.forest_condition === 'Moderate' ? 'text-yellow-600' :
                    'text-red-600'
                  }`}>
                    {CONDITION_LABEL_KEY[modalBlock.forest_condition]
                      ? t(CONDITION_LABEL_KEY[modalBlock.forest_condition])
                      : modalBlock.forest_condition}
                  </div>
                </div>

                {/* Default Multiplier */}
                <div className="bg-blue-50 rounded-lg p-3">
                  <div className="text-sm text-gray-600">{t('fieldInventory.defaultPercent')}</div>
                  <div className="text-xl font-bold text-blue-700">
                    {modalBlock.default_multiplier_percent}%
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    {t('fieldInventory.basedOnCondition', {
                      condition: CONDITION_LABEL_KEY[modalBlock.forest_condition]
                        ? t(CONDITION_LABEL_KEY[modalBlock.forest_condition])
                        : modalBlock.forest_condition,
                    })}
                  </div>
                </div>

                {/* Current Multiplier */}
                <div className={`rounded-lg p-3 ${modalBlock.is_custom ? 'bg-orange-50' : 'bg-gray-50'}`}>
                  <div className="text-sm text-gray-600">{t('fieldInventory.currentPercent')}</div>
                  <div className={`text-xl font-bold ${modalBlock.is_custom ? 'text-orange-600' : 'text-gray-700'}`}>
                    {toNepaliDigit(modalBlock.aah_multiplier_percent, 0)}%
                    {modalBlock.is_custom && <span className="text-sm ml-2">{t('fieldInventory.customTag')}</span>}
                  </div>
                </div>

                {/* Custom Multiplier Input */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {t('fieldInventory.setCustomPercent')}
                  </label>
                  <input
                    type="text" inputMode="decimal"
                    defaultValue={toNepaliDigit(modalBlock.aah_multiplier_percent, 0)}
                    onChange={(e) => {
                      const input = e.target as HTMLInputElement;
                      input.dataset.value = e.target.value;
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                    min="0"
                    max="100"
                    step="1"
                  />
                  <div className="text-xs text-gray-500 mt-1">
                    {t('fieldInventory.recommendedRange')}
                  </div>
                </div>

                {/* Guidance */}
                <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
                  <div className="text-xs font-semibold text-yellow-800 mb-1">{t('fieldInventory.mgmtGuidance')}</div>
                  <ul className="text-xs text-yellow-700 space-y-1">
                    <li>{t('fieldInventory.guideGood')}</li>
                    <li>{t('fieldInventory.guideModerate')}</li>
                    <li>{t('fieldInventory.guideWeak')}</li>
                    <li>{t('fieldInventory.guideLocal')}</li>
                  </ul>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex justify-end gap-3 mt-6">
                <button
                  onClick={() => {
                    // Reset to default
                    handleSaveModal(modalBlock.default_multiplier_percent);
                  }}
                  className="px-4 py-2 text-sm bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300"
                >
                  {t('fieldInventory.useDefault')}
                </button>
                <button
                  onClick={handleCloseModal}
                  className="px-4 py-2 text-sm bg-gray-500 text-white rounded-md hover:bg-gray-600"
                >
                  {t('fieldInventory.cancel')}
                </button>
                <button
                  onClick={(e) => {
                    const input = (e.target as HTMLElement).closest('.bg-white')?.querySelector('input[type="text" inputMode="decimal"]') as HTMLInputElement;
                    const value = parseFloat(input?.value || input?.dataset.value || '0');
                    handleSaveModal(value);
                  }}
                  className="px-4 py-2 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
                >
                  {t('fieldInventory.apply')}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Stock by species, species x DBH, absolute DBH, MAI/AAH by species and
            by DBH class, economic valuation, sustainability index — the
            `totalInventory.*` tables carried over from the old
            `TotalInventoryTab` (P5d). */}
        {view === 'results' && <FieldInventoryResultsTables />}
      </div>
    );
  }

  // Upload interface
  //
  // Data-only. The host locks the Results pane until the step has data, so this
  // should be unreachable from there; the guard makes it a fact rather than a
  // hope, because the alternative is a Results tab offering to replace a file it
  // just said was not there.
  if (view === 'results') {
    return (
      <div className="bg-white rounded-lg shadow p-6 text-sm text-gray-600" data-testid="fieldinventory-results-empty">
        {t('fieldInventory.noDataForResults')}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-1">{t('fieldInventory.uploadTitle')}</h3>
        {/* The Upload Data pane is drawn even when an inventory exists (the file is chosen here), so the line follows the real state: a record
            on the server, or one this very upload just stored (validated, about to be processed). */}
        <UploadStateLine
          present={!!fieldInventory || !!validationResult?.field_inventory_id}
          detail={fieldInventory?.uploaded_filename ?? file?.name}
          className="mb-4"
        />

        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}
        {uploadFindings && <div className="mb-4"><UploadReport findings={uploadFindings} /></div>}

        {validationResult && (
          <div className="mb-4 p-4 bg-blue-50 border border-blue-200 rounded-md">
            <h4 className="text-sm font-semibold text-blue-900 mb-2">{t('fieldInventory.validationResults')}</h4>
            <div className="space-y-1 text-sm text-blue-800">
              <p>{t('fieldInventory.totalRows')}: {validationResult.summary?.total_rows || 0}</p>
              <p>{t('fieldInventory.readyForProcessing')}: {validationResult.summary?.ready_for_processing ? t('common.yes') : t('common.no')}</p>
              {/* the plain-language findings replace the raw error list: what is wrong, where, and how to fix it */}
              {validationResult.findings && validationResult.findings.length > 0 && (
                <div className="mt-2"><UploadReport findings={validationResult.findings} /></div>
              )}
              {validationResult.preview && <UploadPointsPreview preview={validationResult.preview} />}
              {!(validationResult.findings && validationResult.findings.length > 0) && validationResult.errors && validationResult.errors.length > 0 && (
                <div className="mt-2">
                  <p className="font-semibold text-red-700">{t('fieldInventory.errorsLabel')}</p>
                  <ul className="list-disc list-inside">
                    {validationResult.errors.map((err: any, idx: number) => (
                      <li key={idx} className="text-red-700">{err.message || err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Sample Plot Sizes Configuration */}
        <div className="mb-6">
          <h4 className="text-sm font-semibold text-gray-700 mb-3">{t('fieldInventory.plotSizes')}</h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.seedlingM2')}</label>
              <input
                type="text" inputMode="decimal"
                value={sampleSizes.regeneration_area_sqm}
                onChange={(e) => setSampleSizes({ ...sampleSizes, regeneration_area_sqm: parseLocaleNumber(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                step="0.1"
              />
              <p className="text-xs text-gray-500 mt-1">Radius: {toNepaliDigit(Math.sqrt(sampleSizes.regeneration_area_sqm / Math.PI), 2)}m</p>
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.saplingM2')}</label>
              <input
                type="text" inputMode="decimal"
                value={sampleSizes.sapling_area_sqm}
                onChange={(e) => setSampleSizes({ ...sampleSizes, sapling_area_sqm: parseLocaleNumber(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                step="0.1"
              />
              <p className="text-xs text-gray-500 mt-1">Radius: {toNepaliDigit(Math.sqrt(sampleSizes.sapling_area_sqm / Math.PI), 2)}m</p>
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.poleM2')}</label>
              <input
                type="text" inputMode="decimal"
                value={sampleSizes.pole_area_sqm}
                onChange={(e) => setSampleSizes({ ...sampleSizes, pole_area_sqm: parseLocaleNumber(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                step="0.1"
              />
              <p className="text-xs text-gray-500 mt-1">Radius: {toNepaliDigit(Math.sqrt(sampleSizes.pole_area_sqm / Math.PI), 2)}m</p>
            </div>
            <div>
              <label className="block text-sm text-gray-600 mb-1">{t('fieldInventory.treeM2')}</label>
              <input
                type="text" inputMode="decimal"
                value={sampleSizes.tree_area_sqm}
                onChange={(e) => setSampleSizes({ ...sampleSizes, tree_area_sqm: parseLocaleNumber(e.target.value) })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                step="0.1"
              />
              <p className="text-xs text-gray-500 mt-1">Radius: {toNepaliDigit(Math.sqrt(sampleSizes.tree_area_sqm / Math.PI), 2)}m</p>
            </div>
          </div>
        </div>

        {/* File Upload */}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('fieldInventory.csvXlsx')}
            </label>
            <input
              type="file"
              accept=".csv,.xlsx"
              onChange={handleFileChange}
              className="block w-full text-sm text-gray-500
                file:mr-4 file:py-2 file:px-4
                file:rounded-md file:border-0
                file:text-sm file:font-semibold
                file:bg-green-50 file:text-green-700
                hover:file:bg-green-100"
            />
          </div>

          <button
            onClick={handleUpload}
            disabled={!file || uploading || processing}
            className="w-full px-4 py-3 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:bg-gray-400 font-semibold"
          >
            {uploading ? t('fieldInventory.uploading') : processing ? t('fieldInventory.processing') : t('fieldInventory.uploadAndProcess')}
          </button>
        </div>

        {/* Information */}
        <div className="mt-6 p-4 bg-gray-50 rounded-md">
          <h4 className="text-sm font-semibold text-gray-700 mb-2">{t('fieldInventory.requiredColumns')}</h4>
          <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
            <li>{labels.unitNameHeaderEn}, Sample Plot Number</li>
            <li>{t('fieldInventory.latLon')}</li>
            <li>4 Species Columns: Seedling, Sapling, Pole, Tree</li>
            <li>4 DBH Columns: Seedling (&lt;4cm), Sapling (4-10cm), Pole (10-30cm), Tree (≥30cm)</li>
            <li>2 Count Columns: Seedling Count, Sapling Count</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
