/**
 * useFocusManagement — tab panel focus + keyboard shortcuts (Phase 3).
 * Reality-aligned: AccessibleModal moved to components/calculation/.
 */
import { useEffect, useRef } from 'react';
import { shortcutKeyForTab } from '../pages/calculationTabConfig';

/**
 * Moves focus to the tab panel when the active tab changes.
 * Returns a ref to attach to the panel container.
 */
export const useTabFocusManagement = (activeTab: string) => {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const panel = panelRef.current;
    if (panel) {
      panel.tabIndex = -1;
      panel.focus({ preventScroll: true });
    }
  }, [activeTab]);

  return panelRef;
};

/**
 * Keyboard shortcuts for tabs: Ctrl/Cmd+1..4 to switch, Esc to close modals.
 * The digit→tab mapping is shared with the help modal via
 * `shortcutKeyForTab` (calculationTabConfig).
 */
export const useTabKeyboardShortcuts = <const T extends string>(
  tabs: readonly T[],
  activeTab: T,
  onChange: (tab: T) => void,
  enabled: boolean = true,
) => {
  useEffect(() => {
    if (!enabled) return;

    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey) {
        // Only digit keys within the tab count map to a switch.
        const index = tabs.findIndex((_, i) => shortcutKeyForTab(i) === e.key);
        if (index >= 0) {
          e.preventDefault();
          onChange(tabs[index]);
        }
      }

      if (e.key === 'Escape') {
        const openModal = document.querySelector('[role="dialog"][aria-modal="true"]');
        if (openModal) {
          const closeBtn = openModal.querySelector('[data-modal-close]') as HTMLElement | null;
          closeBtn?.click();
        }
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [tabs, activeTab, onChange, enabled]);
};
