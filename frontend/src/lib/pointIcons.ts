import L from 'leaflet';

/**
 * Unified Geometry Drawing plan, D1: the marker for a point the user is
 * ACTIVELY placing/editing (not yet a saved Sample Plot, Fieldbook point, or
 * activity-kind feature). Same numbered-divIcon shape as Sample Plot's
 * `createSamplePlotIcon` (MapCanvas.tsx) — deliberately its own color, not a
 * reuse: a hue-collision audit against every point/line color already in the
 * app (Sample Plot's amber, Field Book's sky blue, the 3 temp draw-line
 * colors, and all 26 `activityKinds.ts` colors) found the entire orange/amber
 * band already claimed 7x over, and one open gap at ~290-330 deg (fuchsia) —
 * see UNIFIED_GEOMETRY_DRAWING_PLAN.md D1.
 */
export const FRESH_POINT_FILL = '#D946EF';
export const FRESH_POINT_RING = '#A21CAF';

/** Numbered divIcon for a point being actively drawn/edited. `index` is
 *  1-based (matches how Sample Plot numbers its own points); pass `null`
 *  for an unnumbered point (e.g. a single freshly-drawn point with no
 *  session-relative index yet). */
export function createFreshPointIcon(index: number | null): L.DivIcon {
  return L.divIcon({
    className: 'custom-fresh-point-marker',
    html: `
      <div style="
        background-color: ${FRESH_POINT_FILL};
        width: 18px;
        height: 18px;
        border-radius: 50%;
        border: 2px solid #fff;
        box-shadow: 0 0 0 2px ${FRESH_POINT_RING}, 0 1px 3px rgba(0,0,0,0.5);
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        color: #ffffff;
        font-size: 9px;
        line-height: 1;
        font-family: 'Noto Sans Devanagari', 'Nirmala UI', 'Mangal', Arial, sans-serif;
        text-shadow: 0 0 1px rgba(0,0,0,0.4);
      ">
        ${index ?? ''}
      </div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
    popupAnchor: [0, -9],
  });
}
