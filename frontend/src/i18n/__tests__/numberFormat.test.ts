import { describe, it, expect, afterEach } from 'vitest';
import i18n from '../index';
import {
  formatNumber, formatDecimal, formatDateTime, normalizeDigits, parseLocaleNumber,
} from '../numberFormat';

const restore = i18n.language;
afterEach(async () => { await i18n.changeLanguage(restore); });

describe('formatNumber — numerals follow the active language (D6, revised)', () => {
  it('renders Devanagari digits with lakh grouping in Nepali', async () => {
    await i18n.changeLanguage('ne');
    expect(formatNumber(1234567.89)).toBe('१२,३४,५६७.८९');
  });

  it('renders ASCII digits with thousands grouping in English', async () => {
    await i18n.changeLanguage('en');
    expect(formatNumber(1234567.89)).toBe('1,234,567.89');
  });

  it('honours Intl options in both languages', async () => {
    await i18n.changeLanguage('ne');
    expect(formatNumber(5, { minimumFractionDigits: 2 })).toBe('५.००');
    await i18n.changeLanguage('en');
    expect(formatNumber(5, { minimumFractionDigits: 2 })).toBe('5.00');
  });
});

describe('formatDecimal — the toFixed replacement', () => {
  it('keeps decimal places while following the language', async () => {
    await i18n.changeLanguage('ne');
    expect(formatDecimal(1234.5, 2)).toBe('१,२३४.५०');
    await i18n.changeLanguage('en');
    expect(formatDecimal(1234.5, 2)).toBe('1,234.50');
  });

  it('renders an em dash for non-numeric input instead of crashing', () => {
    expect(formatDecimal(undefined, 1)).toBe('—');
    expect(formatDecimal(null, 2)).toBe('—');
    expect(formatDecimal(NaN)).toBe('—');
  });
});

describe('normalizeDigits / parseLocaleNumber — accepting Devanagari input', () => {
  it('accepts Devanagari digits a Nepali keyboard produces', () => {
    expect(parseLocaleNumber('१२')).toBe(12);
    expect(parseLocaleNumber('१२.५')).toBe(12.5);
    expect(parseLocaleNumber('०')).toBe(0);
  });

  it('still accepts ASCII, so English users are unaffected', () => {
    expect(parseLocaleNumber('12')).toBe(12);
    expect(parseLocaleNumber('1234.56')).toBe(1234.56);
  });

  it('strips the grouping separators both locales render', () => {
    expect(parseLocaleNumber('१२,३४,५६७')).toBe(1234567);
    expect(parseLocaleNumber('1,234,567')).toBe(1234567);
  });

  it('round-trips what formatNumber renders in Nepali', async () => {
    await i18n.changeLanguage('ne');
    expect(parseLocaleNumber(formatNumber(1234567))).toBe(1234567);
  });

  it('keeps partial input editable rather than destroying it', () => {
    expect(normalizeDigits('१२.')).toBe('12.');
    expect(normalizeDigits('')).toBe('');
  });

  it('returns NaN for non-numeric input so existing guards still fire', () => {
    expect(parseLocaleNumber('abc')).toBeNaN();
    expect(parseLocaleNumber('')).toBeNaN();
  });
});

describe('mixed / malformed numeric input is handled gracefully', () => {
  it('accepts a number typed in both scripts (keyboard switched mid-entry)', () => {
    expect(parseLocaleNumber('१२3')).toBe(123);
    expect(parseLocaleNumber('1२')).toBe(12);
    expect(parseLocaleNumber('१2.५')).toBe(12.5);
  });

  it('accepts mixed grouping separators', () => {
    expect(parseLocaleNumber('१,२34')).toBe(1234);
    expect(parseLocaleNumber('1,२३४')).toBe(1234);
  });

  it('tolerates surrounding whitespace from a paste', () => {
    expect(parseLocaleNumber('  १२  ')).toBe(12);
    expect(parseLocaleNumber('\t42\n')).toBe(42);
  });

  it('returns NaN — not a wrong number — for genuinely invalid input', () => {
    expect(parseLocaleNumber('१२ रूख')).toBeNaN();
    expect(parseLocaleNumber('12abc')).toBeNaN();
    expect(parseLocaleNumber('१.२.३')).toBeNaN();
    expect(parseLocaleNumber('-')).toBeNaN();
  });

  it('keeps negatives working in both scripts', () => {
    expect(parseLocaleNumber('-१२')).toBe(-12);
    expect(parseLocaleNumber('-12')).toBe(-12);
  });
});

describe('formatDateTime — dates follow the active language too', () => {
  const when = new Date(2026, 7, 18, 9, 5);

  it('renders Devanagari digits in Nepali', async () => {
    await i18n.changeLanguage('ne');
    // Exact field order is Intl's business; the digit set is what D6 governs.
    expect(formatDateTime(when)).toMatch(/[०-९]/);
    expect(formatDateTime(when)).not.toMatch(/[0-9]/);
  });

  it('renders ASCII digits in English', async () => {
    await i18n.changeLanguage('en');
    expect(formatDateTime(when)).toMatch(/[0-9]/);
    expect(formatDateTime(when)).not.toMatch(/[०-९]/);
  });

  it('accepts the ISO strings the API returns', async () => {
    await i18n.changeLanguage('en');
    expect(formatDateTime('2026-08-18T09:05:00Z')).toContain('2026');
  });

  it('renders an em dash for absent or unparseable values', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime(undefined)).toBe('—');
    expect(formatDateTime('')).toBe('—');
    expect(formatDateTime('not a date')).toBe('—');
  });
});
