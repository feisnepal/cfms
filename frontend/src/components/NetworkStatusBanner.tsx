/**
 * NetworkStatusBanner — connection status UI for the calculation page.
 * The backend has no WebSocket stream for status updates, so "reconnecting"
 * is shown only transiently when a meta fetch fails; otherwise the banner
 * stays hidden (30s polling is silent).
 */
import { useT } from '../i18n/hooks';

interface NetworkStatusBannerProps {
  isError: boolean;
  reconnecting?: boolean;
}

export function NetworkStatusBanner({ isError, reconnecting = false }: NetworkStatusBannerProps) {
  const t = useT();
  if (isError) {
    return (
      <div className="network-banner network-banner--error" role="alert">
        <span>&#9888; {t('workspace.connectionLost')}</span>
        <button onClick={() => window.location.reload()}>{t('workspace.reloadNow')}</button>
      </div>
    );
  }
  if (reconnecting) {
    return (
      <div className="network-banner network-banner--warning" role="status">
        <span>&#x1F504; {t('workspace.reconnecting')}</span>
      </div>
    );
  }
  return null;
}

export default NetworkStatusBanner;