import type { GeoJSON } from 'geojson';
import type { TFunction } from 'i18next';

export interface ValidationMessage {
  label: string;
  description: string;
  suggestion: string;
}

export interface ValidationError {
  code: string;
  message: ValidationMessage;
  params?: Record<string, string | number>;
}

export function validateMinPoints(
  points: number,
  min: number,
  t: TFunction,
): ValidationError | null {
  if (points < min) {
    return {
      code: 'split_not_enough_points',
      message: {
        label: t('geometry.split.not_enough_points'),
        description: t('geometry.split.not_enough_points_desc', { n: points }),
        suggestion: t('geometry.split.not_enough_points_action'),
      },
      params: { n: points, min },
    };
  }
  return null;
}

export function validateCutLineIntersection(
  intersectionCount: number,
  t: TFunction,
): ValidationError | null {
  if (intersectionCount < 2) {
    return {
      code: 'split_line_too_short',
      message: {
        label: t('geometry.split.line_too_short'),
        description: t('geometry.split.line_too_short_desc', { n: intersectionCount }),
        suggestion: t('geometry.split.line_too_short_action'),
      },
      params: { n: intersectionCount },
    };
  }
  return null;
}

export function validateSplitPieceArea(
  areaHa: number,
  minAreaHa: number,
  t: TFunction,
): ValidationError | null {
  if (areaHa < minAreaHa) {
    return {
      code: 'split_result_too_small',
      message: {
        label: t('geometry.split.result_too_small', { area: areaHa.toFixed(2) }),
        description: t('geometry.split.result_too_small_desc', {
          area: areaHa.toFixed(2),
          min_area: minAreaHa.toFixed(2),
        }),
        suggestion: t('geometry.split.result_too_small_action'),
      },
      params: { area: areaHa.toFixed(2), min_area: minAreaHa.toFixed(2) },
    };
  }
  return null;
}

export function validateBlockName(
  name: string,
  existingNames: Set<string>,
  t: TFunction,
): ValidationError | null {
  const trimmed = name.trim();

  if (!trimmed) {
    return {
      code: 'name_empty',
      message: {
        label: t('geometry.edit.no_name_empty'),
        description: t('geometry.edit.no_name_empty_desc'),
        suggestion: t('geometry.edit.no_name_empty_action'),
      },
    };
  }

  if (existingNames.has(trimmed)) {
    return {
      code: 'name_duplicate',
      message: {
        label: t('geometry.edit.duplicate_name', { name: trimmed }),
        description: t('geometry.edit.duplicate_name_desc', { name: trimmed }),
        suggestion: t('geometry.edit.duplicate_name_action', { name: trimmed }),
      },
      params: { name: trimmed },
    };
  }

  if (trimmed.length > 100) {
    return {
      code: 'name_too_long',
      message: {
        label: t('geometry.edit.name_too_long', { max: 100 }),
        description: t('geometry.edit.name_too_long_desc', { max: 100 }),
        suggestion: t('geometry.edit.name_too_long_action'),
      },
      params: { max: 100 },
    };
  }

  if (!/^[\w\s\-_\u0900-\u097F]+$/.test(trimmed)) {
    return {
      code: 'name_invalid_format',
      message: {
        label: t('geometry.edit.invalid_name_format', {
          pattern: 'Letters, numbers, spaces, hyphens, underscores, and Nepali characters',
        }),
        description: t('geometry.edit.invalid_name_format_desc', {
          name: trimmed,
          pattern: 'alphanumeric + Nepali',
        }),
        suggestion: t('geometry.edit.invalid_name_format_action'),
      },
      params: { name: trimmed, pattern: 'alphanumeric + Nepali' },
    };
  }

  return null;
}

export function validateMergeSelection(
  selectedCount: number,
  t: TFunction,
): ValidationError | null {
  if (selectedCount < 2) {
    return {
      code: 'merge_requires_two',
      message: {
        label: t('geometry.edit.merge_requires_two'),
        description: t('geometry.edit.merge_requires_two_desc'),
        suggestion: t('geometry.edit.merge_requires_two_action'),
      },
      params: { count: selectedCount },
    };
  }
  return null;
}

export function displayValidationError(
  error: ValidationError,
  t: TFunction,
): { label: string; description: string; suggestion: string } {
  return {
    label: error.message.label,
    description: error.message.description,
    suggestion: error.message.suggestion,
  };
}

/**
 * U-4 (Task 4.1, case E): true when the picked points can form a polygon —
 * at least 3 distinct points that are NOT all collinear (the simple closed
 * ring has non-zero area, computed via the shoelace formula).
 */
export function pointsAreNonCollinear(points: ReadonlyArray<readonly [number, number]>): boolean {
  if (!points || points.length < 3) return false;
  let area = 0;
  for (let i = 0; i < points.length; i++) {
    const [x1, y1] = points[i];
    const [x2, y2] = points[(i + 1) % points.length];
    area += x1 * y2 - x2 * y1;
  }
  return Math.abs(area) > 1e-9;
}

