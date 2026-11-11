/**
 * One species list, two labelled groups.
 *
 * POLICY_SPECIES_PLAN P3 / D5, on the owner's instruction that they want *both*
 * views: every species named individually, and the ones not on the policy list
 * gathered under a visible "Other species" heading rather than hidden.
 *
 * Why one table and not two
 * -------------------------
 * A separate "Other species" table answers "what is in Other?" only if the
 * reader goes looking for a second thing. Putting the group in the same reading
 * flow, directly under the species it sits beside, answers it without being
 * found. The owner raised exactly this: a report that summarises a group without
 * naming it is the problem, not the solution.
 *
 * The rules this encodes
 * ----------------------
 * - **Nothing is hidden.** Every recorded species gets a row, in one of the two
 *   groups. A species the list does not name is precisely what "Other" is for.
 * - **The Other group is never collapsed.** It is the transparency section.
 *   Collapsing it would re-create the problem this feature exists to fix. (The
 *   <5 collapse for the *reference* group is a prominence rule and is not
 *   implemented here -- see P4.)
 * - **A `% of total` column and a totals row**, because on the owner's forest
 *   "Other" is 55.9% of stems. That has to be visible without arithmetic, or a
 *   reader cannot tell whether Other is a rounding error or the majority of the
 *   forest.
 * - **Sorted by stems descending within each group**, so the eye lands on what
 *   dominates.
 * - **A genus capture is labelled.** A species-level list entry matching its
 *   genus directly carries no marker; a species that got in *because* a genus
 *   entry spoke for it shows which entry did it. Without that, the asymmetric
 *   rule is invisible and an invisible rule is one nobody can audit.
 */
import React from 'react';
import { useT } from '../../i18n/hooks';
import { formatDecimal, formatNumber } from '../../i18n/numberFormat';

export type PolicyGroup = 'reference' | 'other';

/**
 * A reference group of this size or fewer collapses to a summary line (D5).
 *
 * Four, not five: the owner said "at least five" meaning "below five is not worth
 * a section of its own", so the boundary sits at the point where a table stops
 * being a list and starts being a headline.
 */
export const REFERENCE_COLLAPSE_MAX = 4;

export type SpeciesPolicyRow = {
  species_scientific?: string | null;
  species_local?: string | null;
  classification?: PolicyGroup | string | null;
  matched_by?: string | null;
  matched_by_level?: string | null;
  [measure: string]: unknown;
};

export type SpeciesPolicyMeasure = {
  /** Key on each row. */
  key: string;
  /** i18n token for the column heading. */
  labelKey: string;
  /** Decimal places, or null for a locale-grouped integer. */
  decimals: number | null;
  /** Rendered bolder, for the column a reader scans first (usually volume). */
  emphasis?: boolean;
};

type Props = {
  rows: SpeciesPolicyRow[];
  measures: SpeciesPolicyMeasure[];
  /** The measure the "% of total" column and the sort are based on. */
  shareKey: string;
  /**
   * The heading, rendered by the caller.
   *
   * Passed as a node rather than a token key on purpose. The conventions this
   * file has to satisfy are enforced by *source-scanning* the parent:
   * `tableBasis.test.ts` looks for the parent's `totalInventory.<key>` call and
   * then a basis badge within 900 characters, and
   * `fieldInventoryResultsTables.test.tsx` asserts every report token the old
   * component owned still appears in its source. If the child owned the title,
   * the parent would stop looking up the token at all and both conventions
   * would silently stop being checked.
   *
   * So the parent keeps its tokens and its badge, exactly as it does for every
   * other table, and this component owns only the row and group mechanics.
   */
  title: React.ReactNode;
  /** The basis sentence under the heading, also rendered by the caller. */
  note?: React.ReactNode;
  /** i18n token for the "% of total" column heading. */
  shareLabelKey?: string;
  /** Test hook, so a test can target one instance among several on the page. */
  testId?: string;
};

const isReference = (r: SpeciesPolicyRow) => r.classification === 'reference';
const isOther = (r: SpeciesPolicyRow) => r.classification === 'other';

const num = (v: unknown): number => {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n : 0;
};

const fmtCell = (v: unknown, decimals: number | null): string => {
  if (v == null) return '—';
  return decimals === null
    ? formatNumber(Math.round(num(v)))
    : formatDecimal(num(v), decimals);
};

export const SpeciesPolicyTable: React.FC<Props> = ({
  rows,
  measures,
  shareKey,
  title,
  note,
  shareLabelKey = 'policySpecies.shareOfTotal',
  testId = 'species-policy-table',
}) => {
  const t = useT();

  const referenceRows = rows.filter(isReference);
  const otherRows = rows.filter(isOther);
  // Anything the backend did not classify is shown as "other" rather than
  // dropped. A row that vanishes from the report is worse than one that lands in
  // the group meant for "species the list does not name".
  const unclassified = rows.filter((r) => !isReference(r) && !isOther(r));
  const other = [...otherRows, ...unclassified];

  const totalShare = rows.reduce((s, r) => s + num(r[shareKey]), 0);

  const byStemsDesc = (a: SpeciesPolicyRow, b: SpeciesPolicyRow) =>
    num(b[shareKey]) - num(a[shareKey]);

  const groupTotals = (subset: SpeciesPolicyRow[]) => {
    const out: Record<string, number> = { __share: 0 };
    for (const m of measures) out[m.key] = 0;
    for (const r of subset) {
      out.__share += num(r[shareKey]);
      for (const m of measures) out[m.key] += num(r[m.key]);
    }
    return out;
  };

  const refTotals = groupTotals(referenceRows);
  const othTotals = groupTotals(other);
  const allTotals = groupTotals(rows);

  const pct = (part: number) =>
    totalShare > 0 ? `${formatDecimal((part / totalShare) * 100, 1)}%` : '—';

  const measureCells = (source: Record<string, number>) =>
    measures.map((m) => (
      <td
        key={m.key}
        className={`px-3 py-2 text-sm text-right ${m.emphasis ? 'font-medium' : ''}`}
      >
        {fmtCell(source[m.key], m.decimals)}
      </td>
    ));

  const shareCell = (value: number) => (
    <td className="px-3 py-2 text-sm text-right text-gray-500">
      {pct(value)}
    </td>
  );

  const Divider: React.FC<{ group: PolicyGroup; subset: SpeciesPolicyRow[]; totals: Record<string, number> }> = ({
    group,
    subset,
    totals,
  }) => (
    <tr data-testid={`${testId}-${group}-divider`} className="bg-slate-100">
      <td colSpan={4} className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-700">
        {t(group === 'reference' ? 'policySpecies.referenceDivider' : 'policySpecies.otherDivider', {
          count: subset.length,
          total: rows.length,
          share: pct(totals.__share),
        })}
      </td>
      <td className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-right text-slate-700">
        {fmtCell(totals.__share, shareMeasureDecimals(measures, shareKey))}
      </td>
      {measures.map((m) => (
        <td key={m.key} className="px-3 py-2 text-xs font-semibold text-right text-slate-700">
          {fmtCell(totals[m.key], m.decimals)}
        </td>
      ))}
    </tr>
  );

  const BodyRow: React.FC<{ row: SpeciesPolicyRow; index: number }> = ({ row, index }) => (
    <tr className="hover:bg-gray-50" data-testid={`${testId}-row`}>
      <td className="px-3 py-2 text-sm text-gray-400">{index + 1}</td>
      <td className="px-3 py-2 text-sm text-gray-900 italic">
        {row.species_scientific || '—'}
        {row.matched_by_level === 'genus' && (
          <span
            className="ml-2 align-middle text-[10px] font-normal not-italic text-emerald-700 bg-emerald-50 border border-emerald-200 rounded px-1 py-0.5"
            title={t('policySpecies.matchedByGenus', { entry: row.matched_by ?? '' })}
          >
            {t('policySpecies.viaGenus', { entry: row.matched_by ?? '' })}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-sm text-gray-700">{row.species_local || '—'}</td>
      <td className="px-3 py-2 text-sm text-right">{fmtCell(row[shareKey], shareMeasureDecimals(measures, shareKey))}</td>
      {shareCell(num(row[shareKey]))}
      {measures.map((m) => (
        <td
          key={m.key}
          className={`px-3 py-2 text-sm text-right ${m.emphasis ? 'font-medium' : ''}`}
        >
          {fmtCell(row[m.key], m.decimals)}
        </td>
      ))}
    </tr>
  );

  const hasReference = referenceRows.length > 0;
  const hasOther = other.length > 0;

  /* D5, applied to the headline group only.
   *
   * The owner's instinct was "at least five species" before a table is worth
   * showing. That is right about *prominence* and wrong as a *data* rule: a hard
   * floor would hide species that were actually recorded. So a short reference
   * group collapses to one summary line the reader can expand, and no species is
   * ever removed from the response or from the totals.
   *
   * The Other group never collapses. It is the transparency section, and its
   * whole purpose is to be read -- collapsing it would re-create the problem
   * this feature was built to fix.
   */
  const collapsible = hasReference && referenceRows.length <= REFERENCE_COLLAPSE_MAX;
  const [expanded, setExpanded] = React.useState(false);
  const showReferenceRows = !collapsible || expanded;
  const colCount = 5 + measures.length;

  return (
    <div className="bg-white rounded-lg shadow p-6" data-testid={testId}>
      <h4 className="text-lg font-semibold text-gray-900 mb-2">{title}</h4>
      {note && <div className="mb-4">{note}</div>}
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">#</th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                {t('totalInventory.scientificName')}
              </th>
              <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                {t('totalInventory.localName')}
              </th>
              <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                {t('totalInventory.totalCount')}
              </th>
              <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">
                {t(shareLabelKey)}
              </th>
              {measures.map((m) => (
                <th
                  key={m.key}
                  className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase"
                >
                  {t(m.labelKey)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {/* A forest with species but none on the list gets a sentence saying so.
                A blank section, or a silent omission, would leave the reader
                wondering whether the table is broken. */}
            {!hasReference && rows.length > 0 && (
              <tr data-testid={`${testId}-no-reference`}>
                <td colSpan={colCount} className="px-3 py-3 text-sm text-gray-500 italic">
                  {t('policySpecies.noReferenceSpecies')}
                </td>
              </tr>
            )}

            {/* A short reference group collapses to one line. The button toggles
                rather than links somewhere, because the content is already on the
                page -- this is prominence, not navigation. */}
            {collapsible && !showReferenceRows && (
              <tr data-testid={`${testId}-reference-collapsed`} className="bg-slate-100">
                <td colSpan={4} className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-700">
                  {t('policySpecies.referenceCollapsed', {
                    count: referenceRows.length,
                    total: rows.length,
                    share: pct(refTotals.__share),
                  })}
                </td>
                <td className="px-3 py-2 text-xs font-semibold text-right text-slate-700">
                  {fmtCell(refTotals.__share, shareMeasureDecimals(measures, shareKey))}
                </td>
                {measures.map((m) => (
                  <td key={m.key} className="px-3 py-2 text-xs font-semibold text-right text-slate-700">
                    {fmtCell(refTotals[m.key], m.decimals)}
                  </td>
                ))}
              </tr>
            )}

            {/* Reference species first, individually. */}
            {hasReference && showReferenceRows &&
              [...referenceRows].sort(byStemsDesc).map((row, i) => (
                <BodyRow key={`ref-${i}`} row={row} index={i} />
              ))}

            {/* Then the labelled boundary. Both dividers are rendered only for a
                group that has something in it, so a forest with no Other species
                does not get a divider announcing zero of them, and a collapsed
                reference group is summarised above rather than divided. */}
            {hasReference && showReferenceRows && (
              <Divider group="reference" subset={referenceRows} totals={refTotals} />
            )}
            {hasOther && (
              <Divider group="other" subset={other} totals={othTotals} />
            )}

            {/* Then every remaining species, named, never collapsed. */}
            {hasOther &&
              [...other].sort(byStemsDesc).map((row, i) => (
                <BodyRow key={`oth-${i}`} row={row} index={i} />
              ))}

            {/* The collapse control, after the group it controls. */}
            {collapsible && showReferenceRows && (
              <tr data-testid={`${testId}-reference-expand-row`}>
                <td colSpan={colCount} className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setExpanded(false)}
                    data-testid={`${testId}-reference-collapse`}
                    className="text-xs font-semibold uppercase tracking-wide text-slate-600 hover:text-slate-900 underline"
                  >
                    {t('policySpecies.hideReference')}
                  </button>
                </td>
              </tr>
            )}
            {collapsible && !showReferenceRows && (
              <tr data-testid={`${testId}-reference-expand-control`}>
                <td colSpan={colCount} className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setExpanded(true)}
                    data-testid={`${testId}-reference-expand`}
                    className="text-xs font-semibold uppercase tracking-wide text-emerald-700 hover:text-emerald-900 underline"
                  >
                    {t('policySpecies.showReference', { count: referenceRows.length })}
                  </button>
                </td>
              </tr>
            )}

            <tr data-testid={`${testId}-totals`} className="bg-blue-50 font-bold text-blue-900">
              <td className="px-3 py-2 text-sm" colSpan={3}>
                {t('policySpecies.totalsRow', { species: rows.length })}
              </td>
              <td className="px-3 py-2 text-sm text-right">
                {fmtCell(allTotals.__share, shareMeasureDecimals(measures, shareKey))}
              </td>
              <td className="px-3 py-2 text-sm text-right">
                {totalShare > 0 ? '100.0%' : '—'}
              </td>
              {measureCells(allTotals)}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-gray-500">{t('policySpecies.groupNote')}</p>
    </div>
  );
};

/** The share measure's own decimals, so the stem column matches its measure spec. */
function shareMeasureDecimals(measures: SpeciesPolicyMeasure[], shareKey: string): number | null {
  const found = measures.find((m) => m.key === shareKey);
  return found ? found.decimals : 0;
}
