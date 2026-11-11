/** Volume (growing stock) bar chart broken down by hierarchy level. */
import { Bar } from 'react-chartjs-2';
import { getHierarchyPath, truncateLabel } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';

interface Props {
  hierarchyData: any[];
  topSpeciesData: any[];
  collapsed?: boolean;
  onToggle?: () => void;
}

export function VolumeHierarchySection({ hierarchyData, topSpeciesData, collapsed, onToggle }: Props) {
  const t = useT();
  if (!hierarchyData || hierarchyData.length === 0) return null;

  const chartData = hierarchyData.map(row => ({
    name: truncateLabel(getHierarchyPath(row)),
    stem: row.stem_volume_m3,
    branch: row.branch_volume_m3,
  }));

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold">{t('treeMapping.volume.title')}
          <CopyTag label="{{section:sm_volume_narration}}" value="{{section:sm_volume_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          <div className="mb-6">
            <h4 className="font-medium mb-3">{t('treeMapping.volume.composition')}
              <CopyTag label="{{chart:sm_volume_bar}}" value="{{chart:sm_volume_bar}}" variant="variable" />
            </h4>
            <div style={{ width: '100%', height: 300 }}>
              <Bar
                height={300}
                data={{
                  labels: chartData.map((d) => d.name),
                  datasets: [
                    { label: t('treeMapping.col.stemVolume'), data: chartData.map((d) => d.stem), backgroundColor: '#22c55e', stack: 'a' },
                    { label: t('treeMapping.col.branchVolume'), data: chartData.map((d) => d.branch), backgroundColor: '#3b82f6', stack: 'a' },
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
            <CopyTag label="{{sm_volume_by_hierarchy}}" value="{{sm_volume_by_hierarchy}}" variant="variable" />
          </div>
          <div className="overflow-x-auto mb-6">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.hierarchy')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.stemVolume')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.branchVolume')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.grossVolume')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.netVolume')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.firewood')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.firewoodChatta')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {hierarchyData.map((row, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium">{getHierarchyPath(row)}</td>
                    <td className="px-3 py-2 text-right">{row.stem_volume_m3}</td>
                    <td className="px-3 py-2 text-right">{row.branch_volume_m3}</td>
                    <td className="px-3 py-2 text-right font-medium">{row.total_volume_m3}</td>
                    <td className="px-3 py-2 text-right">{row.net_volume_m3}</td>
                    <td className="px-3 py-2 text-right">{row.firewood_m3}</td>
                    <td className="px-3 py-2 text-right">{row.firewood_chatta}</td>
                  </tr>
                ))}
                <tr className="bg-gray-100 font-semibold">
                  <td className="px-3 py-2">{t('treeMapping.col.total')}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.stem_volume_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.branch_volume_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.total_volume_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.net_volume_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.firewood_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{hierarchyData.reduce((s, r) => s + (r.firewood_chatta || 0), 0).toFixed(2)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {topSpeciesData && topSpeciesData.length > 0 && (
            <div>
              <h4 className="font-medium mb-3">{t('treeMapping.volume.topSpecies')}
                <CopyTag label="{{sm_top_species_by_volume}}" value="{{sm_top_species_by_volume}}" variant="variable" />
              </h4>
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-3 py-2 text-left">{t('treeMapping.col.species')}</th>
                    <th className="px-3 py-2 text-left">{t('treeMapping.col.localName')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.grossVolume')}</th>
                    <th className="px-3 py-2 text-right">{t('treeMapping.col.percent')}</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {topSpeciesData.map((row, idx) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium">{row.species}</td>
                      <td className="px-3 py-2">{row.local_name}</td>
                      <td className="px-3 py-2 text-right">{row.total_volume_m3}</td>
                      <td className="px-3 py-2 text-right">{row.percent}%</td>
                    </tr>
                  ))}
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-3 py-2" colSpan={2}>{t('treeMapping.col.total')}</td>
                    <td className="px-3 py-2 text-right">{topSpeciesData.reduce((s, r) => s + (r.total_volume_m3 || 0), 0).toFixed(2)}</td>
                    <td className="px-3 py-2 text-right">100%</td>
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
