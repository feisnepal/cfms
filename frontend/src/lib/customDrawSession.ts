import L from 'leaflet';
import { area as turfArea, length as turfLength, lineString as turfLineString, polygon as turfPolygon } from '@turf/turf';
import { SQM_PER_HA } from './splitPreview';
import { isTouchDevice } from './touchDevice';
import { createFreshPointIcon } from './pointIcons';

/**
 * customDrawSession — the generalized form of the pre-existing "E.8" scissor-
 * style draw tool (MapWorkspace.tsx's new-block/compartment draw: click to
 * add a vertex, drag an already-placed one, live turf-based measurement).
 * That tool exists because Geoman's own Draw.Line/Draw.Polygon cannot do this
 * — confirmed by reading the installed @geoman-io/leaflet-geoman-free@2.19.2
 * source (UNIFIED_GEOMETRY_DRAWING_PLAN.md P0(b)): draw-time vertex markers
 * are built `draggable: false` with only a finish-shape click handler; there
 * is no native per-vertex delete during an active draw, only "remove the
 * last vertex". This module is Leaflet's own drawing primitives (polyline/
 * polygon/marker + map click) — Geoman is not involved at all.
 *
 * What this module ADDS beyond the original E.8 tool (which only ever
 * handled Polygon, for exactly one call site): Point + Line support, and
 * per-vertex DELETE (E.8 never had this — right-click on desktop, tap-to-
 * select-then-tap-a-floating-trash-icon on touch, per plan D5).
 *
 * Deliberately excluded: anything domain-specific (boundary clipping,
 * overlap-against-existing-features, category pickers, snap-to-block). Those
 * stay in each call site's own `onFinish`/`onChange` handler — this module
 * only owns "how a shape gets drawn on the map," never "what happens once
 * it's committed." See the plan's P1 scope guard.
 */

export type DrawKind = 'Point' | 'Line' | 'Polygon';

export interface DrawMeasurement {
  /** Polygon only (hectares); null for Point/Line. */
  areaHa: number | null;
  /** Line only (metres); null for Point/Polygon. */
  lengthM: number | null;
}

const MIN_VERTICES: Record<DrawKind, number> = { Point: 1, Line: 2, Polygon: 3 };

/** Pure — no Leaflet needed. Unit-testable directly. */
export function measureLatLngCoords(kind: DrawKind, coords: Array<[number, number]>): DrawMeasurement {
  if (kind === 'Polygon' && coords.length >= 3) {
    const ring = [...coords, coords[0]];
    try {
      return { areaHa: turfArea(turfPolygon([ring])) / SQM_PER_HA, lengthM: null };
    } catch {
      return { areaHa: null, lengthM: null };
    }
  }
  if (kind === 'Line' && coords.length >= 2) {
    try {
      return { areaHa: null, lengthM: turfLength(turfLineString(coords), { units: 'meters' }) };
    } catch {
      return { areaHa: null, lengthM: null };
    }
  }
  return { areaHa: null, lengthM: null };
}

export interface CustomDrawSessionOptions {
  map: L.Map;
  kind: DrawKind;
  /** Stroke color for the live preview line/polygon outline (not the vertex handles, which keep the app's existing `.split-vertex-handle` red dot). */
  color?: string;
  /** Fires on every add/move/delete/undo with the live vertex list + measurement. */
  onChange?: (latlngs: L.LatLng[], measurement: DrawMeasurement) => void;
  /** Fires once the session finishes (explicit `finish()`, or immediately after the first click for Point). */
  onFinish: (latlngs: L.LatLng[]) => void;
  /** Fires when the session is cancelled (Escape, or an explicit `cancel()`). */
  onCancel?: () => void;
  /** Point sessions finish on the very first click by default (matches the existing Geoman Marker-draw behavior every call site already relies on). Set false to require an explicit finish() call instead. */
  finishOnFirstClick?: boolean;
}

export interface CustomDrawSession {
  finish(): void;
  cancel(): void;
  undoLastVertex(): void;
  destroy(): void;
  getLatLngs(): L.LatLng[];
}

const VERTEX_ICON = L.divIcon({
  className: 'split-vertex-handle',
  html: '<div class="split-vertex-dot"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

const TRASH_ICON = L.divIcon({
  className: 'draw-vertex-trash',
  html: '<div class="draw-vertex-trash-dot">✕</div>',
  iconSize: [22, 22],
  iconAnchor: [-6, 26],
});

export function startCustomDrawSession(opts: CustomDrawSessionOptions): CustomDrawSession {
  const { map, kind } = opts;
  const color = opts.color ?? '#2E7D32';
  const minVertices = MIN_VERTICES[kind];
  const touch = isTouchDevice();

  const latlngs: L.LatLng[] = [];
  let destroyed = false;
  let selectedIndex: number | null = null; // touch delete flow only

  const layerGroup = L.featureGroup().addTo(map);
  const line = L.polyline([], { color, weight: 2 }).addTo(layerGroup);
  const polygonPreview = L.polygon([], { color, weight: 2, fillColor: color, fillOpacity: 0.2, interactive: false }).addTo(layerGroup);
  polygonPreview.setStyle({ opacity: 0 }); // hidden until >=3 verts

  const vertexLayer = L.featureGroup().addTo(map);
  const trashLayer = L.featureGroup().addTo(map);
  const markers: L.Marker[] = [];

  const measurement = (): DrawMeasurement =>
    measureLatLngCoords(kind, latlngs.map((ll) => [ll.lng, ll.lat]));

  const fireChange = (): void => {
    opts.onChange?.(latlngs.slice(), measurement());
  };

  const clearTrash = (): void => {
    trashLayer.clearLayers();
    selectedIndex = null;
  };

  const redrawShape = (): void => {
    line.setLatLngs(latlngs);
    if (kind === 'Polygon' && latlngs.length >= 3) {
      polygonPreview.setLatLngs([latlngs]);
      polygonPreview.setStyle({ opacity: 0.9 });
    } else {
      polygonPreview.setStyle({ opacity: 0 });
    }
  };

  const deleteVertex = (index: number): void => {
    if (index < 0 || index >= latlngs.length) return;
    latlngs.splice(index, 1);
    clearTrash();
    redraw();
    fireChange();
  };

  const showTrashFor = (index: number): void => {
    clearTrash();
    selectedIndex = index;
    const marker = L.marker(latlngs[index], { icon: TRASH_ICON, zIndexOffset: 3000, interactive: true });
    marker.on('click', (e: L.LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(e);
      deleteVertex(index);
    });
    marker.addTo(trashLayer);
  };

  const redrawVertices = (): void => {
    while (markers.length) vertexLayer.removeLayer(markers.pop()!);
    const icon = kind === 'Point' ? createFreshPointIcon(latlngs.length === 1 ? 1 : null) : VERTEX_ICON;
    latlngs.forEach((ll, i) => {
      const m = L.marker(ll, { icon, draggable: true, zIndexOffset: 2000 });
      m.on('drag', () => {
        latlngs[i] = m.getLatLng();
        redrawShape();
        if (selectedIndex === i) showTrashFor(i);
      });
      m.on('dragend', () => {
        latlngs[i] = m.getLatLng();
        fireChange();
      });
      if (kind !== 'Point') {
        if (touch) {
          m.on('click', (e: L.LeafletMouseEvent) => {
            L.DomEvent.stopPropagation(e);
            if (selectedIndex === i) {
              clearTrash();
            } else {
              showTrashFor(i);
            }
          });
        } else {
          m.on('contextmenu', (e: L.LeafletMouseEvent) => {
            L.DomEvent.stopPropagation(e);
            e.originalEvent?.preventDefault();
            deleteVertex(i);
          });
        }
      }
      m.addTo(vertexLayer);
      markers.push(m);
    });
  };

  function redraw(): void {
    redrawShape();
    redrawVertices();
  }

  const addVertex = (latlng: L.LatLng): void => {
    const last = latlngs[latlngs.length - 1];
    if (last && Math.abs(last.lat - latlng.lat) < 1e-9 && Math.abs(last.lng - latlng.lng) < 1e-9) return;
    latlngs.push(latlng);
    clearTrash();
    redraw();
    fireChange();
    if (kind === 'Point' && (opts.finishOnFirstClick ?? true)) {
      finish();
    }
  };

  const onMapClick = (e: L.LeafletMouseEvent): void => {
    addVertex(e.latlng);
  };

  const onKeyDown = (e: KeyboardEvent): void => {
    if (e.key === 'Escape') {
      cancel();
    } else if (e.key === 'Enter') {
      finish();
    } else if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
      undoLastVertex();
    } else if (e.key === 'Backspace' && latlngs.length > 0 && selectedIndex === null) {
      undoLastVertex();
    }
  };

  function undoLastVertex(): void {
    if (latlngs.length === 0) return;
    latlngs.pop();
    clearTrash();
    redraw();
    fireChange();
  }

  function finish(): void {
    if (destroyed) return;
    if (latlngs.length < minVertices) return;
    const result = latlngs.slice();
    destroy();
    opts.onFinish(result);
  }

  function cancel(): void {
    if (destroyed) return;
    destroy();
    opts.onCancel?.();
  }

  function destroy(): void {
    if (destroyed) return;
    destroyed = true;
    map.off('click', onMapClick);
    window.removeEventListener('keydown', onKeyDown);
    if (map.hasLayer(layerGroup)) map.removeLayer(layerGroup);
    if (map.hasLayer(vertexLayer)) map.removeLayer(vertexLayer);
    if (map.hasLayer(trashLayer)) map.removeLayer(trashLayer);
  }

  map.on('click', onMapClick);
  window.addEventListener('keydown', onKeyDown);

  return {
    finish,
    cancel,
    undoLastVertex,
    destroy,
    getLatLngs: () => latlngs.slice(),
  };
}
