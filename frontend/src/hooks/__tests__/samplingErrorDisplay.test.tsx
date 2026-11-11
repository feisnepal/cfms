/**
 * The error the owner actually saw, pinned as a regression.
 *
 * Refusing a design is correct behaviour - the कार्यविधि §16 floor is real. What was
 * wrong is that the refusal reached the user as a raw JSON blob: the bilingual
 * `detail` was passed through `JSON.stringify`, so `code`, `message`, `message_np` and
 * the `raw` log field (itself a nested escaped service string) all appeared on one
 * line. `readDetail` is the repo's existing reader for exactly this shape and it
 * ignores `raw`, so the fix is to use it rather than re-serialise.
 */

import { readDetail } from '../useErrorHandler';
import i18n from '../../i18n';

const FLOOR_ERROR = {
  code: 'sampling.intensity_below_floor',
  message:
    'Sampling intensity for C12 (production stratum) must be at least 2.0% per कार्यविधि §16. Submitted: 0.5%.',
  message_np:
    'C12 (production stratum) को नमूना सघनता कम्तीमा 2.0% हुनुपर्छ (कार्यविधि §१६)। पेश गरिएको: 0.5%।',
  raw: 'SFM_INTENSITY_BELOW_FLOOR: {"unit": "C12", "stratum": "production", "floor": 2.0, "value": 0.5}',
  unit: 'C12',
  stratum: 'production',
  floor: 2.0,
  value: 0.5,
};

describe('readDetail on a sampling floor refusal', () => {
  it('returns the English message, not the serialised payload', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail(FLOOR_ERROR);
    expect(text).toBe(FLOOR_ERROR.message);
  });

  it('never leaks the raw log field to the user', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail(FLOOR_ERROR) || '';
    expect(text).not.toContain('SFM_INTENSITY_BELOW_FLOOR');
    expect(text).not.toContain('"stratum"');
    expect(text).not.toContain('{');
    expect(text).not.toContain('raw');
  });

  it('never leaks the code or the whole JSON object', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail(FLOOR_ERROR) || '';
    expect(text).not.toContain('"code"');
    expect(text).not.toContain('message_np');
    expect(text).not.toContain(JSON.stringify(FLOOR_ERROR));
  });

  it('returns the Nepali message when the active language is Nepali', async () => {
    await i18n.changeLanguage('ne');
    const text = readDetail(FLOOR_ERROR);
    expect(text).toBe(FLOOR_ERROR.message_np);
    await i18n.changeLanguage('en');
  });

  it('keeps the numbers that make the refusal actionable', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail(FLOOR_ERROR) || '';
    expect(text).toContain('C12');
    expect(text).toContain('2.0%');
    expect(text).toContain('0.5%');
  });

  it('still handles a plain string detail', () => {
    expect(readDetail('something broke')).toBe('something broke');
  });

  it('returns null for an empty detail rather than the string "null"', () => {
    expect(readDetail(null)).toBeNull();
    expect(readDetail({})).toBeNull();
  });
});
