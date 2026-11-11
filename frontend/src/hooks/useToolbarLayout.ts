/**
 * The attribute toolbar's layout, kept per user: localStorage answers at once (no flash of the default bar), and the user's
 * `/workspace/layout` record (key `attribute-toolbar`) follows them to another browser or device. Server calls are skipped when
 * nobody is signed in; a failed read or save only means the local copy is used.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { DEFAULT_LAYOUT, normalizeLayout, type ToolbarLayout } from '../lib/toolbarLayout';

export const TOOLBAR_LAYOUT_KEY = 'attribute-toolbar';
const LOCAL_KEY = 'cfms.attributeToolbar.layout';
const SAVE_DELAY_MS = 600;

const signedIn = (): boolean => {
  try {
    return !!localStorage.getItem('access_token');
  } catch {
    return false;
  }
};

function readLocal(): ToolbarLayout {
  try {
    const raw = localStorage.getItem(LOCAL_KEY);
    return raw ? normalizeLayout(JSON.parse(raw)) : DEFAULT_LAYOUT;
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export interface ToolbarLayoutStore {
  layout: ToolbarLayout;
  setLayout: (next: ToolbarLayout) => void;
}

export function useToolbarLayout(): ToolbarLayoutStore {
  const [layout, setState] = useState<ToolbarLayout>(readLocal);
  const touched = useRef(false); // the user changed it before the server answered: their change wins
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!signedIn()) return undefined;
    let live = true;
    api
      .get<{ layout_json: unknown }>('/api/v1/workspace/layout', { params: { layout_key: TOOLBAR_LAYOUT_KEY } })
      .then((r) => {
        if (live && !touched.current && r.data?.layout_json) setState(normalizeLayout(r.data.layout_json));
      })
      .catch(() => undefined); // the local copy stays
    return () => {
      live = false;
    };
  }, []);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const setLayout = useCallback((next: ToolbarLayout) => {
    touched.current = true;
    setState(next);
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
    } catch {
      /* private window: the choice lasts for this visit */
    }
    if (!signedIn()) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api
        .put('/api/v1/workspace/layout', { layout_key: TOOLBAR_LAYOUT_KEY, layout_json: { version: 1, ...next } })
        .catch(() => undefined); // the next visit on another device starts from its own copy
    }, SAVE_DELAY_MS);
  }, []);

  return { layout, setLayout };
}
