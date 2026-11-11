/** AnalysisTabContent — tab content container for analysis results, charts, and tables. */
import React, { useState, useEffect } from 'react';
import MetricCard from './MetricCard';
import CollapsibleSection from './CollapsibleSection';
import PercentageBar from './PercentageBar';
import { EditableCell } from './EditableCell';
import SpeciesTable from './SpeciesTable';
import SpeciesCoverageChart from './SpeciesCoverageChart';
import SpeciesSummaryTable from './SpeciesSummaryTable';
import AddSpeciesModal from './AddSpeciesModal';
import { forestApi } from '../services/api';
import { useDimensionLabelsFromCalculation } from '../hooks/useDimensionLabels';
import FertilityBadge from './FertilityBadge';
import { useT } from '../i18n/hooks';

interface AnalysisTabContentProps {
  calculation: any;
  blocks: any[];
  totalBlocks: number;
  handleSaveWholeForest: (field: string, value: any) => Promise<void>;
  handleSaveWholeExtent: (field: string, value: any) => Promise<void>;
  handleSaveWholePercentages: (field: string, key: string, value: any) => Promise<void>;
  handleSaveBlockExtent: (blockIndex: number, field: string, value: any) => Promise<void>;
  handleSaveBlockField: (blockIndex: number, field: string, value: any) => Promise<void>;
  handleSaveBlockPercentages: (blockIndex: number, field: string, key: string, value: any) => Promise<void>;
  onRefresh?: () => void;
  subAreas?: any[];
}

const AnalysisTabContent: React.FC<AnalysisTabContentProps> = ({
  calculation,
  blocks,
  totalBlocks,
  handleSaveWholeForest,
  handleSaveWholeExtent,
  handleSaveWholePercentages,
  handleSaveBlockExtent,
  handleSaveBlockField,
  handleSaveBlockPercentages,
  onRefresh,
  subAreas,
}) => {
  const t = useT();
  const [isAddSpeciesModalOpen, setIsAddSpeciesModalOpen] = useState(false);
  const [speciesSummary, setSpeciesSummary] = useState<any>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);

  // Accessible forest area state (Phase 2)
  const [accessibleAreaData, setAccessibleAreaData] = useState<any>(null);
  const [loadingAccessibleArea, setLoadingAccessibleArea] = useState(false);
  const [showSlopeFilter, setShowSlopeFilter] = useState(false);
  const [maxSlopeForView, setMaxSlopeForView] = useState(45.0);

  const data = calculation.result_data || {};
  const labels = useDimensionLabelsFromCalculation(calculation);

  // Fetch species summary data for analytics dashboard
  useEffect(() => {
    const fetchSpeciesSummary = async () => {
      if (!calculation?.id || totalBlocks === 0) return;

      setLoadingSummary(true);
      try {
        const data = await forestApi.getSpeciesSummary(calculation.id);
        setSpeciesSummary(data);
      } catch (err) {
        console.error('Error fetching species summary:', err);
        setSpeciesSummary(null);
      } finally {
        setLoadingSummary(false);
      }
    };

    fetchSpeciesSummary();
  }, [calculation?.id, totalBlocks]);

  // Fetch accessible forest area data (Phase 2)
  useEffect(() => {
    const fetchAccessibleArea = async () => {
      if (!calculation?.id) return;

      setLoadingAccessibleArea(true);
      try {
        const data = await forestApi.getAccessibleForestArea(calculation.id, {
          filter_slope: showSlopeFilter,
          max_slope_degrees: maxSlopeForView
        });
        setAccessibleAreaData(data);
      } catch (err) {
        console.error('Error fetching accessible area:', err);
        setAccessibleAreaData(null);
      } finally {
        setLoadingAccessibleArea(false);
      }
    };

    fetchAccessibleArea();
  }, [calculation?.id, showSlopeFilter, maxSlopeForView]);

  // Prepare slope data for percentage bar
  const slopeData = data.slope_percentages
    ? Object.entries(data.slope_percentages).map(([label, value]: [string, any]) => ({
        label: label.charAt(0).toUpperCase() + label.slice(1),
        value: value,
        color: label === 'gentle' ? '#10b981' : label === 'moderate' ? '#fbbf24' : label === 'steep' ? '#f97316' : '#ef4444'
      }))
    : [];

  // Prepare aspect data for percentage bar
  const aspectData = data.aspect_percentages
    ? Object.entries(data.aspect_percentages).map(([label, value]: [string, any]) => ({
        label: label.toUpperCase(),
        value: value
      }))
    : [];

  // Prepare canopy data with distinct colors for each class
  const getCanopyColor = (label: string): string => {
    const colorMap: { [key: string]: string } = {
      'high_forest': '#059669',        // dark green
      'pole_trees': '#10b981',         // green
      'bush_regenerated': '#84cc16',   // lime
      'non_forest': '#94a3b8',         // slate gray
      'dense': '#059669',              // dark green (fallback)
      'medium': '#10b981',             // green (fallback)
      'sparse': '#84cc16'              // lime (fallback)
    };

    // Check exact match first
    if (colorMap[label]) return colorMap[label];

    // Check if label contains any of the keys
    for (const [key, color] of Object.entries(colorMap)) {
      if (label.includes(key)) return color;
    }

    // Default fallback
    return '#fbbf24'; // amber
  };

  const canopyData = data.canopy_percentages
    ? Object.entries(data.canopy_percentages).map(([label, value]: [string, any]) => ({
        label: label.replace('_', ' ').charAt(0).toUpperCase() + label.replace('_', ' ').slice(1),
        value: value,
        color: getCanopyColor(label)
      }))
    : [];

  return (
    <div className="space-y-6">
      {/* Key Metrics Dashboard - Always Visible */}
      <div className="bg-gradient-to-r from-green-50 to-blue-50 p-6 rounded-lg border border-green-200">
        <h2 className="text-2xl font-bold text-gray-900 mb-4 flex items-center gap-2">
          <span>📊</span>
          {calculation.forest_name} - {t('analysis.keyMetrics')}
        </h2>
        <p className="text-sm text-gray-600 mb-6">
          {t('analysis.keyMetricsDesc')}
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <MetricCard
            icon="📏"
            label={t('analysis.totalArea')}
            value={data.area_hectares}
            unit={t('analysis.hectares')}
            color="green"
            subtitle={totalBlocks > 1 ? `${totalBlocks} ${labels.unitLabelPluralLower}` : `1 ${labels.unitLabelLower}`}
          />

          <MetricCard
            icon="⛰️"
            label={t('analysis.elevationMean')}
            value={data.elevation_mean_m}
            unit={t('analysis.meters')}
            color="blue"
            subtitle={data.elevation_min_m && data.elevation_max_m ? `${data.elevation_min_m?.toFixed(0)} - ${data.elevation_max_m?.toFixed(0)} m` : undefined}
          />

          <MetricCard
            icon="🌳"
            label={t('analysis.carbonStock')}
            value={data.carbon_stock_mg}
            unit={t('analysis.mg')}
            color="green"
            subtitle={data.carbon_stock_mg ? `${(data.carbon_stock_mg / (data.area_hectares || 1)).toFixed(1)} ${t('analysis.mgPerHa')}` : undefined}
          />

          <MetricCard
            icon="💚"
            label={t('analysis.forestHealth')}
            value={data.forest_health_dominant || t('common.na')}
            color={
              data.forest_health_dominant === 'healthy' || data.forest_health_dominant === 'very_healthy' ? 'green' :
              data.forest_health_dominant === 'moderate' ? 'yellow' : 'red'
            }
            subtitle={data.forest_health_percentages && data.forest_health_dominant ?
              `${data.forest_health_percentages[data.forest_health_dominant]?.toFixed(1)}% ${t('analysis.ofArea')}` : undefined}
          />

          <MetricCard
            icon="🧭"
            label={t('analysis.dominantAspect')}
            value={data.aspect_dominant ? data.aspect_dominant.toUpperCase() : t('common.na')}
            color="blue"
            subtitle={data.aspect_percentages && data.aspect_dominant ?
              `${data.aspect_percentages[data.aspect_dominant]?.toFixed(1)}% ${t('analysis.facing')} ${data.aspect_dominant}` : undefined}
          />

          <MetricCard
            icon="⛰️"
            label={t('analysis.dominantSlope')}
            value={data.slope_dominant_class || t('common.na')}
            color={
              data.slope_dominant_class === 'gentle' ? 'green' :
              data.slope_dominant_class === 'moderate' ? 'yellow' :
              data.slope_dominant_class === 'steep' ? 'yellow' : 'red'
            }
            subtitle={data.slope_percentages && data.slope_dominant_class ?
              `${data.slope_percentages[data.slope_dominant_class]?.toFixed(1)}% ${t('analysis.ofArea')}` : undefined}
          />
        </div>
      </div>

{/* Accessible Forest Area (Phase 2) */}
      <CollapsibleSection
        title={t('analysis.accessibleForestAreaTitle')}
        icon="🌲"
        defaultExpanded={true}
        headerColor="green"
      >
        <div className="p-6 space-y-6">
          <p className="text-sm text-gray-600 mb-4">
            {t('analysis.accessibleForestAreaDesc')}
          </p>

          {/* Slope Filter Controls */}
          <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={showSlopeFilter}
                onChange={(e) => setShowSlopeFilter(e.target.checked)}
                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
              />
              <span className="text-sm font-medium text-gray-700">{t('analysis.applySlopeFilter')}</span>
            </label>

            {showSlopeFilter && (
              <select
                value={maxSlopeForView}
                onChange={(e) => setMaxSlopeForView(parseFloat(e.target.value))}
                className="px-3 py-1.5 border border-gray-300 rounded-md bg-white text-sm"
              >
                <option value="30">{t('analysis.maxSlope30')}</option>
                <option value="45">{t('analysis.maxSlope45')}</option>
                <option value="60">{t('analysis.maxSlope60')}</option>
              </select>
            )}
          </div>

          {loadingAccessibleArea ? (
            <div className="flex items-center justify-center py-12">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mx-auto mb-4"></div>
                <p className="text-gray-600">{t('analysis.calculatingAccessibleArea')}</p>
              </div>
            </div>
          ) : accessibleAreaData && accessibleAreaData.blocks ? (
            <div className="space-y-4">
              {/* Summary Cards */}
              {accessibleAreaData.blocks.map((block: any, index: number) => (
                <div key={index} className="bg-white border rounded-lg overflow-hidden">
                  <div className="bg-gray-100 px-4 py-2 border-b">
                    <h4 className="font-semibold text-gray-900">{block.block_name}</h4>
                    <p className="text-xs text-gray-600">{t('analysis.totalAreaLabel', { area: block.total_boundary_area_ha?.toFixed(2) })}</p>
                  </div>

                  <div className="p-4 space-y-3">
                    {/* Accessible Forest */}
                    <div className="flex justify-between items-center py-2 bg-green-50 px-3 rounded border border-green-200">
                      <div>
                        <span className="text-sm font-medium text-green-900">{t('analysis.accessibleForest')}</span>
                        <p className="text-xs text-green-700 mt-0.5">
                          {t('analysis.treeCover', { slope: showSlopeFilter ? `+ ${t('analysis.slopeLe', { degrees: maxSlopeForView })}` : '' })} • {t('analysis.canEstablishSamplePlots')}
                        </p>
                      </div>
                      <div className="text-right">
                        <span className="font-bold text-green-700 text-lg">
                          {block.accessible_forest_area_ha?.toFixed(2)} ha
                        </span>
                        <p className="text-xs text-green-600">
                          ({block.accessible_forest_percentage?.toFixed(1)}%)
                        </p>
                      </div>
                    </div>

                    {/* Inaccessible Forest (if slope filter is on) */}
                    {showSlopeFilter && block.inaccessible_steep_forest_ha > 0 && (
                      <div className="flex justify-between items-center py-2 bg-yellow-50 px-3 rounded border border-yellow-200">
                        <div>
                          <span className="text-sm font-medium text-yellow-900">{t('analysis.inaccessibleForest')}</span>
                          <p className="text-xs text-yellow-700 mt-0.5">
                            {t('analysis.treeCoverSlopeGt', { degrees: maxSlopeForView })} • {t('analysis.tooSteepForSampling')}
                          </p>
                        </div>
                        <div className="text-right">
                          <span className="font-bold text-yellow-700 text-lg">
                            {block.inaccessible_steep_forest_ha?.toFixed(2)} ha
                          </span>
                          <p className="text-xs text-yellow-600">
                            ({block.inaccessible_steep_percentage?.toFixed(1)}%)
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Non-forest */}
                    {block.non_forest_area_ha > 0 && (
                      <div className="flex justify-between items-center py-2 bg-gray-100 px-3 rounded border border-gray-300">
                        <div>
                          <span className="text-sm font-medium text-gray-700">{t('analysis.nonForest')}</span>
                          <p className="text-xs text-gray-600 mt-0.5">
                            {t('analysis.grasslandCroplandWaterSettlements')}
                          </p>
                        </div>
                        <div className="text-right">
                          <span className="font-bold text-gray-600 text-lg">
                            {block.non_forest_area_ha?.toFixed(2)} ha
                          </span>
                          <p className="text-xs text-gray-500">
                            ({block.non_forest_percentage?.toFixed(1)}%)
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Visual Progress Bar */}
                    <div className="mt-2">
                      <div className="flex h-8 rounded-md overflow-hidden border border-gray-300">
                        <div
                          className="bg-green-500 flex items-center justify-center text-xs font-semibold text-white"
                          style={{ width: `${block.accessible_forest_percentage}%` }}
                        >
                          {block.accessible_forest_percentage >= 15 && `${block.accessible_forest_percentage?.toFixed(0)}%`}
                        </div>
                        {showSlopeFilter && block.inaccessible_steep_percentage > 0 && (
                          <div
                            className="bg-yellow-500 flex items-center justify-center text-xs font-semibold text-white"
                            style={{ width: `${block.inaccessible_steep_percentage}%` }}
                          >
                            {block.inaccessible_steep_percentage >= 15 && `${block.inaccessible_steep_percentage?.toFixed(0)}%`}
                          </div>
                        )}
                        {block.non_forest_percentage > 0 && (
                          <div
                            className="bg-gray-400 flex items-center justify-center text-xs font-semibold text-white"
                            style={{ width: `${block.non_forest_percentage}%` }}
                          >
                            {block.non_forest_percentage >= 15 && `${block.non_forest_percentage?.toFixed(0)}%`}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {/* Important Note */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mt-4">
                <p className="text-sm text-blue-900">
                  <span className="font-semibold">💡 {t('analysis.noteColon')}</span> {t('analysis.samplingDesignNote')}
                </p>
              </div>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              {t('analysis.unableToLoadAccessibleArea')}
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* Species Distribution Analytics Dashboard - Phase 2 */}
      {totalBlocks > 0 && (
        <CollapsibleSection
          title={t('analysis.speciesDistributionAnalytics')}
          icon="📊"
          defaultExpanded={false}
          headerColor="green"
        >
          <div className="p-6 space-y-8">
            {loadingSummary ? (
              <div className="flex items-center justify-center py-12">
                <div className="text-center">
                  <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-green-600 mx-auto mb-4"></div>
                  <p className="text-gray-600">{t('analysis.loadingSpeciesAnalytics')}</p>
                </div>
              </div>
            ) : speciesSummary && speciesSummary.species_details && speciesSummary.species_details.length > 0 ? (
              <>
                {/* Summary Stats */}
                <div className="bg-gradient-to-r from-purple-50 to-green-50 p-4 rounded-lg border border-purple-200">
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">{t('analysis.blockLevelSpeciesAnalysis')}</h3>
                  <p className="text-sm text-gray-600 mb-4">
                    {t('analysis.speciesDistributionAcross', { count: totalBlocks })}
                  </p>
                  <div className="grid grid-cols-3 gap-4">
                    <div className="bg-white p-3 rounded-lg text-center">
                      <p className="text-2xl font-bold text-gray-900">{speciesSummary.total_species}</p>
                      <p className="text-xs text-gray-600 mt-1">{t('analysis.totalSpecies')}</p>
                    </div>
                    <div className="bg-white p-3 rounded-lg text-center">
                      <p className="text-2xl font-bold text-purple-600">{speciesSummary.total_blocks}</p>
                      <p className="text-xs text-gray-600 mt-1">{t('analysis.totalBlocks')}</p>
                    </div>
                  </div>
                </div>

                {/* Bar Chart - Species Coverage */}
                <div className="bg-white p-6 rounded-lg border border-gray-200 shadow-sm">
                  <SpeciesCoverageChart
                    speciesData={speciesSummary.species_details}
                    totalBlocks={speciesSummary.total_blocks}
                  />
                </div>

                {/* Detailed Table */}
                <div className="bg-white p-6 rounded-lg border border-gray-200 shadow-sm">
                  <SpeciesSummaryTable speciesData={speciesSummary.species_details} />
                </div>
              </>
            ) : (
              <div className="text-center py-12">
                <p className="text-gray-500">{t('analysis.noSpeciesData')}</p>
              </div>
            )}
          </div>
        </CollapsibleSection>
      )}

      {/* Section 1: Forest Characteristics */}
      <CollapsibleSection
        title={t('analysis.forestCharacteristics')}
        icon="🌲"
        defaultExpanded={true}
        headerColor="green"
      >
        <div className="p-6 space-y-6">
          {/* Canopy Structure */}
          {data.canopy_dominant_class && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.canopyStructure')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-3">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.dominantClassColon')}</span>
                  <span className="text-lg font-bold text-green-700 capitalize">
                    <EditableCell
                      value={data.canopy_dominant_class}
                      onSave={(v) => handleSaveWholeForest('canopy_dominant_class', v)}
                    />
                  </span>
                </div>
                {data.canopy_mean_m && (
                  <div className="flex justify-between items-center mb-3">
                    <span className="text-sm font-medium text-gray-700">{t('analysis.meanHeightColon')}</span>
                    <span className="text-lg font-bold text-gray-700">
                      <EditableCell
                        value={data.canopy_mean_m}
                        displayValue={`${data.canopy_mean_m.toFixed(1)} m`}
                        onSave={(v) => handleSaveWholeForest('canopy_mean_m', v)}
                      />
                    </span>
                  </div>
                )}
                {canopyData.length > 0 && (
                  <div className="mt-4">
                    <p className="text-xs font-medium text-gray-600 mb-2">Distribution:</p>
                    <PercentageBar data={canopyData} height="md" />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Above Ground Biomass */}
          {data.agb_total_mg !== undefined && data.agb_total_mg !== null && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">Above Ground Biomass</h4>
              <div className="bg-gray-50 p-4 rounded-lg space-y-2">
                <div className="flex justify-between">
                  <span className="text-sm text-gray-700">Total Biomass:</span>
                  <span className="text-sm font-semibold text-gray-900">
                    <EditableCell
                      value={data.agb_total_mg}
                      displayValue={`${data.agb_total_mg.toLocaleString()} Mg`}
                      onSave={(v) => handleSaveWholeForest('agb_total_mg', v)}
                    />
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-gray-700">Mean per Hectare:</span>
                  <span className="text-sm font-semibold text-gray-900">
                    <EditableCell
                      value={data.agb_mean_mg_ha}
                      displayValue={`${data.agb_mean_mg_ha?.toFixed(2)} Mg/ha`}
                      onSave={(v) => handleSaveWholeForest('agb_mean_mg_ha', v)}
                    />
                  </span>
                </div>
                {data.carbon_stock_mg && (
                  <div className="flex justify-between pt-2 border-t border-gray-300">
                    <span className="text-sm text-gray-700">Carbon Stock (50% of AGB):</span>
                    <span className="text-sm font-semibold text-green-700">
                      <EditableCell
                        value={data.carbon_stock_mg}
                        displayValue={`${data.carbon_stock_mg.toLocaleString()} Mg`}
                        onSave={(v) => handleSaveWholeForest('carbon_stock_mg', v)}
                      />
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Forest Health */}
          {data.forest_health_dominant && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">Forest Health Status</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-4">
                  <span className="text-sm font-medium text-gray-700">Overall Health:</span>
                  <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                    data.forest_health_dominant === 'very_healthy' ? 'bg-green-100 text-green-800' :
                    data.forest_health_dominant === 'healthy' ? 'bg-green-50 text-green-700' :
                    data.forest_health_dominant === 'moderate' ? 'bg-yellow-100 text-yellow-800' :
                    data.forest_health_dominant === 'poor' ? 'bg-orange-100 text-orange-800' :
                    'bg-red-100 text-red-800'
                  }`}>
                    <EditableCell value={data.forest_health_dominant} onSave={(v) => handleSaveWholeForest('forest_health_dominant', v)} />
                  </span>
                </div>
                {data.forest_health_percentages && (
                  <div className="space-y-2">
                    {Object.entries(data.forest_health_percentages).map(([cls, pct]: [string, any]) => (
                      <div key={cls} className="flex justify-between text-sm">
                        <span className="capitalize text-gray-700">{cls.replace('_', ' ')}:</span>
                        <span className="font-medium">
                          <EditableCell
                            value={pct}
                            displayValue={`${pct.toFixed(1)}%`}
                            onSave={(v) => handleSaveWholePercentages('forest_health_percentages', cls, v)}
                          />
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Forest Type & Species - Keep existing detailed view */}
          {data.forest_type_dominant && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">Forest Type</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-medium text-gray-700">Dominant Type:</span>
                  <span className="text-lg font-bold text-green-700 capitalize">
                    <EditableCell value={data.forest_type_dominant} onSave={(v) => handleSaveWholeForest('forest_type_dominant', v)} />
                  </span>
                </div>
                {data.forest_type_percentages && (
                  <div className="mt-3 space-y-1">
                    {Object.entries(data.forest_type_percentages).map(([type, pct]: [string, any]) => (
                      <div key={type} className="flex justify-between text-sm">
                        <span className="text-gray-700">{type}:</span>
                        <span className="font-medium">
                          <EditableCell
                            value={pct}
                            displayValue={`${pct.toFixed(1)}%`}
                            onSave={(v) => handleSaveWholePercentages('forest_type_percentages', type, v)}
                          />
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Potential Species - Enhanced Table View */}
          {data.potential_species && data.potential_species.length > 0 && (
            <SpeciesTable
              species={data.potential_species}
              calculationId={calculation.id}
              forestName={calculation.forest_name}
              removedSpecies={data.removed_species || []}
              onSpeciesToggle={(speciesName, enabled) => {
                console.log(`Species ${speciesName} ${enabled ? 'enabled' : 'disabled'}`);
              }}
              onAddSpecies={() => setIsAddSpeciesModalOpen(true)}
              onSpeciesRemoved={onRefresh}
            />
          )}
        </div>
      </CollapsibleSection>

      {/* Section 2: Terrain & Climate */}
      <CollapsibleSection
        title={t('analysis.terrainClimate')}
        icon="🏔️"
        defaultExpanded={false}
        headerColor="blue"
      >
        <div className="p-6 space-y-6">
          {/* Elevation */}
          {data.elevation_mean_m !== undefined && data.elevation_mean_m !== null && data.elevation_mean_m > -32000 && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.elevationProfile')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg space-y-2">
                <div className="flex justify-between">
                  <span className="text-sm text-gray-700">{t('analysis.meanElevationColon')}</span>
                  <span className="text-sm font-semibold text-gray-900">
                    <EditableCell
                      value={data.elevation_mean_m}
                      displayValue={`${data.elevation_mean_m.toFixed(1)} m`}
                      onSave={(v) => handleSaveWholeForest('elevation_mean_m', v)}
                    />
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-gray-700">{t('analysis.minimumColon')}</span>
                  <span className="text-sm font-medium text-gray-700">
                    <EditableCell
                      value={data.elevation_min_m}
                      displayValue={`${data.elevation_min_m?.toFixed(0)} m`}
                      onSave={(v) => handleSaveWholeForest('elevation_min_m', v)}
                    />
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-gray-700">{t('analysis.maximumColon')}</span>
                  <span className="text-sm font-medium text-gray-700">
                    <EditableCell
                      value={data.elevation_max_m}
                      displayValue={`${data.elevation_max_m?.toFixed(0)} m`}
                      onSave={(v) => handleSaveWholeForest('elevation_max_m', v)}
                    />
                  </span>
                </div>
                {data.elevation_max_m && data.elevation_min_m && (
                  <div className="flex justify-between pt-2 border-t border-gray-300">
                    <span className="text-sm text-gray-700">{t('analysis.rangeColon')}</span>
                    <span className="text-sm font-semibold text-blue-700">
                      {(data.elevation_max_m - data.elevation_min_m).toFixed(0)} m
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Slope */}
          {data.slope_dominant_class && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.slopeAnalysis')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-4">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.dominantClassColon')}</span>
                  <span className="text-lg font-bold text-gray-900 capitalize">
                    <EditableCell value={data.slope_dominant_class} onSave={(v) => handleSaveWholeForest('slope_dominant_class', v)} />
                  </span>
                </div>
                {slopeData.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-600 mb-2">{t('analysis.distributionColon')}</p>
                    <PercentageBar data={slopeData} height="md" />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Aspect */}
          {data.aspect_dominant && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.aspectSlopeOrientation')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-4">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.dominantDirectionColon')}</span>
                  <span className="text-lg font-bold text-blue-700 uppercase">
                    <EditableCell value={data.aspect_dominant} onSave={(v) => handleSaveWholeForest('aspect_dominant', v)} />
                  </span>
                </div>
                {aspectData.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-600 mb-2">{t('analysis.distributionColon')}</p>
                    <PercentageBar data={aspectData} height="md" showValues={false} />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Climate */}
          {(data.temperature_mean_c !== undefined && data.temperature_mean_c !== null && data.temperature_mean_c > -100) && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.climateConditions')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg space-y-2">
                <div className="flex justify-between">
                  <span className="text-sm text-gray-700">{t('analysis.annualMeanTempColon')}</span>
                  <span className="text-sm font-semibold text-gray-900">
                    <EditableCell
                      value={data.temperature_mean_c}
                      displayValue={`${data.temperature_mean_c.toFixed(1)} °C`}
                      onSave={(v) => handleSaveWholeForest('temperature_mean_c', v)}
                    />
                  </span>
                </div>
                {data.temperature_min_c && (
                  <div className="flex justify-between">
                    <span className="text-sm text-gray-700">{t('analysis.minColdestMonthColon')}</span>
                    <span className="text-sm font-medium text-gray-700">
                      <EditableCell
                        value={data.temperature_min_c}
                        displayValue={`${data.temperature_min_c.toFixed(1)} °C`}
                        onSave={(v) => handleSaveWholeForest('temperature_min_c', v)}
                      />
                    </span>
                  </div>
                )}
                {data.precipitation_mean_mm !== undefined && data.precipitation_mean_mm !== null && data.precipitation_mean_mm >= 0 && (
                  <div className="flex justify-between pt-2 border-t border-gray-300">
                    <span className="text-sm text-gray-700">{t('analysis.annualPrecipitationColon')}</span>
                    <span className="text-sm font-semibold text-blue-700">
                      <EditableCell
                        value={data.precipitation_mean_mm}
                        displayValue={`${data.precipitation_mean_mm.toFixed(0)} mm/year`}
                        onSave={(v) => handleSaveWholeForest('precipitation_mean_mm', v)}
                      />
                    </span>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* Section 3: Land Cover & Change */}
      <CollapsibleSection
        title={t('analysis.landCoverChange')}
        icon="📊"
        defaultExpanded={false}
        headerColor="yellow"
      >
        <div className="p-6 space-y-6">
          {/* Land Cover Timeline */}
          {(data.landcover_1984_dominant || data.hansen2000_dominant || data.landcover_dominant) && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.landCoverEvolution')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex-1 text-center">
                    <div className="text-xs font-medium text-gray-500 mb-1">1984</div>
                    <div className="text-sm font-semibold text-gray-900 capitalize">
                      {data.landcover_1984_dominant || t('common.na')}
                    </div>
                  </div>
                  <div className="px-4">
                    <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                  </div>
                  <div className="flex-1 text-center">
                    <div className="text-xs font-medium text-gray-500 mb-1">2000</div>
                    <div className="text-sm font-semibold text-gray-900 capitalize">
                      {data.hansen2000_dominant || t('common.na')}
                    </div>
                  </div>
                  <div className="px-4">
                    <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                  </div>
                  <div className="flex-1 text-center">
                    <div className="text-xs font-medium text-gray-500 mb-1">{t('analysis.currentColon')}</div>
                    <div className="text-sm font-semibold text-green-700 capitalize">
                      {data.landcover_dominant || t('common.na')}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Forest Loss */}
          {data.forest_loss_hectares !== undefined && data.forest_loss_hectares !== null && data.forest_loss_hectares >= 0 && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.forestLoss20012023')}</h4>
              <div className="bg-red-50 border border-red-200 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-3">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.totalLossColon')}</span>
                  <span className="text-2xl font-bold text-red-700">
                    <EditableCell
                      value={data.forest_loss_hectares}
                      displayValue={`${data.forest_loss_hectares.toFixed(2)} ha`}
                      onSave={(v) => handleSaveWholeForest('forest_loss_hectares', v)}
                    />
                  </span>
                </div>
                {data.forest_loss_by_year && Object.keys(data.forest_loss_by_year).length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-gray-600 mb-2">{t('analysis.lossByYearColon')}</p>
                    <div className="max-h-40 overflow-y-auto space-y-1">
                      {Object.entries(data.forest_loss_by_year)
                        .sort(([yearA], [yearB]) => parseInt(yearB) - parseInt(yearA))
                        .map(([year, ha]: [string, any]) => (
                          ha > 0 && (
                            <div key={year} className="flex justify-between text-xs">
                              <span className="text-gray-700">{year}:</span>
                              <span className="font-medium text-red-700">
                                <EditableCell
                                  value={ha}
                                  displayValue={`${ha.toFixed(2)} ha`}
                                  onSave={(v) => handleSaveWholePercentages('forest_loss_by_year', year, v)}
                                />
                              </span>
                            </div>
                          )
                        ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Forest Gain */}
          {data.forest_gain_hectares !== undefined && data.forest_gain_hectares !== null && data.forest_gain_hectares >= 0 && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.forestGain20002012')}</h4>
              <div className="bg-green-50 border border-green-200 p-4 rounded-lg">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.totalGainColon')}</span>
                  <span className="text-2xl font-bold text-green-700">
                    <EditableCell
                      value={data.forest_gain_hectares}
                      displayValue={`${data.forest_gain_hectares.toFixed(2)} ha`}
                      onSave={(v) => handleSaveWholeForest('forest_gain_hectares', v)}
                    />
                  </span>
                </div>
                <p className="text-xs text-gray-600 mt-2">{t('analysis.netForestGain12Year')}</p>
              </div>
            </div>
          )}

          {/* Fire Loss */}
          {data.fire_loss_hectares !== undefined && data.fire_loss_hectares !== null && data.fire_loss_hectares >= 0 && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.fireRelatedLoss20012023')}</h4>
              <div className="bg-orange-50 border border-orange-200 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-3">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.totalFireLossColon')}</span>
                  <span className="text-2xl font-bold text-orange-700">
                    <EditableCell
                      value={data.fire_loss_hectares}
                      displayValue={`${data.fire_loss_hectares.toFixed(2)} ha`}
                      onSave={(v) => handleSaveWholeForest('fire_loss_hectares', v)}
                    />
                  </span>
                </div>
                {data.fire_loss_by_year && Object.keys(data.fire_loss_by_year).length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-gray-600 mb-2">{t('analysis.fireEventsColon')}</p>
                    <div className="space-y-1">
                      {Object.entries(data.fire_loss_by_year)
                        .sort(([yearA], [yearB]) => parseInt(yearB) - parseInt(yearA))
                        .map(([year, ha]: [string, any]) => (
                          ha > 0 && (
                            <div key={year} className="flex justify-between text-xs">
                              <span className="text-gray-700">{year}:</span>
                              <span className="font-medium text-orange-700">
                                <EditableCell
                                  value={ha}
                                  displayValue={`${ha.toFixed(2)} ha`}
                                  onSave={(v) => handleSaveWholePercentages('fire_loss_by_year', year, v)}
                                />
                              </span>
                            </div>
                          )
                        ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* Section 4: Soil Analysis */}
      <CollapsibleSection
        title={t('analysis.soilAnalysis')}
        icon="🌍"
        defaultExpanded={false}
        headerColor="gray"
      >
        <div className="p-6 space-y-6">
          {/* Soil Texture */}
          {data.soil_texture && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.soilTextureComposition')}</h4>
              <div className="bg-gradient-to-br from-amber-50 to-orange-50 p-5 rounded-lg space-y-4 border border-amber-200">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.textureClassColon')}</span>
                  <span className="px-4 py-2 bg-white rounded-full text-md font-bold text-amber-900 shadow-sm">
                    {data.soil_texture}
                  </span>
                </div>

                {data.interpretations?.texture_interpretation && (
                  <div className="space-y-3 bg-white bg-opacity-60 p-4 rounded-lg">
                    <p className="text-sm text-gray-800 leading-relaxed">
                      <strong>{t('analysis.descriptionColon')}</strong> {data.interpretations.texture_interpretation.description}
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
                      <div className="bg-blue-50 p-3 rounded border-l-4 border-blue-400">
                        <p className="font-semibold text-blue-900 mb-1">{t('analysis.waterRetention')}</p>
                        <p className="text-gray-700">{data.interpretations.texture_interpretation.water_retention}</p>
                      </div>
                      <div className="bg-green-50 p-3 rounded border-l-4 border-green-400">
                        <p className="font-semibold text-green-900 mb-1">{t('analysis.drainage')}</p>
                        <p className="text-gray-700">{data.interpretations.texture_interpretation.drainage}</p>
                      </div>
                      <div className="bg-purple-50 p-3 rounded border-l-4 border-purple-400">
                        <p className="font-semibold text-purple-900 mb-1">{t('analysis.workability')}</p>
                        <p className="text-gray-700">{data.interpretations.texture_interpretation.workability}</p>
                      </div>
                    </div>

                    {data.interpretations.texture_interpretation.suitable_species && data.interpretations.texture_interpretation.suitable_species.length > 0 && (
                      <div className="bg-green-50 p-3 rounded border-l-4 border-green-500">
                        <p className="font-semibold text-green-900 text-sm mb-2">{t('analysis.suitableTreeSpeciesColon')}</p>
                        <ul className="text-xs text-gray-700 space-y-1">
                          {data.interpretations.texture_interpretation.suitable_species.map((species: string, idx: number) => (
                            <li key={idx} className="flex items-start">
                              <span className="text-green-600 mr-2">✓</span>
                              <span>{species}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {data.interpretations.texture_interpretation.management_note && (
                      <div className="bg-yellow-50 p-3 rounded border-l-4 border-yellow-500">
                        <p className="font-semibold text-yellow-900 text-sm mb-1">{t('analysis.managementRecommendationColon')}</p>
                        <p className="text-xs text-gray-700">{data.interpretations.texture_interpretation.management_note}</p>
                      </div>
                    )}
                  </div>
                )}

                {data.soil_properties && (
                  <details className="group">
                    <summary className="cursor-pointer text-xs text-gray-600 hover:text-gray-800 font-medium">
                      {t('analysis.technicalDetailsClickExpand')}
                    </summary>
                    <div className="mt-2 pt-2 border-t border-gray-300 text-xs text-gray-600 grid grid-cols-2 md:grid-cols-4 gap-2">
                      {data.soil_properties.clay_pct !== undefined && (
                        <div><span className="font-medium">{t('analysis.clayColon')}</span> {data.soil_properties.clay_pct}%</div>
                      )}
                      {data.soil_properties.sand_pct !== undefined && (
                        <div><span className="font-medium">{t('analysis.sandColon')}</span> {data.soil_properties.sand_pct}%</div>
                      )}
                      {data.soil_properties.silt_pct !== undefined && (
                        <div><span className="font-medium">{t('analysis.siltColon')}</span> {data.soil_properties.silt_pct}%</div>
                      )}
                      {data.soil_properties.ph_h2o !== undefined && (
                        <div><span className="font-medium">{t('analysis.phColon')}</span> {data.soil_properties.ph_h2o}</div>
                      )}
                    </div>
                  </details>
                )}
              </div>
            </div>
          )}

          {/* pH Interpretation */}
          {data.interpretations?.ph_interpretation && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.soilPhAcidity')}</h4>
              <div className="bg-gradient-to-br from-blue-50 to-indigo-50 p-5 rounded-lg space-y-3 border border-blue-200">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.phLevelColon')}</span>
                  <div className="flex items-center gap-3">
                    <span className="text-2xl font-bold text-blue-900">{data.interpretations.ph_interpretation.value.toFixed(1)}</span>
                    <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                      data.interpretations.ph_interpretation.category.includes('Optimal') ? 'bg-green-100 text-green-800' :
                      data.interpretations.ph_interpretation.category.includes('Acidic') ? 'bg-yellow-100 text-yellow-800' :
                      'bg-orange-100 text-orange-800'
                    }`}>
                      {data.interpretations.ph_interpretation.category}
                    </span>
                  </div>
                </div>

                <div className="bg-white bg-opacity-60 p-3 rounded space-y-2 text-sm">
                  <p className="text-gray-800">{data.interpretations.ph_interpretation.description}</p>
                  <div className="bg-blue-50 p-2 rounded border-l-4 border-blue-400">
                    <p className="font-semibold text-blue-900 text-xs mb-1">{t('analysis.nutrientAvailabilityColon')}</p>
                    <p className="text-xs text-gray-700">{data.interpretations.ph_interpretation.nutrient_availability}</p>
                  </div>
                  <div className="bg-green-50 p-2 rounded border-l-4 border-green-500">
                    <p className="font-semibold text-green-900 text-xs mb-1">{t('analysis.recommendationColon')}</p>
                    <p className="text-xs text-gray-700">{data.interpretations.ph_interpretation.recommendation}</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Nitrogen Interpretation */}
          {data.interpretations?.nitrogen_interpretation && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.soilNitrogenContent')}</h4>
              <div className="bg-gradient-to-br from-green-50 to-emerald-50 p-5 rounded-lg space-y-3 border border-green-200">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.nitrogenLevelColon')}</span>
                  <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                    data.interpretations.nitrogen_interpretation.category === 'High' || data.interpretations.nitrogen_interpretation.category === 'Adequate' ? 'bg-green-100 text-green-800' :
                    data.interpretations.nitrogen_interpretation.category === 'Low' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-red-100 text-red-800'
                  }`}>
                    {data.interpretations.nitrogen_interpretation.category}
                  </span>
                </div>

                <div className="bg-white bg-opacity-60 p-3 rounded space-y-2 text-sm">
                  <p className="text-gray-800">{data.interpretations.nitrogen_interpretation.description}</p>
                  <div className="bg-green-50 p-2 rounded border-l-4 border-green-500">
                    <p className="font-semibold text-green-900 text-xs mb-1">{t('analysis.managementRecommendationColon')}</p>
                    <p className="text-xs text-gray-700">{data.interpretations.nitrogen_interpretation.recommendation}</p>
                  </div>
                </div>

                <div className="text-xs text-gray-600">
                  {t('analysis.nitrogenContent', { percent: data.interpretations.nitrogen_interpretation.value_percent, cgKg: data.interpretations.nitrogen_interpretation.value_cg_kg })}
                </div>
              </div>
            </div>
          )}

          {/* Fertility */}
          {data.fertility_class && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.overallSoilFertilityAssessment')}</h4>
              <div className="bg-gradient-to-br from-purple-50 to-pink-50 p-5 rounded-lg border border-purple-200">
                <div className="flex justify-between items-center mb-4">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.fertilityClassColon')}</span>
                  <FertilityBadge
                    value={data.fertility_class}
                    className="px-4 py-2 rounded-full text-md font-bold"
                  />
                </div>

                {data.fertility_score && (
                  <div className="text-center mb-4 bg-white bg-opacity-60 p-4 rounded-lg">
                    <div className="text-4xl font-bold text-purple-900">{data.fertility_score}<span className="text-2xl text-gray-500">/100</span></div>
                    <p className="text-xs text-gray-600 mt-1">{t('analysis.fertilityScore')}</p>
                  </div>
                )}

                {data.interpretations?.fertility_interpretation && (
                  <div className="bg-white bg-opacity-60 p-3 rounded space-y-2 text-sm">
                    <p className="text-gray-800">{data.interpretations.fertility_interpretation.description}</p>

                    <div className="bg-blue-50 p-2 rounded border-l-4 border-blue-400">
                      <p className="font-semibold text-blue-900 text-xs mb-1">{t('analysis.expectedGrowthRateColon')}</p>
                      <p className="text-xs text-gray-700">{data.interpretations.fertility_interpretation.expected_growth}</p>
                    </div>

                    <div className="bg-green-50 p-2 rounded border-l-4 border-green-500">
                      <p className="font-semibold text-green-900 text-xs mb-1">{t('analysis.recommendationColon')}</p>
                      <p className="text-xs text-gray-700">{data.interpretations.fertility_interpretation.recommendation}</p>
                    </div>
                  </div>
                )}

                {data.limiting_factors && data.limiting_factors.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-purple-200">
                    <p className="text-xs font-semibold text-purple-900 mb-2">{t('analysis.limitingFactorsColon')}</p>
                    <ul className="text-xs text-gray-700 space-y-1">
                      {data.limiting_factors.map((factor: string, idx: number) => (
                        <li key={idx} className="flex items-start">
                          <span className="text-orange-500 mr-2">•</span>
                          <span>{factor}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Carbon Stock */}
          {data.carbon_stock_t_ha && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.soilOrganicCarbonClimateImpact')}</h4>
              <div className="bg-gradient-to-br from-emerald-50 to-teal-50 p-5 rounded-lg space-y-3 border border-emerald-200">
                <div className="flex justify-between items-center">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.carbonStockTopsoilColon')}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-3xl font-bold text-emerald-900">{data.carbon_stock_t_ha}</span>
                    <span className="text-sm text-gray-600">{t('analysis.tonnesPerHa')}</span>
                  </div>
                </div>

                {data.interpretations?.carbon_interpretation && (
                  <div>
                    <span className={`inline-block px-3 py-1 rounded-full text-xs font-semibold mb-3 ${
                      data.interpretations.carbon_interpretation.category === 'High' ? 'bg-green-100 text-green-800' :
                      data.interpretations.carbon_interpretation.category === 'Moderate' ? 'bg-yellow-100 text-yellow-800' :
                      'bg-orange-100 text-orange-800'
                    }`}>
                      {data.interpretations.carbon_interpretation.category} {t('analysis.carbonStock')}
                    </span>

                    <div className="bg-white bg-opacity-60 p-3 rounded space-y-2 text-sm">
                      <p className="text-gray-800">{data.interpretations.carbon_interpretation.description}</p>

                      <div className="bg-green-50 p-2 rounded border-l-4 border-green-500">
                        <p className="font-semibold text-green-900 text-xs mb-1">{t('analysis.climateBenefitColon')}</p>
                        <p className="text-xs text-gray-700">{data.interpretations.carbon_interpretation.climate_benefit}</p>
                      </div>

                      <div className="bg-blue-50 p-2 rounded border-l-4 border-blue-400">
                        <p className="font-semibold text-blue-900 text-xs mb-1">{t('analysis.managementRecommendationColon')}</p>
                        <p className="text-xs text-gray-700">{data.interpretations.carbon_interpretation.recommendation}</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Compaction Status */}
          {data.compaction_status && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.compactionStatus')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg">
                <div className="flex justify-between items-center mb-2">
                  <span className="text-sm font-medium text-gray-700">{t('analysis.statusColon')}</span>
                  <span className={`px-3 py-1 rounded-full text-sm font-semibold ${
                    data.compaction_status === 'Not compacted' ? 'bg-green-100 text-green-800' :
                    data.compaction_status === 'Slight compaction' ? 'bg-yellow-100 text-yellow-800' :
                    data.compaction_status === 'Moderate compaction' ? 'bg-orange-100 text-orange-800' :
                    'bg-red-100 text-red-800'
                  }`}>
                    {data.compaction_status}
                  </span>
                </div>
                {data.compaction_alert && (
                  <p className="text-xs text-gray-600 mt-2">{data.compaction_alert}</p>
                )}
              </div>
            </div>
          )}
        </div>
      </CollapsibleSection>

      {/* Section 5: Location & Context */}
      <CollapsibleSection
        title={t('analysis.locationAdministrativeContext')}
        icon="📍"
        defaultExpanded={false}
        headerColor="gray"
      >
        <div className="p-6 space-y-6">
          {/* Forest Location Address */}
          <div>
            <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.forestLocationAddress')}</h4>
            <div className="bg-gray-50 p-4 rounded-lg">
              <div className="text-sm font-semibold text-gray-900">
                <EditableCell
                  value={data.whole_province}
                  onSave={(v) => handleSaveWholeForest('whole_province', v)}
                />{' '}
                {t('analysis.provinceColon')} {' '}
                <EditableCell
                  value={data.whole_district}
                  onSave={(v) => handleSaveWholeForest('whole_district', v)}
                />{' '}
                {t('analysis.districtColon')} {' '}
                <EditableCell
                  value={data.whole_municipality}
                  onSave={(v) => handleSaveWholeForest('whole_municipality', v)}
                />{' '}
                <EditableCell
                  value={data.whole_municipality_type}
                  onSave={(v) => handleSaveWholeForest('whole_municipality_type', v)}
                />-
                <EditableCell
                  value={data.whole_ward}
                  onSave={(v) => handleSaveWholeForest('whole_ward', v)}
                />
              </div>
            </div>
          </div>

          {/* Watershed & Hydrology */}
          <div>
            <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.watershedHydrology')}</h4>
            <div className="bg-gray-50 p-4 rounded-lg">
              <div className="text-sm font-semibold text-gray-900">
                <EditableCell
                  value={data.whole_watershed}
                  onSave={(v) => handleSaveWholeForest('whole_watershed', v)}
                />, {' '}
                <EditableCell
                  value={data.whole_major_river_basin}
                  onSave={(v) => handleSaveWholeForest('whole_major_river_basin', v)}
                />
              </div>
            </div>
          </div>

          {/* Geographic Classifications */}
          {(data.whole_geology_percentages || data.whole_physiography_percentages || data.whole_ecoregion_percentages) && (
            <div>
              <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.geographicClassifications')}</h4>
              <div className="bg-gray-50 p-4 rounded-lg space-y-3">
                {data.whole_geology_percentages && Object.keys(data.whole_geology_percentages).length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-600 mb-1">{t('analysis.geologyColon')}</p>
                    <div className="text-xs text-gray-700">
                      {Object.entries(data.whole_geology_percentages).map(([cls, pct]: [string, any], idx: number, arr: any[]) => (
                        <span key={cls}>
                          {cls}: <EditableCell value={pct} displayValue={`${pct.toFixed(1)}%`} onSave={(v) => handleSaveWholePercentages('whole_geology_percentages', cls, v)} className="inline" />
                          {idx < arr.length - 1 && ', '}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {data.whole_physiography_percentages && Object.keys(data.whole_physiography_percentages).length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-600 mb-1">{t('analysis.physiographyColon')}</p>
                    <div className="text-xs text-gray-700">
                      {Object.entries(data.whole_physiography_percentages).map(([zone, pct]: [string, any], idx: number, arr: any[]) => (
                        <span key={zone}>
                          {zone}: <EditableCell value={pct} displayValue={`${pct.toFixed(2)}%`} onSave={(v) => handleSaveWholePercentages('whole_physiography_percentages', zone, v)} className="inline" />
                          {idx < arr.length - 1 && ', '}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {data.whole_ecoregion_percentages && Object.keys(data.whole_ecoregion_percentages).length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-600 mb-1">{t('analysis.ecoregionColon')}</p>
                    <div className="text-xs text-gray-700">
                      {Object.entries(data.whole_ecoregion_percentages).map(([eco, pct]: [string, any], idx: number, arr: any[]) => (
                        <span key={eco}>
                          {eco}: <EditableCell value={pct} displayValue={`${pct.toFixed(2)}%`} onSave={(v) => handleSaveWholePercentages('whole_ecoregion_percentages', eco, v)} className="inline" />
                          {idx < arr.length - 1 && ', '}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Directional Features */}
          <div>
            <h4 className="text-md font-semibold text-gray-900 mb-3">{t('analysis.naturalFeaturesWithin100m')}</h4>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-gray-50 p-3 rounded-lg">
                <div className="text-xs text-gray-600 mb-1 font-medium">{t('analysis.north')}</div>
                <div className="text-xs text-gray-700">
                  <EditableCell value={data.whole_features_north || ''} onSave={(v) => handleSaveWholeForest('whole_features_north', v)} />
                </div>
              </div>
              <div className="bg-gray-50 p-3 rounded-lg">
                <div className="text-xs text-gray-600 mb-1 font-medium">{t('analysis.east')}</div>
                <div className="text-xs text-gray-700">
                  <EditableCell value={data.whole_features_east || ''} onSave={(v) => handleSaveWholeForest('whole_features_east', v)} />
                </div>
              </div>
              <div className="bg-gray-50 p-3 rounded-lg">
                <div className="text-xs text-gray-600 mb-1 font-medium">{t('analysis.south')}</div>
                <div className="text-xs text-gray-700">
                  <EditableCell value={data.whole_features_south || ''} onSave={(v) => handleSaveWholeForest('whole_features_south', v)} />
                </div>
              </div>
              <div className="bg-gray-50 p-3 rounded-lg">
                <div className="text-xs text-gray-600 mb-1 font-medium">{t('analysis.west')}</div>
                <div className="text-xs text-gray-700">
                  <EditableCell value={data.whole_features_west || ''} onSave={(v) => handleSaveWholeForest('whole_features_west', v)} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </CollapsibleSection>

      {/* Add Species Modal */}
      <AddSpeciesModal
        isOpen={isAddSpeciesModalOpen}
        onClose={() => setIsAddSpeciesModalOpen(false)}
        calculationId={calculation.id}
        onSpeciesAdded={() => {
          setIsAddSpeciesModalOpen(false);
          if (onRefresh) {
            onRefresh();
          }
        }}
      />

    </div>
  );
};

export default AnalysisTabContent;
