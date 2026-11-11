import { describe, expect, it } from 'vitest';
import { isPlanned, isPlannedYear, parseAmount } from '../yearlyPlanRules';

describe('parseAmount — a stored 0 is a value, not "use the default"', () => {
  it('keeps a real zero, as a number or a Decimal string', () => {
    expect(parseAmount(0, 1)).toBe(0);
    expect(parseAmount('0', 1)).toBe(0);
    expect(parseAmount('0.00', 5000)).toBe(0);
  });

  it('parses Decimal strings and numbers', () => {
    expect(parseAmount('2.5', 1)).toBe(2.5);
    expect(parseAmount(7, 1)).toBe(7);
    expect(parseAmount('1000.00', 0)).toBe(1000);
  });

  it('falls back only for null, undefined, empty or NaN', () => {
    expect(parseAmount(null, 3)).toBe(3);
    expect(parseAmount(undefined, 3)).toBe(3);
    expect(parseAmount('', 3)).toBe(3);
    expect(parseAmount('abc', 3)).toBe(3);
    expect(parseAmount(Number.NaN, 3)).toBe(3);
  });
});

describe('isPlanned — quantity > 0 or budget > 0', () => {
  it.each([
    [5, 5, true], // planned and funded
    [5, 0, true], // planned, no cost (voluntary work)
    [0, 5, true], // funded, no countable output
    [0, 0, false], // not planned this year
    ['0.00', '0.00', false],
    [null, null, false],
  ])('quantity %s, budget %s -> %s', (q, b, expected) => {
    expect(isPlanned(q, b)).toBe(expected);
  });

  it('works on a year cell', () => {
    expect(isPlannedYear({ quantity: 0, budget: 0 })).toBe(false);
    expect(isPlannedYear({ quantity: 1, budget: 0 })).toBe(true);
  });
});
