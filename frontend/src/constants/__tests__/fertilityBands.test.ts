/**
 * The soil-fertility band vocabulary, and the export that used to be keyed on a
 * different one.
 *
 * One concept had three vocabularies in this codebase:
 *
 *   1. the backend producer (`app/core/soil_fertility.py::FertilityClass`) emits
 *      `high` / `good` / `moderate` / `low` / `very_low`;
 *   2. the two analysis badges compared against `'Very High'` / `'High'` /
 *      `'Medium'` / `'Low'`, which the producer never writes, so all five bands fell
 *      through to the last (red) arm - a `high` soil rendered in the Very Low colour;
 *   3. `FERTILITY_NP`, used by the export, was keyed `very_low` / `low` / `medium` /
 *      `high` / `very_high`, which matches neither the producer nor the badges: it had
 *      no `good` or `moderate` at all (so those fell through untranslated), and its
 *      `high` meant the second band where the producer's `high` is the top one, so
 *      exported reports were a band out.
 *
 * `FERTILITY_BANDS` is now the single source, keyed on the producer's own tokens, and
 * both the badges and `FERTILITY_NP` derive from it.
 */

import { describe, it, expect } from 'vitest';
import {
  FERTILITY_BANDS,
  FERTILITY_NP,
  FERTILITY_UNKNOWN_BADGE,
  resolveFertilityBand,
} from '../nepaliLabels';

/** The tokens the backend producer can emit, in descending score order. */
const PRODUCER_TOKENS = ['high', 'good', 'moderate', 'low', 'very_low'] as const;

describe('fertility bands', () => {
  it('covers exactly the producer vocabulary, in descending order', () => {
    expect(Object.keys(FERTILITY_BANDS)).toEqual([...PRODUCER_TOKENS]);
  });

  it('gives every band an English label, a Nepali label and a badge class', () => {
    for (const token of PRODUCER_TOKENS) {
      const band = FERTILITY_BANDS[token];
      expect(band.labelEn, token).toBeTruthy();
      expect(band.labelNp, token).toBeTruthy();
      expect(band.badgeClass, token).toBeTruthy();
      expect(band.color, token).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it('orders the English labels from best to worst', () => {
    expect(PRODUCER_TOKENS.map((t) => FERTILITY_BANDS[t].labelEn)).toEqual([
      'Very High',
      'High',
      'Medium',
      'Low',
      'Very Low',
    ]);
  });

  it('resolves every producer token to its own distinct band', () => {
    const labels = PRODUCER_TOKENS.map((t) => resolveFertilityBand(t)?.labelEn);
    expect(labels).toEqual(['Very High', 'High', 'Medium', 'Low', 'Very Low']);
    expect(new Set(labels).size).toBe(PRODUCER_TOKENS.length);
  });

  it('tolerates case, padding and separators without changing the band', () => {
    for (const token of PRODUCER_TOKENS) {
      for (const variant of [token, token.toUpperCase(), `  ${token} `, token.replace(/_/g, ' ')]) {
        expect(resolveFertilityBand(variant)?.labelEn, variant).toBe(
          FERTILITY_BANDS[token].labelEn,
        );
      }
    }
  });

  it('returns undefined for a class it does not know, rather than a default band', () => {
    // The regression: the old chain's final arm was a band colour, so anything
    // unrecognised was presented as the worst band with full confidence.
    for (const bad of ['bogus', 'excellent', '', '   ', 'Very High', 'Medium']) {
      expect(resolveFertilityBand(bad), bad).toBeUndefined();
    }
    expect(resolveFertilityBand(null)).toBeUndefined();
    expect(resolveFertilityBand(undefined)).toBeUndefined();
  });

  it('does not use the Very Low colour for an unrecognised class', () => {
    expect(FERTILITY_UNKNOWN_BADGE).not.toBe(FERTILITY_BANDS.very_low.badgeClass);
  });
});

describe('FERTILITY_NP export labels', () => {
  it('is keyed on the producer tokens, not on a third vocabulary', () => {
    expect(Object.keys(FERTILITY_NP).sort()).toEqual([...PRODUCER_TOKENS].sort());
  });

  it('translates every producer token, including the two that used to be missing', () => {
    for (const token of PRODUCER_TOKENS) {
      expect(FERTILITY_NP[token], token).toBe(FERTILITY_BANDS[token].labelNp);
      expect(FERTILITY_NP[token], token).toBeTruthy();
    }
    // 'good' and 'moderate' were absent from the old map, so they exported untranslated.
    expect(FERTILITY_NP.good).toBeTruthy();
    expect(FERTILITY_NP.moderate).toBeTruthy();
  });

  it('no longer carries the keys the producer never emits', () => {
    // 'medium' and 'very_high' were never produced, which is how 'high' ended up
    // translating to the second band's wording.
    expect(FERTILITY_NP).not.toHaveProperty('medium');
    expect(FERTILITY_NP).not.toHaveProperty('very_high');
  });

  it('aligns each token with the same band the badge shows', () => {
    for (const token of PRODUCER_TOKENS) {
      expect(FERTILITY_NP[token]).toBe(resolveFertilityBand(token)?.labelNp);
    }
  });
});
