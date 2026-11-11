/**
 * The little symbol on a sub-layer chip (Activity Features: point / line / polygon): it shows the GEOMETRY the chip toggles, so
 * the row reads "● Point  ⁓ Line  ▱ Polygon" in one line instead of three stacked checkboxes. Drawn in `currentColor`, so the chip's
 * pressed / unpressed state recolours it.
 */
interface Props {
  kind: string;
  size?: number;
}

export function SubLayerSymbol({ kind, size = 11 }: Props) {
  const common = { width: size, height: size, viewBox: '0 0 12 12', 'aria-hidden': true, focusable: false as const, style: { display: 'block', flex: '0 0 auto' } };
  if (kind === 'point') {
    return (
      <svg {...common} data-testid="sublayer-symbol-point">
        <circle cx="6" cy="6" r="3.6" fill="currentColor" />
      </svg>
    );
  }
  if (kind === 'line') {
    return (
      <svg {...common} data-testid="sublayer-symbol-line">
        <polyline points="1,9.5 4.2,3 7.6,9 11,2.6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === 'polygon') {
    return (
      <svg {...common} data-testid="sublayer-symbol-polygon">
        <polygon points="2,3 9.5,1.8 11,7.2 6.2,10.6 1.4,8" fill="currentColor" fillOpacity="0.28" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      </svg>
    );
  }
  return <span aria-hidden="true" style={{ width: size, height: size, display: 'block' }} />;
}
