/**
 * Reference-data layers of the map workspace: pure helpers (the server's list is `backend/app/core/reference_layers.py`).
 *
 * The layers are ready-made context round a forest (rivers, roads, wards, settlements, buildings). They are read-only: the workspace draws them, it never edits them.
 */
import type * as L from 'leaflet';
import type { ReferenceLayerInfo } from '../services/api';

/** The pane the layers are drawn in: above the base map and its tiles, below every layer of the forest itself (the overlay pane is 400). */
export const REFERENCE_PANE = 'cfReference';
export const REFERENCE_PANE_Z = '380';

/** Can this browser draw on a canvas? Thousands of footprints are quick on one; where it cannot (or a test has none) the map's own renderer is used instead. */
export const canvasAvailable = (): boolean => {
  try { return typeof document !== 'undefined' && !!document.createElement('canvas').getContext?.('2d'); } catch { return false; }
};

export const BUFFER_CHOICES_M = [500, 1000, 2000, 5000, 10000] as const;
export const DEFAULT_BUFFER_M = 2000;

/** The credit the open data's licence asks to be shown while the layer is on the map. */
export const ATTRIBUTION: Record<string, string> = { roads: '© OpenStreetMap contributors' };

export const layerLabel = (info: Pick<ReferenceLayerInfo, 'label_en' | 'label_ne'>, language: string | undefined): string =>
  (language ?? '').startsWith('ne') ? info.label_ne : info.label_en;

/** Leaflet path options from the server's style (the same colours the printed maps can use). */
export const pathStyle = (info: Pick<ReferenceLayerInfo, 'style' | 'geometry'>): L.PathOptions => {
  const s = info.style as Record<string, unknown>;
  const num = (k: string, d: number) => (typeof s[k] === 'number' ? (s[k] as number) : d);
  const fillOpacity = num('fillOpacity', info.geometry === 'line' ? 0 : 0.2);
  return {
    color: String(s.color ?? '#607d8b'), weight: num('weight', 1.5), opacity: num('opacity', 0.9),
    fill: info.geometry !== 'line' && fillOpacity > 0, fillColor: String(s.fillColor ?? s.color ?? '#607d8b'), fillOpacity,
    dashArray: typeof s.dashArray === 'string' ? s.dashArray : undefined,
  };
};

export const pointRadius = (info: Pick<ReferenceLayerInfo, 'style'>): number => {
  const r = (info.style as Record<string, unknown>).radius;
  return typeof r === 'number' ? r : 4;
};

/** What the person sees of a layer's licence: confirmed (with its name) or plainly not confirmed. */
export const licenceState = (info: Pick<ReferenceLayerInfo, 'licence'>): { confirmed: boolean; name: string | null } =>
  ({ confirmed: !!info.licence, name: info.licence });

// ── what is remembered between visits: which layers were on, and how wide the neighbourhood was ───────────────────────────────

export interface SavedReference { visible: string[]; bufferM: number }

const savedKey = (calculationId: string) => `cf_reference_layers_${calculationId}`;

export const readSaved = (calculationId: string | undefined): SavedReference => {
  const empty = { visible: [], bufferM: DEFAULT_BUFFER_M };
  if (!calculationId) return empty;
  try {
    const raw = JSON.parse(localStorage.getItem(savedKey(calculationId)) || 'null');
    if (!raw || !Array.isArray(raw.visible)) return empty;
    return {
      visible: raw.visible.filter((k: unknown) => typeof k === 'string'),
      bufferM: (BUFFER_CHOICES_M as readonly number[]).includes(raw.bufferM) ? raw.bufferM : DEFAULT_BUFFER_M,
    };
  } catch {
    return empty;   // storage blocked or unreadable: the layers simply start switched off
  }
};

export const writeSaved = (calculationId: string | undefined, saved: SavedReference): void => {
  if (!calculationId) return;
  try { localStorage.setItem(savedKey(calculationId), JSON.stringify(saved)); } catch { /* storage full or blocked: nothing is remembered, nothing breaks */ }
};

// ── the popup of a feature ─────────────────────────────────────────────────────────────────────────────────────────────────

const prettyKey = (k: string): string => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

/**
 * A feature's popup as DOM nodes. The values come from shared data, but they are text and are put in as text (never as markup): a name with `<` in it must show as a name.
 */
export const popupContent = (title: string, properties: Record<string, unknown> | null | undefined): HTMLElement => {
  const root = document.createElement('div');
  root.className = 'reference-popup';
  const head = document.createElement('strong');
  head.textContent = title;
  root.appendChild(head);
  const rows = Object.entries(properties ?? {}).filter(([k, v]) => !k.startsWith('_') && v !== null && v !== undefined && String(v).trim() !== '');
  if (rows.length > 0) {
    const table = document.createElement('table');
    rows.forEach(([k, v]) => {
      const tr = document.createElement('tr');
      const th = document.createElement('th');
      th.textContent = prettyKey(k);
      th.style.textAlign = 'left';
      th.style.paddingRight = '8px';
      const td = document.createElement('td');
      td.textContent = String(v);
      tr.appendChild(th);
      tr.appendChild(td);
      table.appendChild(tr);
    });
    root.appendChild(table);
  }
  return root;
};
