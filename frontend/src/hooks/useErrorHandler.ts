import { useTranslation } from 'react-i18next';
import i18n from '../i18n/index';

const PASSWORD_PATTERN = new RegExp('^(?=.*[a-z])(?=.*[A-Z])(?=.*\\d).{8,}$');
const EMAIL_PATTERN = new RegExp('^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$');
const MOBILE_PATTERN = new RegExp('^\\d{10}$');

const GEOMETRY_ERROR_KEYS: Record<string, { key_sh: string; key_desc?: string; key_action?: string }> = {
  'no_valid_polygons':          { key_sh: 'geometry.upload.no_features' },
  'invalid_geometry':           { key_sh: 'geometry.upload.invalid_geometry' },
  'area_too_small':             { key_sh: 'geometry.upload.area_too_small' },
  'area_too_large':             { key_sh: 'geometry.upload.area_too_large' },
  'overlapping_features':       { key_sh: 'geometry.upload.overlapping' },
  'duplicate_feature':          { key_sh: 'geometry.upload.duplicate' },
  'too_many_vertices':          { key_sh: 'geometry.upload.too_complex' },
  'split_not_enough_points':    { key_sh: 'geometry.split.not_enough_points' },
  'split_line_too_short':       { key_sh: 'geometry.split.line_too_short' },
  'split_result_too_small':     { key_sh: 'geometry.split.result_too_small' },
  'name_empty':                 { key_sh: 'geometry.edit.no_name_empty' },
  'name_duplicate':             { key_sh: 'geometry.edit.duplicate_name' },
  'name_invalid_format':        { key_sh: 'geometry.edit.invalid_name_format' },
  'name_too_long':              { key_sh: 'geometry.edit.name_too_long' },
  'merge_requires_two':         { key_sh: 'geometry.edit.merge_requires_two' },
  'csv_no_coordinates':         { key_sh: 'geometry.csv.no_coordinates' },
  'csv_insufficient_rows':      { key_sh: 'geometry.csv.insufficient_rows' },
  'csv_unexpected_columns':     { key_sh: 'geometry.csv.unexpected_columns' },
  'subarea_outside_boundary':   { key_sh: 'geometry.subarea.outside_boundary' },
  'subarea_outside_block':      { key_sh: 'geometry.subarea.outside_block' },
  'subarea_overlap':            { key_sh: 'geometry.subarea.overlap' },
  'subarea_area_too_small':     { key_sh: 'geometry.subarea.area_too_small' },
  'subarea_duplicate_name':     { key_sh: 'geometry.subarea.duplicate_name' },
};

/**
 * Read the user-facing text out of a FastAPI `detail` field.
 *
 * Handles all three backend shapes:
 *  - `string` — legacy raw message (returned as-is; caller may still try i18n-key guesses)
 *  - `{code, message, message_np}` — new bilingual registry shape (Phase 2)
 *  - `[{loc, msg}, ...]` — Pydantic 422 validation list (first `msg`)
 *
 * For the bilingual shape, picks `message_np` when the active language is Nepali,
 * falling back to `message` (and vice-versa), so converted endpoints immediately
 * render Nepali without any frontend key mapping.
 *
 * The backend appends a top-level `correlation_id` to error bodies (the catch-all
 * 500 handler and the DB error handler). The axios interceptor copies it into
 * `detail.reference`, and fetch-based callers can pass it explicitly as
 * `correlationId`. When present it is appended under the message, so the "quote
 * the reference code below" sentence actually has a code below it.
 */
export function readDetail(detail: unknown, correlationId?: unknown): string | null {
  if (typeof detail === 'string') return detail || null;
  if (Array.isArray(detail)) {
    const first = detail[0];
    if (first && typeof first === 'object' && 'msg' in first) {
      return String((first as { msg?: unknown }).msg ?? '');
    }
    return null;
  }
  if (detail && typeof detail === 'object') {
    const d = detail as { code?: string; message?: string; message_np?: string; reference?: string };
    if (d.code !== undefined || d.message_np !== undefined || d.message !== undefined) {
      const isNe = i18n.language === 'ne';
      // A bundle entry for the code wins, so the wording can be edited on the
      // translation page; the server's own text is the fallback.
      const bundleKey = d.code ? `backendErrors.${d.code}` : '';
      const fromBundle = bundleKey && i18n.exists(bundleKey) ? i18n.t(bundleKey) : null;
      const text =
        fromBundle ??
        (isNe ? (d.message_np ?? d.message) : (d.message ?? d.message_np)) ??
        null;
      if (text === null) return null;
      const ref = d.reference ?? (typeof correlationId === 'string' ? correlationId : '');
      return ref ? `${text}\n\n${i18n.t('generalErrors.referenceCode')}: ${ref}` : text;
    }
    return d.message ?? null;
  }
  return null;
}

/**
 * Hook for handling errors with automatic i18n translation
 * Usage:
 *   const { handleError, t } = useErrorHandler();
 *   try { ... } catch (err) { setError(handleError(err)); }
 */
export const useErrorHandler = () => {
  const { t } = useTranslation();

  /**
   * Extracts and translates error from API response
   * Backend should return: { detail: "error_code" } or { detail: { message: "key" } }
   */
  const handleError = (err: any, fallbackKey?: string): string => {
    if (!err) return t('generalErrors.serverError');
    
    // Try to extract error code from backend response
    const detail = err.response?.data?.detail;
    
    if (detail) {
      // If detail is a string, try to use as i18n key
      if (typeof detail === 'string') {
        // Check geometry error keys first
        const geoMapping = GEOMETRY_ERROR_KEYS[detail];
        if (geoMapping) {
          return t(geoMapping.key_sh);
        }

        // Check if it's a known validation key
        const validationKeys = [
          'cfRegFormat', 'opYearRange', 'snFormat', 'provinceYearRange',
          'fiscalYearFormat', 'dateFormat', 'forestType', 'abundance',
          'avgAge', 'crownDensity', 'phoneFormat', 'dbhRange', 'heightRange',
          'speciesRequired', 'boundaryRequired', 'plotsMin', 'gridSpacing',
          'passwordMinLength', 'passwordUppercase', 'passwordLowercase', 'passwordDigit',
          'genderInvalid', 'positionInvalid', 'casteInvalid', 'mobileLength', 'mobileDigits',
          'mainCommitteeMax', 'advisoryCommitteeMax', 'financialCommitteeMax',
          'landUnitInvalid', 'prosperityInvalid', 'landAreaNegative', 'livestockNegative',
          'intensityRange', 'plotSizeInvalid', 'minPlotsInvalid', 'gridSpacingInvalid', 'boundaryBufferInvalid',
          'plotShapeRequired', 'samplingTypeInvalid', 'noAccessibleForest', 'samplingDesignNotFound', 'samplingDesignEmpty',
          'invalidRoles', 'ratioSumInvalid', 'invalidDistribution', 'invalidCategory', 'geometryValidationFailed',
          'geometryRequired', 'geometryInvalid', 'geometryTypeMismatch', 'pointCoordsInvalid',
          'pointCoordsNumeric', 'lineStringMinPoints', 'lineStringPointFormat', 'polygonRingsRequired',
          'polygonMinPoints', 'polygonRingClosed', 'polygonInvalid', 'subAreaRequiresBlock',
          'activityNameRequired', 'quantityPositive', 'budgetNonNegative', 'yearRange',
          'formatUnsupported', 'fileTooLarge', 'fileEmpty', 'shpMissing', 'noFeatures', 'noGeometries',
          'invalidGeometry', 'noPolygonGeometries',
          'geometryRequired', 'geometryInvalid', 'geometryEmpty', 'selfIntersection', 'areaZero', 'crsInvalid',
          'dbhRange', 'heightRange', 'heightGteDbh', 'speciesRequired', 'speciesUnknown', 'plotIdRequired',
          'treeIdRequired', 'duplicatePlotTree', 'blockRequired', 'coordinatesRequired',
          'notFound', 'permissionDenied', 'unauthorized', 'tokenExpired', 'validationError',
          'serverError', 'networkError', 'fileTooLarge', 'formatUnsupported', 'processingError'
        ];
        
        // Check if detail matches a validation key
        for (const key of validationKeys) {
          if (detail.includes(key) || detail === key) {
            return t(`validation.${key}`);
          }
        }
        
        // Try direct key lookup
        try {
          return t(`validation.${detail}`);
        } catch {
          // Fall through to fallback
        }
      }
      
      // If it's an object — bilingual {code,message,message_np} or Pydantic 422 array
      if (typeof detail === 'object') {
        const text = readDetail(detail);
        if (text) return text;
      }
    }
    
    // Fallback to provided key or generic error
    if (fallbackKey) {
      try {
        return t(`validation.${fallbackKey}`);
      } catch {
        return fallbackKey;
      }
    }
    
    // Generic server error
    return t('generalErrors.serverError');
  };

  /**
   * Get translated validation message by key
   */
  const getValidationMessage = (key: string, params?: Record<string, string>): string => {
    try {
      return t(`validation.${key}`, params);
    } catch {
      return key;
    }
  };

  /**
   * Get the three-level geometry error: short + description + suggestion.
   */
  const getGeometryError = (
    errorCode: string,
    params?: Record<string, string | number>,
  ): { label: string; description: string; suggestion: string } => {
    const mapping = GEOMETRY_ERROR_KEYS[errorCode];
    if (!mapping) {
      return {
        label: t('generic.error_occurred'),
        description: errorCode,
        suggestion: '',
      };
    }
    return {
      label: t(mapping.key_sh, params as Record<string, string>),
      description: mapping.key_desc ? t(mapping.key_desc, params as Record<string, string>) : '',
      suggestion: mapping.key_action ? t(mapping.key_action, params as Record<string, string>) : '',
    };
  };

  return { handleError, getValidationMessage, getGeometryError, t };
};

/**
 * Hook for form validation with i18n
 * Usage:
 *   const { validateField, validateForm } = useFormValidation();
 */
export const useFormValidation = () => {
  const { t } = useTranslation();

  const validateField = (fieldName: string, value: any, rules: any[]): string | null => {
    for (const rule of rules) {
      if (rule.required && (!value || (typeof value === 'string' && !value.trim()))) {
        return t('validation.requiredField', { field: t(`fields.${fieldName}`) });
      }
      if (rule.minLength && value?.length < rule.minLength) {
        return t('validation.minLength', { field: t(`fields.${fieldName}`), min: rule.minLength });
      }
      if (rule.maxLength && value?.length > rule.maxLength) {
        return t('validation.maxLength', { field: t(`fields.${fieldName}`), max: rule.maxLength });
      }
      if (rule.pattern && !rule.pattern.test(value)) {
        return t('validation.pattern', { field: t(`fields.${fieldName}`) });
      }
      if (rule.custom && !rule.custom(value)) {
        return t(`validation.${rule.messageKey}`);
      }
    }
    return null;
  };

  const validateForm = (formData: Record<string, any>, fieldRules: Record<string, any[]>): Record<string, string> => {
    const errors: Record<string, string> = {};
    for (const [fieldName, rules] of Object.entries(fieldRules)) {
      const error = validateField(fieldName, formData[fieldName], rules);
      if (error) errors[fieldName] = error;
    }
    return errors;
  };

  return { validateField, validateForm };
};

/**
 * Hook for displaying translated Ant Design messages
 * Usage:
 *   const { success, error, warning, info } = useMessages();
 *   success(t('common.saveSuccess'));
 */
export const useMessages = () => {
  const message = require('antd').message;
  const { t } = useTranslation();

  return {
    success: (key: string, duration?: number) => message.success(t(key), duration),
    error: (key: string, duration?: number) => message.error(t(key), duration),
    warning: (key: string, duration?: number) => message.warning(t(key), duration),
    info: (key: string, duration?: number) => message.info(t(key), duration),
    loading: (key: string, duration?: number) => message.loading(t(key), duration),
  };
};

/**
 * Pre-defined validation rules for common fields
 */
export const validationRules = {
  required: (fieldName: string) => ({
    required: true,
    message: 'validation.requiredField'
  }),
  email: () => ({
    pattern: EMAIL_PATTERN,
    messageKey: 'authValidation.emailInvalid'
  }),
  password: () => ({
    pattern: PASSWORD_PATTERN,
    messageKey: 'authValidation.passwordMinLength'
  }),
  mobile: () => ({
    pattern: MOBILE_PATTERN,
    messageKey: 'committeeValidation.mobileLength'
  }),
  numeric: (min?: number, max?: number) => ({
    custom: (value: any) => {
      const num = Number(value);
      if (isNaN(num)) return false;
      if (min !== undefined && num < min) return false;
      if (max !== undefined && num > max) return false;
      return true;
    },
    messageKey: 'validation.numericRange'
  }),
  range: (min: number, max: number, fieldName: string) => ({
    custom: (value: any) => {
      const num = Number(value);
      return !isNaN(num) && num >= min && num <= max;
    },
    messageKey: 'validation.range',
    params: { min, max, field: fieldName }
  }),
};

export default useErrorHandler;