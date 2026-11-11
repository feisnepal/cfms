import type { LayerTypeId } from '../lib/layerRegistry';

const TREES = '#2e9e44';
const TRUNK = '#795548';
const RIVER = '#1976d2';
const DIVIDER = '#8d6e63';
const SUBFILL = '#7ccb6e';

function Pine({ y = 0 }: { y?: number }) {
  return (
    <g transform={`translate(0 ${y})`}>
      <path
        d="M10 3 L12.6 6.8 H11.2 L13.4 10.4 H10.4 L12 13.5 H8 L9.6 10.4 H6.6 L8.8 6.8 H7.4 Z"
        fill={TREES}
      />
      <line x1="10" y1="14" x2="10" y2="16" stroke={TRUNK} strokeWidth="1" strokeLinecap="round" />
    </g>
  );
}

export function LayerGlyph({ type, size = 18 }: { type: LayerTypeId; size?: number }) {
  switch (type) {
    case 'boundary':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <Pine y={-1.5} />
          <path d="M4 17.2 h12" stroke={TREES} strokeWidth="1" strokeLinecap="round" />
        </svg>
      );

    case 'blocks':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <Pine y={-3} />
          <path
            d="M2 16 Q4.5 14 7 16 T12 16 T18 15"
            stroke={RIVER}
            strokeWidth="1.6"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
      );

    case 'compartments':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <Pine y={-1} />
          <line x1="10" y1="1.5" x2="10" y2="17.5" stroke={DIVIDER} strokeWidth="1" strokeDasharray="2.2 1.4" />
        </svg>
      );

    case 'sub_compartments':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <Pine y={-1} />
          <line x1="10" y1="1.5" x2="10" y2="17.5" stroke={DIVIDER} strokeWidth="1" strokeDasharray="2.2 1.4" />
          <line x1="10" y1="10.5" x2="15.2" y2="10.5" stroke={DIVIDER} strokeWidth="1" strokeDasharray="2.2 1.4" />
        </svg>
      );

    case 'sub_areas':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <path
            d="M3.5 3.5 H16.5 a1.6 1.6 0 0 1 1.6 1.6 V14.9 a1.6 1.6 0 0 1 -1.6 1.6 H3.5 a1.6 1.6 0 0 1 -1.6 -1.6 V5.1 a1.6 1.6 0 0 1 1.6 -1.6 Z"
            fill="none"
            stroke={TREES}
            strokeWidth="1.1"
          />
          <path d="M7.2 8 H12.8 L11.4 12 H6.8 Z" fill={SUBFILL} stroke={TREES} strokeWidth="0.8" />
        </svg>
      );

    case 'activity_features':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <circle cx="5" cy="14.5" r="2" fill={RIVER} />
          <line x1="9" y1="6" x2="15" y2="9.5" stroke={TREES} strokeWidth="1.8" strokeLinecap="round" />
          <path d="M12 13 H16.5 L15.5 17 H11 Z" fill="#f57c00" />
        </svg>
      );

    case 'sample_plots':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <circle cx="10" cy="10" r="5.2" fill="none" stroke="#f59e0b" strokeWidth="1.4" />
          <line x1="10" y1="2.6" x2="10" y2="6" stroke="#f59e0b" strokeWidth="1.1" />
          <line x1="10" y1="14" x2="10" y2="17.4" stroke="#f59e0b" strokeWidth="1.1" />
          <line x1="2.6" y1="10" x2="6" y2="10" stroke="#f59e0b" strokeWidth="1.1" />
          <line x1="14" y1="10" x2="17.4" y2="10" stroke="#f59e0b" strokeWidth="1.1" />
        </svg>
      );

    case 'stem_mapping':
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <circle cx="6" cy="7" r="2.6" fill="#7C3AED" />
          <circle cx="14" cy="6" r="2" fill="#7C3AED" opacity="0.7" />
          <circle cx="9.5" cy="14" r="2.3" fill="#7C3AED" opacity="0.85" />
        </svg>
      );

    case 'fieldbook':
      // A walked path with numbered waypoints — sky blue, distinct from the amber
      // Sample Plots glyph (fieldbook_map_layer_plan.md E9).
      return (
        <svg viewBox="0 0 20 20" width={size} height={size} aria-hidden="true">
          <path
            d="M3 16 L8.5 8.5 L12.5 12 L17 4"
            fill="none"
            stroke="#0ea5e9"
            strokeWidth="1.4"
            strokeDasharray="2.2 1.4"
            strokeLinecap="round"
          />
          <circle cx="3" cy="16" r="1.8" fill="#38bdf8" stroke="#fff" strokeWidth="0.6" />
          <circle cx="8.5" cy="8.5" r="1.8" fill="#38bdf8" stroke="#fff" strokeWidth="0.6" />
          <circle cx="12.5" cy="12" r="1.8" fill="#38bdf8" stroke="#fff" strokeWidth="0.6" />
          <circle cx="17" cy="4" r="1.8" fill="#38bdf8" stroke="#fff" strokeWidth="0.6" />
        </svg>
      );

    default:
      return null;
  }
}

export default LayerGlyph;