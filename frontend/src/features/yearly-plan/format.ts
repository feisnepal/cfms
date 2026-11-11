import { formatDecimal, formatNumber } from '../../i18n/numberFormat';

/**
 * A quantity as the user typed it: 5 stays "5", 0.5 stays "0.5" — never rounded to a whole number
 * (the legacy page showed 0.5 ha as 1, also in the CSV). Numerals follow the UI language.
 */
export function formatQuantity(value: unknown): string {
  const n = Number(value);
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return '—';
  return Number.isInteger(n) ? formatNumber(n) : formatDecimal(n, 2);
}

/** A quantity for a file: plain ASCII, unrounded (`0.5`, `5`). */
export function quantityForFile(value: unknown): string {
  const n = Number(value);
  return Number.isFinite(n) ? String(n) : '';
}
