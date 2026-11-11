/** Where a floating panel sits, whether it is collapsed and whether it is open, kept per user and per forest on the server
 *  (the existing `/workspace/layout` store, one `layout_key` per panel) so it follows the user across sessions and devices.
 *  Loading or saving may fail (offline, signed out): the panel then simply runs on its defaults and never throws. */
import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';
import type { PanelPosition } from '../lib/forestSummary';

export interface FloatingPanelState {
  position: PanelPosition;
  collapsed: boolean;
  open: boolean;
}

interface Saved extends Partial<FloatingPanelState> {
  version?: number;
}

const SAVE_DELAY_MS = 600;

const isNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Merge what the server returned over the defaults, ignoring anything of the wrong shape. */
export function mergeSaved(defaults: FloatingPanelState, saved: unknown): FloatingPanelState {
  const s = (saved && typeof saved === 'object' ? saved : {}) as Saved;
  const pos = s.position as Partial<PanelPosition> | undefined;
  return {
    position: pos && isNumber(pos.x) && isNumber(pos.y) ? { x: pos.x, y: pos.y } : defaults.position,
    collapsed: typeof s.collapsed === 'boolean' ? s.collapsed : defaults.collapsed,
    open: typeof s.open === 'boolean' ? s.open : defaults.open,
  };
}

export function useFloatingPanelState(layoutKey: string | null, defaults: FloatingPanelState) {
  const [state, setState] = useState<FloatingPanelState>(defaults);
  const [isLoaded, setIsLoaded] = useState(false);
  const loaded = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const defaultsRef = useRef(defaults);
  defaultsRef.current = defaults;

  useEffect(() => {
    loaded.current = false;
    setIsLoaded(false);
    setState(defaultsRef.current);
    if (!layoutKey) return undefined;
    let live = true;
    api
      .get<{ layout_json: unknown }>('/api/v1/workspace/layout', { params: { layout_key: layoutKey } })
      .then((r) => {
        if (live) setState(mergeSaved(defaultsRef.current, r.data?.layout_json));
      })
      .catch(() => undefined) // defaults stay
      .finally(() => {
        if (!live) return;
        loaded.current = true;
        setIsLoaded(true);
      });
    return () => {
      live = false;
    };
  }, [layoutKey]);

  const persist = useCallback(
    (next: FloatingPanelState) => {
      if (!layoutKey || !loaded.current) return;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        api
          .put('/api/v1/workspace/layout', { layout_key: layoutKey, layout_json: { version: 1, ...next } })
          .catch(() => undefined); // a failed save only means the next visit starts from the defaults
      }, SAVE_DELAY_MS);
    },
    [layoutKey],
  );

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const update = useCallback(
    (patch: Partial<FloatingPanelState>) => {
      setState((prev) => {
        const next = { ...prev, ...patch };
        persist(next);
        return next;
      });
    },
    [persist],
  );

  /** `loaded` turns true once the saved layout has been applied (or the attempt has failed). */
  return { state, update, loaded: isLoaded };
}
