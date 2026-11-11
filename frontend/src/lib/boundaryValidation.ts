/**
 * Reads the forest-boundary validation report the backend returns — the reason
 * a boundary was rejected, or a warning about what it changed.
 *
 * Backend contract (`app/services/boundary_validation.py`):
 *  - on rejection: HTTP 422, body `{ detail: { code: "boundary_validation_failed",
 *    message, boundary_validation: { ok, errors[], warnings[], info[], facts } } }`
 *  - on success with a caveat (e.g. the boundary was clipped to Nepal): the
 *    200 body carries `boundary_validation: { ... }` directly.
 *
 * Each finding carries BOTH `message_en` and `message_ne`, so the UI just picks
 * the language — no key mapping needed.
 */

export type BoundaryFindingLevel = 'error' | 'warning' | 'info';

export interface BoundaryFinding {
  code: string;
  level: BoundaryFindingLevel;
  message_en: string;
  message_ne: string;
  detail?: Record<string, unknown>;
}

export interface BoundaryValidationReport {
  ok: boolean;
  errors: BoundaryFinding[];
  warnings: BoundaryFinding[];
  info: BoundaryFinding[];
  facts?: Record<string, unknown>;
}

function coerceReport(raw: unknown): BoundaryValidationReport | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const arr = (k: string): BoundaryFinding[] =>
    Array.isArray(r[k]) ? (r[k] as BoundaryFinding[]) : [];
  const errors = arr('errors');
  const warnings = arr('warnings');
  const info = arr('info');
  if (!('ok' in r) && !errors.length && !warnings.length && !info.length) {
    return null;
  }
  return {
    ok: r.ok !== false,
    errors,
    warnings,
    info,
    facts: (r.facts as Record<string, unknown>) ?? undefined,
  };
}

/**
 * Pull the boundary-validation report out of anything a boundary call hands back
 * — an axios error, a `{ response: { data } }`, a raw error body, or a success
 * response object. Returns null when there is no boundary report in it.
 */
export function readBoundaryValidation(
  source: unknown,
): BoundaryValidationReport | null {
  if (!source || typeof source !== 'object') return null;
  const s = source as Record<string, unknown>;

  // axios error → error.response.data
  const data =
    (s.response as { data?: unknown } | undefined)?.data ?? s.data ?? s;
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;

  // 422 shape: { detail: { boundary_validation: {...} } }
  const detail = d.detail;
  if (detail && typeof detail === 'object') {
    const fromDetail = coerceReport(
      (detail as Record<string, unknown>).boundary_validation,
    );
    if (fromDetail) return fromDetail;
  }

  // success shape: { boundary_validation: {...} } — or the report itself
  return coerceReport(d.boundary_validation) ?? coerceReport(d);
}

/** True when the 422 was specifically a boundary-rules failure. */
export function isBoundaryValidationError(err: unknown): boolean {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail;
  if (detail && typeof detail === 'object') {
    return (detail as { code?: string }).code === 'boundary_validation_failed';
  }
  return false;
}

/** The finding's message in the active language (`ne` → Nepali, else English). */
export function findingText(f: BoundaryFinding, lang: string): string {
  return (lang === 'ne' ? f.message_ne || f.message_en : f.message_en || f.message_ne) ?? '';
}

/** A one-line summary — every error joined, else every warning. */
export function summariseReport(
  report: BoundaryValidationReport,
  lang: string,
): string {
  const src = report.errors.length ? report.errors : report.warnings;
  return src.map((f) => findingText(f, lang)).join(' ');
}
