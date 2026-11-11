import i18n from './index'

/**
 * Locale-aware number formatting (Phase 0.4; D6 revised 2026-08-18).
 *
 * Numerals follow the active language: Nepali renders Devanagari digits with
 * lakh grouping (१२,३४,५६७.८९), English renders ASCII with thousands grouping
 * (1,234,567.89). The earlier policy forced `-u-nu-latn` so Nepali data tables
 * stayed ASCII; that split is retired — the digits a reader sees now match the
 * language they selected.
 *
 * Grouping is unchanged by the revision: `ne` already grouped by lakh under
 * both settings. Only the digit set differs.
 */
export const formatNumber = (n: number, opts?: Intl.NumberFormatOptions): string => {
  const locale = i18n.language === 'ne' ? 'ne' : 'en';
  return n.toLocaleString(locale, opts);
}

/**
 * Fixed-decimal display formatting — the language-aware replacement for
 * `value.toFixed(d)` in render paths. `toFixed` always emits ASCII, so it
 * silently ignores the active language; this keeps the same decimal places
 * while following it. Non-finite input renders as an em dash.
 */
export const formatDecimal = (n: unknown, decimals = 2): string => {
  // Number(null) and Number('') are 0, which would render missing data as
  // "0.00". Absent values are an em dash, matching the `x ?? '—'` shape the
  // call sites used before.
  if (n === null || n === undefined || n === '') return '—';
  const v = Number(n);
  if (!Number.isFinite(v)) return '—';
  return formatNumber(v, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

const DEVANAGARI_ZERO = 0x0966; // '०'

/**
 * Normalise a user-typed numeric string to ASCII digits.
 *
 * A Nepali keyboard produces Devanagari digits, and once the UI renders
 * १२,३४,५६७ people reasonably type them back. `Number('१२')` is NaN, so the
 * raw value cannot be parsed. This maps ०-९ to 0-9 and strips the grouping
 * separators both locales insert, leaving a string `Number()` accepts.
 *
 * Kept separate from parseLocaleNumber so callers that need to keep editing
 * state as text (a half-typed "१२." must survive a keystroke) can normalise
 * without forcing a numeric conversion.
 */
export const normalizeDigits = (input: string): string =>
  input.replace(/[०-९]/g, (d) => String(d.charCodeAt(0) - DEVANAGARI_ZERO))
       .replace(/,/g, '');

/**
 * Parse a user-typed numeric string in either language. Returns NaN when the
 * value is not a number, so callers keep their existing NaN handling.
 */
export const parseLocaleNumber = (input: string): number => {
  const s = normalizeDigits(String(input ?? '')).trim();
  return s === '' ? NaN : Number(s);
}

/**
 * Locale-aware date/time for display — the language-aware replacement for a
 * bare `new Date(x).toLocaleString()` in render paths. A bare call formats in
 * the *browser's* locale, so a Nepali reader on an en-US machine sees ASCII
 * digits regardless of the language they picked.
 *
 * The calendar stays Gregorian. Only the numerals and field order follow the
 * language; Bikram Sambat entry is NepaliDatePicker's job, not this helper's.
 */
export const formatDateTime = (
  value: string | number | Date | null | undefined,
  opts?: Intl.DateTimeFormatOptions,
): string => {
  if (value === null || value === undefined || value === '') return '—'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const locale = i18n.language === 'ne' ? 'ne' : 'en'
  return d.toLocaleString(locale, opts)
}

export default formatNumber