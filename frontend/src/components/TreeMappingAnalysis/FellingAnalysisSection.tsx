/** Pie/bar charts for felling analysis (cut vs. standing trees by species/block). */
import { Pie, Bar } from 'react-chartjs-2';
import { getHierarchyPath } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';

const COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1'];

interface Props {
  totals?: any;
  dbhData: any[];
  speciesData: any[];
  collapsed?: boolean;
  onToggle?: () => void;
}

export function FellingAnalysisSection({ totals, dbhData, speciesData, collapsed, onToggle }: Props) {
  const t = useT();
  if (!dbhData || dbhData.length === 0) return null;

  // DBH class pie chart
  const dbhPieData = dbhData.map(r => ({
    name: r.dbh_class,
    value: r.tree_count,
  }));

  // Species bar chart (top 10)
  const spChartData = speciesData.slice(0, 10).map(r => ({
    species: r.species.length > 15 ? r.species.substring(0, 12) + '...' : r.species,
    tree: r.tree_count,
    timber: r.timber_m3,
  }));

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden border-2 border-red-200">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-red-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold text-red-800">{t('treeMapping.felling.title')}
          <CopyTag label="{{section:sm_felling_narration}}" value="{{section:sm_felling_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          {/* Totals Summary Cards */}
          {totals && (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
              <div className="bg-red-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.totalTrees')}</p>
                <p className="text-xl font-bold text-red-700">{totals.tree_count.toLocaleString()}</p>
              </div>
              <div className="bg-green-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.timber')}</p>
                <p className="text-xl font-bold text-green-700">{totals.timber_m3.toLocaleString()}</p>
              </div>
              <div className="bg-blue-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.firewood')}</p>
                <p className="text-xl font-bold text-blue-700">{totals.firewood_m3.toLocaleString()}</p>
              </div>
              <div className="bg-amber-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.gross')}</p>
                <p className="text-xl font-bold text-amber-700">{totals.gross_volume_m3.toLocaleString()}</p>
              </div>
              <div className="bg-purple-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.net')}</p>
                <p className="text-xl font-bold text-purple-700">{totals.net_volume_m3.toLocaleString()}</p>
              </div>
              <div className="bg-teal-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.fuel')}</p>
                <p className="text-xl font-bold text-teal-700">{totals.fuelwood_m3.toLocaleString()}</p>
              </div>
              <div className="bg-orange-50 rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">{t('treeMapping.stat.chatta')}</p>
                <p className="text-xl font-bold text-orange-700">{totals.fuelwood_chatta.toLocaleString()}</p>
              </div>
            </div>
          )}

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* DBH Pie Chart */}
            <div>
              <h4 className="font-medium mb-3 text-center">{t('treeMapping.felling.byDbhClass')}
                <CopyTag label="{{chart:sm_felling_dbh_pie}}" value="{{chart:sm_felling_dbh_pie}}" variant="variable" />
              </h4>
              <div style={{ width: '100%', height: 280 }}>
                <Pie
                  height={280}
                  data={{
                    labels: dbhPieData.map((d) => d.name),
                    datasets: [{
                      data: dbhPieData.map((d) => d.value),
                      backgroundColor: dbhPieData.map((_, index) => COLORS[index % COLORS.length]),
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
                            const value = ctx.parsed as number;
                            const total = dbhPieData.reduce((s, d) => s + d.value, 0) || 1;
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

            {/* Species Bar Chart */}
            <div>
              <h4 className="font-medium mb-3 text-center">{t('treeMapping.felling.bySpeciesTop10')}
                <CopyTag label="{{chart:sm_felling_species_bar}}" value="{{chart:sm_felling_species_bar}}" variant="variable" />
              </h4>
              <div style={{ width: '100%', height: 280 }}>
                <Bar
                  height={280}
                  data={{
                    labels: spChartData.map((d) => d.species),
                    datasets: [
                      { label: t('treeMapping.col.treeCount'), data: spChartData.map((d) => d.tree), backgroundColor: '#ef4444' },
                      { label: t('treeMapping.col.timberShort'), data: spChartData.map((d) => d.timber), backgroundColor: '#22c55e' },
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
          </div>

          {/* DBH Class Table */}
          <div className="mb-6">
            <h4 className="font-medium mb-3">{t('treeMapping.felling.tableByDbh')}
              <CopyTag label="{{sm_felling_dbh_analysis}}" value="{{sm_felling_dbh_analysis}}" variant="variable" />
            </h4>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-red-50">
                  <tr>
                    <th className="px-3 py-2 text-left">{t('treeMapping.col.dbhClass')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.treeCount')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.percent')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.timber')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.firewood')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.grossM3')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.netM3')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.fuelM3')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.chattaM3')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.avgDbhShort')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {dbhData.map((row, idx) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium">{row.dbh_class}</td>
                      <td className="px-3 py-2 text-right font-medium">{row.tree_count.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{row.percent}%</td>
                      <td className="px-3 py-2 text-right text-green-700 font-medium">{row.timber_m3}</td>
                      <td className="px-3 py-2 text-right text-blue-700">{row.firewood_m3}</td>
                      <td className="px-3 py-2 text-right font-medium">{row.gross_volume_m3}</td>
                      <td className="px-3 py-2 text-right text-purple-700">{row.net_volume_m3}</td>
                      <td className="px-3 py-2 text-right text-teal-700">{row.fuelwood_m3}</td>
                      <td className="px-3 py-2 text-right text-orange-700">{row.fuelwood_chatta}</td>
                      <td className="px-3 py-2 text-right">{row.avg_dbh_cm}</td>
                    </tr>
                  ))}
                  {totals && (
                    <tr className="bg-gray-100 font-semibold">
                      <td className="px-3 py-2">{t('treeMapping.col.total')}</td>
                      <td className="px-3 py-2 text-right">{totals.tree_count.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">100%</td>
                      <td className="px-3 py-2 text-right text-green-700">{totals.timber_m3}</td>
                      <td className="px-3 py-2 text-right text-blue-700">{totals.firewood_m3}</td>
                      <td className="px-3 py-2 text-right">{totals.gross_volume_m3}</td>
                      <td className="px-3 py-2 text-right text-purple-700">{totals.net_volume_m3}</td>
                      <td className="px-3 py-2 text-right text-teal-700">{totals.fuelwood_m3}</td>
                      <td className="px-3 py-2 text-right text-orange-700">{totals.fuelwood_chatta}</td>
                      <td className="px-3 py-2 text-right">-</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Species Table */}
          <div>
            <h4 className="font-medium mb-3">{t('treeMapping.felling.tableBySpecies')}
              <CopyTag label="{{sm_felling_species_analysis}}" value="{{sm_felling_species_analysis}}" variant="variable" />
            </h4>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-red-50">
                  <tr>
                    <th className="px-3 py-2 text-left">{t('treeMapping.col.species')}</th>
                    <th className="px-3 py-2 text-left">{t('treeMapping.col.localName')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.treeCount')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.percent')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.timber')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.firewood')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.grossM3')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.netM3')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.avgDbhShort')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {speciesData.map((row, idx) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium">{row.species}</td>
                      <td className="px-3 py-2">{row.local_name}</td>
                      <td className="px-3 py-2 text-right font-medium">{row.tree_count.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{row.percent}%</td>
                      <td className="px-3 py-2 text-right text-green-700 font-medium">{row.timber_m3}</td>
                      <td className="px-3 py-2 text-right text-blue-700">{row.firewood_m3}</td>
                      <td className="px-3 py-2 text-right font-medium">{row.gross_volume_m3}</td>
                      <td className="px-3 py-2 text-right text-purple-700">{row.net_volume_m3}</td>
                      <td className="px-3 py-2 text-right">{row.avg_dbh_cm}</td>
                    </tr>
                  ))}
                  <tr className="bg-red-50 font-semibold">
                    <td className="px-3 py-2" colSpan={2}>{t('treeMapping.col.total')}</td>
                    <td className="px-3 py-2 text-right">{speciesData.reduce((s, r) => s + r.tree_count, 0).toLocaleString()}</td>
                    <td className="px-3 py-2 text-right">100%</td>
                    <td className="px-3 py-2 text-right">{speciesData.reduce((s, r) => s + (r.timber_m3 || 0), 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{speciesData.reduce((s, r) => s + (r.firewood_m3 || 0), 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{speciesData.reduce((s, r) => s + (r.gross_volume_m3 || 0), 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">{speciesData.reduce((s, r) => s + (r.net_volume_m3 || 0), 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">-</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
