/**
 * The shared upload findings (UPLOAD_EXPERIENCE_PLAN.md, UP-2): what is wrong with an upload and how to fix it, in both languages.
 * Mirrors `backend/app/services/upload/findings.py`.
 */
export type FindingSeverity = 'error' | 'warning' | 'info';

/** A replacement the system proposes for a value the rules refuse (a random value inside the column's own size class). */
export interface CorrectionProposal {
  row: number;
  column: string;
  stand: string;
  measure: string;
  old: number;
  new: number | null;
  range: string;
  /** The class the old value really belongs to (a pole of 50 cm belongs to 'tree'), when there is one. */
  belongs_to: string | null;
}

/** What the user accepted: the server applies it only to a cell the rules already refuse. */
export interface AcceptedCorrection {
  row: number;
  column: string;
  value: number;
}

export interface UploadFinding {
  code: string;
  severity: FindingSeverity;
  title_en: string;
  title_ne: string;
  fix_en: string;
  fix_ne: string;
  where: { file?: string; sheet?: string; row?: number; rows?: number[]; column?: string; proposals?: CorrectionProposal[] };
  found: string;
  expected: string;
  auto_fix?: string | null;
}

const isFinding = (x: unknown): x is UploadFinding =>
  !!x && typeof x === 'object' && typeof (x as UploadFinding).code === 'string' && typeof (x as UploadFinding).title_en === 'string';

/** The findings carried by a refused upload (`error.response.data.detail.findings`), or null when the error is not one of ours. */
export function findingsFromError(err: unknown): UploadFinding[] | null {
  const detail = (err as { response?: { data?: { detail?: { findings?: unknown } } } } | null | undefined)?.response?.data?.detail;
  const list = detail && typeof detail === 'object' ? (detail as { findings?: unknown }).findings : null;
  if (!Array.isArray(list)) return null;
  const ok = list.filter(isFinding);
  return ok.length ? ok : null;
}

/** The findings in a successful-but-imperfect response body (`body.findings`), or an empty list. */
export function findingsFromBody(body: unknown): UploadFinding[] {
  const list = (body as { findings?: unknown } | null | undefined)?.findings;
  return Array.isArray(list) ? list.filter(isFinding) : [];
}

export const findingText = (f: UploadFinding, lang: string) => ({
  title: lang === 'ne' && f.title_ne ? f.title_ne : f.title_en,
  fix: lang === 'ne' && f.fix_ne ? f.fix_ne : f.fix_en,
});

/** CSV (UTF-8 with a BOM so Excel opens Nepali text correctly) of the rows that need attention: the row number and the problem. */
export function problemRowsCsv(rows: Array<{ row: number; problem: string }>): string {
  const esc = (v: string) => `"${v.replace(/"/g, '""')}"`;
  return '\ufeff' + ['row,problem', ...rows.map((r) => `${r.row},${esc(r.problem)}`)].join('\r\n');
}

/**
 * The rows that need attention, taken from the findings' `where.rows`, as the
 * report's downloadable list. A finding that names no row contributes nothing;
 * a finding over many rows contributes one line for each.
 */
export function problemRowsFromFindings(
  findings: UploadFinding[],
  lang = 'en',
): Array<{ row: number; problem: string }> {
  const rows: Array<{ row: number; problem: string }> = [];
  for (const f of findings) {
    const where = f.where?.rows;
    if (!Array.isArray(where) || where.length === 0) continue;
    const { title } = findingText(f, lang);
    for (const row of where) rows.push({ row, problem: title });
  }
  return rows;
}
