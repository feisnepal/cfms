import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import i18n from '../../i18n/index';
import { readDetail } from '../useErrorHandler';

describe('readDetail (Phase 2.4 frontend error reader)', () => {
  const originalLng = i18n.language;

  afterEach(() => {
    i18n.changeLanguage(originalLng);
  });

  it('returns raw string detail as-is', () => {
    expect(readDetail('Boundary updated successfully')).toBe('Boundary updated successfully');
    expect(readDetail('')).toBeNull();
  });

  it('prefers message_np when language is ne', async () => {
    await i18n.changeLanguage('ne');
    const text = readDetail({ code: 'success.boundary_updated', message: 'Boundary updated successfully', message_np: 'सिमाना सफलतापूर्वक अद्यावधिक भयो' });
    expect(text).toBe('सिमाना सफलतापूर्वक अद्यावधिक भयो');
  });

  it('falls back to message when ne is missing but language is ne', async () => {
    await i18n.changeLanguage('ne');
    expect(readDetail({ code: 'x', message: 'Only EN' })).toBe('Only EN');
  });

  it('prefers message when language is en', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail({ code: 'success.boundary_updated', message: 'Boundary updated successfully', message_np: 'सिमाना सफलतापूर्वक अद्यावधिक भयो' });
    expect(text).toBe('Boundary updated successfully');
  });

  it('falls back to message_np when message missing and language is en', async () => {
    await i18n.changeLanguage('en');
    expect(readDetail({ code: 'x', message_np: 'नेपाली मात्र' })).toBe('नेपाली मात्र');
  });

  it('extracts first msg from Pydantic 422 array', () => {
    expect(readDetail([{ loc: ['body', 'name'], msg: 'String should have at least 1 character', type: 'string_too_short' }]))
      .toBe('String should have at least 1 character');
  });

  it('appends the reference code injected into detail.reference (axios path)', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail({ code: 'general.unexpected_error', message: 'Something went wrong at our end', message_np: 'हाम्रो तर्फबाट केही गडबड भयो', reference: 'abc-123' });
    expect(text).toBe(`Something went wrong at our end\n\n${i18n.t('generalErrors.referenceCode')}: abc-123`);
  });

  it('appends the reference code passed as correlationId (fetch path)', async () => {
    await i18n.changeLanguage('en');
    const text = readDetail({ code: 'general.unexpected_error', message: 'Something went wrong at our end', message_np: 'हाम्रो तर्फबाट केही गडबड भयो' }, 'xyz-456');
    expect(text).toBe('Something went wrong at our end\n\nReference: xyz-456');
  });

  it('uses the Nepali label when language is ne', async () => {
    await i18n.changeLanguage('ne');
    const text = readDetail({ code: 'general.internal_error', message: 'Service unavailable', message_np: 'सेवा अस्थायी रूपमा अनुपलब्ध', reference: 'nep-1' });
    expect(text).toBe(`सेवा अस्थायी रूपमा अनुपलब्ध\n\n${i18n.t('generalErrors.referenceCode')}: nep-1`);
  });

  it('leaves bilingual detail alone when no reference is present', async () => {
    await i18n.changeLanguage('en');
    expect(readDetail({ code: 'success.boundary_updated', message: 'Boundary updated successfully', message_np: 'सिमाना सफलतापूर्वक अद्यावधिक भयो' }))
      .toBe('Boundary updated successfully');
  });

  it('ignores bogus correlationId values', () => {
    expect(readDetail({ code: 'x', message: 'Only EN' }, 42)).toBe('Only EN');
    expect(readDetail({ code: 'x', message: 'Only EN' }, null)).toBe('Only EN');
  });

  it('returns null for empty / unexpected shapes', () => {
    expect(readDetail(null)).toBeNull();
    expect(readDetail(undefined)).toBeNull();
    expect(readDetail(42)).toBeNull();
    expect(readDetail([])).toBeNull();
    expect(readDetail([{}])).toBeNull();
  });
});