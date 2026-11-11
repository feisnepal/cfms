/**
 * Renders the forest-boundary validation report — why a boundary was refused,
 * or what the system changed about it — instead of a bare "422".
 *
 * Errors are shown red and block; warnings are amber and informational (e.g.
 * "30% of the boundary fell outside Nepal and was removed"). Each line is the
 * backend's own bilingual message, picked by the active language.
 */

import { Alert } from 'antd';
import { useT } from '../i18n/hooks';
import { useTranslation } from 'react-i18next';
import {
  findingText,
  type BoundaryValidationReport,
  type BoundaryFinding,
} from '../lib/boundaryValidation';

interface Props {
  report: BoundaryValidationReport | null;
  /** Show the info-level findings too (reference-layer-unavailable notes). */
  showInfo?: boolean;
  className?: string;
}

export default function BoundaryValidationNotice({
  report,
  showInfo = false,
  className,
}: Props) {
  const t = useT();
  const { i18n } = useTranslation();
  const lang = i18n.language;

  if (!report) return null;
  const { errors, warnings, info } = report;
  if (!errors.length && !warnings.length && !(showInfo && info.length)) return null;

  const list = (findings: BoundaryFinding[]) => (
    <ul className="list-disc pl-5 space-y-1 mt-1">
      {findings.map((f, i) => (
        <li key={`${f.code}-${i}`} className="text-sm">
          {findingText(f, lang)}
        </li>
      ))}
    </ul>
  );

  return (
    <div className={className}>
      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          className="mb-2"
          message={t('boundaryValidation.rejectedTitle')}
          description={list(errors)}
        />
      )}
      {warnings.length > 0 && (
        <Alert
          type="warning"
          showIcon
          className="mb-2"
          message={t('boundaryValidation.adjustedTitle')}
          description={list(warnings)}
        />
      )}
      {showInfo && info.length > 0 && (
        <Alert type="info" showIcon message={list(info)} className="mb-2" />
      )}
    </div>
  );
}
