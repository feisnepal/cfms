/** Settlement statistics card — displays household count, population, and map markers for each settlement. */
import React from 'react';
import { Home, Users, MapPin } from 'lucide-react';
import { useT } from '../../i18n/hooks';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';

interface Settlement {
  settlement_id?: number;
  settlement_name: string;
  building_count: number;
  total_area_m2: number;
  small_buildings?: number;
  medium_buildings?: number;
  large_buildings?: number;
  avg_building_size_m2?: number;
  direction_from_forest: string;
  lat?: number;
  lon?: number;
}

interface SettlementStatisticsProps {
  settlements: Settlement[];
}

export function SettlementStatistics({ settlements }: SettlementStatisticsProps) {
  const t = useT();
  const totalBuildings = settlements.reduce((sum, s) => sum + s.building_count, 0);
  const totalArea = settlements.reduce((sum, s) => sum + s.total_area_m2, 0);
  const totalSmall = settlements.reduce((sum, s) => sum + (s.small_buildings || 0), 0);
  const totalMedium = settlements.reduce((sum, s) => sum + (s.medium_buildings || 0), 0);
  const totalLarge = settlements.reduce((sum, s) => sum + (s.large_buildings || 0), 0);
  const avgBuildingSize = totalBuildings > 0 ? totalArea / totalBuildings : 0;

  return (
    <div className="settlement-statistics mt-6">
      <h3 className="text-xl font-semibold mb-4">{t('userGroup.settlement.title')}</h3>

      {/* Summary Cards */}
      <div className="summary-cards grid grid-cols-4 gap-4 mb-6">
        <div className="card bg-blue-100 p-4 rounded shadow">
          <div className="flex items-center">
            <MapPin className="text-blue-600 mr-3" size={32} />
            <div>
              <p className="text-sm text-gray-600">{t('userGroup.settlement.totalSettlements')}</p>
              <p className="text-2xl font-bold">{settlements.length}</p>
              <p className="text-xs text-gray-400 font-mono mt-1">{'{{ug_total_settlements}}'}</p>
            </div>
          </div>
        </div>

        <div className="card bg-green-100 p-4 rounded shadow">
          <div className="flex items-center">
            <Home className="text-green-600 mr-3" size={32} />
            <div>
              <p className="text-sm text-gray-600">{t('userGroup.settlement.totalBuildings')}</p>
              <p className="text-2xl font-bold">{totalBuildings}</p>
              <p className="text-xs text-gray-400 font-mono mt-1">{'{{ug_total_buildings}}'}</p>
            </div>
          </div>
        </div>

        <div className="card bg-yellow-100 p-4 rounded shadow">
          <div className="flex items-center">
            <Users className="text-yellow-600 mr-3" size={32} />
            <div>
              <p className="text-sm text-gray-600">{t('userGroup.settlement.totalArea')}</p>
              <p className="text-2xl font-bold">{formatNumber(Math.round(totalArea))} {t('units.sqM')}</p>
              <p className="text-xs text-gray-400 font-mono mt-1">{'{{ug_total_building_area_m2}}'}</p>
            </div>
          </div>
        </div>

        <div className="card bg-purple-100 p-4 rounded shadow">
          <div>
            <p className="text-sm text-gray-600 mb-2">{t('userGroup.settlement.buildingSizes')}</p>
            <div className="flex justify-between text-xs">
              <div className="text-center">
                <div className="bg-green-200 px-2 py-1 rounded mb-1">
                  <span className="font-bold">{totalSmall}</span>
                </div>
                <span className="text-gray-600">{t('userGroup.settlement.sizeSmall')}</span>
                <p className="text-gray-400 font-mono mt-0.5">{'{{ug_small_buildings}}'}</p>
              </div>
              <div className="text-center">
                <div className="bg-yellow-200 px-2 py-1 rounded mb-1">
                  <span className="font-bold">{totalMedium}</span>
                </div>
                <span className="text-gray-600">{t('userGroup.settlement.sizeMedium')}</span>
                <p className="text-gray-400 font-mono mt-0.5">{'{{ug_medium_buildings}}'}</p>
              </div>
              <div className="text-center">
                <div className="bg-orange-200 px-2 py-1 rounded mb-1">
                  <span className="font-bold">{totalLarge}</span>
                </div>
                <span className="text-gray-600">{t('userGroup.settlement.sizeLarge')}</span>
                <p className="text-gray-400 font-mono mt-0.5">{'{{ug_large_buildings}}'}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Additional Stats */}
      <div className="bg-gray-50 p-4 rounded mb-6 border border-gray-200">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div>
            <p className="text-sm text-gray-600">{t('userGroup.settlement.avgSize')}</p>
            <p className="text-xl font-semibold text-gray-800">{formatDecimal(avgBuildingSize, 1)} {t('units.sqM')}</p>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{'{{ug_avg_building_size_m2}}'}</p>
          </div>
          <div>
            <p className="text-sm text-gray-600">{t('userGroup.settlement.smallBuildings')}</p>
            <p className="text-xl font-semibold text-green-600">
              {formatNumber(totalSmall)} ({totalBuildings > 0
                ? formatDecimal((totalSmall / totalBuildings) * 100, 1)
                : formatNumber(0)}%)
            </p>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{'{{ug_small_pct}}'} {'{{ug_small_buildings}}'}</p>
          </div>
          <div>
            <p className="text-sm text-gray-600">{t('userGroup.settlement.mediumBuildings')}</p>
            <p className="text-xl font-semibold text-yellow-600">
              {formatNumber(totalMedium)} ({totalBuildings > 0
                ? formatDecimal((totalMedium / totalBuildings) * 100, 1)
                : formatNumber(0)}%)
            </p>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{'{{ug_medium_pct}}'} {'{{ug_medium_buildings}}'}</p>
          </div>
        </div>
        <div className="grid grid-cols-1 gap-4 text-center mt-4">
          <div>
            <p className="text-sm text-gray-600">{t('userGroup.settlement.largeBuildings')}</p>
            <p className="text-xl font-semibold text-orange-600">
              {formatNumber(totalLarge)} ({totalBuildings > 0
                ? formatDecimal((totalLarge / totalBuildings) * 100, 1)
                : formatNumber(0)}%)
            </p>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{'{{ug_large_pct}}'} {'{{ug_large_buildings}}'}</p>
          </div>
        </div>
      </div>

      {/* Detailed Table */}
      <p className="text-xs text-gray-400 font-mono mb-1">{'{{ug_buildings}}'}</p>
      <div className="overflow-x-auto">
        <table className="min-w-full bg-white border border-gray-300">
          <thead className="bg-gray-100">
            <tr>
              <th className="px-4 py-2 border text-left">{t('userGroup.settlement.colName')}</th>
              <th className="px-4 py-2 border text-center">{t('userGroup.settlement.totalBuildings')}</th>
              <th className="px-4 py-2 border text-center" title="Buildings < 50 m²">
                Small<br />
                <span className="text-xs text-gray-500">(&lt; 50 m²)</span>
              </th>
              <th className="px-4 py-2 border text-center" title="Buildings 50-150 m²">
                Medium<br />
                <span className="text-xs text-gray-500">(50-150 m²)</span>
              </th>
              <th className="px-4 py-2 border text-center" title="Buildings > 150 m²">
                Large<br />
                <span className="text-xs text-gray-500">(&gt; 150 m²)</span>
              </th>
              <th className="px-4 py-2 border text-center">{t('userGroup.settlement.colAvgSize')}</th>
              <th className="px-4 py-2 border text-center">{t('userGroup.settlement.colTotalArea')}</th>
              <th className="px-4 py-2 border text-center">{t('userGroup.settlement.colDirection')}</th>
            </tr>
          </thead>
          <tbody>
            {settlements.map((settlement, idx) => (
              <tr key={idx} className="hover:bg-gray-50">
                <td className="px-4 py-2 border">{settlement.settlement_name}</td>
                <td className="px-4 py-2 border text-center font-semibold">{settlement.building_count}</td>
                <td className="px-4 py-2 border text-center">
                  <span className="inline-block bg-green-100 px-2 py-1 rounded text-sm">
                    {settlement.small_buildings || 0}
                  </span>
                </td>
                <td className="px-4 py-2 border text-center">
                  <span className="inline-block bg-yellow-100 px-2 py-1 rounded text-sm">
                    {settlement.medium_buildings || 0}
                  </span>
                </td>
                <td className="px-4 py-2 border text-center">
                  <span className="inline-block bg-orange-100 px-2 py-1 rounded text-sm">
                    {settlement.large_buildings || 0}
                  </span>
                </td>
                <td className="px-4 py-2 border text-center">
                  {settlement.avg_building_size_m2 != null
                    ? formatDecimal(settlement.avg_building_size_m2, 1)
                    : t('common.notAvailable')}
                </td>
                <td className="px-4 py-2 border text-center">{formatDecimal(settlement.total_area_m2)}</td>
                <td className="px-4 py-2 border text-center">
                  <span className="inline-block bg-blue-200 px-3 py-1 rounded">
                    {settlement.direction_from_forest}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
