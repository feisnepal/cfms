/**
 * One row per polygon for the sampling form - for ANY forest, with or without a forest type or plots.
 *
 * - The checkbox chooses which polygons get sample plots. Nothing ticked = every polygon that can be sampled; once any is ticked, only
 *   the ticked ones (the others are sent as 0 % = "do not sample this unit").
 * - The stratum (production / conservation / protection) is proposed from the unit's own setting, SFM, the slope or a protected area,
 *   and says why. Changing it is saved on the unit's orientation, so SFM and the Operational Plan agree. It sets the legal minimum
 *   intensity and plot size (कार्यविधि §16).
 * - The intensity says how many plots to expect: the row shows the number it amounts to and the number we SUGGEST (never fewer than 5).
 *   The user may then type any number of plots - more or fewer, fewer than 5 included - and sees the intensity it amounts to. The only
 *   limits are the legal ones: at least the stratum's minimum intensity, at most 5 %. 0 leaves the polygon out.
 * - A polygon that already has plots cannot be sampled again. Its checkbox is disabled, the row says so in writing, and the hover
 *   tells the user what to do next: delete that polygon's plots first (possible only while no field inventory exists).
 */
import { useT } from '../../i18n/hooks';
import { parseLocaleNumber } from '../../i18n/numberFormat';
import { slopeBandLabel } from '../../lib/sfmFeatureProps';
import type { SamplingSuggestion, SamplingUnitRow } from '../../services/api';

export const STRATA: Array<SamplingUnitRow['stratum']> = ['production', 'conservation', 'protection'];
const ORIENTATION_OF: Record<SamplingUnitRow['stratum'], 'Production' | 'Conservation' | 'Protection'> = {
  production: 'Production',
  conservation: 'Conservation',
  protection: 'Protection',
};
const SOURCE_KEY: Record<SamplingUnitRow['stratum_source'], string> = {
  user: 'sampling.unitTable.source.user',
  sfm: 'sampling.unitTable.source.sfm',
  slope: 'sampling.unitTable.source.slope',
  protected_area: 'sampling.unitTable.source.protected_area',
  working_circle: 'sampling.unitTable.source.working_circle',
  default: 'sampling.unitTable.source.default',
};
export const orientationFor = (s: SamplingUnitRow['stratum']) => ORIENTATION_OF[s];

/** The highest intensity the system accepts for a polygon (percent). */
export const MAX_INTENSITY_PCT = 5;

/** One arrow-key step of the intensity cell: 0.1 up or down, kept to one decimal (0.1 + 0.2 must not become 0.30000000000000004)
 *  and never below 0. There is no upper stop: going above the usual 5 % is allowed (the row warns). A non-number starts from 0. */
export const INTENSITY_ARROW_STEP = 0.1;
export function stepIntensity(current: number, direction: 1 | -1): number {
  const base = Number.isFinite(current) ? current : 0;
  const next = Math.round((base + direction * INTENSITY_ARROW_STEP) * 10) / 10;
  return Math.max(0, next);
}

/** The intensity one plot amounts to in this polygon (percent): plot size / polygon area. */
export const perPlotPct = (r: SamplingUnitRow): number => (r.area_ha > 0 ? (r.plot_size_sqm / (r.area_ha * 10_000)) * 100 : 0);

/** The legal range of plots for a polygon: at least the stratum's minimum intensity, at most the 5 % ceiling. */
export function legalRange(r: SamplingUnitRow): { min: number; max: number } {
  const one = perPlotPct(r);
  return one > 0 ? { min: Math.ceil(r.floor_pct / one - 1e-9), max: Math.floor(MAX_INTENSITY_PCT / one + 1e-9) } : { min: 0, max: 0 };
}

/** 'low' when a number of plots is BELOW the polygon's legal minimum (this stops the design); null when it is fine (0 = left out is
 *  fine). More than the usual 5 % is not a problem here - it is only a warning, see ``plotCountWarning``. */
export function plotCountProblem(r: SamplingUnitRow, count: number | undefined): 'low' | null {
  if (count == null || Number.isNaN(count) || count === 0) return null;
  return count < legalRange(r).min ? 'low' : null;
}

/** True when a number of plots amounts to more than the usual 5 % ceiling: allowed, but the user is told. */
export function plotCountWarning(r: SamplingUnitRow, count: number | undefined): boolean {
  if (count == null || Number.isNaN(count) || count === 0) return false;
  return count > legalRange(r).max;
}

/** True when an intensity is above the usual 5 % ceiling: allowed, but the user is told. */
export function intensityWarning(value: number): boolean {
  return Number.isFinite(value) && value > MAX_INTENSITY_PCT;
}

interface Props {
  rows: SamplingUnitRow[];
  fieldDataExists: boolean;
  ticked: Set<string>;
  /** typed intensities by polygon name; a polygon without one uses its minimum */
  intensities: Record<string, number>;
  /** the number of plots each polygon's intensity amounts to, and what we suggest (from the server), by polygon name */
  suggestions?: Record<string, SamplingSuggestion>;
  /** the usual minimum we suggest (5) */
  minSuggested?: number;
  /** plots the user typed, by polygon name; a polygon without one uses the suggestion */
  plots?: Record<string, number>;
  /** polygons selected on the map (feature ids), if any */
  mapSelectedIds?: string[];
  busyUnit?: string | null;
  stratumLabel: (stratum: string) => string;
  onToggle: (name: string) => void;
  onTickAll: () => void;
  onTickNone: () => void;
  onTickFromMap?: () => void;
  onIntensity: (name: string, value: number) => void;
  onPlots?: (name: string, value: number) => void;
  onResetPlots?: (name: string) => void;
  onStratum: (row: SamplingUnitRow, stratum: SamplingUnitRow['stratum']) => void;
  onDeletePlots: (row: SamplingUnitRow) => void;
}

export function SamplingUnitTable(p: Props) {
  const t = useT();
  const minSuggested = p.minSuggested ?? 5;
  const sampleable = p.rows.filter((r) => r.sampled_plots === 0);
  const anyTicked = sampleable.some((r) => p.ticked.has(r.name));
  const willSample = (r: SamplingUnitRow) => r.sampled_plots === 0 && (!anyTicked || p.ticked.has(r.name));
  const value = (r: SamplingUnitRow) => p.intensities[r.name] ?? r.floor_pct;
  const mapHits = (p.mapSelectedIds ?? []).filter((id) => p.rows.some((r) => r.unit_id === id && r.sampled_plots === 0));

  const sampledHover = (r: SamplingUnitRow): string =>
    p.fieldDataExists
      ? t('sampling.unitTable.sampledHoverLocked', {
          defaultValue:
            '{{name}} already has {{n}} sample plots, and field inventory data now exists, so its plots can no longer be deleted here. To sample it again, delete the field inventory first, then delete this polygon\'s plots.',
          name: r.name,
          n: r.sampled_plots,
        })
      : t('sampling.unitTable.sampledHover', {
          defaultValue:
            '{{name}} already has {{n}} sample plots, so it cannot be sampled again. To sample it again, first delete its plots with "Delete this polygon\'s plots" in this row, then tick it.',
          name: r.name,
          n: r.sampled_plots,
        });

  return (
    <div data-testid="sampling-unit-table">
      <div className="flex flex-wrap items-center gap-2 text-xs mb-2">
        <button type="button" className="underline text-emerald-800" onClick={p.onTickAll} data-testid="unit-tick-all">
          {t('sampling.unitTable.tickAll', { defaultValue: 'Tick all' })}
        </button>
        <button type="button" className="underline text-emerald-800" onClick={p.onTickNone} data-testid="unit-tick-none">
          {t('sampling.unitTable.clear', { defaultValue: 'Clear' })}
        </button>
        {p.onTickFromMap && mapHits.length > 0 && (
          <button type="button" className="underline text-emerald-800" onClick={p.onTickFromMap} data-testid="unit-tick-map">
            {t('sampling.unitTable.fromMap', { defaultValue: 'Use the {{n}} polygon(s) selected on the map', n: mapHits.length })}
          </button>
        )}
        <span className="text-gray-600" data-testid="unit-selection-note">
          {anyTicked
            ? t('sampling.unitTable.onlyTicked', { defaultValue: 'Only the ticked polygons will get sample plots.' })
            : t('sampling.unitTable.allUnticked', { defaultValue: 'Nothing is ticked: every polygon without plots will be sampled.' })}
        </span>
      </div>

      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="text-left text-gray-600 border-b border-emerald-200">
            <th className="py-1 pr-2 w-6" />
            <th className="py-1 pr-2">{t('sampling.unitTable.polygon', { defaultValue: 'Polygon' })}</th>
            <th className="py-1 pr-2">{t('sampling.unitTable.area', { defaultValue: 'Area (ha)' })}</th>
            <th className="py-1 pr-2">{t('sampling.unitTable.slope', { defaultValue: 'Slope' })}</th>
            <th className="py-1 pr-2">{t('sampling.stratumTableStratum')}</th>
            <th className="py-1 pr-2">{t('sampling.stratumTableFloor')}</th>
            <th className="py-1 pr-2">{t('sampling.stratumTablePlotSize')}</th>
            <th className="py-1 pr-2">{t('sampling.intensityPct')}</th>
            <th className="py-1 pr-2">{t('sampling.unitTable.suggested', { defaultValue: 'Suggested plots' })}</th>
            <th className="py-1">{t('sampling.unitTable.plots', { defaultValue: 'Plots' })}</th>
          </tr>
        </thead>
        <tbody>
          {p.rows.map((r) => {
            const sampled = r.sampled_plots > 0;
            const v = value(r);
            const sampling = willSample(r);
            const sug = p.suggestions?.[r.name];
            const typed = p.plots?.[r.name];
            const count = typed ?? sug?.suggested;
            const excluded = sampling && (v === 0 || count === 0);
            const below = sampling && v !== 0 && (Number.isNaN(v) || v < r.floor_pct);
            const problem = sampling ? plotCountProblem(r, count) : null;
            const range = legalRange(r);
            const equivalent = count != null && count > 0 ? count * perPlotPct(r) : null;
            const fewer = sampling && !problem && count != null && count > 0 && count < minSuggested;
            return (
              <tr key={r.unit_id} className={`border-b border-emerald-100 align-top ${sampled ? 'bg-gray-50 text-gray-500' : ''}`} data-testid={`unit-row-${r.name}`}>
                <td className="py-1 pr-2">
                  <input
                    type="checkbox"
                    checked={!sampled && p.ticked.has(r.name)}
                    disabled={sampled}
                    onChange={() => p.onToggle(r.name)}
                    title={sampled ? sampledHover(r) : undefined}
                    aria-label={t('sampling.unitTable.tickUnit', { defaultValue: 'Sample {{name}}', name: r.name })}
                    data-testid={`unit-tick-${r.name}`}
                  />
                </td>
                <td className="py-1 pr-2">
                  <div className="font-medium">{r.display_name ?? r.name}</div>
                  {sampled && (
                    <div className="mt-0.5 text-amber-800" data-testid={`unit-sampled-${r.name}`} title={sampledHover(r)}>
                      {t('sampling.unitTable.sampledNote', {
                        defaultValue: 'Already has {{n}} sample plots. To sample it again, first delete its plots.',
                        n: r.sampled_plots,
                      })}
                      <button
                        type="button"
                        className="ml-2 underline disabled:opacity-50 disabled:no-underline"
                        disabled={p.fieldDataExists || p.busyUnit === r.name}
                        onClick={() => p.onDeletePlots(r)}
                        title={p.fieldDataExists ? sampledHover(r) : undefined}
                        data-testid={`unit-delete-plots-${r.name}`}
                      >
                        {t('sampling.unitTable.deletePlots', { defaultValue: 'Delete this polygon\'s plots' })}
                      </button>
                    </div>
                  )}
                </td>
                <td className="py-1 pr-2">{r.area_ha}</td>
                <td className="py-1 pr-2">{slopeBandLabel(r.slope_band) ?? '—'}</td>
                <td className="py-1 pr-2">
                  <select
                    value={r.stratum}
                    disabled={p.busyUnit === r.name}
                    onChange={(e) => p.onStratum(r, e.target.value as SamplingUnitRow['stratum'])}
                    className="border border-gray-300 rounded px-1 py-0.5 bg-white"
                    aria-label={t('sampling.unitTable.stratumOf', { defaultValue: 'Stratum of {{name}}', name: r.name })}
                    data-testid={`unit-stratum-${r.name}`}
                  >
                    {STRATA.map((s) => (
                      <option key={s} value={s}>{p.stratumLabel(s)}</option>
                    ))}
                  </select>
                  <div className="text-[10px] text-gray-500" data-testid={`unit-source-${r.name}`}>
                    {t(SOURCE_KEY[r.stratum_source] ?? 'sampling.unitTable.source.default')}
                  </div>
                </td>
                <td className="py-1 pr-2">{r.floor_pct}%</td>
                <td className="py-1 pr-2">{r.plot_size_sqm} m²</td>
                <td className="py-1 pr-2">
                  <input
                    type="text"
                    inputMode="decimal"
                    value={v}
                    disabled={sampled}
                    onChange={(e) => p.onIntensity(r.name, parseLocaleNumber(e.target.value))}
                    onKeyDown={(e) => {
                      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
                      e.preventDefault(); // the arrows change the number, they do not move the caret
                      p.onIntensity(r.name, stepIntensity(v, e.key === 'ArrowUp' ? 1 : -1));
                    }}
                    data-testid={`unit-intensity-${r.name}`}
                    className={`w-16 px-1.5 py-0.5 border rounded ${below ? 'border-red-500 bg-red-50 text-red-800' : 'border-gray-300'}`}
                    aria-label={t('sampling.stratumTableIntensityFor', { block: r.name })}
                  />
                  {below && <div className="text-red-600 mt-0.5">{t('sampling.stratumBelowFloor', { floor: r.floor_pct })}</div>}
                  {sampling && intensityWarning(v) && (
                    <div className="text-amber-700 mt-0.5" data-testid={`unit-intensity-above-${r.name}`}>
                      {t('sampling.unitTable.intensityAboveUsual', { max: MAX_INTENSITY_PCT })}
                    </div>
                  )}
                </td>
                <td className="py-1 pr-2" data-testid={`unit-suggested-${r.name}`}>
                  {sampled || !sampling || !sug ? (
                    '—'
                  ) : (
                    <>
                      <div className="font-medium">{sug.suggested}</div>
                      {sug.raised_to_minimum && (
                        <div className="text-[10px] text-gray-500" data-testid={`unit-raised-${r.name}`}>
                          {t('sampling.unitTable.raisedToMinimum', {
                            defaultValue: 'The intensity gives {{n}}; we suggest at least {{min}}.',
                            n: sug.computed,
                            min: minSuggested,
                          })}
                        </div>
                      )}
                    </>
                  )}
                </td>
                <td className="py-1">
                  {sampling && p.onPlots ? (
                    <>
                      <div className="flex items-center gap-1">
                        <input
                          type="text"
                          inputMode="numeric"
                          value={count ?? ''}
                          onChange={(e) => p.onPlots?.(r.name, Math.max(0, Math.trunc(parseLocaleNumber(e.target.value) || 0)))}
                          className={`w-14 px-1.5 py-0.5 border rounded ${problem ? 'border-red-500 bg-red-50 text-red-800' : 'border-gray-300'}`}
                          aria-label={t('sampling.unitTable.plotsFor', { defaultValue: 'Number of plots in {{name}}', name: r.name })}
                          data-testid={`unit-plots-${r.name}`}
                        />
                        {typed != null && sug && typed !== sug.suggested && (
                          <button
                            type="button"
                            className="underline text-emerald-800"
                            onClick={() => p.onResetPlots?.(r.name)}
                            title={t('sampling.unitTable.useSuggestion', { defaultValue: 'Use the suggested number ({{n}})', n: sug.suggested })}
                            data-testid={`unit-plots-reset-${r.name}`}
                          >
                            ↺
                          </button>
                        )}
                      </div>
                      {typed != null && sug && typed !== sug.suggested && (
                        <div className="text-[10px] text-gray-600" data-testid={`unit-deviation-${r.name}`}>
                          {typed > sug.suggested
                            ? t('sampling.unitTable.deviationMore', { defaultValue: '{{n}} more than suggested', n: typed - sug.suggested })
                            : t('sampling.unitTable.deviationFewer', { defaultValue: '{{n}} fewer than suggested', n: sug.suggested - typed })}
                        </div>
                      )}
                      {equivalent != null && (
                        <div className="text-[10px] text-gray-500" data-testid={`unit-equivalent-${r.name}`}>
                          {t('sampling.unitTable.equivalent', { defaultValue: '= {{pct}} % intensity', pct: equivalent.toFixed(2) })}
                        </div>
                      )}
                      {problem && (
                        <div className="text-red-600 mt-0.5" data-testid={`unit-plots-problem-${r.name}`}>
                          {t('sampling.unitTable.plotsTooFew', { min: range.min, floor: r.floor_pct })}
                        </div>
                      )}
                      {sampling && plotCountWarning(r, count) && (
                        <div className="text-amber-700 mt-0.5" data-testid={`unit-plots-above-${r.name}`}>
                          {t('sampling.unitTable.plotsAboveUsual', { n: count, max: range.max })}
                        </div>
                      )}
                      {fewer && (
                        <div className="text-amber-700 mt-0.5" data-testid={`unit-plots-fewer-${r.name}`}>
                          {t('sampling.unitTable.fewerThanUsual', {
                            defaultValue: 'Fewer than the usual {{min}} plots. Allowed here; we suggest at least {{min}}.',
                            min: minSuggested,
                          })}
                        </div>
                      )}
                      {excluded && <div className="text-amber-700 mt-0.5">{t('sampling.stratumUnitExcluded')}</div>}
                    </>
                  ) : (
                    '—'
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
