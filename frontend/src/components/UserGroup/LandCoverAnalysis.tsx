/** Land-cover analysis panel — queries raster stats and displays class-area breakdown with charts. */
import React, { useState } from 'react';
import { BarChart3, Leaf, TreePine, AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import { useT } from '../../i18n/hooks';
import { formatDecimal } from '../../i18n/numberFormat';
import { userGroupApi } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { useWorkspaceStore } from '../../store/workspaceStore';

interface LandCoverAnalysisProps {
  calculationId: string;
  forestName?: string;
}

interface LandCoverClass {
  class_code: number;
  class_name: string;
  area_ha: number;
  percentage: number;
  avg_biomass_mg_per_ha: number;
  total_biomass_mg: number;
  avg_volume_m3_per_ha: number;
  total_volume_m3: number;
}

interface LandCoverResults {
  user_group_area_ha: number;
  forest_overlap_area_ha: number;
  net_analysis_area_ha: number;
  land_cover_classes: LandCoverClass[];
  total_biomass_mg: number;
  total_volume_m3: number;
  avg_biomass_mg_per_ha: number;
  avg_volume_m3_per_ha: number;
  has_forest_overlap: boolean;
}

export function LandCoverAnalysis({ calculationId, forestName }: LandCoverAnalysisProps) {
  const t = useT();
  const [results, setResults] = useState<LandCoverResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const [cacheInfo, setCacheInfo] = useState<{ size: number; age: string } | null>(null);

  // Get cache info
  const getCacheInfo = () => {
    const localCacheKey = `land_cover_${calculationId}`;
    const cached = localStorage.getItem(localCacheKey);
    if (cached) {
      try {
        const parsed = JSON.parse(cached);
        const sizeKB = new Blob([cached]).size / 1024;
        const ageMs = Date.now() - new Date(parsed.cached_at).getTime();
        const ageHours = Math.floor(ageMs / (1000 * 60 * 60));
        const ageMinutes = Math.floor((ageMs % (1000 * 60 * 60)) / (1000 * 60));
        const ageStr = ageHours > 0 ? `${ageHours}h ${ageMinutes}m ago` : `${ageMinutes}m ago`;
        setCacheInfo({ size: sizeKB, age: ageStr });
      } catch (e) {
        setCacheInfo(null);
      }
    } else {
      setCacheInfo(null);
    }
  };

  // Auto-load cached results on component mount
  // a new automatic run finishing (the polygons changed) re-reads the numbers
  const analysisFinishedAt = useWorkspaceStore((st) => st.userGroupAnalysis?.finishedAt ?? null);

  React.useEffect(() => {
    const loadCachedResults = async () => {
      try {
        setLoading(true);

        // The browser no longer answers for the server (owner, 2026-10-12): the land cover is recomputed automatically whenever the polygons
        // change, so a copy kept here for up to 24 h showed the OLD numbers after an edit. The server keeps its own cache, which is fast.
        localStorage.removeItem(`land_cover_${calculationId}`);

        // Ask the server (its cache answers in milliseconds, or the analysis runs)
        const data = await userGroupApi.analyzeLandCover(calculationId, false);
        setResults(data);
        setFromCache(data.from_cache === true);

        setInitialLoadDone(true);
      } catch (err: any) {
        // If no cached results or error, just show the button
        console.log('No cached results available');
        setInitialLoadDone(true);
      } finally {
        setLoading(false);
      }
    };

    loadCachedResults();
  }, [calculationId, analysisFinishedAt]);

  const handleAnalyze = async (forceRefresh: boolean = false) => {
    setLoading(true);
    setError(null);

    try {
      const data = await userGroupApi.analyzeLandCover(calculationId, forceRefresh);
      setResults(data);
      setFromCache(data.from_cache === true);

      // Save to LocalStorage for instant future access
      const localCacheKey = `land_cover_${calculationId}`;
      try {
        localStorage.setItem(localCacheKey, JSON.stringify({
          data: data,
          cached_at: new Date().toISOString(),
          calculation_id: calculationId
        }));
        console.log('💾 Saved fresh analysis to LocalStorage');
        getCacheInfo(); // Update cache info display
      } catch (storageError) {
        console.warn('LocalStorage save failed:', storageError);
      }
    } catch (err: any) {
      const errorMessage = apiErrorText(err, err.message || t('userGroup.landCover.failed'));
      setError(errorMessage);
      console.error('Land cover analysis error:', err);
    } finally {
      setLoading(false);
    }
  };

  // Get color for land cover class
  const getLandCoverColor = (classCode: number): string => {
    const colors: Record<number, string> = {
      10: '#006400', // Tree cover - Dark green
      20: '#8B4513', // Shrubland - Saddle brown
      30: '#90EE90', // Grassland - Light green
      40: '#FFD700', // Cropland - Gold
      50: '#FF6347', // Built-up - Tomato
      60: '#D2B48C', // Bare/sparse - Tan
      70: '#FFFFFF', // Snow and ice - White
      80: '#4169E1', // Water - Royal blue
      90: '#00CED1', // Wetland - Dark turquoise
      95: '#2E8B57', // Mangroves - Sea green
      100: '#98FB98', // Moss and lichen - Pale green
    };
    return colors[classCode] || '#999999';
  };

  return (
    <div className="bg-white rounded-lg shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-3 bg-green-50 rounded-lg">
            <Leaf className="w-6 h-6 text-green-600" />
          </div>
          <div>
            <h3 className="text-xl font-semibold text-gray-800">{t('userGroup.landCover.title')}</h3>
            <p className="text-sm text-gray-500">
              {t('userGroup.landCover.subtitle', { name: forestName || t('userGroup.landCover.defaultName') })}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {results && (
            <div className="flex items-center gap-2">
              {fromCache && (
                <span className="text-xs px-2 py-1 bg-green-50 text-green-700 border border-green-200 rounded flex items-center gap-1">
                  <CheckCircle className="w-3 h-3" />
                  ⚡ Instant load (LocalStorage)
                </span>
              )}
              {cacheInfo && (
                <span className="text-xs px-2 py-1 bg-gray-50 text-gray-600 border border-gray-200 rounded">
                  {formatDecimal(cacheInfo.size, 1)} KB · {cacheInfo.age}
                </span>
              )}
              <button
                onClick={() => {
                  // Clear LocalStorage cache
                  const localCacheKey = `land_cover_${calculationId}`;
                  localStorage.removeItem(localCacheKey);
                  setCacheInfo(null);
                  setFromCache(false);
                  console.log('🗑️ Cleared LocalStorage cache');
                  alert(t('userGroup.landCover.msgCacheCleared'));
                }}
                className="text-xs px-2 py-1 text-gray-600 hover:text-red-600 hover:bg-red-50 rounded border border-gray-200 hover:border-red-200 transition-colors"
                title={t('userGroup.landCover.clearCacheHint')}
              >
                🗑️ {t('userGroup.landCover.clearCache')}
              </button>
            </div>
          )}
          <button
            onClick={() => handleAnalyze(results !== null)}
            disabled={loading}
            className="px-6 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700
                     disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors
                     flex items-center gap-2 font-medium"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {results ? t('userGroup.landCover.reanalyzing') : t('userGroup.landCover.analyzing')}
              </>
            ) : (
              <>
                <BarChart3 className="w-4 h-4" />
                {results ? t('userGroup.landCover.rerun') : t('userGroup.landCover.run')}
              </>
            )}
          </button>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 mt-0.5 flex-shrink-0" />
          <div>
            <p className="font-medium text-red-800">{t('userGroup.landCover.failedTitle')}</p>
            <p className="text-sm text-red-600 mt-1">{error}</p>
            {error.includes('not found') && (
              <p className="text-xs text-red-500 mt-2">
                {t('userGroup.landCover.makeSure')}
                <br />• {t('userGroup.landCover.needBoundary')}
                <br />• {t('userGroup.landCover.needExtent')}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Results */}
      {results && (
        <div className="space-y-6">
          {/* Area Summary */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
              <p className="text-sm text-blue-600 font-medium mb-1">{t('userGroup.landCover.userGroupArea')}</p>
              <p className="text-2xl font-bold text-blue-800">
                {formatDecimal(results.user_group_area_ha)} {t('units.hectare')}
              </p>
              <p className="text-xs text-gray-400 font-mono mt-1">{'{{ug_user_group_area_ha}}'}</p>
            </div>

            <div className="p-4 bg-orange-50 rounded-lg border border-orange-200">
              <p className="text-sm text-orange-600 font-medium mb-1">{t('userGroup.landCover.forestOverlap')}</p>
              <p className="text-2xl font-bold text-orange-800">
                {formatDecimal(results.forest_overlap_area_ha)} {t('units.hectare')}
              </p>
              <p className="text-xs text-gray-400 font-mono mt-1">{'{{ug_forest_overlap_area_ha}}'}</p>
              {results.has_forest_overlap && (
                <p className="text-xs text-orange-600 mt-1">{t('userGroup.landCover.excludedFromAnalysis')}</p>
              )}
            </div>

            <div className="p-4 bg-green-50 rounded-lg border border-green-200">
              <p className="text-sm text-green-600 font-medium mb-1">{t('userGroup.landCover.netArea')}</p>
              <p className="text-2xl font-bold text-green-800">
                {formatDecimal(results.net_analysis_area_ha)} {t('units.hectare')}
              </p>
              <p className="text-xs text-gray-400 font-mono mt-1">{'{{ug_net_analysis_area_ha}}'}</p>
              <p className="text-xs text-green-600 mt-1">{t('userGroup.landCover.afterExclusion')}</p>
            </div>
          </div>

          {/* Biomass & Volume Summary */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-5 bg-gradient-to-br from-emerald-50 to-green-50 rounded-lg border border-emerald-200">
              <div className="flex items-center gap-2 mb-3">
                <TreePine className="w-5 h-5 text-emerald-600" />
                <p className="text-sm font-semibold text-emerald-700">{t('userGroup.landCover.totalBiomass')}</p>
              </div>
              <p className="text-3xl font-bold text-emerald-800">
                {formatDecimal(results.total_biomass_mg)} {t('units.mg')}
              </p>
              <p className="text-xs text-gray-400 font-mono">{'{{ug_total_biomass_mg}}'}</p>
              <p className="text-sm text-emerald-600 mt-2">
                {t('userGroup.landCover.average', {
                  value: `${formatDecimal(results.avg_biomass_mg_per_ha)} ${t('units.mgPerHa')}`,
                })}
              </p>
              <p className="text-xs text-gray-400 font-mono">{'{{ug_avg_biomass_mg_per_ha}}'}</p>
            </div>

            <div className="p-5 bg-gradient-to-br from-amber-50 to-yellow-50 rounded-lg border border-amber-200">
              <div className="flex items-center gap-2 mb-3">
                <BarChart3 className="w-5 h-5 text-amber-600" />
                <p className="text-sm font-semibold text-amber-700">{t('userGroup.landCover.totalVolume')}</p>
              </div>
              <p className="text-3xl font-bold text-amber-800">
                {formatDecimal(results.total_volume_m3)} {t('units.cubicMeter')}
              </p>
              <p className="text-xs text-gray-400 font-mono">{'{{ug_total_volume_m3}}'}</p>
              <p className="text-sm text-amber-600 mt-2">
                {t('userGroup.landCover.average', {
                  value: `${formatDecimal(results.avg_volume_m3_per_ha)} ${t('units.m3PerHa')}`,
                })}
              </p>
              <p className="text-xs text-gray-400 font-mono">{'{{ug_avg_volume_m3_per_ha}}'}</p>
            </div>
          </div>

          {/* Land Cover Breakdown */}
          <p className="text-xs text-gray-400 font-mono mb-1">{'{{ug_land_cover_classes}}'}</p>
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <div className="bg-gray-50 px-6 py-3 border-b border-gray-200">
              <h4 className="font-semibold text-gray-800">{t('userGroup.landCover.breakdownTitle')}</h4>
              <p className="text-xs text-gray-500 mt-1">
                Based on ESA World Cover (10m resolution) and AGB 2022 Nepal (100m resolution)
              </p>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colType')}
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colArea')}
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colPercentage')}
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colBiomassPerHa')}
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colVolumePerHa')}
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colTotalBiomass')}
                    </th>
                    <th className="px-6 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      {t('userGroup.landCover.colTotalVolume')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {results.land_cover_classes.map((cls) => (
                    <tr key={cls.class_code} className="hover:bg-gray-50 transition-colors">
                      <td className="px-6 py-4 whitespace-nowrap">
                        <div className="flex items-center gap-3">
                          <div
                            className="w-4 h-4 rounded border border-gray-300"
                            style={{ backgroundColor: getLandCoverColor(cls.class_code) }}
                          />
                          <span className="text-sm font-medium text-gray-800">
                            {cls.class_name}
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4 text-right text-sm text-gray-700">
                        {formatDecimal(cls.area_ha)}
                      </td>
                      <td className="px-6 py-4 text-right text-sm text-gray-700">
                        <span className="font-medium">{formatDecimal(cls.percentage, 1)}%</span>
                      </td>
                      <td className="px-6 py-4 text-right text-sm text-gray-700">
                        {formatDecimal(cls.avg_biomass_mg_per_ha)}
                      </td>
                      <td className="px-6 py-4 text-right text-sm text-gray-700">
                        {formatDecimal(cls.avg_volume_m3_per_ha)}
                      </td>
                      <td className="px-6 py-4 text-right text-sm font-medium text-emerald-700">
                        {formatDecimal(cls.total_biomass_mg)}
                      </td>
                      <td className="px-6 py-4 text-right text-sm font-medium text-amber-700">
                        {formatDecimal(cls.total_volume_m3)}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-gray-50 border-t-2 border-gray-300">
                  <tr className="font-semibold">
                    <td className="px-6 py-4 text-sm text-gray-800">TOTAL</td>
                    <td className="px-6 py-4 text-right text-sm text-gray-800">
                      {formatDecimal(results.net_analysis_area_ha)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-gray-800">100.0%</td>
                    <td className="px-6 py-4 text-right text-sm text-gray-800">
                      {formatDecimal(results.avg_biomass_mg_per_ha)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm text-gray-800">
                      {formatDecimal(results.avg_volume_m3_per_ha)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm font-bold text-emerald-700">
                      {formatDecimal(results.total_biomass_mg)}
                    </td>
                    <td className="px-6 py-4 text-right text-sm font-bold text-amber-700">
                      {formatDecimal(results.total_volume_m3)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* Analysis Info */}
          <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-blue-600 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-blue-800">
              <p className="font-medium">{t('userGroup.landCover.methodologyTitle')}</p>
              <ul className="mt-2 space-y-1 text-blue-700">
                <li>• {t('userGroup.landCover.methodLandCover')}</li>
                <li>• {t('userGroup.landCover.methodBiomass')}</li>
                <li>• {t('userGroup.landCover.methodVolume')}</li>
                {results.has_forest_overlap && (
                  <li className="text-orange-700 font-medium">
                    • {t('userGroup.landCover.methodOverlap', {
                      value: `${formatDecimal(results.forest_overlap_area_ha)} ${t('units.hectare')}`,
                    })}
                  </li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

      {/* Instructions (when no results) */}
      {!results && !loading && !error && (
        <div className="text-center py-12 text-gray-500">
          <Leaf className="w-16 h-16 mx-auto mb-4 text-gray-300" />
          <p className="text-lg font-medium text-gray-600 mb-2">
            {t('userGroup.landCover.readyTitle')}
          </p>
          <p className="text-sm max-w-md mx-auto">
            {t('userGroup.landCover.readyBody', { action: t('userGroup.landCover.run') })}
          </p>
        </div>
      )}
    </div>
  );
}
