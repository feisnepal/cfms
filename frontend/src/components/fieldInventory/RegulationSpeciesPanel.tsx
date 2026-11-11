/**
 * Species by the regulation's groups: the 21 designated species named, every other species as "Other species" (Terai or Hill).
 *
 * Shows the very tables, charts and narration the Operational Plan prints (GET .../regulation-species uses the OP's own
 * builders), each with the placeholder that places it in a template, so a reader can look at a result and copy its token.
 * The all / classified-only switch only changes what is shown here; both sets have their own placeholders (`fi_reg_*`,
 * `fi_regc_*`) and nothing is saved.
 */
import React from 'react';
import { Bar } from 'react-chartjs-2';
import '../../utils/chartSetup';
import { useT } from '../../i18n/hooks';
import { formatDecimal } from '../../i18n/numberFormat';
import { fieldInventoryApi } from '../../services/api';
import CopyTag from '../DetailDescription/CopyTag';

type VariantName = 'all' | 'classified';
type Table = { key: string; token: string; label: string; headers: string[]; rows: Record<string, unknown>[] };
type Chart = { key: string; token: string; title: string; y_label: string; labels: string[]; values: number[] };
type Variant = { prefix: string; narration: { token: string; text: string | null }; tables: Table[]; charts: Chart[] };
type View = { region: 'terai' | 'hill'; variants: Record<VariantName, Variant> };

const header = (h: string) => h.replace(/_/g, ' ');
const isTotal = (r: Record<string, unknown>) => Object.values(r).some((v) => v === 'जम्मा');

const cell = (v: unknown): string => {
  if (v === null || v === undefined || v === '') return '-';
  if (typeof v === 'number') return formatDecimal(v, Number.isInteger(v) ? 0 : 2);
  return String(v);
};

const TableBlock: React.FC<{ table: Table }> = ({ table }) => {
  if (!table.rows.length) return null;
  return (
    <div className="mb-6" data-testid={`reg-species-table-${table.key}`}>
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <h5 className="text-sm font-semibold text-gray-800">{table.label}</h5>
        <CopyTag label={table.token} value={table.token} />
      </div>
      <div className="overflow-x-auto max-h-96 overflow-y-auto border border-gray-200 rounded">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {table.headers.map((h) => (
                <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-500">{header(h)}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {table.rows.map((r, i) => (
              <tr key={i} className={isTotal(r) ? 'bg-gray-50 font-semibold' : undefined}>
                {table.headers.map((h) => (
                  <td key={h} className="px-3 py-1.5 text-gray-700 whitespace-nowrap">{cell(r[h])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const RegulationSpeciesPanel: React.FC<{ fieldInventoryId: string }> = ({ fieldInventoryId }) => {
  const t = useT();
  const [view, setView] = React.useState<View | null>(null);
  const [failed, setFailed] = React.useState(false);
  const [which, setWhich] = React.useState<VariantName>('all');

  React.useEffect(() => {
    let live = true;
    setFailed(false);
    fieldInventoryApi
      .getRegulationSpecies(fieldInventoryId)
      .then((v: View) => live && setView(v))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [fieldInventoryId]);

  if (failed) return <p className="text-sm text-red-600">{t('totalInventory.regSpLoadFailed')}</p>;
  if (!view) return null;
  const v = view.variants[which];
  if (!v.tables.some((x) => x.rows.length)) return <p className="text-sm text-gray-500">{t('totalInventory.regSpEmpty')}</p>;
  const region = t(view.region === 'terai' ? 'totalInventory.regSpTerai' : 'totalInventory.regSpHill');

  return (
    <div className="bg-white rounded-lg shadow p-6" data-testid="regulation-species-panel">
      <h4 className="text-lg font-semibold text-gray-900 mb-1">{t('totalInventory.regSpTitle')}</h4>
      <p className="text-xs text-gray-500 mb-3">{t('totalInventory.regSpNote', { region })}</p>
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="inline-flex rounded-md border border-gray-300 overflow-hidden" role="group">
          {(['all', 'classified'] as VariantName[]).map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setWhich(n)}
              aria-pressed={which === n}
              className={`px-3 py-1.5 text-sm ${which === n ? 'bg-green-700 text-white' : 'bg-white text-gray-700 hover:bg-gray-50'}`}
            >
              {t(n === 'all' ? 'totalInventory.regSpAll' : 'totalInventory.regSpClassified')}
            </button>
          ))}
        </div>
        {which === 'all' && <span className="text-xs text-gray-600">{t('totalInventory.regSpRegion', { region })}</span>}
        <span className="text-xs text-gray-400">{t('totalInventory.regSpClickCopy')}</span>
      </div>

      {v.narration.text && (
        <div className="mb-5 p-3 bg-gray-50 rounded border border-gray-200">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="text-sm font-semibold text-gray-800">{t('totalInventory.regSpNarration')}</span>
            <CopyTag label={v.narration.token} value={v.narration.token} variant="section" />
          </div>
          <p className="text-sm text-gray-700">{v.narration.text}</p>
        </div>
      )}

      {v.tables.slice(0, 3).map((x) => <TableBlock key={x.key} table={x} />)}

      {v.charts.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
          {v.charts.map((c) => (
            <div key={c.key} className="border border-gray-200 rounded p-3" data-testid={`reg-species-chart-${c.key}`}>
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className="text-sm font-semibold text-gray-800">{c.title}</span>
                <CopyTag label={c.token} value={c.token} />
              </div>
              <Bar
                data={{ labels: c.labels, datasets: [{ label: c.y_label, data: c.values, backgroundColor: '#15803d' }] }}
                options={{ responsive: true, plugins: { legend: { display: false } } }}
              />
            </div>
          ))}
        </div>
      )}

      <h5 className="text-sm font-bold text-gray-900 mb-2">{t('totalInventory.regSpUnit')}</h5>
      {v.tables.slice(3).map((x) => <TableBlock key={x.key} table={x} />)}
    </div>
  );
};

export default RegulationSpeciesPanel;
