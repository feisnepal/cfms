/**
 * The last boundary before a blank page (H3.8 · S2-37 family).
 *
 * `MapErrorBoundary` and `LayerPanelErrorBoundary` cover the map workspace, but
 * nothing wrapped `<App />` — so a render error anywhere else unmounted the whole
 * tree and left an empty `<div id="root">`. To a district officer that is not an
 * error, it is a broken computer: nothing to read, nothing to report, nothing to
 * do but close the tab.
 *
 * ## Why the fallback is deliberately primitive
 *
 * It uses no hooks, no context, no i18n, no design system, and no network call.
 * An error boundary renders precisely when something below it has already
 * failed, and the cause may well be the thing a richer fallback would depend on
 * — an i18n bundle that failed to load, a broken theme provider, a crashed
 * store. Calling `t()` here would risk throwing inside the handler for a throw.
 *
 * So both languages are hard-coded. That duplicates strings the translation
 * system would normally own, and it is the right trade: this component must
 * render when the translation system is the thing that is broken.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
  /** Short id the user can quote; ties the screen to the console/Sentry entry. */
  reference: string | null;
}

function makeReference(): string {
  // Not a correlation id from the server — the failure is client-side and may
  // never have reached one. Enough to match a screenshot to a console entry.
  return Math.random().toString(36).slice(2, 8).toUpperCase();
}

export class RootErrorBoundary extends Component<Props, State> {
  state: State = { error: null, reference: null };

  static getDerivedStateFromError(error: Error): State {
    return { error, reference: makeReference() };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const reference = this.state.reference ?? makeReference();
    // Console first and unconditionally: it is the one reporting channel that
    // works with no configuration, and Sentry is not configured in this
    // deployment (see runbooks/OPS-ASSETS-VERIFICATION.md).
    console.error(`[RootErrorBoundary:${reference}]`, error, info.componentStack);

    // Best effort, and never allowed to throw — a failure to report must not
    // replace the fallback with a second blank screen.
    try {
      const sentry = (window as unknown as { Sentry?: { captureException?: (e: unknown, c?: unknown) => void } }).Sentry;
      sentry?.captureException?.(error, {
        tags: { boundary: 'root', reference },
        contexts: { react: { componentStack: info.componentStack } },
      });
    } catch {
      /* reporting is optional; the fallback is not */
    }
  }

  handleReload = () => {
    window.location.reload();
  };

  handleHome = () => {
    // Assign rather than push: the router may be the thing that crashed.
    window.location.href = '/';
  };

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div
        role="alert"
        aria-live="assertive"
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px',
          // Inline styles on purpose: a stylesheet that failed to load is one
          // of the reasons this component might be rendering at all.
          fontFamily: 'system-ui, -apple-system, "Segoe UI", sans-serif',
          background: '#f7f7f5',
          color: '#1a1a1a',
        }}
      >
        <div style={{ maxWidth: '520px', textAlign: 'center' }}>
          <div aria-hidden="true" style={{ fontSize: '40px', marginBottom: '12px' }}>
            ⚠️
          </div>

          <h1 style={{ fontSize: '20px', margin: '0 0 8px' }}>
            केही गडबड भयो
          </h1>
          <h2 style={{ fontSize: '17px', fontWeight: 400, margin: '0 0 16px', color: '#444' }}>
            Something went wrong
          </h2>

          <p style={{ margin: '0 0 8px', lineHeight: 1.6 }}>
            तपाईंको काम सुरक्षित नभएको हुन सक्छ। कृपया पृष्ठ पुन: लोड गर्नुहोस्।
          </p>
          <p style={{ margin: '0 0 20px', lineHeight: 1.6, color: '#444' }}>
            Your work may not have been saved. Please reload the page.
          </p>

          <div style={{ display: 'flex', gap: '10px', justifyContent: 'center', flexWrap: 'wrap' }}>
            <button
              type="button"
              onClick={this.handleReload}
              style={{
                padding: '10px 20px', fontSize: '15px', cursor: 'pointer',
                border: 'none', borderRadius: '6px', background: '#2d6a4f', color: '#fff',
              }}
            >
              पुन: लोड गर्नुहोस् / Reload
            </button>
            <button
              type="button"
              onClick={this.handleHome}
              style={{
                padding: '10px 20px', fontSize: '15px', cursor: 'pointer',
                border: '1px solid #ccc', borderRadius: '6px', background: '#fff', color: '#1a1a1a',
              }}
            >
              गृहपृष्ठ / Home
            </button>
          </div>

          {this.state.reference && (
            <p style={{ marginTop: '20px', fontSize: '13px', color: '#666' }}>
              सन्दर्भ / Reference:{' '}
              <code style={{ background: '#eee', padding: '2px 6px', borderRadius: '4px' }}>
                {this.state.reference}
              </code>
            </p>
          )}

          {/* The message is shown only in development. In production it would
              put an exception string in front of a forest officer, which is the
              same mistake H3.11 fixed on the server side. */}
          {import.meta.env.DEV && (
            <pre
              style={{
                marginTop: '16px', textAlign: 'left', fontSize: '12px', color: '#a00',
                background: '#fff', border: '1px solid #eee', borderRadius: '6px',
                padding: '10px', overflow: 'auto', maxHeight: '180px',
              }}
            >
              {this.state.error.message}
            </pre>
          )}
        </div>
      </div>
    );
  }
}

export default RootErrorBoundary;
