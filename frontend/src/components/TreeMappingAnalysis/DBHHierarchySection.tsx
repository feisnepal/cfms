/** DBH-class distribution chart across hierarchy levels. */
import { getHierarchyPath, truncateLabel } from './hierarchyUtils';
import CopyTag from '../DetailDescription/CopyTag';
import { useT } from '../../i18n/hooks';
import '../../utils/chartSetup';

const COLORS = ['#22c55e', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#f97316'];

interface Props {
  data: any[];
  hierRemarkData?: any[];
  collapsed?: boolean;
  onToggle?: () => void;
}

export function DBHHierarchySection({ data, hierRemarkData, collapsed, onToggle }: Props) {
  const t = useT();
  if (!data || data.length === 0) return null;

  // Build lookup: key = hierarchy+dbh_class -> { mother, felling }
  const remarkLookup: Record<string, { mother: number; felling: number }> = {};
  (hierRemarkData || []).forEach((row: any) => {
    const key = `${getHierarchyPath(row)}|${row.dbh_class}`;
    if (!remarkLookup[key]) remarkLookup[key] = { mother: 0, felling: 0 };
    if (row.remark === 'Mother Tree') remarkLookup[key].mother = row.tree_count;
    else if (row.remark === 'Felling Tree') remarkLookup[key].felling = row.tree_count;
  });

  const allClasses = [...new Set(data.map(r => r.dbh_class))];

  return (
    <div className="bg-white rounded-lg shadow overflow-hidden">
      <div
        className="flex justify-between items-center px-6 py-4 border-b cursor-pointer hover:bg-gray-50"
        onClick={onToggle}
      >
        <h3 className="text-lg font-semibold">{t('treeMapping.dbh.title')}
          <CopyTag label="{{section:sm_dbh_narration}}" value="{{section:sm_dbh_narration}}" variant="section" />
        </h3>
        <span className="text-gray-400">{collapsed ? '▶' : '▼'}</span>
      </div>
      {!collapsed && (
        <div className="p-6">
          <div className="mb-1">
            <CopyTag label="{{sm_dbh_by_hierarchy}}" value="{{sm_dbh_by_hierarchy}}" variant="variable" />
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.hierarchy')}</th>
                  <th className="px-3 py-2 text-left">{t('treeMapping.col.dbhClass')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.totalTrees')}</th>
                  <th className="px-3 py-2 text-right bg-green-50">{t('treeMapping.col.motherTrees')}</th>
                  <th className="px-3 py-2 text-right bg-red-50">{t('treeMapping.col.fellingTrees')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.timber')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.firewood')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.grossVolume')}</th>
                  <th className="px-3 py-2 text-right">{t('treeMapping.col.levelPercent')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {data.map((row, idx) => {
                  const key = `${getHierarchyPath(row)}|${row.dbh_class}`;
                  const rk = remarkLookup[key];
                  return (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-3 py-2">{getHierarchyPath(row)}</td>
                      <td className="px-3 py-2 font-medium">{row.dbh_class}</td>
                      <td className="px-3 py-2 text-right font-medium">{row.tree_count}</td>
                      <td className="px-3 py-2 text-right text-green-600 bg-green-50">{rk?.mother || 0}</td>
                      <td className="px-3 py-2 text-right text-red-600 bg-red-50">{rk?.felling || 0}</td>
                      <td className="px-3 py-2 text-right">{row.timber_m3}</td>
                      <td className="px-3 py-2 text-right">{row.firewood_m3}</td>
                      <td className="px-3 py-2 text-right">{row.gross_volume_m3}</td>
                      <td className="px-3 py-2 text-right">{row.hierarchy_percent}%</td>
                    </tr>
                  );
                })}
                <tr className="bg-gray-100 font-semibold">
                  <td className="px-3 py-2" colSpan={2}>{t('treeMapping.col.total')}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + r.tree_count, 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right text-green-700 bg-green-50">{Object.values(remarkLookup).reduce((s, r) => s + r.mother, 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right text-red-700 bg-red-50">{Object.values(remarkLookup).reduce((s, r) => s + r.felling, 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.timber_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.firewood_m3 || 0), 0).toFixed(2)}</td>
                  <td className="px-3 py-2 text-right">{data.reduce((s, r) => s + (r.gross_volume_m3 || 0), 0).toFixed(2)}</td>
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
