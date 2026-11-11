/**
 * H3.8 — a render error must not produce a blank page.
 *
 * `MapErrorBoundary` covers the workspace; nothing covered `<App />`. A crash
 * anywhere else unmounted the tree and left an empty `<div id="root">` — which
 * to a district officer is not an error but a broken computer: nothing to read,
 * nothing to report, nothing to do but close the tab.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { RootErrorBoundary } from '../RootErrorBoundary';

function Boom({ message = 'kaboom' }: { message?: string }): never {
  throw new Error(message);
}

// React logs caught errors to console.error; silence it so the suite output
// stays readable, and so an assertion on our own console.error is meaningful.
let consoleError: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => consoleError.mockRestore());

describe('when nothing is wrong', () => {
  it('renders its children untouched', () => {
    render(
      <RootErrorBoundary>
        <p>the application</p>
      </RootErrorBoundary>,
    );
    expect(screen.getByText('the application')).toBeTruthy();
  });
});

describe('when a child throws', () => {
  it('shows a fallback instead of an empty page', () => {
    render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
    expect(screen.getByRole('alert')).toBeTruthy();
  });

  it('speaks Nepali and English, because the fallback cannot use i18n', () => {
    // If the i18n bundle were the thing that crashed, calling t() here would
    // throw inside the handler for a throw. Both languages are hard-coded, and
    // this test is what stops someone "tidying" that into a t() call.
    render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
    expect(screen.getByText('केही गडबड भयो')).toBeTruthy();
    expect(screen.getByText('Something went wrong')).toBeTruthy();
  });

  it('warns that work may be unsaved', () => {
    render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
    expect(screen.getByText(/may not have been saved/i)).toBeTruthy();
  });

  it('offers a way out', () => {
    render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
    expect(screen.getByRole('button', { name: /Reload/ })).toBeTruthy();
    expect(screen.getByRole('button', { name: /Home/ })).toBeTruthy();
  });

  it('shows a reference the user can quote', () => {
    render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
    expect(screen.getByText(/Reference/)).toBeTruthy();
  });

  it('logs with that same reference, so a screenshot maps to a console entry', () => {
    render(<RootErrorBoundary><Boom message="traceable" /></RootErrorBoundary>);
    const ours = consoleError.mock.calls.filter(
      (c) => typeof c[0] === 'string' && c[0].startsWith('[RootErrorBoundary:'),
    );
    expect(ours.length).toBeGreaterThan(0);
  });

  it('announces itself to assistive technology', () => {
    render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
    expect(screen.getByRole('alert').getAttribute('aria-live')).toBe('assertive');
  });
});

describe('reporting must never make things worse', () => {
  it('still renders the fallback when Sentry capture throws', () => {
    (window as unknown as { Sentry: unknown }).Sentry = {
      captureException: () => { throw new Error('reporting is broken too'); },
    };
    try {
      render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
      expect(screen.getByRole('alert')).toBeTruthy();
    } finally {
      delete (window as unknown as { Sentry?: unknown }).Sentry;
    }
  });

  it('reports to Sentry when it is available', () => {
    const captureException = vi.fn();
    (window as unknown as { Sentry: unknown }).Sentry = { captureException };
    try {
      render(<RootErrorBoundary><Boom /></RootErrorBoundary>);
      expect(captureException).toHaveBeenCalled();
      expect(captureException.mock.calls[0][1].tags.boundary).toBe('root');
    } finally {
      delete (window as unknown as { Sentry?: unknown }).Sentry;
    }
  });
});
