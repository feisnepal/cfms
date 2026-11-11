/**
 * CFMG harvest classes, per compartment and for the forest.
 *
 * DBH_SSOT_PLAN P2b rendered the data, P3 puts it on screen. The grouping itself
 * is the server's (`app/core/harvest_groups.py`), reached through
 * `get_total_inventory`; nothing here recomputes it. That is deliberate twice
 * over: the OP and this table must not be able to disagree, and a second
 * implementation in TypeScript is exactly how they would.
 *
 * Three groups, and Regeneration is shown rather than dropped (D12). It is
 * marked non-harvestable because it *looks* like the other two in a table of
 * stems, and a reader who does not notice the marker will read 0-10 cm as
 * harvestable. On the owner's forest it is 90,418 stems against 9,300 in the two
 * harvestable groups combined, so it is the largest group on the page.
 *
 * Every figure is **per hectare**. The absolute figures already exist in the DBH
 * class tables; multiplying again here would double-count, and this table sits
 * beside the three-stage per-hectare section for that reason.
 */
import React from 'react';
import { useT } from '../../i18n/hooks';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';

type Group = {
  group_key: string;
  block_name?: string | null;
  block_count?: number;
  dbh_classes?: string[];
  harvestable?: boolean;
  count_per_ha?: number;
  timber_m3_per_ha?: number;
  firewood_m3_per_ha?: number;
  total_volume_m3_per_ha?: number;
};

const GROUP_LABEL: Record<string, string> = {
  regeneration: 'harvestGroup.regeneration',
  advance_growth: 'harvestGroup.advanceGrowth',
  mature_tree: 'harvestGroup.matureTree',
};

const num = (v: unknown): number => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

export const HarvestGroupTable: React.FC<{
  blocks: any[];
  /** The forest rollup, which lives on `forest_totals` -- not on any block. */
  forestGroups?: Group[];
}> = ({ blocks, forestGroups }) => {
  const t = useT();

  const rows: Array<{ block: string; group: Group }> = [];
  for (const b of blocks ?? []) {
    for (const g of (b?.harvest_class_groups ?? []) as Group[]) {
      rows.push({ block: b?.block_name ?? '', group: g });
    }
  }
  const forest: Group[] = forestGroups ?? [];

  if (!rows.length && !forest.length) return null;

  const groupCell = (g: Group) => (
    <span className="inline-flex items-center gap-2">
      <span>{t(GROUP_LABEL[g.group_key] ?? g.group_key)}</span>
      {!g.harvestable && (
        <span className="text-[10px] font-bold uppercase tracking-wide text-amber-800 bg-amber-100 border border-amber-300 rounded px-1.5 py-0.5">
          {t('harvestGroup.notHarvestable')}
        </span>
      )}
    </span>
  );

  const classCell = (g: Group) => (
    <span className="text-xs text-gray-500 font-mono">
      {(g.dbh_classes ?? []).join(' · ')}
    </span>
  );

  const measureCells = (g: Group) => (
    <>
      <td className="px-3 py-2 text-sm text-right">{formatNumber(Math.round(num(g.count_per_ha)))}</td>
      <td className="px-3 py-2 text-sm text-right">{formatDecimal(num(g.timber_m3_per_ha), 2)}</td>
      <td className="px-3 py-2 text-sm text-right">{formatDecimal(num(g.firewood_m3_per_ha), 2)}</td>
      <td className="px-3 py-2 text-sm text-right font-medium">
        {formatDecimal(num(g.total_volume_m3_per_ha), 2)}
      </td>
    </>
  );

  return (
    <div className="bg-white rounded-lg shadow p-6" data-testid="harvest-group-table">
      <h4 className="text-lg font-semibold text-gray-900 mb-2">
        {t('harvestGroup.title')}
      </h4>
      <p className="text-xs text-gray-500 mb-4">{t('harvestGroup.note')}</p>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                {t('harvestGroup.block')}
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                {t('harvestGroup.dbhClasses')}
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase" />
              <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                {t('harvestGroup.countPerHa')}
              </th>
              <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                {t('harvestGroup.timberPerHa')}
              </th>
              <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                {t('harvestGroup.firewoodPerHa')}
              </th>
              <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                {t('harvestGroup.volumePerHa')}
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {rows.map(({ block, group }, i) => (
              <tr
                key={`${block}-${group.group_key}-${i}`}
                className="hover:bg-gray-50"
                data-testid="harvest-group-row"
              >
                <td className="px-3 py-2 text-sm text-gray-900">{block}</td>
                <td className="px-3 py-2 text-sm">{classCell(group)}</td>
                <td className="px-3 py-2 text-sm">{groupCell(group)}</td>
                {measureCells(group)}
              </tr>
            ))}
            {forest.map((g, i) => (
              <tr
                key={`forest-${g.group_key}-${i}`}
                className="bg-blue-50 font-bold text-blue-900"
                data-testid="harvest-group-forest"
              >
                <td className="px-3 py-2 text-sm" colSpan={2}>
                  {t('harvestGroup.forestTotal')}
                </td>
                <td className="px-3 py-2 text-sm">{groupCell(g)}</td>
                {measureCells(g)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
