import { useEffect } from 'react';
import { useWorkspaceStore } from '../store/workspaceStore';

/**
 * FocusModeClassManager — adds/removes `.focus-mode` class on `<body>`
 * when focusMode is toggled in workspaceStore.
 * Also handles Escape key to exit focus mode.
 * Place this component once in the app root (e.g., App.tsx).
 *
 * On focus mode exit, forces layout recalculation and Leaflet invalidation.
 */
export function FocusModeClassManager(): null {
  const focusMode = useWorkspaceStore((s) => s.focusMode);
  const toggleFocusMode = useWorkspaceStore((s) => s.toggleFocusMode);

  useEffect(() => {
    if (focusMode) {
      document.body.classList.add('focus-mode');
    } else {
      document.body.classList.remove('focus-mode');
    }
    return () => document.body.classList.remove('focus-mode');
  }, [focusMode]);

  // Escape key to exit focus mode
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && focusMode) {
        toggleFocusMode();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [focusMode, toggleFocusMode]);

  // On focus mode exit: force layout recalculation and Leaflet invalidation
  useEffect(() => {
    if (!focusMode) {
      // Force synchronous reflow
      document.body.offsetHeight;

      const timer = setTimeout(() => {
        // 1. Dispatch resize to wake up react-resizable-panels
        window.dispatchEvent(new Event('resize'));

        // 2. Invalidate Leaflet map size
        const leafletContainer = document.querySelector('.leaflet-container');
        if (leafletContainer && (leafletContainer as any)._leaflet_map) {
          (leafletContainer as any)._leaflet_map.invalidateSize();
        }

        // 3. Also try map instance from dev hook
        const devMap = (window as any).__mapInstance;
        if (devMap && typeof devMap.invalidateSize === 'function') {
          devMap.invalidateSize();
        }
      }, 50);

      return () => clearTimeout(timer);
    }
  }, [focusMode]);

  // Force synchronous reflow on focus mode change
  useEffect(() => {
    document.body.offsetHeight;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        window.dispatchEvent(new Event('resize'));
      });
    });
  }, [focusMode]);

  return null;
}

export default FocusModeClassManager;