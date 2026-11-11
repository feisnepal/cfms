/**
 * calcChromeStore — per-browser layout of the tabbed calculation shell's own
 * chrome. After Tier 2 W1e the merged `ActivityRail` is the only navigation, so
 * the only thing left to persist is whether the shell header + its strip are
 * folded away.
 *
 * Same pattern as `calcRailStore`: zustand + `persist` under a `cfms.*` key, a
 * private-mode `localStorage` throw swallowed by the middleware.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface CalcChromeState {
  /** Fold `.calc-header` into a slim strip. */
  headerCollapsed: boolean;

  toggleHeader: () => void;
  setHeaderCollapsed: (v: boolean) => void;
}

export const useCalcChromeStore = create<CalcChromeState>()(
  persist(
    (set) => ({
      headerCollapsed: false,
      toggleHeader: () => set((s) => ({ headerCollapsed: !s.headerCollapsed })),
      setHeaderCollapsed: (v) => set({ headerCollapsed: v }),
    }),
    {
      name: 'cfms.calcChrome',
      partialize: (s) => ({ headerCollapsed: s.headerCollapsed }),
    },
  ),
);
