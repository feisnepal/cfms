/**
 * TabErrorBoundary — isolates crashes to a single tab in the tabbed container.
 * Non-fatal (fatal:false) errors are logged to Sentry (if available) + GA4;
 * the rest of the page keeps working.
 */
import React, { Component, type ErrorInfo, type ReactNode } from 'react';
import { useT } from '../i18n/hooks';

interface Props {
  children: ReactNode;
  tab: string;
  calculationId?: string;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

function TabErrorFallback({
  tab,
  message,
  stack,
  onReload,
}: {
  tab: string;
  message?: string;
  stack?: string;
  onReload: () => void;
}) {
  const t = useT();
  return (
    <div className="tab-error-fallback" role="alert" aria-live="assertive">
      <div className="tab-error-fallback__icon">💥</div>
      <h3>{t('workspace.error.tabErrorTitle', { tab })}</h3>
      <p className="tab-error-fallback__details">
        {message || t('workspace.error.unexpectedError')}
      </p>
      <div className="tab-error-fallback__actions">
        <button onClick={onReload} className="btn btn--primary">
          {t('workspace.error.reloadTab')}
        </button>
        <button onClick={() => window.location.reload()} className="btn btn--secondary">
          {t('workspace.error.reloadPage')}
        </button>
      </div>
      {process.env.NODE_ENV === 'development' && (
        <pre className="tab-error-fallback__stack">{stack}</pre>
      )}
    </div>
  );
}

export class TabErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    const sentry = (window as any).Sentry;
    if (sentry) {
      sentry.withScope((scope: any) => {
        scope.setTag('tab', this.props.tab);
        scope.setTag('calculation_id', this.props.calculationId || 'unknown');
        scope.setContext('react', { componentStack: errorInfo.componentStack });
        sentry.captureException(error);
      });
    }

    console.error(`[TabErrorBoundary:${this.props.tab}]`, error, errorInfo);

    const gtag = (window as any).gtag;
    if (gtag) {
      gtag('event', 'exception', {
        description: `${this.props.tab}: ${error.message}`,
        fatal: false,
      });
    }
  }

  handleReload = () => {
    this.setState({ hasError: false, error: undefined });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <TabErrorFallback
          tab={this.props.tab}
          message={this.state.error?.message}
          stack={this.state.error?.stack}
          onReload={this.handleReload}
        />
      );
    }

    return this.props.children;
  }
}

export default TabErrorBoundary;