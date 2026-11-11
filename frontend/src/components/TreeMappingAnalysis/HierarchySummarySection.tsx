/** Summary bar chart of key metrics (count, volume, carbon) across hierarchy levels. */
import { Bar } from 'react-chartjs-2';
import { getHierarchyPath, truncateLabel } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';

interface Props {
  data: any[];
  remarkBreakdown?: Record<string, any>;
  collapsed?: boolean;
  onToggle?: () => void;
}

function getRemarkKey(row: any): string {
  // Must match the backend key in sm_hierarchy_remark_breakdown: "compartment|sub_compartment".
  return `${row.compartment ?? '-'}|${row.sub_compartment ?? '-'}`;
}

export function HierarchySummarySection({ data, remarkBreakdown, collapsed, onToggle }: Props) {
  const t = useT();
  if (!data || data.length === 0) return null;

  const chartData = data.slice(0, 12).map((row) => {
    const rk = remarkBreakdown?.[getRemarkKey(row)];
    return {
      name: truncateLabel(getHierarchyPath(row)),
      mother: rk?.mother_trees || 0,
      felling: rk?.felling_trees || 0,
    };
  });

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold">{t('treeMapping.summary.title')}
          <CopyTag label="{{section:sm_hierarchy_narration}}" value="{{section:sm_hierarchy_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          {/* Stacked Bar Chart - Mother vs Felling by Hierarchy */}
          <div className="mb-6">
            <h4 className="text-sm font-medium text-gray-600 mb-2">{t('treeMapping.summary.motherVsFelling')}
              <CopyTag label="{{chart:sm_mother_felling_hierarchy_bar}}" value="{{chart:sm_mother_felling_hierarchy_bar}}" variant="variable" />
            </h4>
            <div style={{ width: '100%', height: 300 }}>
              <Bar
                height={300}
                data={{
                  labels: chartData.map((d) => d.name),
                  datasets: [
                    { label: t('treeMapping.col.mother'), data: chartData.map((d) => d.mother), backgroundColor: '#22c55e', stack: 'a' },
                    { label: t('treeMapping.col.felling'), data: chartData.map((d) => d.felling), backgroundColor: '#ef4444', stack: 'a' },
                  ],
                }}
                options={{
                  indexAxis: 'y',
                  responsive: true,
                  maintainAspectRatio: false,
                  scales: {
                    x: { beginAtZero: true, grid: { display: true } },
                    y: { ticks: { font: { size: 11 } } },
                  },
                }}
              />
            </div>
          </div>

          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            <div className="bg-green-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-green-700">{data.length}</div>
              <div className="text-xs text-green-600">{t('treeMapping.summary.levels')}</div>
            </div>
            <div className="bg-blue-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-blue-700">{data.reduce((s, r) => s + r.tree_count, 0).toLocaleString()}</div>
              <div className="text-xs text-blue-600">{t('treeMapping.summary.totalTrees')}</div>
            </div>
            <div className="bg-amber-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-amber-700">{data.reduce((s, r) => s + (r.total_volume_m3 || 0), 0).toFixed(0)}</div>
              <div className="text-xs text-amber-600">{t('treeMapping.summary.totalVolume')}</div>
            </div>
            <div className="bg-purple-50 rounded-lg p-3 text-center">
              <div className="text-2xl font-bold text-purple-700">{data.filter(r => r.sub_area_name !== '-').length}</div>
              <div className="text-xs text-purple-600">{t('treeMapping.summary.subAreas')}</div>
            </div>
          </div>

          {/* Table */}
          <div className="mb-2">
            <CopyTag label="{{sm_hierarchy_summary}}" value="{{sm_hierarchy_summary}}" variant="variable" />
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.hierarchy')}</th>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.subArea')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.totalTrees')}</th>
                  <th className="px-3 py-2 text-right bg-green-50">{t('treeMapping.col.motherTrees')}</th>
                  <th className="px-3 py-2 text-right bg-red-50">{t('treeMapping.col.fellingTrees')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.areaHa')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.treesPerHa')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.grossVolume')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.volumePerHa')}</th>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.dominantSpecies')}</th>
                  <th className="px-3 py-2 text-right">DBH (cm)</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.heightM')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data.map((row, idx) => {
                  const rk = remarkBreakdown?.[getRemarkKey(row)];
                  const motherCount = rk?.mother_trees || 0;
                  const fellingCount = rk?.felling_trees || 0;
                  return (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium">
                        <span className="text-xs text-gray-400 mr-1">{idx + 1}.</span>
                        {getHierarchyPath(row)}
                      </td>
                      <td className="px-3 py-2 text-xs">{row.sub_area_name !== '-' ? row.sub_area_name : ''}</td>
                      <td className="px-3 py-2 text-right font-medium">{row.tree_count.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-green-600 font-medium bg-green-50">{motherCount.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-red-600 font-medium bg-red-50">{fellingCount.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{row.area_ha}</td>
                      <td className="px-3 py-2 text-right">{row.trees_per_ha}</td>
                      <td className="px-3 py-2 text-right">{row.total_volume_m3.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{row.volume_per_ha}</td>
                      <td className="px-3 py-2 text-xs">{row.dominant_species}</td>
                      <td className="px-3 py-2 text-right">{row.avg_dbh_cm}</td>
                      <td className="px-3 py-2 text-right">{row.avg_height_m}</td>
                    </tr>
                  );
                })}
                <tr className="bg-gray-100 font-semibold">
                  <td className="px-3 py-2" colSpan={2}>{t('treeMapping.col.total')}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + r.tree_count, 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right text-green-700 bg-green-50">{data.reduce((s, r) => {
                    const rk = remarkBreakdown?.[getRemarkKey(r)];
                    return s + (rk?.mother_trees || 0);
                  }, 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right text-red-700 bg-red-50">{data.reduce((s, r) => {
                    const rk = remarkBreakdown?.[getRemarkKey(r)];
                    return s + (rk?.felling_trees || 0);
                  }, 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right">-</td>
                  <td className="px-3 py-2 text-right">-</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.total_volume_m3 || 0), 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right">-</td>
                  <td className="px-3 py-2">-</td>
                  <td className="px-3 py-2 text-right">-</td>
                  <td className="px-3 py-2 text-right">-</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
