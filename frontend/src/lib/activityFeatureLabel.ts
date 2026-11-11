/**
 * How an Activity Features map feature is named on screen: "<activity> · Year 1".
 *
 * Features used to be labelled with the drawing tool's counter ("Feature 1", "Feature 2"),
 * which restarts each session, so the same names appeared under different activities and said
 * nothing about what the feature was. The label now comes from what the feature *is*: the
 * activity it belongs to and the plan year(s) it applies to.
 *
 * - A name the user typed is kept ("Baseshi plantation · Year 1").
 * - A default name (the old "Feature N", or the activity's own name) is replaced by the activity.
 * - Years are compressed: 1, 2, 4 -> "1, 2, 4"; 1, 2, 3, 4 -> "1–4".
 * - Two features that would read identically are numbered, so they can be told apart.
 *
 * Pure functions: the caller passes `t` and the number formatter, which is what makes them
 * testable and lets the language decide the year word and the digits.
 */
import i18n from 'i18next';
import { formatNumber } from '../i18n/numberFormat';

export type Translate = (key: string, options?: Record<string, unknown>) => string;

export interface LabelOptions {
  t?: Translate;
  format?: (n: number) => string;
}

/** The counter names the drawing tool used to save. */
const DEFAULT_FEATURE_NAME = /^\s*Feature\s+\d+\s*$/i;

const defaultT: Translate = (key, options) => String(i18n.t(key, options as never));

/** `[1, 2, 4]` -> "1, 2, 4"; `[1, 2, 3, 4]` -> "1–4". Three or more in a row become a range. */
export function formatYears(years: number[], format: (n: number) => string = formatNumber): string {
  const ys = [...new Set(years.filter((y) => Number.isFinite(y)))].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < ys.length; ) {
    let j = i;
    while (j + 1 < ys.length && ys[j + 1] === ys[j] + 1) j++;
    parts.push(j - i >= 2 ? `${format(ys[i])}–${format(ys[j])}` : ys.slice(i, j + 1).map(format).join(', '));
    i = j + 1;
  }
  return parts.join(', ');
}

/** The years a feature applies to, from either `years` (array) or the older single `year`. */
export function featureYears(props: Record<string, unknown> | null | undefined): number[] {
  const raw = props?.years;
  if (Array.isArray(raw)) return raw.map(Number).filter((y) => Number.isFinite(y));
  const one = Number(props?.year);
  return Number.isFinite(one) && props?.year != null ? [one] : [];
}

/** The first part of the label: what the user called it, else the activity it belongs to. */
export function activityFeatureBase(
  props: Record<string, unknown> | null | undefined,
  t: Translate = defaultT,
): string {
  const custom = String(props?.name ?? '').trim();
  const activity = String(props?.activity_name ?? '').trim();
  if (custom && !DEFAULT_FEATURE_NAME.test(custom) && custom !== activity) return custom;
  return activity || t('layer.activityFeatureFallback');
}

/** "<activity or custom name> · Year 1" (no suffix when the feature has no year). */
export function activityFeatureLabel(
  props: Record<string, unknown> | null | undefined,
  { t = defaultT, format = formatNumber }: LabelOptions = {},
): string {
  const base = activityFeatureBase(props, t);
  const years = featureYears(props);
  if (years.length === 0) return base;
  const suffix =
    years.length === 1
      ? t('yearlyActivities.page.yearN', { year: format(years[0]) })
      : t('yearlyActivities.page.yearsN', { years: formatYears(years, format) });
  return `${base} · ${suffix}`;
}

/**
 * Number labels that would otherwise read the same: "X · Year 1 (1)", "X · Year 1 (2)".
 * Oldest first, so a feature keeps its number as new ones are added. Unique labels are untouched.
 */
export function disambiguateLabels<T extends { label: string; createdAt?: string | null }>(
  items: T[],
  format: (n: number) => string = formatNumber,
): string[] {
  const groups = new Map<string, number[]>();
  items.forEach((it, i) => groups.set(it.label, [...(groups.get(it.label) ?? []), i]));
  const out = items.map((it) => it.label);
  for (const idxs of groups.values()) {
    if (idxs.length < 2) continue;
    idxs
      .slice()
      .sort((a, b) => String(items[a].createdAt ?? '').localeCompare(String(items[b].createdAt ?? '')) || a - b)
      .forEach((itemIdx, n) => {
        out[itemIdx] = `${items[itemIdx].label} (${format(n + 1)})`;
      });
  }
  return out;
}
