/** Bar-chart breakdown of carbon stock by hierarchy level (compartment/block/stand type). */
import { Bar } from 'react-chartjs-2';
import { getHierarchyPath, truncateLabel } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';

interface Props {
  data: any[];
  collapsed?: boolean;
  onToggle?: () => void;
}

export function CarbonHierarchySection({ data, collapsed, onToggle }: Props) {
  const t = useT();
  if (!data || data.length === 0) return null;

  const chartData = data.map(row => ({
    name: truncateLabel(getHierarchyPath(row)),
    carbon: row.carbon_tc,
    co2: row.co2_tco2,
  }));

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold">{t('treeMapping.carbon.title')}
          <CopyTag label="{{section:sm_carbon_narration}}" value="{{section:sm_carbon_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          <div className="mb-6">
            <h4 className="text-sm font-medium text-gray-600 mb-2">{t('treeMapping.carbon.byHierarchy')}
              <CopyTag label="{{chart:sm_carbon_bar}}" value="{{chart:sm_carbon_bar}}" variant="variable" />
            </h4>
            <div style={{ width: '100%', height: 300 }}>
              <Bar
                height={300}
                data={{
                  labels: chartData.map((d) => d.name),
                  datasets: [
                    { label: 'Carbon (tC)', data: chartData.map((d) => d.carbon), backgroundColor: '#22c55e' },
                    { label: 'CO₂e (tCO₂)', data: chartData.map((d) => d.co2), backgroundColor: '#3b82f6' },
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
            <CopyTag label="{{sm_carbon_by_hierarchy}}" value="{{sm_carbon_by_hierarchy}}" variant="variable" />
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.hierarchy')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.grossVolumeRaw')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.weightedWoodDensity')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.agb')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.bgb')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.biomass')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.carbon')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.co2e')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data.map((row, idx) => (
                  <tr key={idx} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium">{getHierarchyPath(row)}</td>
                    <td className="px-3 py-2 text-right">{row.gross_volume_m3}</td>
                    <td className="px-3 py-2 text-right">{row.wood_density}</td>
                    <td className="px-3 py-2 text-right">{row.agb_t}</td>
                    <td className="px-3 py-2 text-right">{row.bgb_t}</td>
                    <td className="px-3 py-2 text-right">{row.biomass_t}</td>
                    <td className="px-3 py-2 text-right font-medium">{row.carbon_tc}</td>
                    <td className="px-3 py-2 text-right font-medium">{row.co2_tco2}</td>
                  </tr>
                ))}
                <tr className="bg-gray-100 font-semibold">
                  <td className="px-3 py-2">{t('treeMapping.col.total')}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.gross_volume_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">-</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.agb_t || 0), 0).toFixed(3)}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.bgb_t || 0), 0).toFixed(3)}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.biomass_t || 0), 0).toFixed(3)}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.carbon_tc || 0), 0).toFixed(3)}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.co2_tco2 || 0), 0).toFixed(3)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
