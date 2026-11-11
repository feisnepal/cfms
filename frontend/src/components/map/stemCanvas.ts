/**
 * Canvas renderer that can draw a star as well as a circle.
 *
 * Leaflet's canvas only draws circles for a CircleMarker. Mother trees are a star,
 * and drawing them on the SAME shared canvas keeps the cost of the layer flat: no
 * DOM icon per tree. A marker opts in with `options.shape === 'star'`; everything
 * else falls through to Leaflet's own circle drawing. The star's outer radius is the
 * marker's `_radius`, so Leaflet's bounds and hit-testing stay correct.
 */
import L from 'leaflet';

type CanvasProto = { _updateCircle: (this: unknown, layer: unknown) => void };

const StemCanvasClass = (L.Canvas as unknown as { extend: (o: object) => new (opts?: L.RendererOptions) => L.Canvas }).extend({
  _updateCircle(this: any, layer: any) {
    if (layer.options?.shape !== 'star') {
      (L.Canvas.prototype as unknown as CanvasProto)._updateCircle.call(this, layer);
      return;
    }
    if (!this._drawing || layer._empty()) return;
    const p = layer._point;
    const ctx = this._ctx as CanvasRenderingContext2D;
    const outer = Math.max(layer._radius, 2);
    const inner = outer * 0.45;
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const rad = i % 2 === 0 ? outer : inner;
      const a = -Math.PI / 2 + (i * Math.PI) / 5;
      const x = p.x + rad * Math.cos(a);
      const y = p.y + rad * Math.sin(a);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    this._fillStroke(ctx, layer);
  },
});

let shared: L.Canvas | null = null;

/** One canvas for every individual tree marker (never one per marker). */
export function getStemCanvasRenderer(): L.Canvas {
  if (!shared) shared = new StemCanvasClass({ padding: 0.5, tolerance: 10 } as L.RendererOptions);
  return shared;
}
