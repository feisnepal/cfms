/**
 * Source gates for the two legacy yearly-activities screens (YEARLY_ACTIVITIES plan §4.6, §4.7, §4.1 #4/#6).
 *
 * These read the source on purpose: the defects were "a raw server sentence reaches the user" and "a
 * quantity is silently rounded", and both come back the moment somebody re-types the old line.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import en from '../../../i18n/locales/en.json';
import ne from '../../../i18n/locales/ne.json';
import { formatQuantity, quantityForFile } from '../format';

const root = resolve(__dirname, '../../..');
const SCREENS = {
  'YearlyActivitiesPage.tsx': readFileSync(resolve(root, 'components/YearlyActivities/YearlyActivitiesPage.tsx'), 'utf-8'),
  'YearlyActivitiesTab.tsx': readFileSync(resolve(root, 'components/YearlyActivitiesTab.tsx'), 'utf-8'),
};

describe.each(Object.entries(SCREENS))('%s', (_name, source) => {
  it('never shows the server\'s own error text to the user', () => {
    expect(source).not.toMatch(/response\?\.data\?\.detail/);
    expect(source).not.toMatch(/\{\s*detail\s*:/); // t('…', { detail: … })
  });

  it('never rounds a quantity to a whole number', () => {
    // 0.5 ha used to show as 1, also in the CSV
    expect(source).not.toMatch(/Math\.round\([^)]*quantity/);
    expect(source).not.toMatch(/Math\.round\([^)]*_qty/);
  });
});

describe('the legacy save message', () => {
  it('no longer interpolates the raw detail, in either language', () => {
    const page = (b: typeof en) => (b.yearlyActivities as { page: Record<string, string> }).page;
    expect(page(en).saveFailed).toBeUndefined();
    expect(page(ne as unknown as typeof en).saveFailed).toBeUndefined();
  });
});

describe('formatQuantity / quantityForFile keep what was typed', () => {
  it('shows a whole number as one and a fraction with its decimals', () => {
    expect(formatQuantity(5)).toBe('5');
    expect(formatQuantity('5.00')).toBe('5');
    expect(formatQuantity(0.5)).toBe('0.50');
    expect(formatQuantity(2.4)).toBe('2.40');
  });

  it('shows nothing invented for a missing value', () => {
    expect(formatQuantity(null)).toBe('—');
    expect(formatQuantity(undefined)).toBe('—');
    expect(formatQuantity('')).toBe('—');
    expect(formatQuantity('abc')).toBe('—');
  });

  it('writes an unrounded plain number to a file', () => {
    expect(quantityForFile(0.5)).toBe('0.5');
    expect(quantityForFile('2.75')).toBe('2.75');
    expect(quantityForFile(5)).toBe('5');
    expect(quantityForFile('x')).toBe('');
  });
});
