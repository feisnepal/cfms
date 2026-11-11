import { describe, it, expect } from 'vitest';
import {
  readBoundaryValidation,
  isBoundaryValidationError,
  findingText,
  summariseReport,
  type BoundaryValidationReport,
} from '../boundaryValidation';

const REPORT: BoundaryValidationReport = {
  ok: false,
  errors: [
    {
      code: 'boundary.area_exceeds_limit',
      level: 'error',
      message_en: 'The forest area is 1,085 ha — the limit is 1,000 ha.',
      message_ne: 'वन क्षेत्रफल १,०८५ हेक्टर छ — सीमा १,००० हेक्टर हो।',
      detail: { area_ha: 1085, limit_ha: 1000 },
    },
  ],
  warnings: [],
  info: [],
  facts: { area_ha: 1085 },
};

describe('readBoundaryValidation', () => {
  it('pulls the report out of a 422 axios error', () => {
    const err = {
      response: { data: { detail: { code: 'boundary_validation_failed', message: 'x', boundary_validation: REPORT } } },
    };
    const rep = readBoundaryValidation(err);
    expect(rep?.ok).toBe(false);
    expect(rep?.errors[0].code).toBe('boundary.area_exceeds_limit');
  });

  it('pulls the report out of a 200 success body', () => {
    const okRep = { ...REPORT, ok: true, errors: [], warnings: [REPORT.errors[0]] };
    const rep = readBoundaryValidation({ success: true, boundary_validation: okRep });
    expect(rep?.ok).toBe(true);
    expect(rep?.warnings).toHaveLength(1);
  });

  it('accepts the raw report object', () => {
    expect(readBoundaryValidation(REPORT)?.errors).toHaveLength(1);
  });

  it('returns null when there is no boundary report', () => {
    expect(readBoundaryValidation({ response: { data: { detail: 'plain string' } } })).toBeNull();
    expect(readBoundaryValidation(new Error('boom'))).toBeNull();
    expect(readBoundaryValidation(null)).toBeNull();
  });
});

describe('isBoundaryValidationError', () => {
  it('is true only for the boundary_validation_failed code', () => {
    expect(
      isBoundaryValidationError({ response: { data: { detail: { code: 'boundary_validation_failed' } } } }),
    ).toBe(true);
    expect(
      isBoundaryValidationError({ response: { data: { detail: { code: 'something_else' } } } }),
    ).toBe(false);
    expect(isBoundaryValidationError(new Error('x'))).toBe(false);
  });
});

describe('findingText / summariseReport', () => {
  it('picks the language', () => {
    expect(findingText(REPORT.errors[0], 'en')).toMatch(/1,085 ha/);
    expect(findingText(REPORT.errors[0], 'ne')).toMatch(/हेक्टर/);
  });
  it('summary joins errors, else warnings', () => {
    expect(summariseReport(REPORT, 'en')).toMatch(/limit is 1,000 ha/);
    const warnRep = { ...REPORT, errors: [], warnings: [REPORT.errors[0]] };
    expect(summariseReport(warnRep, 'en')).toMatch(/1,085 ha/);
  });
});
