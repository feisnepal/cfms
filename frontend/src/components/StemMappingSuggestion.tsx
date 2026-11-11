/**
 * Where to do stem mapping when shelterwood is the chosen system (owner rule, 2026-10-12).
 *
 * The units of the shelterwood series are compared on the field inventory: trees and volume per hectare, kept apart, for 10-40 cm, 10 cm and
 * above, and 40 cm and above. The unit with the highest volume of trees of 40 cm and above is marked as the suggestion. Shown only when a
 * felling series is managed by shelterwood; otherwise it renders nothing.
 */
import { useEffect, useState } from 'react';
import { sfmApi, type StemMappingSuggestion as Suggestion, type StemSuggestionRange } from '../services/api';
import { useT } from '../i18n/hooks';
import { formatDecimal, formatNumber } from '../i18n/numberFormat';

function RangeHeads({ t }: { t: (k: string) => string }) {
  return (
    <>
      <th className="px-2 py-1 text-right border-l">{t('stemSuggestion.trees')}</th>
      <th className="px-2 py-1 text-right">{t('stemSuggestion.volume')}</th>
    </>
  );
}

export default function StemMappingSuggestion({ calculationId, reloadKey = 0 }: { calculationId: string; reloadKey?: number }) {
  const t = useT();
  const [data, setData] = useState<Suggestion | null>(null);

  useEffect(() => {
    let cancelled = false;
    sfmApi
      .getStemMappingSuggestion(calculationId)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setData(null); // advisory: a failed read shows nothing rather than an error on the page
      });
    return () => {
      cancelled = true;
    };
  }, [calculationId, reloadKey]);

  if (!data?.applies) return null;

  const cell = (r: StemSuggestionRange | undefined | null) => (
    <>
      <td className="px-2 py-1 text-right border-l">{r ? formatNumber(Math.round(r.count_per_ha)) : '—'}</td>
      <td className="px-2 py-1 text-right">{r ? formatDecimal(r.volume_m3_per_ha, 1) : '—'}</td>
    </>
  );

  return (
    <section className="bg-white border rounded-lg p-4" data-testid="stem-mapping-suggestion">
      <h3 className="text-base font-semibold text-gray-900">{t('stemSuggestion.title')}</h3>
      <p className="mt-1 text-sm text-gray-600">{t('stemSuggestion.intro')}</p>
      {data.suggested ? (
        <p className="mt-2 text-sm font-medium text-green-800" data-testid="stem-suggestion-best">
          {t('stemSuggestion.best', { unit: data.suggested })}
        </p>
      ) : (
        <p className="mt-2 text-sm text-amber-700">{t('stemSuggestion.none')}</p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="min-w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-50 text-gray-700">
              <th rowSpan={2} className="px-2 py-1 text-left">{t('stemSuggestion.unit')}</th>
              <th rowSpan={2} className="px-2 py-1 text-right">{t('stemSuggestion.area')}</th>
              <th rowSpan={2} className="px-2 py-1 text-right">{t('stemSuggestion.plots')}</th>
              <th colSpan={2} className="px-2 py-1 text-center border-l">{t('stemSuggestion.range1040')}</th>
              <th colSpan={2} className="px-2 py-1 text-center border-l">{t('stemSuggestion.range10')}</th>
              <th colSpan={2} className="px-2 py-1 text-center border-l">{t('stemSuggestion.range40')}</th>
              <th rowSpan={2} className="px-2 py-1 text-left border-l">{t('stemSuggestion.status')}</th>
            </tr>
            <tr className="bg-gray-50 text-xs text-gray-600">
              <RangeHeads t={t} />
              <RangeHeads t={t} />
              <RangeHeads t={t} />
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr
                key={r.block_name}
                className={r.suggested ? 'bg-green-50 font-medium' : ''}
                data-testid={`stem-suggestion-row-${r.block_name}`}
                data-suggested={r.suggested ? 'true' : 'false'}
              >
                <td className="px-2 py-1">{r.block_name}</td>
                <td className="px-2 py-1 text-right">{r.area_ha != null ? formatDecimal(r.area_ha, 1) : '—'}</td>
                <td className="px-2 py-1 text-right">{formatNumber(r.plot_count)}</td>
                {cell(r.ranges?.from10_to40)}
                {cell(r.ranges?.from10)}
                {cell(r.ranges?.from40)}
                <td className="px-2 py-1 border-l">
                  {r.suggested && (
                    <span className="inline-block rounded bg-green-600 px-2 py-0.5 text-xs text-white">{t('stemSuggestion.suggested')}</span>
                  )}{' '}
                  {r.stem_mapped && <span className="text-xs text-gray-600">{t('stemSuggestion.mapped')}</span>}
                  {!r.has_inventory && <span className="text-xs text-amber-700">{t('stemSuggestion.noInventory')}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
