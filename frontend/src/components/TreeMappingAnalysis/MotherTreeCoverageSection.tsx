/** Pie/bar charts showing mother-tree coverage and seedling distribution by block. */
import { Pie, Bar } from 'react-chartjs-2';
import { getHierarchyPath } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';

const COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#6366f1'];

interface Props {
  coverageData?: any;
  hierarchyData: any[];
  remarkBreakdown?: Record<string, any>;
  motherBySpecies?: any[];
  fellingBySpecies?: any[];
  summary?: any;
  collapsed?: boolean;
  onToggle?: () => void;
}

export function MotherTreeCoverageSection({
  coverageData,
  hierarchyData,
  remarkBreakdown,
  motherBySpecies,
  fellingBySpecies,
  summary,
  collapsed,
  onToggle,
}: Props) {
  const t = useT();
  if (!hierarchyData || hierarchyData.length === 0) return null;

  // Pie chart data for mother vs felling
  const pieData = summary ? [
    { name: t('treeMapping.col.motherTrees'), value: summary.total_mother_trees },
    { name: t('treeMapping.col.fellingTrees'), value: summary.total_felling_trees },
  ] : [];

  // Species bar chart data
  const speciesChartData = motherBySpecies && fellingBySpecies ? (() => {
    const speciesMap: Record<string, { mother: number; felling: number }> = {};
    motherBySpecies.forEach((r: any) => {
      if (!speciesMap[r.species]) speciesMap[r.species] = { mother: 0, felling: 0 };
      speciesMap[r.species].mother = r.tree_count;
    });
    fellingBySpecies.forEach((r: any) => {
      if (!speciesMap[r.species]) speciesMap[r.species] = { mother: 0, felling: 0 };
      speciesMap[r.species].felling = r.tree_count;
    });
    return Object.entries(speciesMap)
      .sort((a, b) => (b[1].mother + b[1].felling) - (a[1].mother + a[1].felling))
      .slice(0, 10)
      .map(([species, counts]) => ({
        species: species.length > 15 ? species.substring(0, 12) + '...' : species,
        mother: counts.mother,
        felling: counts.felling,
      }));
  })() : [];

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold">{t('treeMapping.mother.title')}
          <CopyTag label="{{section:sm_mother_tree_narration}}" value="{{section:sm_mother_tree_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          {/* Coverage Summary Cards */}
          {coverageData && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <div className="bg-green-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">{t('treeMapping.mother.gridSpacing')}</p>
                <p className="text-2xl font-bold text-green-600">{coverageData.grid_spacing_m}</p>
              </div>
              <div className="bg-blue-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">{t('treeMapping.mother.totalCells')}</p>
                <p className="text-2xl font-bold text-blue-600">{coverageData.total_grid_cells}</p>
              </div>
              <div className="bg-amber-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">{t('treeMapping.mother.cellsWithMother')}</p>
                <p className="text-2xl font-bold text-amber-600">{coverageData.cells_with_mother}</p>
              </div>
              <div className="bg-purple-50 rounded-lg p-4 text-center">
                <p className="text-sm text-gray-500">{t('treeMapping.mother.coveragePercent')}</p>
                <p className="text-2xl font-bold text-purple-600">{coverageData.coverage_percent}%</p>
              </div>
            </div>
          )}

          {/* Mother vs Felling Summary */}
          {summary && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
              {/* Pie Chart */}
              <div>
                <h4 className="font-medium mb-3 text-center">{t('treeMapping.mother.vsFelling')}
                  <CopyTag label="{{chart:sm_mother_felling_pie}}" value="{{chart:sm_mother_felling_pie}}" variant="variable" />
                </h4>
                <div style={{ width: '100%', height: 250 }}>
                  <Pie
                    height={250}
                    data={{
                      labels: pieData.map((d) => d.name),
                      datasets: [{
                        data: pieData.map((d) => d.value),
                        backgroundColor: pieData.map((_, index) => (index === 0 ? '#22c55e' : '#ef4444')),
                        borderColor: '#fff',
                        borderWidth: 1,
                      }],
                    }}
                    options={{
                      plugins: {
                        legend: { position: 'bottom' },
                        tooltip: {
                          callbacks: {
                            label: (ctx) => {
                              const value = ctx.parsed as number;
                              const total = pieData.reduce((s, d) => s + d.value, 0) || 1;
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

              {/* Summary Stats */}
              <div className="flex flex-col justify-center">
                <div className="space-y-4">
                  <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg">
                    <span className="font-medium text-green-800">{t('treeMapping.mother.motherTreesLabel')}</span>
                    <span className="text-2xl font-bold text-green-600">{summary.total_mother_trees.toLocaleString()}</span>
                  </div>
                  <div className="flex items-center justify-between p-3 bg-red-50 rounded-lg">
                    <span className="font-medium text-red-800">{t('treeMapping.mother.fellingTreesLabel')}</span>
                    <span className="text-2xl font-bold text-red-600">{summary.total_felling_trees.toLocaleString()}</span>
                  </div>
                  <div className="flex items-center justify-between p-3 bg-gray-100 rounded-lg">
                    <span className="font-medium text-gray-800">{t('treeMapping.mother.totalLabel')}</span>
                    <span className="text-2xl font-bold text-gray-600">{summary.total_trees.toLocaleString()}</span>
                  </div>
                  <div className="text-sm text-gray-500 text-center">
                    {t('treeMapping.col.mother')}: {summary.mother_percent}% | {t('treeMapping.col.felling')}: {summary.felling_percent}%
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Species-wise Mother vs Felling Chart */}
          {speciesChartData.length > 0 && (
            <div className="mb-6">
              <h4 className="font-medium mb-3">{t('treeMapping.mother.speciesWise')}
                <CopyTag label="{{chart:sm_mother_felling_species_bar}}" value="{{chart:sm_mother_felling_species_bar}}" variant="variable" />
              </h4>
              <div style={{ width: '100%', height: 350 }}>
                <Bar
                  height={350}
                  data={{
                    labels: speciesChartData.map((d) => d.species),
                    datasets: [
                      { label: t('treeMapping.col.motherTrees'), data: speciesChartData.map((d) => d.mother), backgroundColor: '#22c55e' },
                      { label: t('treeMapping.col.fellingTrees'), data: speciesChartData.map((d) => d.felling), backgroundColor: '#ef4444' },
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
          )}

          {/* Species Tables */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Mother Tree by Species */}
            {motherBySpecies && motherBySpecies.length > 0 && (
              <div>
                <h4 className="font-medium mb-3 text-green-700">{t('treeMapping.mother.bySpecies')}
                  <CopyTag label="{{sm_mother_tree_by_species}}" value="{{sm_mother_tree_by_species}}" variant="variable" />
                </h4>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-green-50">
                      <tr>
                        <th className="px-3 py-2 text-left">{t('treeMapping.col.species')}</th>
                        <th className="px-3 py-2 text-left">{t('treeMapping.col.localName')}</th>
                        <th className="px-3 py-2 text-right">{t('treeMapping.col.count')}</th>
                        <th className="px-3 py-2 text-right">{t('treeMapping.col.percent')}</th>
                        <th className="px-3 py-2 text-right">{t('treeMapping.col.timber')}</th>
                        <th className="px-3 py-2 text-right">DBH (cm)</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {motherBySpecies.map((row, idx) => (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-3 py-2 font-medium">{row.species}</td>
                          <td className="px-3 py-2">{row.local_name}</td>
                          <td className="px-3 py-2 text-right font-medium">{row.tree_count}</td>
                          <td className="px-3 py-2 text-right">{row.percent}%</td>
                          <td className="px-3 py-2 text-right">{row.timber_m3}</td>
                          <td className="px-3 py-2 text-right">{row.avg_dbh_cm}</td>
                        </tr>
                      ))}
                      <tr className="bg-green-50 font-semibold">
                        <td className="px-3 py-2" colSpan={2}>{t('treeMapping.col.total')}</td>
                        <td className="px-3 py-2 text-right">{motherBySpecies.reduce((s, r) => s + r.tree_count, 0).toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">100%</td>
                        <td className="px-3 py-2 text-right">{motherBySpecies.reduce((s, r) => s + r.timber_m3, 0).toFixed(2)}</td>
                        <td className="px-3 py-2 text-right">-</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* Felling Tree by Species */}
            {fellingBySpecies && fellingBySpecies.length > 0 && (
              <div>
                <h4 className="font-medium mb-3 text-red-700">{t('treeMapping.mother.fellingBySpecies')}
                  <CopyTag label="{{sm_felling_tree_by_species}}" value="{{sm_felling_tree_by_species}}" variant="variable" />
                </h4>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-red-50">
                      <tr>
                        <th className="px-3 py-2 text-left">{t('treeMapping.col.species')}</th>
                        <th className="px-3 py-2 text-left">{t('treeMapping.col.localName')}</th>
                        <th className="px-3 py-2 text-right">{t('treeMapping.col.count')}</th>
                        <th className="px-3 py-2 text-right">{t('treeMapping.col.percent')}</th>
                        <th className="px-3 py-2 text-right">{t('treeMapping.col.timber')}</th>
                        <th className="px-3 py-2 text-right">DBH (cm)</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {fellingBySpecies.map((row, idx) => (
                        <tr key={idx} className="hover:bg-gray-50">
                          <td className="px-3 py-2 font-medium">{row.species}</td>
                          <td className="px-3 py-2">{row.local_name}</td>
                          <td className="px-3 py-2 text-right font-medium">{row.tree_count}</td>
                          <td className="px-3 py-2 text-right">{row.percent}%</td>
                          <td className="px-3 py-2 text-right">{row.timber_m3}</td>
                          <td className="px-3 py-2 text-right">{row.avg_dbh_cm}</td>
                        </tr>
                      ))}
                      <tr className="bg-red-50 font-semibold">
                        <td className="px-3 py-2" colSpan={2}>{t('treeMapping.col.total')}</td>
                        <td className="px-3 py-2 text-right">{fellingBySpecies.reduce((s, r) => s + r.tree_count, 0).toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">100%</td>
                        <td className="px-3 py-2 text-right">{fellingBySpecies.reduce((s, r) => s + r.timber_m3, 0).toFixed(2)}</td>
                        <td className="px-3 py-2 text-right">-</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>

          {/* Hierarchy Table */}
          <div>
            <h4 className="font-medium mb-3">{t('treeMapping.mother.byHierarchy')}
              <CopyTag label="{{sm_mother_tree_by_hierarchy}}" value="{{sm_mother_tree_by_hierarchy}}" variant="variable" />
            </h4>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left">{t('treeMapping.col.hierarchy')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.gridCells')}</th>
                    <th className="px-3 py-2 text-right bg-green-50">{t('treeMapping.col.motherTrees')}</th>
                    <th className="px-3 py-2 text-right bg-red-50">{t('treeMapping.col.fellingTrees')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.coverageRatio')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {hierarchyData.map((row, idx) => {
                    const rk = remarkBreakdown?.[`${row.compartment}|${row.sub_compartment}`];
                    const motherCount = rk?.mother_trees ?? row.mother_trees ?? 0;
                    const fellingCount = rk?.felling_trees ?? 0;
                    return (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-3 py-2 font-medium">{getHierarchyPath(row)}</td>
                        <td className="px-3 py-2 text-right">{row.grid_cells}</td>
                        <td className="px-3 py-2 text-right text-green-600 font-medium bg-green-50">{motherCount.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right text-red-600 font-medium bg-red-50">{fellingCount.toLocaleString()}</td>
                        <td className="px-3 py-2 text-right">
                          <span className={`px-2 py-1 rounded text-xs font-semibold ${
                            row.coverage_ratio >= 0.7 ? 'bg-green-100 text-green-700' :
                            row.coverage_ratio >= 0.5 ? 'bg-amber-100 text-amber-700' :
                            'bg-red-100 text-red-700'
                          }`}>
                            {(row.coverage_ratio * 100).toFixed(1)}%
                          </span>
                        </td>
                      </tr>
                      );
                    })}
                    <tr className="bg-gray-100 font-semibold">
                      <td className="px-3 py-2">{t('treeMapping.col.total')}</td>
                      <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.grid_cells || 0), 0)}</td>
                      <td className="px-3 py-2 text-right text-green-700 bg-green-50">{hierarchyData.reduce((s, r) => {
                        const rk = remarkBreakdown?.[`${r.compartment}|${r.sub_compartment}`];
                        return s + (rk?.mother_trees ?? r.mother_trees ?? 0);
                      }, 0).toLocaleString()}</td>
                      <td className="px-3 py-2 text-right text-red-700 bg-red-50">{hierarchyData.reduce((s, r) => {
                        const rk = remarkBreakdown?.[`${r.compartment}|${r.sub_compartment}`];
                        return s + (rk?.felling_trees ?? 0);
                      }, 0).toLocaleString()}</td>
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
