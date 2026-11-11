import { useT } from '../i18n/hooks';

interface WorkspaceErrorProps {
  onRetry: () => void;
  message?: string;
}

export function WorkspaceError({ onRetry, message }: WorkspaceErrorProps) {
  const t = useT();
  return (
    <div className="workspace-error" role="alert">
      <div className="workspace-error-content">
        <h2>{t('workspace.error.unavailable')}</h2>
        <p>{message || t('workspace.error.loadFailed')}</p>
        <button onClick={onRetry} className="retry-btn" aria-label={t('workspace.error.retryLoading')}>
          {t('workspace.error.retry')}
        </button>
      </div>
    </div>
  );
}