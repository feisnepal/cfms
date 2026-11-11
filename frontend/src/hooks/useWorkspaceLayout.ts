/**
 * useWorkspaceLayout — coordinates the resizable dock panels in the map
 * workspace: registers Group/Panel imperative handles, applies the saved
 * server layout on mount, tracks collapsed state for the header toggles,
 * and debounce-saves any user-driven layout change back to the server.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import type { GroupImperativeHandle } from 'react-resizable-panels';
import {
  DEFAULT_LAYOUT,
  DOCK_POSITIONS,
  fetchLayout,
  mergeDefaultLayout,
  saveLayout,
  type GroupId,
  type PanelId,
  type WorkspaceLayout,
} from '../lib/workspaceLayout';

const SAVE_DEBOUNCE_MS = 500;

interface DockHandle {
  collapse: () => void;
  expand: () => void;
  isCollapsed: () => boolean;
}

const PANEL_IDS: PanelId[] = [
  'layers',
  'basemap',
  'imported',
  'raster',
  'attributeTable',
  'legend',
];

/**
 * Panels that share one dock position (a column). Owner decision 2026-10-11: a position shows ONE panel at a time. Opening a panel
 * (from its header chip or its own title bar) gives it the whole position and closes the others there; opening another replaces it.
 */
export const DOCK_COLUMN = Object.fromEntries(
  DOCK_POSITIONS.flatMap((pos) => pos.members.map((m) => [m, { group: pos.group, members: pos.members }])),
) as Record<PanelId, { group: GroupId; members: PanelId[] }>;

export function useWorkspaceLayout() {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({
    ...DEFAULT_LAYOUT.collapsed,
  });
  const [layoutLoaded, setLayoutLoaded] = useState(false);

  const groupRefs = useRef<Partial<Record<GroupId, GroupImperativeHandle | null>>>({});
  const panelRefs = useRef<Partial<Record<PanelId, DockHandle | null>>>({});
  const collapsedRef = useRef(collapsed);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const userInteractedRef = useRef(false);

  collapsedRef.current = collapsed;

  const registerGroup = useCallback((id: GroupId) => (ref: GroupImperativeHandle | null) => {
    groupRefs.current[id] = ref;
  }, []);

  const registerPanel = useCallback((id: PanelId) => (ref: DockHandle | null) => {
    panelRefs.current[id] = ref;
  }, []);

  const scheduleSave = useCallback(() => {
    userInteractedRef.current = true;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      const layout: WorkspaceLayout = {
        version: 1,
        groups: {
          'workspace-horizontal':
            groupRefs.current['workspace-horizontal']?.getLayout() ??
            DEFAULT_LAYOUT.groups['workspace-horizontal'],
          'workspace-left':
            groupRefs.current['workspace-left']?.getLayout() ??
            DEFAULT_LAYOUT.groups['workspace-left'],
          'workspace-right':
            groupRefs.current['workspace-right']?.getLayout() ??
            DEFAULT_LAYOUT.groups['workspace-right'],
        },
        collapsed: { ...collapsedRef.current },
      };
      void saveLayout(layout);
    }, SAVE_DEBOUNCE_MS);
  }, []);

  const setPanelCollapsed = useCallback(
    (id: string, value: boolean) => {
      setCollapsed((prev) => (prev[id] === value ? prev : { ...prev, [id]: value }));
    },
    [],
  );

  const togglePanel = useCallback(
    (id: PanelId) => {
      const ref = panelRefs.current[id];
      if (!ref) return;
      const wasCollapsed = ref.isCollapsed();
      if (!wasCollapsed) {
        ref.collapse();
        const next: Record<string, boolean> = { [id]: true };
        // Closing a secondary panel returns the position to its home panel (Layers / Attribute Table) so it is never left empty.
        const pos = DOCK_POSITIONS.find((x) => x.members.includes(id));
        if (pos && id !== pos.primary && pos.members.every((m) => m === id || panelRefs.current[m]?.isCollapsed() !== false)) {
          panelRefs.current[pos.primary]?.expand();
          groupRefs.current[pos.group]?.setLayout(Object.fromEntries(pos.members.map((m) => [m, m === pos.primary ? 100 : 0])));
          next[pos.primary] = false;
        }
        setCollapsed((prev) => ({ ...prev, ...next }));
        scheduleSave();
        return;
      }
      // Opening: the panel takes the whole position and the others in it close.
      const { group, members } = DOCK_COLUMN[id];
      const closed: Record<string, boolean> = {};
      for (const other of members) {
        if (other === id) continue;
        const o = panelRefs.current[other];
        if (o && !o.isCollapsed()) o.collapse();
        closed[other] = true;
      }
      ref.expand();
      const share: Record<string, number> = {};
      for (const m of members) share[m] = m === id ? 100 : 0;
      groupRefs.current[group]?.setLayout(share);
      setCollapsed((prev) => ({ ...prev, ...closed, [id]: false }));
      scheduleSave();
    },
    [scheduleSave],
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const saved = await fetchLayout();
      if (cancelled) return;
      if (userInteractedRef.current) {
        setLayoutLoaded(true);
        return;
      }
      const merged = mergeDefaultLayout(saved);

      groupRefs.current['workspace-horizontal']?.setLayout(
        merged.groups['workspace-horizontal'],
      );
      groupRefs.current['workspace-left']?.setLayout(merged.groups['workspace-left']);
      groupRefs.current['workspace-right']?.setLayout(merged.groups['workspace-right']);

      for (const pid of PANEL_IDS) {
        if (merged.collapsed[pid]) {
          panelRefs.current[pid]?.collapse();
        }
      }

      setCollapsed(merged.collapsed);
      collapsedRef.current = merged.collapsed;
      setLayoutLoaded(true);
    })();

    return () => {
      cancelled = true;
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  return {
    collapsed,
    layoutLoaded,
    registerGroup,
    registerPanel,
    togglePanel,
    setPanelCollapsed,
    scheduleSave,
  };
}
