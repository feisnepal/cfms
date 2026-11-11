/**
 * WorkspaceTab — thin lazy wrapper around the real Leaflet `MapWorkspace`
 * (Phase 5). Code-splits the map into its own chunk, shows an animated skeleton
 * while it loads, and provides a retryable load-error fallback. Also wires the
 * digitize-draft autosave/restore safety net.
 *
 * Reality note: the AI_READY plan assumed a Mapbox-based `WorkspaceTabCore`.
 * This app's map is Leaflet `MapWorkspace` (`src/components/MapWorkspace.tsx`,
 * default export), which reads permission/lock state directly from the
 * workspace store — so no `permissions`/`structureLocked` props are threaded
 * through here.
 */
import React, { Suspense, useCallback, useEffect, useState } from 'react';
import { useT } from '../i18n/hooks';
import { useDigitizeDraftAutosave } from '../hooks/useDigitizeDraftAutosave';
import { useWorkspaceStore } from '../store/workspaceStore';
import { getMapRef } from '../lib/mapRef';
import { measureMapInit } from '../lib/performance';

// Phase 10 — time the map chunk fetch + module init (the costly part of "map
// init"); Leaflet's own render time is downstream of this and dominated by it.
const mapInitStart = typeof performance !== 'undefined' ? performance.now() : 0;

const LazyMapWorkspace = React.lazy(() =>
  import('./MapWorkspace').then((m) => {
    if (mapInitStart) {
      measureMapInit(performance.now() - mapInitStart);
    }
    return { default: m.default };
  }),
);

/**
 * The workspace views the map workspace can open on.
 *
 * Exported so `calculation/contextComponents.tsx` can type its context -> view
 * map against it. Duplicating this union there would let the two drift, and the
 * compiler would not catch it because the resolver builds the element through a
 * `React.lazy` wrapper.
 */
export type WorkspaceContext =
  | 'block_naming'
  | 'sub_areas'
  | 'activity_features'
  | 'boundary_edit'
  | 'unified'
  | 'compartments'
  | 'sub_compartments';

interface WorkspaceTabProps {
  calculationId: string;
  /** Optional explicit context; defaults to 'unified' for the tabbed shell. */
  context?: WorkspaceContext;
}

const MapSkeleton = () => {
  const t = useT();
  return (
  <div className="map-skeleton" role="status" aria-label={t('workspace.tab.loadingMap')}>
    <div className="map-skeleton__toolbar">
      <div className="skeleton-pill" />
      <div className="skeleton-pill" />
      <div className="skeleton-pill" />
    </div>
    <div className="map-skeleton__canvas">
      <div className="skeleton-grid">
        {Array.from({ length: 12 }).map((_, i) => (
          <div key={i} className="skeleton-tile" style={{ animationDelay: `${i * 50}ms` }} />
        ))}
      </div>
      <div className="map-skeleton__spinner">
        <span className="spinner" aria-hidden="true" />
        <span>{t('workspace.tab.loadingEngine')}</span>
      </div>
    </div>
  </div>
  );
};

const MapLoadError = ({ onRetry }: { onRetry: () => void }) => {
  const t = useT();
  return (
  <div className="map-load-error" role="alert">
    <div className="map-load-error__icon">🗺️</div>
    <h3>{t('workspace.tab.loadFailed')}</h3>
    <p>{t('workspace.tab.loadFailedHint')}</p>
    <button onClick={onRetry} className="btn btn--primary">
      {t('common.retry')}
    </button>
  </div>
  );
};

/**
 * Catches a failed lazy import (network/chunk error) so the retry UI renders
 * instead of the whole tab error boundary taking over. Retry remounts the
 * lazy component via a fresh `key`.
 */
class MapChunkBoundary extends React.Component<{ onRetry: () => void; children: React.ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error('[WorkspaceTab] map chunk load failed', error);
  }

  handleRetry = () => {
    this.setState({ hasError: false });
    this.props.onRetry();
  };

  render() {
    if (this.state.hasError) return <MapLoadError onRetry={this.handleRetry} />;
    return this.props.children;
  }
}

export const WorkspaceTab: React.FC<WorkspaceTabProps> = ({
  calculationId,
  context = 'unified',
}) => {
  const [retryKey, setRetryKey] = useState(0);
  const isDev = import.meta.env.DEV;

  // Draft autosave safety net (restores on remount, persists every 30s).
  useDigitizeDraftAutosave(calculationId);

  // Phase 9 — DEV-only test introspection (Playwright). Exposes the live
  // Zustand store + Leaflet map instance without polluting prod builds.
  useEffect(() => {
    if (!isDev) return;
    const w = window as unknown as Record<string, unknown>;
    Object.defineProperty(w, '__workspaceStore', {
      configurable: true,
      get: () => useWorkspaceStore.getState(),
    });
    Object.defineProperty(w, '__mapInstance', {
      configurable: true,
      get: () => getMapRef(),
    });
  }, [isDev]);

  const handleRetry = useCallback(() => setRetryKey((k) => k + 1), []);

  // Performance mark once the lazy chunk resolves (map init path is measured
  // downstream by MapWorkspace's own load event).
  useEffect(() => {
    if (typeof performance !== 'undefined') {
      performance.mark('workspace-tab-mounted');
    }
  }, []);

  // Phase 9 — DEV-only crash hook: lets Playwright verify tab-level error
  // isolation by forcing the workspace tab to throw during render.
  if (isDev && (window as unknown as { __crashWorkspace?: boolean }).__crashWorkspace) {
    throw new Error('E2E crash hook: workspace tab');
  }

  return (
    <div className="workspace-tab" data-testid="workspace-tab">
      <MapChunkBoundary onRetry={handleRetry}>
        <Suspense fallback={<MapSkeleton />}>
          <LazyMapWorkspace
            key={retryKey}
            calculationId={calculationId}
            context={context}
          />
        </Suspense>
      </MapChunkBoundary>
    </div>
  );
};

export default WorkspaceTab;