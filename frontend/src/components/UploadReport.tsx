/**
 * What is wrong with an upload and how to fix it (owner, 2026-10-12: user-friendly, not user-distracting).
 *
 * Problems are grouped by severity (errors first); each says WHAT is wrong, WHERE (rows / sheet / column) and HOW to fix it, in the user's
 * language. Info lines are quiet. When the screen knows the problem rows it offers them as a file to correct and upload again.
 */
import { useT } from '../i18n/hooks';
import i18n from '../i18n';
import { findingText, problemRowsCsv, type FindingSeverity, type UploadFinding } from '../lib/uploadFindings';

const LOOK: Record<FindingSeverity, { box: string; icon: string; label: string }> = {
  error: { box: 'border-red-300 bg-red-50 text-red-900', icon: '✕', label: 'uploadReport.error' },
  warning: { box: 'border-amber-300 bg-amber-50 text-amber-900', icon: '⚠', label: 'uploadReport.warning' },
  info: { box: 'border-gray-200 bg-gray-50 text-gray-700', icon: 'ℹ', label: 'uploadReport.info' },
};

export interface UploadReportProps {
  findings: UploadFinding[];
  /** rows the user needs to correct (row number + problem): offered as a downloadable CSV */
  problemRows?: Array<{ row: number; problem: string }>;
  /** base name for the downloaded file */
  fileName?: string;
  /** When given, a finding that proposes replacements offers to apply them (the caller imports the file again with them). */
  onApplyCorrections?: (finding: UploadFinding) => void;
  /** When given, a finding whose fix is `renumber_plots` offers to renumber the sample plots 1..N in order. */
  onRenumber?: (finding: UploadFinding) => void;
}

function whereText(f: UploadFinding, t: (k: string, v?: Record<string, unknown>) => string): string {
  const parts: string[] = [];
  if (f.where.sheet) parts.push(`${t('uploadReport.sheet')} ${f.where.sheet}`);
  if (f.where.column) parts.push(`${t('uploadReport.column')} ${f.where.column}`);
  if (f.where.rows?.length) {
    const shown = f.where.rows.slice(0, 12).join(', ');
    parts.push(`${t('uploadReport.rows')} ${shown}${f.where.rows.length > 12 ? ` … (+${f.where.rows.length - 12})` : ''}`);
  } else if (f.where.row) parts.push(`${t('uploadReport.row')} ${f.where.row}`);
  return parts.join(' · ');
}

export function UploadReport({ findings, problemRows, fileName = 'problem_rows', onApplyCorrections, onRenumber }: UploadReportProps) {
  const t = useT();
  if (!findings.length) return null;
  const lang = i18n.language === 'ne' ? 'ne' : 'en';
  const order: FindingSeverity[] = ['error', 'warning', 'info'];
  const sorted = [...findings].sort((a, b) => order.indexOf(a.severity) - order.indexOf(b.severity));

  const download = () => {
    const blob = new Blob([problemRowsCsv(problemRows ?? [])], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${fileName}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-2" data-testid="upload-report" role="region" aria-label={t('uploadReport.title')}>
      {sorted.map((f, i) => {
        const look = LOOK[f.severity];
        const { title, fix } = findingText(f, lang);
        const where = whereText(f, t);
        return (
          <div key={`${f.code}-${i}`} className={`rounded border p-3 text-sm ${look.box}`} data-testid={`finding-${f.code}`} data-severity={f.severity}>
            <div className="font-semibold">
              <span aria-hidden="true">{look.icon}</span> <span className="sr-only">{t(look.label)}: </span>
              {title}
            </div>
            {where && <div className="mt-0.5 text-xs opacity-80" data-testid="finding-where">{where}</div>}
            {f.severity !== 'info' && fix && (
              <div className="mt-1">
                <span className="font-medium">{t('uploadReport.howToFix')} </span>
                {fix}
              </div>
            )}
            {f.auto_fix === 'renumber_plots' && onRenumber && (
              <button type="button" onClick={() => onRenumber(f)} className="mt-2 px-3 py-1 rounded border border-green-700 bg-green-600 text-white text-sm hover:bg-green-700" data-testid="renumber-plots">
                {t('uploadReport.renumber')}
              </button>
            )}
            {!!f.where.proposals?.length && (
              <div className="mt-2" data-testid="proposals">
                <table className="text-xs border-collapse bg-white/60">
                  <thead>
                    <tr className="text-left">
                      <th className="pr-3">{t('uploadReport.proposals.row')}</th>
                      <th className="pr-3">{t('uploadReport.proposals.column')}</th>
                      <th className="pr-3">{t('uploadReport.proposals.was')}</th>
                      <th className="pr-3">{t('uploadReport.proposals.proposed')}</th>
                      <th>{t('uploadReport.proposals.belongsIn')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {f.where.proposals.slice(0, 20).map((p) => (
                      <tr key={`${p.row}-${p.column}`}>
                        <td className="pr-3">{p.row}</td>
                        <td className="pr-3 font-mono">{p.column}</td>
                        <td className="pr-3">{p.old}</td>
                        <td className="pr-3 font-semibold">{p.new ?? '—'}</td>
                        <td>{p.belongs_to ? t('uploadReport.proposals.classNote', { class: p.belongs_to }) : p.range}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {f.where.proposals.length > 20 && <div className="text-xs mt-1">+{f.where.proposals.length - 20}</div>}
                <div className="text-xs mt-1 opacity-80">{t('uploadReport.proposals.note')}</div>
                {onApplyCorrections && (
                  <button type="button" onClick={() => onApplyCorrections(f)} className="mt-2 px-3 py-1 rounded border border-green-700 bg-green-600 text-white text-sm hover:bg-green-700" data-testid="apply-corrections">
                    {t('uploadReport.proposals.apply')}
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
      {!!problemRows?.length && (
        <button type="button" onClick={download} className="text-sm underline text-blue-700 hover:text-blue-900" data-testid="download-problem-rows">
          {t('uploadReport.downloadRows', { count: problemRows.length })}
        </button>
      )}
    </div>
  );
}

export default UploadReport;
