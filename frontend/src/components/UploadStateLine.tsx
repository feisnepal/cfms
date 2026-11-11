/**
 * One quick line on every upload screen (owner decision D3, 2026-10-12): is the data already in the system? Uploading again replaces it, so the
 * user should know before choosing a file. Green dot = in the system (with what it is, e.g. the file name or the count); grey = not in the system.
 */
import { useT } from '../i18n/hooks';

export interface UploadStateLineProps {
  present: boolean;
  /** what is there: a file name, "118 households", ... shown after the status */
  detail?: string | null;
  className?: string;
}

export function UploadStateLine({ present, detail, className = '' }: UploadStateLineProps) {
  const t = useT();
  return (
    <div
      className={`text-xs ${present ? 'text-green-700' : 'text-gray-500'} ${className}`}
      role="status"
      data-testid="upload-state-line"
      data-present={present ? 'true' : 'false'}
    >
      <span aria-hidden="true">{present ? '●' : '○'}</span>{' '}
      {present ? t('uploadState.inSystem') : t('uploadState.notInSystem')}
      {present && detail ? <span className="text-gray-600"> · {detail}</span> : null}
    </div>
  );
}

export default UploadStateLine;
