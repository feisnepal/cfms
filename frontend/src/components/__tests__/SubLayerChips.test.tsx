import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { SubLayerSymbol } from '../SubLayerSymbol';

describe('SubLayerSymbol — the geometry a sub-layer chip toggles', () => {
  it('draws a dot for points, a polyline for lines and a polygon for polygons', () => {
    const { container } = render(<><SubLayerSymbol kind="point" /><SubLayerSymbol kind="line" /><SubLayerSymbol kind="polygon" /></>);
    expect(screen.getByTestId('sublayer-symbol-point').querySelector('circle')).toBeTruthy();
    expect(screen.getByTestId('sublayer-symbol-line').querySelector('polyline')).toBeTruthy();
    expect(screen.getByTestId('sublayer-symbol-polygon').querySelector('polygon')).toBeTruthy();
    expect(container.querySelectorAll('svg[aria-hidden="true"]').length).toBe(3); // decoration: the chip's own name says what it is
  });

  it('is drawn in the current colour, so a pressed / unpressed chip recolours it', () => {
    render(<SubLayerSymbol kind="point" />);
    expect(screen.getByTestId('sublayer-symbol-point').querySelector('circle')!.getAttribute('fill')).toBe('currentColor');
  });

  it('an unknown kind draws an empty placeholder of the same size, never throws', () => {
    const { container } = render(<SubLayerSymbol kind="raster" size={11} />);
    expect(container.querySelector('svg')).toBeNull();
    expect((container.firstChild as HTMLElement).style.width).toBe('11px');
  });
});
