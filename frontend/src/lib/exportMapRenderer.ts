import L from 'leaflet';
import html2canvas from 'html2canvas';

const CAPTURE_OPTIONS = {
  scale: 2,
  backgroundColor: '#fff',
  allowTaint: false,
  useCORS: true,
  proxy: '/api/image-proxy',
  logging: false,
} as any;

const HIDDEN_PANE_SELECTORS = [
  '.leaflet-overlay-pane',
  '.leaflet-marker-pane',
  '.leaflet-shadow-pane',
  '.leaflet-tooltip-pane',
];

const VECTOR_DOWNSCALE = 0.15;
const STROKE_BASE = 0.5;
const RADIUS_BASE = 2;

function exportWeight(opts: Record<string, any>): number {
  return STROKE_BASE + (opts.weight ?? 3) * VECTOR_DOWNSCALE;
}

function exportRadius(radius: number): number {
  return RADIUS_BASE + radius * VECTOR_DOWNSCALE;
}

function extractRings(latlngs: any): any[][] {
  const first = latlngs?.[0];
  if (!first) return [];
  const isRing = (x: any) => x && typeof x[0]?.lat === 'number';
  if (isRing(first)) return latlngs;
  const rings: any[][] = [];
  for (const poly of latlngs) {
    if (isRing(poly)) rings.push(poly);
    else for (const r of poly) if (isRing(r)) rings.push(r);
  }
  return rings;
}

function buildPath(latlngs: any, map: L.Map, scale: number): Path2D | null {
  const rings = extractRings(latlngs);
  if (!rings.length) return null;
  const path = new Path2D();
  for (const ring of rings) {
    if (ring.length < 2) continue;
    const first = map.latLngToContainerPoint(ring[0]);
    path.moveTo(first.x * scale, first.y * scale);
    for (let i = 1; i < ring.length; i++) {
      const p = map.latLngToContainerPoint(ring[i]);
      path.lineTo(p.x * scale, p.y * scale);
    }
    path.closePath();
  }
  return path;
}

function drawPath(ctx: CanvasRenderingContext2D, layer: L.Path, path: Path2D, scale: number): void {
  const opts = (layer as any).options ?? {};
  const weight = exportWeight(opts);
  if (opts.fillColor && (opts.fillOpacity ?? 0) > 0) {
    ctx.fillStyle = opts.fillColor;
    ctx.globalAlpha = opts.fillOpacity ?? 1;
    ctx.fill(path);
    ctx.globalAlpha = 1;
  }
  if (opts.color && weight > 0) {
    ctx.strokeStyle = opts.color;
    ctx.lineWidth = weight;
    if (opts.dashArray) {
      ctx.setLineDash(String(opts.dashArray).split(/[\s,]+/).map((n) => Math.max(1, Number(n) * VECTOR_DOWNSCALE)));
    }
    ctx.stroke(path);
    ctx.setLineDash([]);
  }
}

function drawLayer(ctx: CanvasRenderingContext2D, map: L.Map, layer: any, scale: number): void {
  const opts = layer.options ?? {};
  if (layer instanceof L.Polygon) {
    const path = buildPath(layer.getLatLngs(), map, scale);
    if (path) drawPath(ctx, layer, path, scale);
    return;
  }
  if (layer instanceof L.Polyline) {
    const latlngs = layer.getLatLngs();
    const rings = extractRings(latlngs);
    const path = new Path2D();
    for (const ring of rings) {
      if (ring.length < 2) continue;
      const first = map.latLngToContainerPoint(ring[0]);
      path.moveTo(first.x * scale, first.y * scale);
      for (let i = 1; i < ring.length; i++) {
        const p = map.latLngToContainerPoint(ring[i]);
        path.lineTo(p.x * scale, p.y * scale);
      }
    }
    drawPath(ctx, layer, path, scale);
    return;
  }
  if (layer instanceof L.CircleMarker) {
    const pt = map.latLngToContainerPoint(layer.getLatLng());
    const radius = exportRadius(layer.getRadius() ?? 8);
    const cx = pt.x * scale;
    const cy = pt.y * scale;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    if (opts.fillColor) {
      ctx.fillStyle = opts.fillColor;
      ctx.globalAlpha = opts.fillOpacity ?? 1;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    if (opts.color) {
      ctx.strokeStyle = opts.color;
      ctx.lineWidth = exportWeight(opts);
      ctx.stroke();
    }
  }
}

function walkLayers(layer: any, fn: (l: any) => void): void {
  if (layer && typeof layer.getLayers === 'function') {
    for (const sub of layer.getLayers()) walkLayers(sub, fn);
  } else {
    fn(layer);
  }
}

export async function renderMapToCanvas(map: L.Map, container: HTMLElement, scale: number): Promise<HTMLCanvasElement> {
  const hidden: Array<{ el: HTMLElement; prev: string }> = [];
  for (const sel of HIDDEN_PANE_SELECTORS) {
    const el = container.querySelector(sel) as HTMLElement | null;
    if (el) {
      hidden.push({ el, prev: el.style.display });
      el.style.display = 'none';
    }
  }

  let canvas: HTMLCanvasElement;
  try {
    canvas = await html2canvas(container, { ...CAPTURE_OPTIONS, scale });
  } finally {
    for (const h of hidden) h.el.style.display = h.prev;
  }

  const ctx = canvas.getContext('2d');
  if (ctx) {
    map.eachLayer((layer: any) => walkLayers(layer, (l) => drawLayer(ctx, map, l, scale)));
  }
  return canvas;
}
