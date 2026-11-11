/**
 * Field Inventory Results -- the tables that were still only in the old
 * `TotalInventoryTab`.
 *
 * P5d splits Field Inventory into Upload Data / Forest Metadata / Results, and
 * Results already re-implements five of the old total-inventory tables against
 * the shared provider (`summary`, `speciesBreakdown`, `maiAahData`). This module
 * carries the rest, so that no `totalInventory.*` table is lost when
 * `TotalInventoryTab` is deleted in P5e:
 *
 *   summary : effective-area context, forest-wide grand total
 *   tables  : stock by species, species x DBH (block + forest-wide), DBH class
 *             absolute, MAI by species / by DBH, AAH by species / by DBH,
 *             economic valuation, sustainability index
 *
 * The old component owned its own copy of the inventory record, the multiplier
 * settings and the tree-cover/total-inventory fetches. That is exactly the
 * duplication D3 forbids, so all of it now lives in `useFieldInventoryData`;
 * this component only renders. The JSX below is lifted verbatim from the old
 * file, so the i18n keys, the `{{ti_*}}` / `{{section:ti_*_narration}}` report
 * tokens and the backend field names are unchanged -- the generated DOCX is
 * built server-side from its own section builders, so DOM order here is
 * cosmetic and the report is unaffected.
 */
import React from 'react';
import { Pie, Bar } from 'react-chartjs-2';
import '../../utils/chartSetup';
import { resolveClassLabel, useDbhClassConfig } from '../../hooks/useDbhClasses';
import { HarvestGroupTable } from './HarvestGroupTable';
import i18n from '../../i18n';
import { useT } from '../../i18n/hooks';
import { formatDecimal, formatNumber, parseLocaleNumber } from '../../i18n/numberFormat';
import { useFieldInventoryData, BlockRates } from './useFieldInventoryData';
import { SpeciesPolicyTable } from './SpeciesPolicyTable';
import { RegulationSpeciesPanel } from './RegulationSpeciesPanel';

/** Default economic rates (NPR) used until a rate is typed for a unit. */
const DEFAULT_BLOCK_RATES = { timber: 5000, fuelwood: 1500, carbon: 1500 };

/** Block/Compartment noun for the active language (dimension SSOT holds both). */
function dimensionUnit(labels: { unitLabelNp: string; unitLabel: string }): string {
  return i18n.language === 'ne' ? labels.unitLabelNp : labels.unitLabel;
}

/**
 * Shared table helpers. Lifted out of the old component so both exports below
 * use one definition instead of two copies.
 */
const useTotalsHelpers = () => {
  const t = useT();

  // P3: the class list comes from the API, not a bundled copy. The i18n
  // *key* still comes from the frontend map, so a super-admin translation edit
  // still renames the class; only the structure is the database's now.
  const dbhClasses = useDbhClassConfig('guideline_2061');
  const DBH_CLASS_CONFIG = React.useMemo(
    () =>
      dbhClasses.map((c) => ({
        key: c.key,
        label: resolveClassLabel(c, t, i18n.language === 'ne'),
      })),
    [dbhClasses, t]
  );

  const sortDbhClasses = (items: any[]): any[] =>
    [...items].sort((a, b) => {
      const getNum = (s: string): number => {
        const m = s.match(/(\d+)/);
        return m ? parseInt(m[1], 10) : 999;
      };
      return getNum(a.dbh_class) - getNum(b.dbh_class);
    });

  const computeBlockSubtotal = (block: any, field: string, isPerHa: boolean): number => {
    const data = isPerHa ? block.dbh_class_per_ha : block.dbh_class_totals;
    if (!data) return 0;
    return DBH_CLASS_CONFIG.reduce((sum, { key }) => {
      const d = data[key];
      return sum + (d ? Number(d[field] || 0) : 0);
    }, 0);
  };

  const fmt = (v: any, decimals: number = 2): string => formatDecimal(Number(v || 0), decimals);
  const fmtPH = (v: any): string => formatDecimal(Number(v || 0), 1);

  const CHART_COLORS = [
    '#4CAF50', '#2196F3', '#FF9800', '#9C27B0', '#F44336',
    '#00BCD4', '#FFEB3B', '#795548', '#607D8B', '#E91E63',
    '#3F51B5', '#009688', '#FF5722', '#CDDC39', '#03A9F4',
  ];

  const buildSpeciesChartData = (speciesList: any[]) => {
    if (!speciesList || speciesList.length === 0) return null;
    // A pie with 17 named slices is unreadable, so the tail is still lumped --
    // but the lump now says how many species it covers instead of reading as a
    // species called "Other". The species it swallowed are named in the caption
    // under the chart (`speciesChartTail`), so the bar is a summary the reader
    // can expand, not a place a species disappears. This was the same opacity the
    // species tables had, and it is the reason the tables now group explicitly.
    const topSpecies = speciesList.slice(0, 10);
    const tail = speciesList.slice(10);
    const otherVolume = tail.reduce((s: number, sp: any) => s + (sp.volume_m3 || 0), 0);
    const chartLabels = topSpecies.map((sp: any) => sp.species_local || sp.species_scientific || '—');
    const data = topSpecies.map((sp: any) => Math.round(sp.volume_m3 || 0));
    if (otherVolume > 0) {
      chartLabels.push(t('totalInventory.otherWithCount', { count: tail.length }));
      data.push(Math.round(otherVolume));
    }
    return { labels: chartLabels, datasets: [{ data, backgroundColor: CHART_COLORS.slice(0, chartLabels.length), borderWidth: 1 }] };
  };

  /** The names behind the lumped slice, so it is a summary and not a hiding place. */
  const speciesChartTailNames = (speciesList: any[]): string[] =>
    (speciesList || []).slice(10).map((sp: any) => sp.species_local || sp.species_scientific || '—');

  const buildBlockBarChartData = (blocks: any[]) => {
    if (!blocks || blocks.length === 0) return null;
    const chartLabels = blocks.map((b: any) => b.block_name);
    const growingStock = blocks.map((b: any) => b.total_growing_stock_m3 || 0);
    const mai = blocks.map((b: any) => b.total_mai_m3 || 0);
    const aah = blocks.map((b: any) => b.total_aah_m3 || 0);
    return {
      labels: chartLabels,
      datasets: [
        { label: t('totalInventory.growingStockM3'), data: growingStock, backgroundColor: '#4CAF50', borderColor: '#388E3C', borderWidth: 1 },
        { label: t('totalInventory.maiUnitYr'), data: mai, backgroundColor: '#2196F3', borderColor: '#1976D2', borderWidth: 1 },
        { label: t('totalInventory.aahUnitYr'), data: aah, backgroundColor: '#FF9800', borderColor: '#F57C00', borderWidth: 1 },
      ],
    };
  };

  /**
   * Per-species MAI and AAH, per block.
   *
   * The backend apportions a block's MAI and AAH across DBH classes by VOLUME
   * SHARE (`field_inventory.py`: `cls_mai_vol = mai_ha * class_vol / total_vol`,
   * and the same for AAH plus a count share for the tree tally). It does the same
   * split per species nowhere, so `block.mai_by_species` and `block.aah_by_species`
   * are never written and the two per-species tables could never render - the
   * keys the frontend guards on do not exist in any response.
   *
   * Rather than add a second backend apportionment that could disagree with the
   * first, this performs the SAME operation with species in place of class, from
   * the per-species per-hectare volumes the Results pane already loads via
   * `species-dbh-breakdown`. The shares are a true partition - measured on the
   * owner's forest, species volume/ha summed to 491.61 against the block's
   * 491.62 from `dbh_class_per_ha` - so the per-species figures sum back to the
   * block MAI and AAH, which is the property the tests assert.
   */
  const speciesGrowthByBlock = (
    blocks: any[],
    speciesRows: any[],
  ): Record<string, any[]> => {
    const out: Record<string, any[]> = {};
    if (!Array.isArray(blocks) || !Array.isArray(speciesRows)) return out;

    for (const block of blocks) {
      const name = block?.block_name;
      if (!name) continue;
      const area = Number(block.area_ha) || 0;

      const mine = speciesRows.filter((r: any) => r?.block_name === name);
      if (mine.length === 0) continue;

      const bySpecies: Record<string, any> = {};
      for (const r of mine) {
        const sp = r.species_local || r.species_scientific;
        if (!sp) continue;
        const row =
          bySpecies[sp] ||
          (bySpecies[sp] = {
            species: sp,
            count_per_ha: 0,
            timber_m3_per_ha: 0,
            firewood_m3_per_ha: 0,
            volume_per_ha: 0,
          });
        row.count_per_ha += Number(r.count_per_ha) || 0;
        row.timber_m3_per_ha += Number(r.timber_m3_per_ha) || 0;
        row.firewood_m3_per_ha += Number(r.firewood_m3_per_ha) || 0;
        row.volume_per_ha += Number(r.volume_m3_per_ha) || 0;
      }

      const speciesList = Object.values(bySpecies).filter((r: any) => r.volume_per_ha > 0);
      const totalVol = speciesList.reduce((s: number, r: any) => s + r.volume_per_ha, 0);
      if (totalVol <= 0) continue;

      out[name] = speciesList.map((r: any) => {
        const share = r.volume_per_ha / totalVol;
        const maiPerHa = (Number(block.mai_m3_per_ha) || 0) * share;
        const aahPerHa = (Number(block.aah_m3_per_ha) || 0) * share;
        return {
          ...r,
          mai_per_ha: maiPerHa,
          mai_total: maiPerHa * area,
          aah_per_ha: aahPerHa,
          aah_total: aahPerHa * area,
          growing_stock_total: r.volume_per_ha * area,
          timber_total: r.timber_m3_per_ha * area,
          firewood_total: r.firewood_m3_per_ha * area,
        };
      });
    }
    return out;
  };

  return { DBH_CLASS_CONFIG, sortDbhClasses, computeBlockSubtotal, fmt, fmtPH, buildSpeciesChartData, buildBlockBarChartData, speciesGrowthByBlock, speciesChartTailNames };
};

/**
 * Says, in words, whether a table's numbers are rates or quantities.
 *
 * The old convention was the *presence or absence* of "/ha", and absence is not a
 * label: a bare `Count` gives a reader nothing to distinguish "this is a total"
 * from "the suffix was forgotten", and the codebase was inconsistent about it
 * anyway - `Trees/hectare` in one table, `Count/ha` in another, `Trees/ha` in a
 * third. So the rule is now positive on BOTH sides: a rate says per hectare, a
 * quantity says Total. Three tables carry both and are badged MIXED.
 *
 * Colour is redundant reinforcement, never the primary signal - it fails in
 * greyscale, in print, and for a colour-blind reader. The text does the work.
 */
export type TableBasis = 'perha' | 'absolute' | 'mixed';

const BASIS_STYLE: Record<TableBasis, { chip: string; bar: string; key: string }> = {
  perha: { chip: 'bg-emerald-100 text-emerald-800 border-emerald-300', bar: 'bg-emerald-500', key: 'totalInventory.basisPerHectare' },
  absolute: { chip: 'bg-slate-100 text-slate-800 border-slate-300', bar: 'bg-slate-500', key: 'totalInventory.basisAbsolute' },
  mixed: { chip: 'bg-amber-100 text-amber-900 border-amber-300', bar: 'bg-amber-500', key: 'totalInventory.basisMixed' },
};

const BasisBadge: React.FC<{ basis: TableBasis }> = ({ basis }) => {
  const t = useT();
  const s = BASIS_STYLE[basis];
  return (
    <span
      data-testid={`basis-${basis}`}
      className={`inline-flex items-center align-middle text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded border ${s.chip}`}
    >
      {t(s.key)}
    </span>
  );
};

/** The legend, stated once, above the first table. */
export const BasisLegend: React.FC = () => {
  const t = useT();
  return (
    <div className="rounded-lg border-2 border-gray-300 bg-gray-50 p-4">
      {/* Badges only. An earlier version put a text label in front of each,
          which read "Per Hectare PER HECTARE" - the badge already says it, and
          the note below is what explains the difference. */}
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-500 mr-1">
          {t('totalInventory.basisLegendLabel')}
        </span>
        <BasisBadge basis="perha" />
        <BasisBadge basis="absolute" />
        <BasisBadge basis="mixed" />
      </div>
      <p className="text-sm text-gray-700">{t('totalInventory.basisRuleNote')}</p>
    </div>
  );
};

/**
 * One of the three stages the totals are derived through, in the order they are

 * actually applied: per-hectare rates, then the effective area they are spread
 * over, then the totals that fall out of the two multiplied together
 * (CFMG 6.4).
 *
 * The order is the point. The pane used to open on the area block and the grand
 * total, with the per-hectare figures underneath - so the output came before the
 * input and the multiplication had to be inferred from two distant tables. The
 * stage headers make the derivation legible instead of merely available.
 */
const StageSection: React.FC<{
  n: 1 | 2 | 3;
  titleKey: string;
  noteKey: string;
  testid: string;
  children: React.ReactNode;
}> = ({ n, titleKey, noteKey, testid, children }) => {
  const t = useT();
  const tone =
    n === 1
      ? 'border-emerald-400 bg-emerald-50'
      : n === 2
        ? 'border-sky-400 bg-sky-50'
        : 'border-green-400 bg-green-50';
  const badge =
    n === 1 ? 'bg-emerald-600' : n === 2 ? 'bg-sky-600' : 'bg-green-700';
  return (
    <section className="space-y-4" data-testid={testid} data-stage={n}>
      <div className={`rounded-lg border-2 ${tone} p-4`}>
        <h3 className="flex items-center gap-2 text-lg font-bold text-gray-900">
          <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full ${badge} text-white text-sm`}>
            {n}
          </span>
          {t(titleKey)}
        </h3>
        <p className="text-sm text-gray-700 mt-1 ml-9">{t(noteKey)}</p>
      </div>
      {children}
    </section>
  );
};

/**
 * Area context + forest-wide grand total.
 *
 * Rendered above the existing Results tables: the per-hectare and absolute
 * numbers below are all derived from the effective areas shown here, so the
 * reader needs this block first.
 */
export const FieldInventoryTotalsSummary: React.FC = () => {
  const t = useT();
  const {
    fieldInventory,
    labels,
    blockAreas,
    treeCoverAreas,
    polygonAreas,
    treeCoverLoading,
    treeCoverError,
    totalData,
    totalsLoading: loading,
    ensureResultsLoaded,
    loadTreeCoverAreas,
    handleCalculateTotals,
  } = useFieldInventoryData();

  // Results-only data (tree cover, effective areas, totals). Guarded by the
  // provider, so switching panes does not refetch.
  React.useEffect(() => {
    ensureResultsLoaded();
  }, [ensureResultsLoaded]);

  if (!fieldInventory) return null;


  /**
   * The compartments to show in stage 2, and the only list the totals are
   * actually derived from.
   *
   * This used to render `Object.values(treeCoverAreas)` alone, which is empty on
   * any forest where `POST /tree-cover-areas` fails - it answers 400 when the
   * raster does not overlap the boundary, and then the areas come from
   * `/block-area-detail` via the `loadTreeCoverAreas` fallback. The result was
   * the worst kind of silent failure: the totals were computed correctly from
   * `blockAreas`, and stage 2 displayed *nothing at all*, so a reader could not
   * see the area the totals were spread over. Driving the list from `blockAreas`
   * fixes that, because `blockAreas` is what the numbers are built from; the
   * tree-cover detail is then added where it happens to exist.
   */
  const areaRows: Array<{
    name: string;
    effective: number;
    total: number | null;
    pct: number | null;
  }> = React.useMemo(
    () =>
      Object.entries((blockAreas ?? {}) as Record<string, number>).map(
        ([name, effective]) => {
          const tc: any = (treeCoverAreas as Record<string, any>)?.[name];
          return {
            name,
            effective: Number(effective) || Number(tc?.effective_area_ha) || 0,
            // The polygon's own area is always known (block-area-detail); the raster recompute is only a fallback.
            total: (polygonAreas as Record<string, number> | undefined)?.[name] ?? (tc?.total_area_ha != null ? Number(tc.total_area_ha) : null),
            pct: tc?.tree_cover_percentage != null ? Number(tc.tree_cover_percentage) : null,
          };
        },
      ),
    [blockAreas, treeCoverAreas, polygonAreas],
  );

  return (
    <div className="space-y-8">
      {/* The old page's banner, minus its H3: the pane already has a title, but
          the note explaining that the areas below are auto-filled from the
          tree-cover calculation still belongs above them. */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border-2 border-blue-300 p-6">
        <p className="text-sm text-gray-600">
          {t('totalInventory.autofillNote', { unit: dimensionUnit(labels) })}
        </p>
      </div>

      {/* The convention, stated once, before any number. Every table below also
          carries a badge and every column says its own basis, so this is the one
          place a reader has to learn the rule. */}
      <BasisLegend />


  {/* ============================================================
   * STAGE 1 - Per-hectare analysis. The rates, from the sample plots.
   * Rendered first because it is the INPUT to everything after it.
   * ============================================================ */}
  <StageSection
    n={1}
    titleKey="totalInventory.stage1Title"
    noteKey="totalInventory.stage1Note"
    testid="fi-stage-1-perha"
  >
      {/* ------------------------------------------------------------------
       * STAGE 1 - the per-hectare figures.
       *
       * This block used to be NESTED inside the grand-total card, below the
       * absolute totals, so the output was shown before the input it is derived
       * from. It is now its own stage, placed first, because it is the input:
       * every total below is one of these numbers multiplied by the effective
       * area in stage 2 (CFMG 6.4).
       *
       * Stem densities are averaged over the WHOLE forest area, not the sum of
       * the per-block rates -- the blocks differ in area, so adding their rates
       * would weight a 3.4 ha block the same as a 226 ha one.
       * ------------------------------------------------------------------ */}
      {totalData && totalData.forest_totals && (() => {
        const ft = totalData.forest_totals;
        const area = Number(ft.total_area_ha || 0);
        // No denominator, no per-hectare figure: a number divided by nothing
        // is worse than an absent one.
        if (!area) return null;
        const perHa = (v: any) => formatNumber(Number(v || 0) / area);
        const cells: Array<{ label: string; value: string; cls: string }> = [
          { label: t('dbhClass.seedling'), value: perHa(ft.total_regeneration), cls: 'text-emerald-700' },
          { label: t('dbhClass.sapling'), value: perHa(ft.total_sapling), cls: 'text-emerald-700' },
          { label: t('totalInventory.pole'), value: perHa(ft.total_pole), cls: 'text-emerald-700' },
          { label: t('totalInventory.tree'), value: perHa(ft.total_tree), cls: 'text-emerald-700' },
          { label: t('totalInventory.growingStockPerHa'), value: perHa(ft.total_growing_stock_m3), cls: 'text-amber-700' },
          { label: t('totalInventory.maiPerHaYr'), value: perHa(ft.total_mai_m3_per_year), cls: 'text-purple-700' },
          { label: t('totalInventory.aahPerHaYr'), value: perHa(ft.total_aah_m3_per_year), cls: 'text-amber-800' },
        ];
        return (
          <div className="bg-white rounded-lg shadow p-6">
            <h4 className="text-lg font-semibold text-gray-900 mb-1">
              {t('totalInventory.perHectare')}
              <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_forest_total_perha_narration}}'}</code>
            </h4>
            <p className="text-xs text-gray-600 mb-4">
              {t('totalInventory.perHaBasisNote', { area: formatNumber(area) })}
            </p>
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
              {cells.map((c) => (
                <div key={c.label} className="bg-emerald-50 rounded-lg p-3 shadow-sm border border-emerald-200">
                  <div className="text-xs text-gray-500 mb-1">{c.label}</div>
                  <div className={`text-lg font-bold ${c.cls}`}>{c.value}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })()}
  </StageSection>

  {/* ============================================================
   * STAGE 2 - Effective area. Derived from geometry + tree cover.
   * No editable control exists here and none is wanted: the backend
   * recomputes these areas itself, so a typed value would be discarded.
   * ============================================================ */}
  <StageSection
    n={2}
    titleKey="totalInventory.stage2Title"
    noteKey="totalInventory.stage2Note"
    testid="fi-stage-2-area"
  >
  {/* Block Areas Input */}
  <div className="bg-white rounded-lg shadow p-6">

    <h4 className="text-lg font-semibold text-gray-900 mb-4">
      {t('totalInventory.step1', { unit: dimensionUnit(labels) })}
      <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_block_area_table}}'}</code>
    </h4>

    {treeCoverLoading ? (
      <div className="text-center py-8">
        <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        <p className="text-sm text-gray-600 mt-2">{t('totalInventory.calcTreeCover')}</p>
      </div>
    ) : treeCoverError ? (
      <div className="p-4 bg-red-50 rounded-md border border-red-200">
        <p className="text-sm text-red-800 font-medium">{t('totalInventory.calcTreeCoverError')}</p>
        <p className="text-sm text-red-700 mt-1">{treeCoverError}</p>
        <button
          onClick={loadTreeCoverAreas}
          className="mt-3 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm"
        >
          {t('totalInventory.recalculate')}
        </button>
      </div>
    ) : (
      <>
        <div className="mb-4 p-3 bg-blue-50 rounded-md text-sm text-blue-800">
          <p className="font-medium">{t('totalInventory.treeCoverAutofilled')}</p>
          <p className="text-xs mt-1">
            {t('totalInventory.effectiveCoverNote')}
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {areaRows.map(({ name, effective, total, pct }) => (
            <div key={name} className="p-4 bg-gray-50 rounded-lg border border-gray-200">
              <label className="font-semibold text-gray-900 mb-2 block">{name}</label>

              {/* The unit's own polygon area, always shown. The effective forest cover below it is what is left after
                  private land, protected area and non-forest cover, so it is never larger. */}
              {total != null && (
                <div className="flex justify-between text-sm text-gray-700 mb-1" data-testid={`polygon-area-${name}`}>
                  <span>{t('totalInventory.polygonArea')}</span>
                  <span className="font-medium">{t('totalInventory.haValue', { value: formatDecimal(total, 2) })}</span>
                </div>
              )}
              <div className="flex items-center gap-2 mb-2">
                <div className="flex-1 px-3 py-2 bg-gray-100 border border-gray-300 rounded-md text-gray-700 font-medium">
                  {formatDecimal(effective, 2)}
                </div>
                <span className="text-sm font-medium text-gray-600">{t('totalInventory.ha')}</span>
              </div>

              {/* The tree-cover breakdown is only available when the recompute
                  succeeded. `POST /tree-cover-areas` answers 400 on some forests
                  (no raster overlap), and the areas then come from
                  `/block-area-detail` alone - so these two lines are shown only
                  when there is something to show, rather than as zeroes. */}
              {pct != null && (
                <div className="text-xs text-gray-600 space-y-1 bg-white p-2 rounded border border-gray-200">
                  {pct != null && (
                    <div className="flex justify-between text-green-700 font-medium">
                      <span>{t('totalInventory.forestCover')}</span>
                      <span>
                        {t('totalInventory.haValue', { value: formatDecimal(effective, 2) })} ({formatDecimal(pct, 1)}%)
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* The forest total, which is the denominator every stage-1 rate is
            divided by. Without it the reader cannot check stage 1 against
            stage 3. */}
        {areaRows.length > 0 && (
          <div className="mt-4 flex items-center justify-between px-4 py-3 rounded-lg bg-sky-50 border-2 border-sky-300">
            <span className="text-sm font-semibold text-sky-900">
              {t('totalInventory.totalEffectiveArea')}
            </span>
            <span className="text-lg font-bold text-sky-900">
              {/* Rendered directly rather than through `haValue` so the number is
                  in the DOM on its own - the per-compartment cards above do the
                  same, and a reader checking stage 1 against stage 3 needs to
                  see this figure without reading prose. */}
              {formatDecimal(
                areaRows.reduce((s: number, r) => s + (Number(r.effective) || 0), 0),
                2,
              )}{' '}
              {t('totalInventory.ha')}
            </span>
          </div>
        )}
      </>
    )}
  </div>

  {/* Manual calculate trigger (fallback if auto-calc didn't run) */}
  {areaRows.length > 0 && !totalData && !loading && (
    <div className="text-center">
      <button
        onClick={() => handleCalculateTotals(true)}
        disabled={loading}
        className="px-6 py-3 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 font-medium"
      >
        {loading ? t('totalInventory.calculatingShort') : t('totalInventory.calculateBtn')}
      </button>
    </div>
  )}

  {/* Loading indicator */}
  {loading && !totalData && (
    <div className="text-center py-8">
      <div className="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      <p className="text-sm text-gray-600 mt-2">{t('totalInventory.calculating')}</p>
    </div>
  )}

  {/* No matching blocks warning */}
  {totalData && (!totalData.forest_totals || Object.keys(totalData.forest_totals).length === 0) && (
    <div className="p-4 bg-red-50 rounded-md border border-red-200">
      <p className="text-sm text-red-800 font-medium">{t('totalInventory.noUnitFound', { unit: dimensionUnit(labels) })}</p>
      <p className="text-xs text-red-700 mt-1">
        {t('totalInventory.unitMismatch', { units: labels.unitNameHeaderPluralNp, list: Object.keys(blockAreas).join(', ') })}
      </p>
      <p className="text-xs text-red-600 mt-1">
        {t('totalInventory.reuploadHint', { unit: labels.unitNameHeaderNp })}
      </p>
    </div>
  )}
  </StageSection>

  {/* ============================================================
   * STAGE 3 - Total inventory. Per-hectare (stage 1) x effective
   * area (stage 2). The identity is stated in the stage note so the
   * multiplication is not something the reader has to infer.
   * ============================================================ */}
  <StageSection
    n={3}
    titleKey="totalInventory.stage3Title"
    noteKey="totalInventory.stage3Note"
    testid="fi-stage-3-totals"
  >
      {/* Forest-Wide Totals Summary */}

  {totalData && totalData.forest_totals && Object.keys(totalData.forest_totals).length > 0 && (
      <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg border-2 border-green-400 p-6 shadow-lg">
        <h3 className="text-xl font-bold text-green-800 mb-4">
          {t('totalInventory.cfGrandTotal')}
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_forest_total_narration}}'}</code>
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg p-4 shadow-md">
            <div className="text-xs text-gray-500 mb-1">{t('totalInventory.totalArea')}</div>
            <div className="text-2xl font-bold text-green-700">{t('totalInventory.haValue', { value: formatNumber(totalData.forest_totals.total_area_ha || 0) })}</div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md">
            <div className="text-xs text-gray-500 mb-1">{t('totalInventory.totalTrees')}</div>
            <div className="text-2xl font-bold text-blue-700">
              {formatNumber(((totalData.forest_totals.total_pole || 0) + (totalData.forest_totals.total_tree || 0)))}
            </div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md">
            <div className="text-xs text-gray-500 mb-1">{t('totalInventory.growingStock')}</div>
            <div className="text-xl font-bold text-amber-700">
              {formatNumber((totalData.forest_totals.total_growing_stock_m3 || 0))} m³
            </div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md">
            <div className="text-xs text-gray-500 mb-1">{t('totalInventory.maiPerYear')}</div>
            <div className="text-xl font-bold text-purple-700">
              {formatNumber((totalData.forest_totals.total_mai_m3_per_year || 0))} m³
            </div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md bg-amber-50">
            <div className="text-xs text-gray-600 mb-1 font-medium">{t('totalInventory.aahPerYear')}</div>
            <div className="text-2xl font-bold text-amber-800">
              {formatNumber((totalData.forest_totals.total_aah_m3_per_year || 0))} m³
            </div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md">
            <div className="text-xs text-gray-500 mb-1">{t('totalInventory.totalBiomass')}</div>
            <div className="text-xl font-bold text-teal-700">
              {formatNumber((totalData.forest_totals.total_biomass_tonnes || 0))} t
            </div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md">
            <div className="text-xs text-gray-500 mb-1">{t('totalInventory.carbonStock')}</div>
            <div className="text-xl font-bold text-teal-700">
              {formatNumber((totalData.forest_totals.total_carbon_tc || 0))} tC
            </div>
          </div>
          <div className="bg-white rounded-lg p-4 shadow-md bg-teal-50">
            <div className="text-xs text-gray-600 mb-1 font-medium">{t('totalInventory.co2e')}</div>
            <div className="text-xl font-bold text-teal-800">
              {formatNumber((totalData.forest_totals.total_co2_tco2 || 0))} tCO₂
            </div>
          </div>
        </div>
      </div>
  )}



      {/* Block-wise Totals Table */}
      {totalData?.forest_totals && totalData.blocks && totalData.blocks.length > 0 && (
      <div className="bg-white rounded-lg shadow p-6">
        <h4 className="text-lg font-semibold text-gray-900 mb-4">
          {t('totalInventory.unitWiseStock', { unit: dimensionUnit(labels) })}
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_block_growing_stock}}'}</code>
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_block_growing_stock_narration}}'}</code>
      <BasisBadge basis="absolute" />
        </h4>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitLabelNp}</th>
                <th rowSpan={2} className="px-3 py-3 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.areaHa')}</th>
                <th colSpan={4} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-blue-50">{t('totalInventory.totalTrees')}</th>
                <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300 bg-amber-50">{t('totalInventory.totalVolumeM3')}</th>
                <th colSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-teal-50">{t('totalInventory.totalCarbon')}</th>
              </tr>
              <tr>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('dbhClass.seedling')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('dbhClass.sapling')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.pole')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.tree')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.stock')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.maiPerYear')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.aahPerYear')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.biomassT')}</th>
                <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.co2Unit')}</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {totalData.blocks.map((block: any, index: number) => (
                <tr key={index} className="hover:bg-gray-50">
                  <td className="px-3 py-3 text-sm font-medium text-gray-900 border-r border-gray-200">{block.block_name}</td>
                  <td className="px-3 py-3 text-sm text-center border-r border-gray-200">{formatNumber((block.area_ha || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_regeneration || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_sapling || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_pole || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{formatNumber((block.total_tree || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_growing_stock_m3 || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_mai_m3 || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right border-r border-gray-200 font-semibold text-amber-700">{formatNumber((block.total_aah_m3 || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_biomass_tonnes || 0))}</td>
                  <td className="px-2 py-3 text-sm text-right">{formatNumber((block.total_co2_tco2 || 0))}</td>
                </tr>
              ))}
              <tr className="bg-green-100 font-bold">
                <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.totalForest')}</td>
                <td className="px-3 py-3 text-sm text-center border-r border-gray-200">{formatNumber((totalData.forest_totals.total_area_ha || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_regeneration || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_sapling || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_pole || 0))}</td>
                <td className="px-2 py-3 text-sm text-right border-r border-gray-200">{formatNumber((totalData.forest_totals.total_tree || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_growing_stock_m3 || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_mai_m3_per_year || 0))}</td>
                <td className="px-2 py-3 text-sm text-right border-r border-gray-200 text-amber-900">{formatNumber((totalData.forest_totals.total_aah_m3_per_year || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_biomass_tonnes || 0))}</td>
                <td className="px-2 py-3 text-sm text-right">{formatNumber((totalData.forest_totals.total_co2_tco2 || 0))}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      )}

      {/* Missing Area Data Warning */}
      {areaRows.length > 0 && !loading && (!totalData || !totalData.forest_totals || Object.keys(totalData.forest_totals).length === 0) && (
        <div className="p-4 bg-yellow-50 rounded-md border border-yellow-200">
          <p className="text-sm text-yellow-800 font-medium">{t('totalInventory.noAreaData')}</p>
          <p className="text-xs text-yellow-700 mt-1">
            {t('totalInventory.calcHint', { unit: dimensionUnit(labels) })}
          </p>
        </div>
      )}

      {/* Missing Area Data Warning */}
      {areaRows.length > 0 && !loading && (!totalData || !totalData.forest_totals || Object.keys(totalData.forest_totals).length === 0) && (
        <div className="p-4 bg-yellow-50 rounded-md border border-yellow-200">
          <p className="text-sm text-yellow-800 font-medium">{t('totalInventory.noAreaData')}</p>
          <p className="text-xs text-yellow-700 mt-1">
            {t('totalInventory.calcHint', { unit: dimensionUnit(labels) })}
          </p>
        </div>
      )}
  </StageSection>
    </div>
  );
};


/**
 * The remaining per-species / per-DBH tables, the economic valuation and the
 * sustainability index.
 */
export const FieldInventoryResultsTables: React.FC = () => {
  const t = useT();
  const {
    fieldInventory,
    labels,
    speciesDbhData,
    speciesDbhForestWide,
    totalData,
    blockRates,
    setBlockRates,
    totalsLoading: loading,
    ensureResultsLoaded,
  } = useFieldInventoryData();
  const { DBH_CLASS_CONFIG, sortDbhClasses, computeBlockSubtotal, fmt, fmtPH, buildSpeciesChartData, buildBlockBarChartData, speciesGrowthByBlock, speciesChartTailNames } = useTotalsHelpers();
  // The per-species MAI/AAH split, derived from the per-species per-ha volumes.
  const speciesGrowth = React.useMemo(
    () => speciesGrowthByBlock(totalData?.blocks ?? [], speciesDbhData ?? []),
    [speciesGrowthByBlock, totalData?.blocks, speciesDbhData],
  );

  React.useEffect(() => {
    ensureResultsLoaded();
  }, [ensureResultsLoaded]);

  if (!fieldInventory || !totalData) return null;
  if (!totalData.forest_totals || Object.keys(totalData.forest_totals).length === 0) return null;

  // The economic table seeds a rate entry from the typed field alone
  // (`{ ...prev[name], timber: v }`), so the first edit for a block with no
  // entry yet leaves the sibling rates undefined, and a block whose rates were
  // never seeded (tree cover present, absent from the totals response) reads as
  // a partial record. Merging the defaults on read covers both.
  const getBlockRate = (blockName: string): BlockRates => ({ ...DEFAULT_BLOCK_RATES, ...blockRates[blockName] });

  return (
    <>

      {/* Species Breakdown Table — one list, two labelled groups (P3).
          Was a flat table of every species with no grouping, no share column and
          no totals row, so a reader could not tell how much of the forest sat
          outside the policy list. `SpeciesPolicyTable` groups the in-list species
          first and gathers the rest under a labelled "Other species" divider,
          naming every one of them. */}
      {totalData.species_breakdown && totalData.species_breakdown.length > 0 && (
        <SpeciesPolicyTable
          testId="species-absolute"
          rows={totalData.species_breakdown}
          shareKey="count"
          title={
            <>
              {t('totalInventory.bySpeciesTitle')}
              <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_species_block_growing_stock}}'}</code>
              <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_species_stock_narration}}'}</code>
              <BasisBadge basis="absolute" />
            </>
          }
          note={<p className="text-xs text-gray-500">{t('totalInventory.absoluteBySpecies', { units: labels.allUnitsNp })}</p>}
          measures={[
            { key: 'timber_m3', labelKey: 'totalInventory.totalTimberM3', decimals: 2 },
            { key: 'fuelwood_m3', labelKey: 'totalInventory.totalFirewoodM3', decimals: 2 },
            { key: 'volume_m3', labelKey: 'totalInventory.totalVolumeM3b', decimals: 2, emphasis: true },
          ]}
        />
      )}

      {/* The same species by the regulation's groups (21 designated + Other Terai/Hill), with the OP placeholders. */}
      {fieldInventory?.id && <RegulationSpeciesPanel fieldInventoryId={fieldInventory.id} />}

      {/* Species × DBH Class Breakdown Table */}
      {speciesDbhData && speciesDbhData.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-2">
            {t('totalInventory.speciesDbhTitle')}
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_species_dbh_class_table}}'}</code>
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_species_dbh_narration}}'}</code>
      <BasisBadge basis="perha" />
          </h4>
          <p className="text-xs text-gray-500 mb-4">{t('totalInventory.speciesDbhSubtitle')}</p>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{labels.unitLabelNp}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('totalInventory.localName')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('totalInventory.dbhClass')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.countPerHa')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.timberPerHa')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.firewoodPerHa')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.volumePerHa')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {(() => {
                  const blockGroups: Record<string, any[]> = {};
                  speciesDbhData.forEach((item: any) => {
                    if (!blockGroups[item.block_name]) blockGroups[item.block_name] = [];
                    blockGroups[item.block_name].push(item);
                  });
                  const blockNames = Object.keys(blockGroups);
                  const rows: React.ReactElement[] = [];
                  let grandCount = 0, grandTimber = 0, grandFuel = 0, grandVol = 0;
                  blockNames.forEach((bn, bi) => {
                    const items = blockGroups[bn];
                    // Group by species within block
                    const spGroups: Record<string, any[]> = {};
                    items.forEach((item: any) => {
                      const sk = item.species_local || item.species_scientific || '—';
                      if (!spGroups[sk]) spGroups[sk] = [];
                      spGroups[sk].push(item);
                    });
                    let blkCount = 0, blkTimber = 0, blkFuel = 0, blkVol = 0;
                    Object.keys(spGroups).forEach((sk) => {
                      const spItems = sortDbhClasses(spGroups[sk]);
                      let spCount = 0, spTimber = 0, spFuel = 0, spVol = 0;
                      spItems.forEach((item: any) => {
                        spCount += item.count_per_ha || 0;
                        spTimber += item.timber_m3_per_ha || 0;
                        spFuel += item.fuelwood_m3_per_ha || 0;
                        spVol += item.volume_m3_per_ha || 0;
                        rows.push(
                          <tr key={`${bi}-${sk}-${item.dbh_class}`} className="hover:bg-gray-50">
                            <td className="px-3 py-2 text-sm text-gray-900">{item.block_name}</td>
                            <td className="px-3 py-2 text-sm text-gray-700">{sk}</td>
                            <td className="px-3 py-2 text-sm text-gray-600">{DBH_CLASS_CONFIG.find((c: any) => c.key === item.dbh_class)?.label || item.dbh_class}</td>
                            <td className="px-3 py-2 text-sm text-right">{item.count_per_ha != null ? formatDecimal(item.count_per_ha, 1) : '—'}</td>
                            <td className="px-3 py-2 text-sm text-right">{item.timber_m3_per_ha != null ? formatDecimal(item.timber_m3_per_ha, 2) : '—'}</td>
                            <td className="px-3 py-2 text-sm text-right">{item.fuelwood_m3_per_ha != null ? formatDecimal(item.fuelwood_m3_per_ha, 2) : '—'}</td>
                            <td className="px-3 py-2 text-sm text-right font-medium">{item.volume_m3_per_ha != null ? formatDecimal(item.volume_m3_per_ha, 2) : '—'}</td>
                          </tr>
                        );
                      });
                      // Species subtotal within block
                      rows.push(
                        <tr key={`${bi}-sp-sub-${sk}`} className="bg-yellow-50 font-semibold text-yellow-800">
                          <td className="px-3 py-2 text-sm" colSpan={3}>{t('totalInventory.speciesTotalNamed', { name: sk })}</td>
                          <td className="px-3 py-2 text-sm text-right">{formatDecimal(spCount, 1)}</td>
                          <td className="px-3 py-2 text-sm text-right">{formatDecimal(spTimber, 2)}</td>
                          <td className="px-3 py-2 text-sm text-right">{formatDecimal(spFuel, 2)}</td>
                          <td className="px-3 py-2 text-sm text-right">{formatDecimal(spVol, 2)}</td>
                        </tr>
                      );
                      blkCount += spCount; blkTimber += spTimber; blkFuel += spFuel; blkVol += spVol;
                    });
                    // Block subtotal
                    rows.push(
                      <tr key={`sub-${bi}`} className="bg-green-50 font-semibold">
                        <td className="px-3 py-2 text-sm text-green-800" colSpan={3}>{labels.unitTotalNp} — {bn}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(blkCount, 1)}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(blkTimber, 2)}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(blkFuel, 2)}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(blkVol, 2)}</td>
                      </tr>
                    );
                    grandCount += blkCount; grandTimber += blkTimber; grandFuel += blkFuel; grandVol += blkVol;
                  });
                  // Grand total
                  rows.push(
                    <tr key="grand" className="bg-blue-50 font-bold text-blue-900">
                      <td className="px-3 py-2 text-sm" colSpan={3}>{t('totalInventory.wholeForestTotal')}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandCount, 1)}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandTimber, 2)}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandFuel, 2)}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandVol, 2)}</td>
                    </tr>
                  );
                  return rows;
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Species × DBH Class — Forest-Wide */}
      {speciesDbhForestWide && speciesDbhForestWide.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-2">
            {t('totalInventory.wholeForestSpeciesDbh')}
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_forest_dbh_class_table}}'}</code>
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_forest_dbh_narration}}'}</code>
      <BasisBadge basis="perha" />
          </h4>
          <p className="text-xs text-gray-500 mb-4">{t('totalInventory.perHaBySpeciesDbh', { units: labels.allUnitsNp })}</p>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('totalInventory.localName')}</th>
                  <th className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase">{t('totalInventory.dbhClass')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.countPerHa')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.timberPerHa')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.firewoodPerHa')}</th>
                  <th className="px-3 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.volumePerHa')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {(() => {
                  const spGroups: Record<string, any[]> = {};
                  speciesDbhForestWide.forEach((item: any) => {
                    const key = item.species_local || item.species_scientific || '—';
                    if (!spGroups[key]) spGroups[key] = [];
                    spGroups[key].push(item);
                  });
                  const spNames = Object.keys(spGroups);
                  const rows: React.ReactElement[] = [];
                  let grandCount = 0, grandTimber = 0, grandFuel = 0, grandVol = 0;
                  spNames.forEach((sp, si) => {
                    const items = sortDbhClasses(spGroups[sp]);
                    let spCount = 0, spTimber = 0, spFuel = 0, spVol = 0;
                    items.forEach((item: any) => {
                      spCount += item.count_per_ha || 0;
                      spTimber += item.timber_m3_per_ha || 0;
                      spFuel += item.fuelwood_m3_per_ha || 0;
                      spVol += item.volume_m3_per_ha || 0;
                      rows.push(
                        <tr key={`fw-${si}-${item.dbh_class}`} className="hover:bg-gray-50">
                          <td className="px-3 py-2 text-sm text-gray-700">{sp}</td>
                          <td className="px-3 py-2 text-sm text-gray-600">{DBH_CLASS_CONFIG.find((c: any) => c.key === item.dbh_class)?.label || item.dbh_class}</td>
                          <td className="px-3 py-2 text-sm text-right">{item.count_per_ha != null ? formatDecimal(item.count_per_ha, 1) : '—'}</td>
                          <td className="px-3 py-2 text-sm text-right">{item.timber_m3_per_ha != null ? formatDecimal(item.timber_m3_per_ha, 2) : '—'}</td>
                          <td className="px-3 py-2 text-sm text-right">{item.fuelwood_m3_per_ha != null ? formatDecimal(item.fuelwood_m3_per_ha, 2) : '—'}</td>
                          <td className="px-3 py-2 text-sm text-right font-medium">{item.volume_m3_per_ha != null ? formatDecimal(item.volume_m3_per_ha, 2) : '—'}</td>
                        </tr>
                      );
                    });
                    // Species subtotal
                    rows.push(
                      <tr key={`fw-sub-${si}`} className="bg-green-50 font-semibold">
                        <td className="px-3 py-2 text-sm text-green-800" colSpan={2}>{t('totalInventory.speciesTotalNamed', { name: sp })}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(spCount, 1)}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(spTimber, 2)}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(spFuel, 2)}</td>
                        <td className="px-3 py-2 text-sm text-right text-green-800">{formatDecimal(spVol, 2)}</td>
                      </tr>
                    );
                    grandCount += spCount; grandTimber += spTimber; grandFuel += spFuel; grandVol += spVol;
                  });
                  // Grand total
                  rows.push(
                    <tr key="fw-grand" className="bg-blue-50 font-bold text-blue-900">
                      <td className="px-3 py-2 text-sm" colSpan={2}>{t('totalInventory.wholeForestTotal')}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandCount, 1)}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandTimber, 2)}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandFuel, 2)}</td>
                      <td className="px-3 py-2 text-sm text-right">{formatDecimal(grandVol, 2)}</td>
                    </tr>
                  );
                  return rows;
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* CFMG harvest classes, per compartment and for the forest (P2b/P3).
          Placed after the species tables and before the DBH class tables: it is a
          *grouping of* those classes, so it reads after the per-species view and
          before the per-class detail it summarises. */}
      <HarvestGroupTable
        blocks={totalData.blocks || []}
        forestGroups={totalData.forest_totals?.harvest_class_groups || []}
      />

      {/* DBH Class-wise Total Inventory (Absolute) */}
      {totalData.blocks && totalData.blocks.length > 0 && totalData.blocks[0].dbh_class_totals && (
      <div className="bg-white rounded-lg shadow p-6">
        <h4 className="text-lg font-semibold text-gray-900 mb-4">
          {t('totalInventory.byDbhTitle')}
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_dbh_class_totals_table}}'}</code>
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_dbh_total_narration}}'}</code>
      <BasisBadge basis="absolute" />
        </h4>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitLabelNp}</th>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.dbhClass')}</th>
                <th colSpan={4} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-blue-50 border-r border-gray-300">{t('totalInventory.grandTotal')}</th>
              </tr>
              <tr>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalCount')}</th>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalTimberM3')}</th>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalFirewoodM3')}</th>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.totalVolumeM3b')}</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {totalData.blocks.map((block: any, bi: number) => {
                const absData = block.dbh_class_totals || {};
                const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                  const d = absData[key];
                  if (!d) return [];
                  return [{
                    key, label,
                    count: d.total_count,
                    timber: d.total_timber_m3,
                    firewood: d.total_firewood_m3,
                    volume: d.total_tree_volume_m3,
                  }];
                });
                if (rows.length === 0) return null;
                const subtotal = {
                  count: computeBlockSubtotal(block, 'total_count', false),
                  timber: computeBlockSubtotal(block, 'total_timber_m3', false),
                  firewood: computeBlockSubtotal(block, 'total_firewood_m3', false),
                  volume: computeBlockSubtotal(block, 'total_tree_volume_m3', false),
                };
                return [
                  ...rows.map((r, ri) => (
                    <tr key={`${bi}_abs_${ri}`} className={ri === 0 ? 'border-t border-gray-200' : ''}>
                      {ri === 0 && (
                        <td rowSpan={rows.length + 1} className="px-3 py-2 text-sm font-medium text-gray-900 border-r border-gray-200 align-top">{block.block_name}</td>
                      )}
                      <td className="px-3 py-2 text-sm text-gray-700 border-r border-gray-200">{r.label}</td>
                      <td className="px-2 py-2 text-sm text-right">{formatNumber((r.count || 0))}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmt(r.timber)}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmt(r.firewood)}</td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(r.volume)}</td>
                    </tr>
                  )),
                  <tr key={`${bi}_abs_sub`} className="bg-blue-50 font-semibold">
                    <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{t('totalInventory.rowTotal', { name: block.block_name })}</td>
                    <td className="px-2 py-2 text-sm text-right">{formatNumber((Math.round(subtotal.count)))}</td>
                    <td className="px-2 py-2 text-sm text-right">{fmt(subtotal.timber)}</td>
                    <td className="px-2 py-2 text-sm text-right">{fmt(subtotal.firewood)}</td>
                    <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(subtotal.volume)}</td>
                  </tr>,
                ];
              })}
              {/* Forest-wide DBH class totals */}
              {totalData.forest_totals?.dbh_class_totals && (
                <>
                  {(() => {
                    const ftDBH = totalData.forest_totals.dbh_class_totals;
                    const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                      const d = ftDBH[key];
                      if (!d) return [];
                      return [{
                        key, label,
                        count: d.total_count,
                        timber: d.total_timber_m3,
                        firewood: d.total_firewood_m3,
                        volume: d.total_tree_volume_m3,
                      }];
                    });
                    const fsub = {
                      count: rows.reduce((s: number, r: any) => s + (r.count || 0), 0),
                      timber: rows.reduce((s: number, r: any) => s + (r.timber || 0), 0),
                      firewood: rows.reduce((s: number, r: any) => s + (r.firewood || 0), 0),
                      volume: rows.reduce((s: number, r: any) => s + (r.volume || 0), 0),
                    };
                    return [
                      ...rows.map((r, ri) => (
                        <tr key={`ft_abs_${ri}`} className="bg-green-100 font-bold">
                          {ri === 0 && (
                            <td rowSpan={rows.length + 1} className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.totalForest')}</td>
                          )}
                          <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{r.label}</td>
                          <td className="px-2 py-2 text-sm text-right">{formatNumber((r.count || 0))}</td>
                          <td className="px-2 py-2 text-sm text-right">{fmt(r.timber)}</td>
                          <td className="px-2 py-2 text-sm text-right">{fmt(r.firewood)}</td>
                          <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(r.volume)}</td>
                        </tr>
                      )),
                      <tr key="ft_abs_sub" className="bg-green-100 font-bold border-t-2 border-green-400">
                        <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.forestTotal')}</td>
                        <td className="px-2 py-3 text-sm text-right">{formatNumber((Math.round(fsub.count)))}</td>
                        <td className="px-2 py-3 text-sm text-right">{fmt(fsub.timber)}</td>
                        <td className="px-2 py-3 text-sm text-right">{fmt(fsub.firewood)}</td>
                        <td className="px-2 py-3 text-sm text-right border-r border-gray-300">{fmt(fsub.volume)}</td>
                      </tr>,
                    ];
                  })()}
                </>
              )}
            </tbody>
          </table>
        </div>
      </div>
      )}

      {/* DBH Class-wise Total Inventory (Growing Stock) */}
      {totalData.blocks && totalData.blocks.length > 0 && totalData.blocks[0].dbh_class_totals && (
      <div className="bg-white rounded-lg shadow p-6">
        <h4 className="text-lg font-semibold text-gray-900 mb-4">
          {t('totalInventory.byDbhPerHaTitle')}
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_dbh_class_perha_table}}'}</code>
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_dbh_perha_narration}}'}</code>
      <BasisBadge basis="perha" />
        </h4>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitLabelNp}</th>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.dbhClass')}</th>
                <th colSpan={4} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-amber-50 border-r border-gray-300">{t('totalInventory.perHectare')}</th>
              </tr>
              <tr>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.countPerHa')}</th>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.timberPerHa')}</th>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.firewoodPerHa')}</th>
                <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.volumePerHa')}</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {totalData.blocks.map((block: any, bi: number) => {
                const gsData = block.dbh_class_per_ha || block.dbh_class_totals || {};
                const absData = block.dbh_class_totals || {};
                const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                  const d = gsData[key];
                  const abs = absData[key];
                  if (!d && !abs) return [];
                  return [{
                    key, label,
                    count: abs?.total_count || 0,
                    timber: abs?.total_timber_m3 || 0,
                    firewood: abs?.total_firewood_m3 || 0,
                    volume: abs?.total_tree_volume_m3 || 0,
                    ph_count: d?.count_per_ha ?? d?.per_ha_count ?? 0,
                    ph_timber: d?.timber_m3_per_ha ?? d?.per_ha_timber_m3 ?? 0,
                    ph_firewood: d?.firewood_m3_per_ha ?? d?.per_ha_firewood_m3 ?? 0,
                    ph_volume: d?.tree_volume_m3_per_ha ?? d?.per_ha_tree_volume_m3 ?? 0,
                  }];
                });
                if (rows.length === 0) return null;
                const ha = block.area_ha || 1;
                const subtotalPH = {
                  count: rows.reduce((s: number, r: any) => s + (r.ph_count || 0), 0),
                  timber: rows.reduce((s: number, r: any) => s + (r.ph_timber || 0), 0),
                  firewood: rows.reduce((s: number, r: any) => s + (r.ph_firewood || 0), 0),
                  volume: rows.reduce((s: number, r: any) => s + (r.ph_volume || 0), 0),
                };
                return [
                  ...rows.map((r, ri) => (
                    <tr key={`${bi}_gs_${ri}`} className={ri === 0 ? 'border-t border-gray-200' : ''}>
                      {ri === 0 && (
                        <td rowSpan={rows.length + 1} className="px-3 py-2 text-sm font-medium text-gray-900 border-r border-gray-200 align-top">{block.block_name}</td>
                      )}
                      <td className="px-3 py-2 text-sm text-gray-700 border-r border-gray-200">{r.label}</td>
                      <td className="px-2 py-2 text-sm text-right">{formatDecimal((r.ph_count || 0), 1)}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmtPH(r.ph_timber)}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmtPH(r.ph_firewood)}</td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmtPH(r.ph_volume)}</td>
                    </tr>
                  )),
                  <tr key={`${bi}_gs_sub`} className="bg-amber-50 font-semibold">
                    <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{t('totalInventory.rowTotalPerHa', { name: block.block_name })}</td>
                    <td className="px-2 py-2 text-sm text-right">{formatDecimal(subtotalPH.count, 1)}</td>
                    <td className="px-2 py-2 text-sm text-right">{fmtPH(subtotalPH.timber)}</td>
                    <td className="px-2 py-2 text-sm text-right">{fmtPH(subtotalPH.firewood)}</td>
                    <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmtPH(subtotalPH.volume)}</td>
                  </tr>,
                ];
              })}
              {/* Forest-wide DBH class per-hectare totals */}
              {totalData.forest_totals?.dbh_class_totals && (() => {
                const ftArea = totalData.forest_totals.total_area_ha || 1;
                const ftDBH = totalData.forest_totals.dbh_class_totals;
                const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                  const d = ftDBH[key];
                  if (!d) return [];
                  return [{
                    key, label,
                    ph_count: (d.total_count || 0) / ftArea,
                    ph_timber: (d.total_timber_m3 || 0) / ftArea,
                    ph_firewood: (d.total_firewood_m3 || 0) / ftArea,
                    ph_volume: (d.total_tree_volume_m3 || 0) / ftArea,
                  }];
                });
                const fsubPH = {
                  count: rows.reduce((s: number, r: any) => s + r.ph_count, 0),
                  timber: rows.reduce((s: number, r: any) => s + r.ph_timber, 0),
                  firewood: rows.reduce((s: number, r: any) => s + r.ph_firewood, 0),
                  volume: rows.reduce((s: number, r: any) => s + r.ph_volume, 0),
                };
                return (
                  <>
                    {rows.map((r, ri) => (
                      <tr key={`ft_gs_${ri}`} className="bg-green-100 font-bold">
                        {ri === 0 && (
                          <td rowSpan={rows.length + 1} className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.totalForest')}</td>
                        )}
                        <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{r.label}</td>
                        <td className="px-2 py-2 text-sm text-right">{formatDecimal(r.ph_count, 1)}</td>
                        <td className="px-2 py-2 text-sm text-right">{fmtPH(r.ph_timber)}</td>
                        <td className="px-2 py-2 text-sm text-right">{fmtPH(r.ph_firewood)}</td>
                        <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmtPH(r.ph_volume)}</td>
                      </tr>
                    ))}
                    <tr key="ft_gs_sub" className="bg-green-100 font-bold border-t-2 border-green-400">
                      <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.forestTotalPerHa')}</td>
                      <td className="px-2 py-3 text-sm text-right">{formatDecimal(fsubPH.count, 1)}</td>
                      <td className="px-2 py-3 text-sm text-right">{fmtPH(fsubPH.timber)}</td>
                      <td className="px-2 py-3 text-sm text-right">{fmtPH(fsubPH.firewood)}</td>
                      <td className="px-2 py-3 text-sm text-right border-r border-gray-300">{fmtPH(fsubPH.volume)}</td>
                    </tr>
                  </>
                );
              })()}
            </tbody>
          </table>
        </div>
      </div>
      )}

      {/* MAI (Mean Annual Increment) */}
      {totalData.blocks && Object.keys(speciesGrowth).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-2">
            {t('totalInventory.maiBySpecies')}
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_mai_table}}'}</code>
      <BasisBadge basis="mixed" />
          </h4>
          <p className="text-xs text-gray-500 mb-4">{t('totalInventory.maiBySpeciesSub')}</p>
          <div className="overflow-x-auto">
            {totalData.blocks.map((block: any, bi: number) => {
              const species = speciesGrowth[block.block_name] || [];
              if (species.length === 0) return null;
              return (
                <div key={bi} className="mb-4">
                  <h5 className="text-sm font-semibold text-gray-800 mb-2">{block.block_name}</h5>
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('totalInventory.species')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.countPerHa')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.volumePerHaShort')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.maiPerHa')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalMai')}</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {species.map((sp: any, si: number) => (
                        <tr key={si} className="hover:bg-gray-50">
                          <td className="px-3 py-1.5 text-sm">{sp.species || '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.count_per_ha != null ? formatDecimal(sp.count_per_ha, 1) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.volume_per_ha != null ? formatDecimal(sp.volume_per_ha, 2) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.mai_per_ha != null ? formatDecimal(sp.mai_per_ha, 2) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right font-medium">{sp.mai_total != null ? formatDecimal(sp.mai_total, 2) : '—'}</td>
                        </tr>
                      ))}
                      <tr className="bg-purple-50 font-semibold">
                        <td className="px-3 py-1.5 text-sm">{t('totalInventory.rowTotal', { name: block.block_name })}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.count_per_ha || 0), 0), 1)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.volume_per_ha || 0), 0), 2)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.mai_per_ha || 0), 0), 2)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.mai_total || 0), 0), 2)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* DBH Class-wise MAI */}
      {totalData.blocks && totalData.blocks.some((b: any) => b.dbh_class_totals) && (
        <div className="bg-white rounded-lg shadow p-6">
        <h4 className="text-lg font-semibold text-gray-900 mb-4">
          {t('totalInventory.maiByDbh')}
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_dbh_mai_table}}'}</code>
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_dbh_mai_narration}}'}</code>
      <BasisBadge basis="mixed" />
        </h4>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitLabelNp}</th>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.dbhClass')}</th>
                <th colSpan={2} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-purple-50 border-r border-gray-300">MAI</th>
                </tr>
                <tr>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.maiPerHaYr')}</th>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.totalMaiYr')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {totalData.blocks.map((block: any, bi: number) => {
                  const dbhData = block.dbh_class_totals || {};
                  const blockMaiTotal = block.total_mai_m3 || 0;
                  const blockVolume = (Object.values(dbhData) as any[]).reduce((s: number, d: any) => s + (d.total_tree_volume_m3 || 0), 0);
                  const ha = block.area_ha || 1;
                  const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                    const d = dbhData[key];
                    if (!d) return [];
                    const classVol = d.total_tree_volume_m3 || 0;
                    const maiTotal = blockVolume > 0 ? (classVol / blockVolume) * blockMaiTotal : 0;
                    return { key, label, mai_per_ha: maiTotal / ha, mai_total: maiTotal };
                  });
                  if (rows.length === 0) return null;
                  const subtotal = {
                    per_ha: rows.reduce((s, r) => s + r.mai_per_ha, 0),
                    total: rows.reduce((s, r) => s + r.mai_total, 0),
                  };
                  return [
                    ...rows.map((r, ri) => (
                      <tr key={`${bi}_mai_${ri}`} className={ri === 0 ? 'border-t border-gray-200' : ''}>
                        {ri === 0 && (
                          <td rowSpan={rows.length + 1} className="px-3 py-2 text-sm font-medium text-gray-900 border-r border-gray-200 align-top">{block.block_name}</td>
                        )}
                        <td className="px-3 py-2 text-sm text-gray-700 border-r border-gray-200">{r.label}</td>
                        <td className="px-2 py-2 text-sm text-right">{fmtPH(r.mai_per_ha)}</td>
                        <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(r.mai_total)}</td>
                      </tr>
                    )),
                    <tr key={`${bi}_mai_sub`} className="bg-purple-50 font-semibold">
                      <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{t('totalInventory.rowTotal', { name: block.block_name })}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmtPH(subtotal.per_ha)}</td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(subtotal.total)}</td>
                    </tr>,
                  ];
                })}
                {totalData.forest_totals?.dbh_class_totals && (() => {
                  const ftArea = totalData.forest_totals.total_area_ha || 1;
                  const ftMai = totalData.forest_totals.total_mai_m3_per_year || 0;
                  const ftDBH = totalData.forest_totals.dbh_class_totals;
                  const ftVolume = (Object.values(ftDBH) as any[]).reduce((s: number, d: any) => s + (d.total_tree_volume_m3 || 0), 0);
                  const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                    const d = ftDBH[key];
                    if (!d) return [];
                    const classVol = d.total_tree_volume_m3 || 0;
                    const maiTotal = ftVolume > 0 ? (classVol / ftVolume) * ftMai : 0;
                    return { key, label, mai_per_ha: maiTotal / ftArea, mai_total: maiTotal };
                  });
                  const fsub = { per_ha: rows.reduce((s, r) => s + r.mai_per_ha, 0), total: rows.reduce((s, r) => s + r.mai_total, 0) };
                  return (
                    <>
                      {rows.map((r, ri) => (
                        <tr key={`ft_mai_${ri}`} className="bg-green-100 font-bold">
                          {ri === 0 && <td rowSpan={rows.length + 1} className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.totalForest')}</td>}
                          <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{r.label}</td>
                          <td className="px-2 py-2 text-sm text-right">{fmtPH(r.mai_per_ha)}</td>
                          <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(r.mai_total)}</td>
                        </tr>
                      ))}
                      <tr key="ft_mai_sub" className="bg-green-100 font-bold border-t-2 border-green-400">
                        <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.forestTotal')}</td>
                          <td className="px-2 py-3 text-sm text-right">{fmtPH(fsub.per_ha)}</td>
                          <td className="px-2 py-3 text-sm text-right border-r border-gray-300">{fmt(fsub.total)}</td>
                        </tr>
                    </>
                  );
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* AAH (Allowable Annual Harvest) */}
      {totalData.blocks && Object.keys(speciesGrowth).length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-2">
            {t('totalInventory.aahBySpecies')}
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_aah_table}}'}</code>
      <BasisBadge basis="absolute" />
          </h4>
          <p className="text-xs text-gray-500 mb-4">{t('totalInventory.aahBySpeciesSub')}</p>
          <div className="overflow-x-auto">
            {totalData.blocks.map((block: any, bi: number) => {
              const species = speciesGrowth[block.block_name] || [];
              if (species.length === 0) return null;
              return (
                <div key={bi} className="mb-4">
                  <h5 className="text-sm font-semibold text-gray-800 mb-2">{block.block_name}</h5>
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('totalInventory.species')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalMaiM3')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalGrowingStockM3')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalAahM3')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalTimberM3')}</th>
                        <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalFirewoodM3')}</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {species.map((sp: any, si: number) => (
                        <tr key={si} className="hover:bg-gray-50">
                          <td className="px-3 py-1.5 text-sm">{sp.species || '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.mai_total != null ? formatDecimal(sp.mai_total, 2) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.growing_stock_total != null ? formatDecimal(sp.growing_stock_total, 2) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right font-semibold text-amber-700">{sp.aah_total != null ? formatDecimal(sp.aah_total, 2) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.timber_total != null ? formatDecimal(sp.timber_total, 2) : '—'}</td>
                          <td className="px-3 py-1.5 text-sm text-right">{sp.firewood_total != null ? formatDecimal(sp.firewood_total, 2) : '—'}</td>
                        </tr>
                      ))}
                      <tr className="bg-amber-50 font-semibold">
                        <td className="px-3 py-1.5 text-sm">{t('totalInventory.rowTotal', { name: block.block_name })}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.mai_total || 0), 0), 2)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.growing_stock_total || 0), 0), 2)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.aah_total || 0), 0), 2)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.timber_total || 0), 0), 2)}</td>
                        <td className="px-3 py-1.5 text-sm text-right">{formatDecimal(species.reduce((s: number, sp: any) => s + (sp.firewood_total || 0), 0), 2)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* DBH Class-wise AAH */}
      {totalData.blocks && totalData.blocks.some((b: any) => b.dbh_class_totals) && (
        <div className="bg-white rounded-lg shadow p-6">
        <h4 className="text-lg font-semibold text-gray-900 mb-4">
          {t('totalInventory.aahByDbh')}
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_dbh_aah_table}}'}</code>
          <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_dbh_aah_narration}}'}</code>
      <BasisBadge basis="mixed" />
        </h4>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitLabelNp}</th>
                <th rowSpan={2} className="px-3 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.dbhClass')}</th>
                <th colSpan={3} className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-amber-50 border-r border-gray-300">AAH</th>
                </tr>
                <tr>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.aahPerHaYr')}</th>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.totalTimberM3')}</th>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.totalAahYr')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {totalData.blocks.map((block: any, bi: number) => {
                  const dbhData = block.dbh_class_totals || {};
                  const blockAahTotal = block.total_aah_m3 || 0;
                  const ha = block.area_ha || 1;
                  const blockVolume = (Object.values(dbhData) as any[]).reduce((s: number, d: any) => s + (d.total_tree_volume_m3 || 0), 0);
                  const blockTimberVol = (Object.values(dbhData) as any[]).reduce((s: number, d: any) => s + (d.total_timber_m3 || 0), 0);
                  const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                    const d = dbhData[key];
                    if (!d) return [];
                    const classVol = d.total_tree_volume_m3 || 0;
                    const classTimber = d.total_timber_m3 || 0;
                    const aahTotal = blockVolume > 0 ? (classVol / blockVolume) * blockAahTotal : 0;
                    const aahTimber = blockTimberVol > 0 ? (classTimber / blockTimberVol) * blockAahTotal : 0;
                    return { key, label, aah_per_ha: aahTotal / ha, aah_total: aahTotal, aah_timber: aahTimber };
                  });
                  if (rows.length === 0) return null;
                  const subtotal = {
                    per_ha: rows.reduce((s, r) => s + r.aah_per_ha, 0),
                    timber: rows.reduce((s, r) => s + r.aah_timber, 0),
                    total: rows.reduce((s, r) => s + r.aah_total, 0),
                  };
                  return [
                    ...rows.map((r, ri) => (
                      <tr key={`${bi}_aah_${ri}`} className={ri === 0 ? 'border-t border-gray-200' : ''}>
                        {ri === 0 && (
                          <td rowSpan={rows.length + 1} className="px-3 py-2 text-sm font-medium text-gray-900 border-r border-gray-200 align-top">{block.block_name}</td>
                        )}
                        <td className="px-3 py-2 text-sm text-gray-700 border-r border-gray-200">{r.label}</td>
                        <td className="px-2 py-2 text-sm text-right">{fmtPH(r.aah_per_ha)}</td>
                        <td className="px-2 py-2 text-sm text-right">{fmt(r.aah_timber)}</td>
                        <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(r.aah_total)}</td>
                      </tr>
                    )),
                    <tr key={`${bi}_aah_sub`} className="bg-amber-50 font-semibold">
                      <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{t('totalInventory.rowTotal', { name: block.block_name })}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmtPH(subtotal.per_ha)}</td>
                      <td className="px-2 py-2 text-sm text-right">{fmt(subtotal.timber)}</td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(subtotal.total)}</td>
                    </tr>,
                  ];
                })}
                {totalData.forest_totals?.dbh_class_totals && (() => {
                  const ftArea = totalData.forest_totals.total_area_ha || 1;
                  const ftAah = totalData.forest_totals.total_aah_m3_per_year || 0;
                  const ftDBH = totalData.forest_totals.dbh_class_totals;
                  const ftVolume = (Object.values(ftDBH) as any[]).reduce((s: number, d: any) => s + (d.total_tree_volume_m3 || 0), 0);
                  const ftTimberVol = (Object.values(ftDBH) as any[]).reduce((s: number, d: any) => s + (d.total_timber_m3 || 0), 0);
                  const rows = DBH_CLASS_CONFIG.flatMap(({ key, label }) => {
                    const d = ftDBH[key];
                    if (!d) return [];
                    const classVol = d.total_tree_volume_m3 || 0;
                    const classTimber = d.total_timber_m3 || 0;
                    const aahTotal = ftVolume > 0 ? (classVol / ftVolume) * ftAah : 0;
                    const aahTimber = ftTimberVol > 0 ? (classTimber / ftTimberVol) * ftAah : 0;
                    return { key, label, aah_per_ha: aahTotal / ftArea, aah_total: aahTotal, aah_timber: aahTimber };
                  });
                  const fsub = { per_ha: rows.reduce((s, r) => s + r.aah_per_ha, 0), timber: rows.reduce((s, r) => s + r.aah_timber, 0), total: rows.reduce((s, r) => s + r.aah_total, 0) };
                  return (
                    <>
                      {rows.map((r, ri) => (
                        <tr key={`ft_aah_${ri}`} className="bg-green-100 font-bold">
                          {ri === 0 && <td rowSpan={rows.length + 1} className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.totalForest')}</td>}
                          <td className="px-3 py-2 text-sm text-gray-900 border-r border-gray-200">{r.label}</td>
                          <td className="px-2 py-2 text-sm text-right">{fmtPH(r.aah_per_ha)}</td>
                          <td className="px-2 py-2 text-sm text-right">{fmt(r.aah_timber)}</td>
                          <td className="px-2 py-2 text-sm text-right border-r border-gray-300">{fmt(r.aah_total)}</td>
                        </tr>
                      ))}
                      <tr key="ft_aah_sub" className="bg-green-100 font-bold border-t-2 border-green-400">
                        <td className="px-3 py-3 text-sm font-bold text-gray-900 border-r border-gray-200">{t('totalInventory.forestTotal')}</td>
                        <td className="px-2 py-3 text-sm text-right">{fmtPH(fsub.per_ha)}</td>
                        <td className="px-2 py-3 text-sm text-right">{fmt(fsub.timber)}</td>
                        <td className="px-2 py-3 text-sm text-right border-r border-gray-300">{fmt(fsub.total)}</td>
                      </tr>
                    </>
                  );
                })()}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Charts: Species Composition Pie Chart + Block-wise Bar Chart */}
      {totalData.species_breakdown && totalData.species_breakdown.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-4">
            {t('totalInventory.speciesAndUnitComparison', { unit: dimensionUnit(labels) })}
          </h4>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Species Composition Pie Chart */}
            <div className="bg-gray-50 rounded-lg p-4">
              <h5 className="text-sm font-semibold text-gray-700 mb-3 text-center">
                {t('totalInventory.speciesCompositionLocal')}
                <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_species_composition_narration}}'}</code>
              </h5>
              {(() => {
                const speciesChartData = buildSpeciesChartData(totalData.species_breakdown);
                return speciesChartData ? (
                  <Pie
                    data={speciesChartData}
                    options={{
                      responsive: true,
                      plugins: {
                        legend: {
                          position: 'right',
                          labels: { font: { size: 11 }, boxWidth: 12, padding: 8 },
                        },
                        tooltip: {
                          callbacks: {
                            label: (ctx: any) => {
                              const label = ctx.label || '';
                              const val = ctx.parsed || 0;
                              const total = ctx.dataset.data.reduce((a: number, b: number) => a + b, 0);
                              const pct = total > 0 ? ((val / total) * 100).toFixed(1) : '0.0';
                              return `${label}: ${formatNumber(val)} (${pct}%)`;
                            },
                          },
                        },
                      },
                    }}
                  />
                  ) : (
                    <p className="text-sm text-gray-500 text-center py-8">{t('totalInventory.noSpeciesData')}</p>
                  );
                })()}
                {(() => {
                  // Name the species the lumped slice covers. A bar labelled
                  // "Other (7 species)" is a summary; without this line it is
                  // where seven species quietly went missing.
                  const tail = speciesChartTailNames(totalData.species_breakdown);
                  if (!tail.length) return null;
                  return (
                    <p className="mt-3 text-xs text-gray-500 text-center" data-testid="species-chart-tail">
                      {t('totalInventory.speciesChartTail', { names: tail.join(', ') })}
                    </p>
                  );
                })()}
              </div>
            {/* Block-wise Growing Stock Bar Chart */}

            {/* Block-wise Growing Stock Bar Chart */}
            <div className="bg-gray-50 rounded-lg p-4">
              <h5 className="text-sm font-semibold text-gray-700 mb-3 text-center">
                {t('totalInventory.unitWiseGrowingStock', { unit: dimensionUnit(labels) })}
                <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_productivity_narration}}'}</code>
              </h5>
              {(() => {
                const barChartData = buildBlockBarChartData(totalData.blocks);
                return barChartData ? (
                  <Bar
                    data={barChartData}
                    options={{
                      responsive: true,
                      indexAxis: 'y',
                      plugins: {
                        legend: { display: false },
                        tooltip: {
                          callbacks: {
                            label: (ctx: any) => `${ctx.parsed.x?.toLocaleString() || 0} m³`,
                          },
                        },
                      },
                      scales: {
                        x: {
                          beginAtZero: true,
                          title: { display: true, text: 'm³', font: { size: 11 } },
                          ticks: { font: { size: 10 } },
                        },
                        y: {
                          ticks: { font: { size: 10 } },
                        },
                      },
                    }}
                  />
                ) : (
                  <p className="text-sm text-gray-500 text-center py-8">{t('totalInventory.noUnitData', { unit: dimensionUnit(labels) })}</p>
                );
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Economic Valuation */}

      {/* Economic Valuation */}
      {totalData.blocks && totalData.blocks.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-4">
            {t('totalInventory.economicValuation')}
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_economic_valuation_table}}'}</code>
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_economic_narration}}'}</code>
      <BasisBadge basis="absolute" />
          </h4>
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th rowSpan={2} className="px-2 py-3 text-left text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{labels.unitLabelNp}</th>
                  <th rowSpan={2} className="px-2 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.totalGrowingStockM3')}</th>
                  <th colSpan={2} className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-blue-50 border-r border-gray-300">{t('totalInventory.timber')}</th>
                  <th colSpan={2} className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-amber-50 border-r border-gray-300">{t('totalInventory.firewood')}</th>
                  <th rowSpan={2} className="px-2 py-3 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.totalRs')}</th>
                  <th colSpan={2} className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase bg-teal-50 border-r border-gray-300">{t('totalInventory.carbon')}</th>
                  <th rowSpan={2} className="px-2 py-3 text-right text-xs font-medium text-gray-500 uppercase">{t('totalInventory.sumRs')}</th>
                </tr>
                <tr>
                  <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.ratePerM3')}</th>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.value')}</th>
                  <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.ratePerM3')}</th>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.value')}</th>
                  <th className="px-2 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('totalInventory.ratePerTco2')}</th>
                  <th className="px-2 py-2 text-right text-xs font-medium text-gray-500 uppercase border-r border-gray-300">{t('totalInventory.value')}</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {totalData.blocks.map((block: any, bi: number) => {
                  const gs = block.total_growing_stock_m3 || 0;
                  const rate = getBlockRate(block.block_name);
                  const timberVol = (block.total_pole_timber_m3 || 0) + (block.total_tree_timber_m3 || 0);
                  const firewoodVol = (block.total_pole_firewood_m3 || 0) + (block.total_tree_firewood_m3 || 0);
                  const co2 = block.total_co2_tco2 || 0;
                  const timberVal = timberVol * rate.timber;
                  const fuelwoodVal = firewoodVol * rate.fuelwood;
                  const carbonVal = co2 * rate.carbon;
                  const totalVal = timberVal + fuelwoodVal + carbonVal;
                  return (
                    <tr key={bi} className="hover:bg-gray-50">
                      <td className="px-2 py-2 text-sm font-medium text-gray-900 border-r border-gray-200">{block.block_name}</td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-200">{formatNumber(gs)}</td>
                      <td className="px-2 py-2 text-center border-r border-gray-200">
                        <input
                          type="text" inputMode="decimal"
                          value={rate.timber}
                          onChange={(e) => setBlockRates((prev) => ({ ...prev, [block.block_name]: { ...prev[block.block_name], timber: Math.max(0, parseLocaleNumber(e.target.value)) } }))}
                          className="w-20 px-1 py-0.5 border border-blue-300 rounded text-xs text-right"
                          min={0}
                        />
                      </td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-200">{formatNumber(timberVal)}</td>
                      <td className="px-2 py-2 text-center border-r border-gray-200">
                        <input
                          type="text" inputMode="decimal"
                          value={rate.fuelwood}
                          onChange={(e) => setBlockRates((prev) => ({ ...prev, [block.block_name]: { ...prev[block.block_name], fuelwood: Math.max(0, parseLocaleNumber(e.target.value)) } }))}
                          className="w-20 px-1 py-0.5 border border-amber-300 rounded text-xs text-right"
                          min={0}
                        />
                      </td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-200">{formatNumber(fuelwoodVal)}</td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-200 font-medium">{formatNumber((timberVal + fuelwoodVal))}</td>
                      <td className="px-2 py-2 text-center border-r border-gray-200">
                        <input
                          type="text" inputMode="decimal"
                          value={rate.carbon}
                          onChange={(e) => setBlockRates((prev) => ({ ...prev, [block.block_name]: { ...prev[block.block_name], carbon: Math.max(0, parseLocaleNumber(e.target.value)) } }))}
                          className="w-20 px-1 py-0.5 border border-teal-300 rounded text-xs text-right"
                          min={0}
                        />
                      </td>
                      <td className="px-2 py-2 text-sm text-right border-r border-gray-200">{formatNumber(carbonVal)}</td>
                      <td className="px-2 py-2 text-sm text-right font-semibold text-green-700">{formatNumber(totalVal)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Sustainability Index */}
      {totalData.blocks && totalData.blocks.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h4 className="text-lg font-semibold text-gray-900 mb-4">
            {t('totalInventory.sustainabilityIndex')}
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{ti_sustainability_table}}'}</code>
            <code className="ml-2 text-xs text-blue-600 font-mono bg-blue-50 px-1.5 py-0.5 rounded border border-blue-200 select-all">{'{{section:ti_sustainability_narration}}'}</code>
      <BasisBadge basis="absolute" />
          </h4>

          {/* Methodology Summary */}
          <div className="mb-6 p-4 bg-blue-50 rounded-lg border border-blue-200 text-xs text-blue-900 space-y-2">
            <p className="font-semibold text-sm">{t('totalInventory.methodology')}</p>
            <ul className="list-disc pl-5 space-y-1">
              <li><strong>{t('totalInventory.siLabel')}</strong> {t('totalInventory.siFormula')}</li>
              <li><strong>{t('totalInventory.hpLabel')}</strong> {t('totalInventory.hpFormula')}</li>
              <li><strong>{t('totalInventory.growingStockPerHa')}</strong> {t('totalInventory.gsFormula', { unit: dimensionUnit(labels) })}</li>
            </ul>
            <p className="mt-2 pt-2 border-t border-blue-200 text-blue-700">
              <strong>{t('totalInventory.englishLabel')}</strong> SI = (AAH / Productive Growing Stock) × 100 — harvest rate against total stock. HP = (AAH / MAI) × 100 — harvest pressure against annual growth. GS/ha = Productive Growing Stock / block area.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {totalData.blocks.map((block: any, bi: number) => {
              const gs = block.total_growing_stock_m3 || 0;
              const mai = block.total_mai_m3 || 1;
              const aah = block.total_aah_m3 || 0;
              const sustainabilityIndex = gs > 0 ? (aah / gs) * 100 : 0;
              const harvestingPressure = mai > 0 ? (aah / mai) * 100 : 0;
              return (
                <div key={bi} className="p-4 bg-gray-50 rounded-lg border border-gray-200">
                  <h5 className="text-sm font-semibold text-gray-900 mb-2">{block.block_name}</h5>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600">{t('totalInventory.siColon')}</span>
                      <span className={`font-semibold ${sustainabilityIndex < 5 ? 'text-green-600' : sustainabilityIndex < 10 ? 'text-yellow-600' : 'text-red-600'}`}>
                        {formatDecimal(sustainabilityIndex, 2)}%
                        <span className={`ml-1 text-xs ${sustainabilityIndex < 5 ? 'text-green-600' : sustainabilityIndex < 10 ? 'text-yellow-600' : 'text-red-600'}`}>
                          ({sustainabilityIndex < 5 ? t('totalInventory.siSustainable') : sustainabilityIndex < 10 ? t('totalInventory.siModerate') : t('totalInventory.siOverused')})
                        </span>
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600">{t('totalInventory.hpColon')}</span>
                      <span className={`font-semibold ${harvestingPressure < 50 ? 'text-green-600' : harvestingPressure < 80 ? 'text-yellow-600' : 'text-red-600'}`}>
                        {formatDecimal(harvestingPressure, 1)}%
                        <span className={`ml-1 text-xs ${harvestingPressure < 50 ? 'text-green-600' : harvestingPressure < 80 ? 'text-yellow-600' : 'text-red-600'}`}>
                          ({harvestingPressure < 50 ? t('totalInventory.hpLow') : harvestingPressure < 80 ? t('totalInventory.hpModerate') : t('totalInventory.hpHigh')})
                        </span>
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600">{t('totalInventory.growingStockPerHaColon')}</span>
                      <span className="font-semibold">{formatDecimal((gs / (block.area_ha || 1)), 1)} m³
                        <span className={`ml-1 text-xs ${(gs / (block.area_ha || 1)) > 200 ? 'text-green-600' : (gs / (block.area_ha || 1)) >= 50 ? 'text-yellow-600' : 'text-red-600'}`}>
                          ({(gs / (block.area_ha || 1)) > 200 ? t('totalInventory.gsGood') : (gs / (block.area_ha || 1)) >= 50 ? t('totalInventory.gsModerate') : t('totalInventory.gsLow')})
                        </span>
                      </span>
                    </div>

                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
};