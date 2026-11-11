/**
 * Field Book map marker.
 *
 * A numbered circle like Sample Plots (E1/E2 of fieldbook_map_layer_plan.md: the label IS the text, no separate
 * tooltip), but SKY BLUE, not amber: the two layers used to share one colour and could not be told apart. A `vertex`
 * point is a solid filled marker; an `interpolated` point is a smaller hollow ring (E3).
 *
 * The label is what people read and quote -- `O1` for an outer-boundary point, `I7` for an internal one -- so the
 * marker becomes a pill when the label is longer than two characters. Colour says OUTER (sky blue) or INTERNAL
 * (violet); an amber ring says JUNCTION (three or more regions meet).
 */
import L from 'leaflet';
import { FIELDBOOK_COLOR, FIELDBOOK_TEXT_COLOR } from './layerStyles';

export const FIELDBOOK_INTERNAL_COLOR = '#7C3AED';
export const FIELDBOOK_JUNCTION_COLOR = '#F59E0B';

// Owner report 2026-10-02: `isSelected` swaps the marker's own colours (gold/orange, like Sample Plots) while the
// vertex/interpolated shape distinction and the label stay exactly as they were.
export function createFieldbookIcon(
  pointLabel: string | number | null,
  pointType: string | undefined,
  isSelected = false,
  boundaryClass?: string | null,
  isJunction = false,
) {
  const isVertex = pointType !== 'interpolated';
  const text = pointLabel == null ? '' : String(pointLabel);
  // 'O173' needs more room than '5': the marker becomes a pill when the label is longer than two characters
  const width = isVertex ? Math.max(18, 8 + text.length * 6) : 13;
  const size = isVertex ? 18 : 13;
  const base = boundaryClass === 'internal' ? FIELDBOOK_INTERNAL_COLOR : FIELDBOOK_COLOR;
  const ring = isJunction ? FIELDBOOK_JUNCTION_COLOR : '#fff';
  const style = isSelected
    ? (isVertex
        ? 'background-color: #FF8C00; border: 3px solid #FFD700; color: #1f2937;'
        : 'background-color: transparent; border: 3px solid #FF8C00; color: #FF8C00;')
    : (isVertex
        ? `background-color: ${base}; border: ${isJunction ? 3 : 2}px solid ${ring}; color: ${boundaryClass === 'internal' ? '#fff' : FIELDBOOK_TEXT_COLOR};`
        : `background-color: transparent; border: ${isJunction ? 3 : 2}px solid ${isJunction ? FIELDBOOK_JUNCTION_COLOR : base}; color: ${FIELDBOOK_TEXT_COLOR};`);
  return L.divIcon({
    className: 'custom-fieldbook-marker',
    html: `
      <div style="
        ${style}
        width: ${width}px;
        height: ${size}px;
        border-radius: ${size / 2}px;
        box-sizing: border-box;
        box-shadow: ${isSelected ? '0 0 0 2px rgba(255,140,0,0.4), 0 1px 4px rgba(0,0,0,0.6)' : '0 1px 3px rgba(0,0,0,0.5)'};
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        font-size: ${isVertex ? 9 : 7}px;
        line-height: 1;
        font-family: 'Noto Sans Devanagari', 'Nirmala UI', 'Mangal', Arial, sans-serif;
        text-shadow: 0 0 1px rgba(255,255,255,0.6);
      ">
        ${isVertex ? text : ''}
      </div>
    `,
    iconSize: [width, size],
    iconAnchor: [width / 2, size / 2],
    popupAnchor: [0, -(size / 2)],
  });
}
