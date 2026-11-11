/** Bar chart of area or tree count grouped by stand type within the selected hierarchy. */
import { Bar } from 'react-chartjs-2';
import { getHierarchyPath, truncateLabel } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';

interface Props {
  hierarchyData: any[];
  statusData?: any;
  collapsed?: boolean;
  onToggle?: () => void;
}

export function StandTypeSection({ hierarchyData, statusData, collapsed, onToggle }: Props) {
  const t = useT();
  if (!hierarchyData || hierarchyData.length === 0) return null;

  const chartData = hierarchyData.map(row => ({
    name: truncateLabel(getHierarchyPath(row)),
    regeneration: row.regeneration,
    sapling: row.sapling,
    pole: row.pole,
    tree: row.tree,
  }));

  const getStatusColor = (status: string) => {
    if (status === 'राम्रो') return 'text-green-600 bg-green-100';
    if (status === 'मध्यम') return 'text-amber-600 bg-amber-100';
    return 'text-red-600 bg-red-100';
  };

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold">{t('treeMapping.stand.title')}
          <CopyTag label="{{section:sm_stand_type_narration}}" value="{{section:sm_stand_type_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          {statusData && (
            <div className="mb-6 p-4 rounded-lg bg-gray-50">
              <div className="flex items-center gap-4 flex-wrap">
                <span className="text-sm font-medium">{t('treeMapping.stand.overallStatus')}</span>
                <span className={`px-3 py-1 rounded-full text-sm font-semibold ${getStatusColor(statusData.overall_status)}`}>
                  {statusData.overall_status}
                </span>
                <span className="text-sm text-gray-500">
                  {t('treeMapping.col.regeneration')}: {statusData.overall_regeneration_percent}% | 
                  {t('treeMapping.stand.good')}: {statusData.good_structure_blocks} | 
                  {t('treeMapping.stand.moderate')}: {statusData.moderate_structure_blocks} | 
                  {t('treeMapping.stand.weak')}: {statusData.weak_structure_blocks}
                </span>
              </div>
            </div>
          )}

          <div className="mb-6">
            <h4 className="text-sm font-medium text-gray-600 mb-2">{t('treeMapping.stand.byHierarchy')}
              <CopyTag label="{{chart:sm_stand_type_bar}}" value="{{chart:sm_stand_type_bar}}" variant="variable" />
            </h4>
            <div style={{ width: '100%', height: 300 }}>
              <Bar
                height={300}
                data={{
                  labels: chartData.map((d) => d.name),
                  datasets: [
                    { label: t('treeMapping.col.regeneration'), data: chartData.map((d) => d.regeneration), backgroundColor: '#22c55e', stack: 'a' },
                    { label: t('treeMapping.col.sapling'), data: chartData.map((d) => d.sapling), backgroundColor: '#3b82f6', stack: 'a' },
                    { label: t('treeMapping.col.pole'), data: chartData.map((d) => d.pole), backgroundColor: '#f59e0b', stack: 'a' },
                    { label: t('treeMapping.col.tree'), data: chartData.map((d) => d.tree), backgroundColor: '#ef4444', stack: 'a' },
                  ],
                }}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  scales: {
                    x: { ticks: { font: { size: 11 } }, grid: { display: true } },
                    y: { beginAtZero: true },
                  },
                }}
              />
            </div>
          </div>

          <div className="mb-1">
            <CopyTag label="{{sm_stand_type_by_hierarchy}}" value="{{sm_stand_type_by_hierarchy}}" variant="variable" />
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.hierarchy')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.regeneration')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.sapling')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.pole')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.tree')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.total')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.regenerationPercent')}</th>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.status')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {hierarchyData.map((row, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium">{getHierarchyPath(row)}</td>
                    <td className="px-3 py-2 text-right">{row.regeneration}</td>
                    <td className="px-3 py-2 text-right">{row.sapling}</td>
                    <td className="px-3 py-2 text-right">{row.pole}</td>
                    <td className="px-3 py-2 text-right">{row.tree}</td>
                    <td className="px-3 py-2 text-right font-medium">{row.total}</td>
                    <td className="px-3 py-2 text-right">{row.regeneration_percent}%</td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-1 rounded-full text-xs font-semibold ${getStatusColor(row.structure_status)}`}>
                        {row.structure_status}
                      </span>
                    </td>
                  </tr>
                ))}
                <tr className="bg-gray-100 font-semibold">
                  <td className="px-3 py-2">{t('treeMapping.col.total')}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.regeneration || 0), 0)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.sapling || 0), 0)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.pole || 0), 0)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.tree || 0), 0)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.total || 0), 0)}</td>
                  <td className="px-3 py-2 text-right">-</td>
                  <td className="px-3 py-2">-</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
