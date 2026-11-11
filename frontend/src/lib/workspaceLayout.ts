/**
 * Workspace dock layout — types, defaults, and server persistence helpers.
 *
 * The map workspace exposes six independently resizable/collapsible panels
 * (Layers, Basemap, Imported, Raster, Attribute Table, Legend). Their sizes
 * and collapsed state are persisted per-user on the backend so the layout
 * follows the user across sessions and devices.
 */

export type PanelId =
  | 'layers'
  | 'basemap'
  | 'imported'
  | 'raster'
  | 'attributeTable'
  | 'legend';

export type GroupId = 'workspace-horizontal' | 'workspace-left' | 'workspace-right';

export interface WorkspaceLayout {
  version: 1;
  groups: Record<string, Record<string, number>>;
  collapsed: Record<string, boolean>;
}

export const DEFAULT_LAYOUT: WorkspaceLayout = {
  version: 1,
  groups: {
    'workspace-horizontal': { left: 20, center: 60, right: 20 },
    'workspace-left': { layers: 100, basemap: 0, imported: 0, raster: 0 },
    'workspace-right': { attributeTable: 100, legend: 0 },
  },
  // One panel per dock position (owner, 2026-10-11): Layers (left) and Attribute Table (right) are the home panels and are open
  // by default; the others open on request and replace them.
  collapsed: {
    layers: false,
    basemap: true,
    imported: true,
    raster: true,
    attributeTable: false,
    legend: true,
  },
};

/** The panel each dock position falls back to, and the group of panels that share the position. */
export const DOCK_POSITIONS: { group: GroupId; primary: PanelId; members: PanelId[] }[] = [
  { group: 'workspace-left', primary: 'layers', members: ['layers', 'basemap', 'imported', 'raster'] },
  { group: 'workspace-right', primary: 'attributeTable', members: ['attributeTable', 'legend'] },
];

/** Merge a server-loaded layout over the defaults (missing keys keep defaults). */
export function mergeDefaultLayout(saved?: WorkspaceLayout | null): WorkspaceLayout {
  if (!saved || typeof saved !== 'object') return DEFAULT_LAYOUT;
  const groups: Record<string, Record<string, number>> = {};
  for (const [gid, defaults] of Object.entries(DEFAULT_LAYOUT.groups)) {
    groups[gid] = { ...defaults, ...(saved.groups?.[gid] ?? {}) };
  }
  const collapsed: Record<string, boolean> = { ...DEFAULT_LAYOUT.collapsed };
  for (const [key, value] of Object.entries(saved.collapsed ?? {})) {
    if (key in collapsed) collapsed[key] = Boolean(value);
  }
  // A layout saved before positions showed one panel can have several open (or none) in one position: keep the home panel if it
  // is open, else the first open one, else open the home panel -- a position is never left empty.
  for (const pos of DOCK_POSITIONS) {
    const open = pos.members.filter((m) => !collapsed[m]);
    if (open.length === 1) continue;
    const keep = open.includes(pos.primary) ? pos.primary : open[0] ?? pos.primary;
    for (const m of pos.members) collapsed[m] = m !== keep;
    groups[pos.group] = { ...groups[pos.group], ...Object.fromEntries(pos.members.map((m) => [m, m === keep ? 100 : 0])) };
  }
  return { version: 1, groups, collapsed };
}

function apiBase(): string {
  return import.meta.env.VITE_API_URL ?? '';
}

function authHeaders(json = false): Record<string, string> {
  const headers: Record<string, string> = {};
  if (json) headers['Content-Type'] = 'application/json';
  const token = localStorage.getItem('access_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}

export async function fetchLayout(layoutKey = 'workspace'): Promise<WorkspaceLayout | null> {
  try {
    const res = await fetch(
      `${apiBase()}/api/v1/workspace/layout?layout_key=${encodeURIComponent(layoutKey)}`,
      { headers: authHeaders(), credentials: 'include' },
    );
    if (!res.ok) return null;
    const data = await res.json();
    return data?.layout_json ?? null;
  } catch (err) {
    console.error('Failed to load workspace layout:', err);
    return null;
  }
}

export async function saveLayout(
  layout: WorkspaceLayout,
  layoutKey = 'workspace',
): Promise<boolean> {
  try {
    const res = await fetch(`${apiBase()}/api/v1/workspace/layout`, {
      method: 'PUT',
      headers: authHeaders(true),
      credentials: 'include',
      body: JSON.stringify({ layout_key: layoutKey, layout_json: layout }),
    });
    return res.ok;
  } catch (err) {
    console.error('Failed to save workspace layout:', err);
    return false;
  }
}
