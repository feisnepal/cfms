import { describe, it, expect, vi } from 'vitest';
import { getStemCanvasRenderer } from '../stemCanvas';

/** A canvas renderer wired to a recording 2D context, so the drawing path runs without a browser canvas. */
function rig() {
  const ctx = {
    beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), arc: vi.fn(),
    save: vi.fn(), restore: vi.fn(), scale: vi.fn(),
  };
  const r = getStemCanvasRenderer() as unknown as Record<string, unknown>;
  r._drawing = true;
  r._ctx = ctx;
  r._fillStroke = vi.fn();
  return { r, ctx };
}

const layer = (shape: string | undefined, radius = 5) => ({
  options: { shape },
  _point: { x: 100, y: 100 },
  _radius: radius,
  _radiusY: radius,
  _empty: () => false,
});

describe('stem canvas renderer', () => {
  it('is one shared renderer, not one per marker', () => {
    expect(getStemCanvasRenderer()).toBe(getStemCanvasRenderer());
  });

  it('draws a 5-point star (10 vertices) for shape "star" and fills it', () => {
    const { r, ctx } = rig();
    (r as { _updateCircle: (l: unknown) => void })._updateCircle(layer('star'));
    expect(ctx.moveTo).toHaveBeenCalledTimes(1);
    expect(ctx.lineTo).toHaveBeenCalledTimes(9);
    expect(ctx.closePath).toHaveBeenCalled();
    expect(ctx.arc).not.toHaveBeenCalled();
    expect(r._fillStroke).toHaveBeenCalledTimes(1);
  });

  it('keeps every star vertex inside the marker radius so Leaflet bounds / hit-testing stay right', () => {
    const { r, ctx } = rig();
    (r as { _updateCircle: (l: unknown) => void })._updateCircle(layer('star', 6));
    const points = [...ctx.moveTo.mock.calls, ...ctx.lineTo.mock.calls] as [number, number][];
    for (const [x, y] of points) {
      expect(Math.hypot(x - 100, y - 100)).toBeLessThanOrEqual(6 + 1e-9);
    }
  });

  it('falls through to Leaflet circle drawing for everything else', () => {
    const { r, ctx } = rig();
    (r as { _updateCircle: (l: unknown) => void })._updateCircle(layer('circle'));
    expect(ctx.arc).toHaveBeenCalledTimes(1);
    expect(ctx.lineTo).not.toHaveBeenCalled();
    (r as { _updateCircle: (l: unknown) => void })._updateCircle(layer(undefined));
    expect(ctx.arc).toHaveBeenCalledTimes(2);
  });
});
