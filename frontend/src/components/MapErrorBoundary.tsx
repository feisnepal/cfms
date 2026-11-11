import { Component, type ReactNode, type ErrorInfo } from 'react';
import { useT } from '../i18n/hooks';

interface Props {
  children: ReactNode;
  name?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

function ErrorBoundaryContent({
  title,
  message,
  onRetry,
}: {
  title: string;
  message?: string;
  onRetry: () => void;
}) {
  const t = useT();
  return (
    <div className="error-boundary-fallback" role="alert">
      <p className="error-boundary-title">{title}</p>
      <p className="error-boundary-detail">{message}</p>
      <button onClick={onRetry} className="error-boundary-retry">
        {t('workspace.error.retry')}
      </button>
    </div>
  );
}

export class MapErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[MapErrorBoundary:${this.props.name || 'unknown'}]`, error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <MapErrorFallback
          name={this.props.name}
          message={this.state.error?.message}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}

function MapErrorFallback({
  name,
  message,
  onRetry,
}: {
  name?: string;
  message?: string;
  onRetry: () => void;
}) {
  const t = useT();
  return (
    <ErrorBoundaryContent
      title={t('workspace.error.fallbackTitle', { section: name || t('workspace.error.thisSection') })}
      message={message}
      onRetry={onRetry}
    />
  );
}

export class LayerPanelErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[LayerPanelErrorBoundary:${this.props.name || 'unknown'}]`, error, info.componentStack);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <LayerPanelErrorFallback
          message={this.state.error?.message}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}

function LayerPanelErrorFallback({
  message,
  onRetry,
}: {
  message?: string;
  onRetry: () => void;
}) {
  const t = useT();
  return (
    <div className="layer-panel" data-testid="layer-panel" role="alert">
      <div className="error-boundary-fallback">
        <p className="error-boundary-title">{t('workspace.error.layerPanelTitle')}</p>
        <p className="error-boundary-detail">{message}</p>
        <button onClick={onRetry} className="error-boundary-retry">{t('workspace.error.retry')}</button>
      </div>
    </div>
  );
}