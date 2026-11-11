/**
 * GD 2.2.3 — Purpose → style map (review #8, Gap 8.2).
 *
 * Draft + finalized digitize layers are styled by purpose so users can
 * distinguish them at a glance. Color + pattern + shape together keep the
 * styling usable for colorblind users (Gap 8.2) — water uses a diagonal-hatch
 * fill pattern on top of a distinct color, roads use dashed red, inventory
 * uses green circle markers.
 */
import type { GeoJSON } from 'geojson';
import type { PurposeId } from './purposeGeometryRules';
import type { LeafletEventHandlerFn } from 'leaflet';
import L from 'leaflet';

export interface PurposeLayerStyle {
  color: string;
  weight: number;
  opacity: number;
  fillColor: string;
  fillOpacity: number;
  /** SVG dash pattern for lines/polygon borders (colorblind support). */
  dashArray?: string;
  /** Circle-marker radius when the purpose renders points (inventory/sample_plot). */
  pointRadius?: number;
  /** Pattern applied to polygon fills (colorblind support). */
  fillPattern?: 'diagonal-hatch' | 'solid';
  /** Marker/point symbol for the purpose. */
  pointShape?: 'circle' | 'square' | 'diamond';
}

export const PURPOSE_STYLE: Record<PurposeId, PurposeLayerStyle> = {
  inventory: {
    color: '#2e7d32',
    weight: 2,
    opacity: 0.9,
    fillColor: '#4caf50',
    fillOpacity: 0.35,
    pointRadius: 6,
    pointShape: 'circle',
  },
  sample_plot: {
    color: '#1b5e20',
    weight: 2,
    opacity: 0.9,
    fillColor: '#81c784',
    fillOpacity: 0.35,
    pointRadius: 8,
    pointShape: 'square',
  },
  user_group_boundary: {
    color: '#6a1b9a',
    weight: 2,
    opacity: 0.9,
    fillColor: '#ab47bc',
    fillOpacity: 0.3,
    dashArray: '6 4',
    fillPattern: 'solid',
  },
  boundary: {
    color: '#f57c00',
    weight: 3,
    opacity: 0.9,
    fillColor: '#ffb74d',
    fillOpacity: 0.25,
  },
  blocks: {
    color: '#1565c0',
    weight: 2,
    opacity: 0.9,
    fillColor: '#64b5f6',
    fillOpacity: 0.25,
  },
  sub_blocks: {
    color: '#283593',
    weight: 2,
    opacity: 0.9,
    fillColor: '#9fa8da',
    fillOpacity: 0.25,
  },
  compartments: {
    color: '#0d47a1',
    weight: 2,
    opacity: 0.9,
    fillColor: '#90caf9',
    fillOpacity: 0.25,
  },
  sub_compartments: {
    color: '#4527a0',
    weight: 2,
    opacity: 0.9,
    fillColor: '#b39ddb',
    fillOpacity: 0.25,
  },
  roads: {
    color: '#d32f2f',
    weight: 3,
    opacity: 0.95,
    fillColor: '#e57373',
    fillOpacity: 0.3,
    dashArray: '8 6',
    fillPattern: 'solid',
  },
  water: {
    color: '#0277bd',
    weight: 2,
    opacity: 0.9,
    fillColor: '#29b6f6',
    fillOpacity: 0.4,
    fillPattern: 'diagonal-hatch',
  },
  other: {
    color: '#616161',
    weight: 2,
    opacity: 0.85,
    fillColor: '#9e9e9e',
    fillOpacity: 0.3,
  },
  sub_areas: {
    color: '#00695c',
    weight: 2,
    opacity: 0.85,
    fillColor: '#4db6ac',
    fillOpacity: 0.3,
  },
};

export function purposeStyle(purpose: string): PurposeLayerStyle {
  return PURPOSE_STYLE[purpose as PurposeId] ?? PURPOSE_STYLE.other;
}

/** Leaflet path options for a digitize layer by purpose. */
export function purposeLeafletStyle(purpose: string, isDraft: boolean): {
  color: string;
  weight: number;
  opacity: number;
  fillColor: string;
  fillOpacity: number;
  dashArray?: string;
  fillPattern?: 'diagonal-hatch' | 'solid';
} {
  const s = purposeStyle(purpose);
  const style: {
    color: string;
    weight: number;
    opacity: number;
    fillColor: string;
    fillOpacity: number;
    dashArray?: string;
    fillPattern?: 'diagonal-hatch' | 'solid';
  } = {
    color: s.color,
    weight: s.weight,
    opacity: s.opacity,
    fillColor: s.fillColor,
    fillOpacity: s.fillOpacity,
  };
  if (s.dashArray) style.dashArray = s.dashArray;
  if (s.fillPattern === 'diagonal-hatch' && isDraft) {
    style.fillPattern = 'diagonal-hatch';
  }
  return style;
}

/**
 * Point-to-layer for purposes that draw point markers (inventory/sample_plot).
 * Circle/square/diamond div-icons give colorblind users a shape cue.
 */
export function purposePointToLayer(
  feature: GeoJSON.Feature,
  latlng: L.LatLng,
  purpose: string,
  onEachFeature?: LeafletEventHandlerFn,
): L.Marker {
  const s = purposeStyle(purpose);
  const shape = s.pointShape ?? 'circle';
  const bg = s.fillColor ?? '#4caf50';
  const border = s.color ?? '#2e7d32';
  const radius = s.pointRadius ?? 6;
  const cls = `purpose-point purpose-point-${shape}`;
  const size = radius * 2 + 4;
  const html = `<span class="purpose-point-inner" style="width:${size}px;height:${size}px;background:${bg};border:2px solid ${border};border-radius:${shape === 'circle' ? '50%' : shape === 'square' ? '2px' : '0'};transform:${shape === 'diamond' ? 'rotate(45deg)' : 'none'}"></span>`;
  const marker = L.marker(latlng, {
    icon: L.divIcon({
      className: `custom-point-icon ${cls}`,
      html,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    }),
  });
  return marker;
}
