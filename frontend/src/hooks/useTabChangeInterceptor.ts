/**
 * useTabChangeInterceptor — guards leaving the page while there are unsaved
 * edits (Phase 3).
 *
 * Reality-aligned (2026-08): in-page tab switches are guarded by the page's
 * own `handleTabChange` -> `shouldAllowTabChange` (clean -> switch, dirty ->
 * confirm modal), so that path is NOT routed through here.
 *
 * This hook is the *route-level* guard. react-router v7's `useBlocker` is only
 * available inside a **data router** (`createBrowserRouter`); this app still
 * mounts `<BrowserRouter>`, so calling `useBlocker` here throws
 * "useBlocker must be used within a data router" and unmounts the page to a
 * blank screen. To keep the guard working without a full router migration, we
 * use a `beforeunload` listener instead: when the user refreshes/closes the
 * tab with unsaved edits, the browser itself prompts to keep the changes.
 */
import { useEffect } from 'react';

export interface TabChangeGuardOptions {
  /** True while there are unsaved edits that must be confirmed. */
  hasUnsavedChanges: boolean;
  /** Kept for API compatibility; browser navigation prompts are native. */
  onConfirm?: () => void;
}

/**
 * Non-hook guard for in-page (component-level) tab switches. Callers show
 * their own confirm; returning false means "switching is allowed".
 */
export const shouldAllowTabChange = (hasUnsavedChanges: boolean): boolean =>
  !hasUnsavedChanges;

export interface TabBlockerApi {
  state: 'unblocked' | 'blocked';
  proceed?: () => void;
  reset?: () => void;
  cancel?: () => void;
}

/**
 * Hook: registers a `beforeunload` guard so closing/refreshing with unsaved
 * edits triggers the browser's native "leave site?" prompt. Returns a
 * `blocker` object shaped like the v7 `useBlocker` result for call-site
 * compatibility; the page's own modal drives in-page switch confirmation.
 */
export const useTabChangeInterceptor = ({
  hasUnsavedChanges,
}: TabChangeGuardOptions) => {
  useEffect(() => {
    if (!hasUnsavedChanges) return;

    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };

    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [hasUnsavedChanges]);

  const proceed = () => undefined;
  const cancel = () => undefined;

  const blocker: TabBlockerApi = { state: 'unblocked', proceed, cancel };

  return { blocker, proceed, cancel };
};