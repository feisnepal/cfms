/**
 * calcRailStore — shared collapse + width state for the tabbed calculation
 * shell's navigation rail (`ActivityRail`). Single Workspace task A6; after
 * Tier 2 W1e `ActivityRail` is the sole consumer (it replaced the four
 * per-group `GroupSubNav` rails).
 *
 * One store, not per-render state, so the rail's collapse state + width stay
 * identical across group switches. Persisted per browser via zustand's
 * `persist` (same pattern as `workspaceStore`); a private-mode `localStorage`
 * throw is swallowed by the middleware and the store falls back to its initial
 * state.
 *
 * Two modes only: `expanded` (icon + label) and `compact` (icon only). The
 * header button is a plain toggle between them — there is no third "hidden"
 * state, so collapsing and restoring are always symmetric (the old
 * three-mode cycle trapped the user: leaving `expanded` could never be undone
 * from the rail because the hidden mode's reopen restored `compact`, not
 * `expanded`). `version: 3` migrates away the legacy `mode`/`userSet`/
 * `hidden` shape the same way.
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type RailMode = 'expanded' | 'compact';

export const RAIL_WIDTH = {
  MIN: 140,
  MAX: 280,
  DEFAULT: 176,
  /** fixed width of the icon-only rail */
  COMPACT: 48,
} as const;

interface CalcRailState {
  mode: RailMode;
  /** width of the expanded rail, px; clamped to [MIN, MAX] */
  width: number;
  toggleMode: () => void;
  setWidth: (width: number) => void;
}

export const useCalcRailStore = create<CalcRailState>()(
  persist(
    (set, get) => ({
      mode: 'expanded',
      width: RAIL_WIDTH.DEFAULT,

      toggleMode: () => set({ mode: get().mode === 'expanded' ? 'compact' : 'expanded' }),

      setWidth: (width) =>
        set({ width: Math.max(RAIL_WIDTH.MIN, Math.min(RAIL_WIDTH.MAX, Math.round(width))) }),
    }),
    {
      name: 'cfms.calcRail',
      version: 3,
      migrate: (persisted, version) => {
        const p = (persisted ?? {}) as { mode?: unknown; width?: number };
        let mode: RailMode = 'expanded';
        if (version < 3 && p.mode === 'compact') mode = 'compact';
        // every other legacy value ('expanded' / 'hidden' / missing) → expanded,
        // so no one is left stuck in a mode with no way back.
        return { mode, width: p.width ?? RAIL_WIDTH.DEFAULT };
      },
      partialize: (s) => ({ mode: s.mode, width: s.width }),
    },
  ),
);