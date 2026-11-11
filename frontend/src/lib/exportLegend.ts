import { getAllLayerConfigs } from './layerRegistry';
import { BLOCK_COLORS, SUB_BLOCK_COLORS, COMPARTMENT_COLORS, SUB_AREA_COLORS, SUB_COMPARTMENT_COLORS, STYLE_PRESETS, PROTECTION_WC_COLOR, layerStyleKey, type CustomLayerStyle } from './layerStyles';
import { rendererLegendRows, type RendererSpec } from './layerRenderers';
import { resolveRasterLegend } from './rasterLegends';
import { useWorkspaceStore } from '../store/workspaceStore';
import { ACTIVITY_KINDS, ACTIVITY_KIND_IDS, activityKindCountKey, activityKindLabel } from './activityKinds';

const FONT_STACK = `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif`;

const PADDING = 28;
const HEADER_FONT = 30;
const LABEL_FONT = 36;
const COUNT_FONT = 30;
const SECTION_FONT = 30;
const SYMBOL_CELL = 48;
const GAP = 18;
const ROW_H = 60;
const MAX_LABEL_W = 380;

function getSwatchColor(layerId: string): string {
  switch (layerId) {
    case 'boundary': return '#228B22';
    case 'user_group': return STYLE_PRESETS.user_group.color || '#4338CA';
    case 'blocks': return BLOCK_COLORS[0];
    case 'sub_blocks': return SUB_BLOCK_COLORS[0];
    case 'compartments': return COMPARTMENT_COLORS[0];
    case 'sub_compartments': return SUB_COMPARTMENT_COLORS[0];
    case 'sub_areas': return '#8B4513';
    case 'activity_features': return '#1E90FF';
    default: return '#999';
  }
}

/** Exported legend swatch, honouring a user's custom layer style (P1.3). */
function resolveSwatch(layerId: string, custom?: CustomLayerStyle): string {
  if (custom) {
    const palette = ['blocks', 'sub_blocks', 'compartments', 'sub_compartments', 'sub_areas'].includes(layerId);
    if (!palette || custom.__flat) return custom.fillColor || custom.color || getSwatchColor(layerId);
  }
  return getSwatchColor(layerId);
}

function ellipsize(ctx: CanvasRenderingContext2D, text: string, maxW: number): string {
  if (ctx.measureText(text).width <= maxW) return text;
  let out = text;
  while (out.length > 1 && ctx.measureText(out + '…').width > maxW) {
    out = out.slice(0, -1);
  }
  return out + '…';
}

function drawPolygonSymbol(ctx: CanvasRenderingContext2D, cx: number, cy: number, size: number, color: string): void {
  const w = size / 2;
  const h = size * 0.42;
  ctx.beginPath();
  ctx.moveTo(cx - w, cy + h * 0.5);
  ctx.lineTo(cx - w * 0.55, cy - h);
  ctx.lineTo(cx + w * 0.3, cy - h * 0.75);
  ctx.lineTo(cx + w, cy - h * 0.1);
  ctx.lineTo(cx + w * 0.5, cy + h * 0.75);
  ctx.closePath();
  ctx.globalAlpha = 0.55;
  ctx.fillStyle = color;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.lineWidth = 1.4;
  ctx.strokeStyle = color;
  ctx.stroke();
}

function drawLineSymbol(ctx: CanvasRenderingContext2D, cx: number, cy: number, width: number, color: string): void {
  ctx.beginPath();
  ctx.moveTo(cx - width / 2, cy);
  ctx.lineTo(cx + width / 2, cy);
  ctx.lineCap = 'round';
  ctx.lineWidth = 4;
  ctx.strokeStyle = color;
  ctx.stroke();
  ctx.lineCap = 'butt';
}

function drawPointSymbol(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, color: string): void {
  ctx.beginPath();
  ctx.arc(cx, cy, r, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 1.2;
  ctx.strokeStyle = '#ffffff';
  ctx.stroke();
}

function drawSymbols(ctx: CanvasRenderingContext2D, cx: number, cy: number, geometryTypes: string[], color: string): void {
  const hasPoint = geometryTypes.some((t) => t === 'Point' || t === 'MultiPoint');
  const hasLine = geometryTypes.some((t) => t === 'LineString' || t === 'MultiLineString');
  const hasPoly = geometryTypes.some((t) => t === 'Polygon' || t === 'MultiPolygon');
  if (hasPoly && !hasLine && !hasPoint) {
    drawPolygonSymbol(ctx, cx, cy, 32, color);
    return;
  }
  if (hasLine && !hasPoly && !hasPoint) {
    drawLineSymbol(ctx, cx, cy, 34, color);
    return;
  }
  if (hasPoint && !hasPoly && !hasLine) {
    drawPointSymbol(ctx, cx, cy, 6, color);
    return;
  }
  drawPointSymbol(ctx, cx - 16, cy - 7, 5, color);
  drawLineSymbol(ctx, cx - 2, cy, 24, color);
  drawPolygonSymbol(ctx, cx + 13, cy + 4, 15, color);
}

interface Row {
  kind: 'header' | 'layer' | 'section' | 'raster-name' | 'raster-item';
  label?: string;
  color?: string;
  geometryTypes?: string[];
  count?: number;
}

export function renderLegendToCanvas(): HTMLCanvasElement {
  const store = useWorkspaceStore.getState();
  const configs = getAllLayerConfigs();
  const visibleLayers = configs.filter((c) => store.layerVisibility[c.id] !== false);
  const rasters = store.rasterCatalog.filter((r) => store.activeRasterLayers.includes(r.id));

  const rows: Row[] = [{ kind: 'header', label: 'Legend' }];

  for (const config of visibleLayers) {
    const count = store.featureCounts[config.id] ?? 0;
    const custom = store.customLayerStyles[layerStyleKey(config.id, 'builtin', store.calculationId)] as CustomLayerStyle | undefined;
    // P4.4 — a thematic renderer expands into a labelled block of class rows.
    const renderer = store.layerRenderers[config.id] as RendererSpec | undefined;
    if (renderer) {
      rows.push({ kind: 'raster-name', label: `${config.label} — ${renderer.field}` });
      for (const r of rendererLegendRows(renderer)) {
        rows.push({ kind: 'raster-item', label: r.label, color: r.color });
      }
      continue;
    }
    rows.push({
      kind: 'layer',
      label: config.label,
      color: resolveSwatch(config.id, custom),
      geometryTypes: config.geometryTypes,
      count: count > 0 ? count : undefined,
    });
    // Activity Features: one indented row per symbol kind on the map (mirrors LegendPanel).
    if (config.id === 'activity_features') {
      for (const k of ACTIVITY_KIND_IDS) {
        const n = store.featureCounts[activityKindCountKey(k)] ?? 0;
        if (n <= 0) continue;
        const geom = ACTIVITY_KINDS[k].geom;
        rows.push({
          kind: 'layer',
          label: `   ${activityKindLabel(k, 'en')}`,
          color: ACTIVITY_KINDS[k].color,
          geometryTypes: [geom === 'point' ? 'Point' : geom === 'line' ? 'LineString' : 'Polygon'],
          count: n,
        });
      }
    }
  }

  // Protection Working Circle — one row when a felling-free unit is on a visible
  // unit layer (P5-display; mirrors LegendPanel).
  const protectionUnitCount = (['blocks', 'sub_blocks', 'compartments', 'sub_compartments'] as const)
    .filter((id) => store.layerVisibility[id] !== false)
    .reduce((n, id) => n + (store.featureCounts[`${id}:protection`] ?? 0), 0);
  if (protectionUnitCount > 0) {
    rows.push({
      kind: 'layer',
      label: 'Protection working circle (no felling)',
      color: PROTECTION_WC_COLOR,
      geometryTypes: ['Polygon'],
      count: protectionUnitCount,
    });
  }

  if (rasters.length > 0) {
    rows.push({ kind: 'section', label: 'Raster Overlays' });
    for (const raster of rasters) {
      rows.push({ kind: 'raster-name', label: raster.name });
      for (const item of resolveRasterLegend(raster.id)) {
        rows.push({ kind: 'raster-item', label: item.label, color: item.color });
      }
    }
  }

  const measure = document.createElement('canvas').getContext('2d');
  let maxLabelW = 0;
  if (measure) {
    measure.font = `600 ${LABEL_FONT}px ${FONT_STACK}`;
    for (const row of rows) {
      if (row.label) {
        maxLabelW = Math.max(maxLabelW, Math.min(MAX_LABEL_W, measure.measureText(row.label).width));
      }
    }
  }

  let maxCountW = 0;
  if (measure) {
    measure.font = `600 ${COUNT_FONT}px ${FONT_STACK}`;
    for (const row of rows) {
      if (row.count != null) maxCountW = Math.max(maxCountW, measure.measureText(String(row.count)).width);
    }
  }
  maxCountW = Math.max(maxCountW, 40);

  const width = Math.ceil(PADDING * 2 + SYMBOL_CELL + GAP + maxLabelW + GAP + maxCountW);

  let height = PADDING * 2 + HEADER_FONT * 1.5;
  for (const row of rows) {
    height += row.kind === 'header' ? HEADER_FONT * 1.1 : row.kind === 'section' ? SECTION_FONT * 1.6 : ROW_H;
  }
  height += rasters.length > 0 ? 12 : 0;

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = Math.ceil(height);
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);
  ctx.textBaseline = 'middle';

  let y = PADDING;
  const symbolCx = PADDING + SYMBOL_CELL / 2;
  const labelX = PADDING + SYMBOL_CELL + GAP;

  for (const row of rows) {
    if (row.kind === 'header') {
      ctx.font = `700 ${HEADER_FONT}px ${FONT_STACK}`;
      ctx.fillStyle = '#555';
      ctx.fillText(row.label || '', PADDING, y);
      ctx.fillStyle = '#d0d0d0';
      ctx.fillRect(PADDING, y + HEADER_FONT * 0.85, width - PADDING * 2, 1.5);
      y += HEADER_FONT * 1.1;
      continue;
    }

    if (row.kind === 'section') {
      ctx.font = `700 ${SECTION_FONT}px ${FONT_STACK}`;
      ctx.fillStyle = '#999';
      ctx.fillText((row.label || '').toUpperCase(), PADDING, y);
      y += SECTION_FONT * 1.6;
      continue;
    }

    const rowCy = y + ROW_H / 2;
    if (row.kind === 'layer') {
      drawSymbols(ctx, symbolCx, rowCy, row.geometryTypes || ['Polygon'], row.color || '#999');
      ctx.font = `600 ${LABEL_FONT}px ${FONT_STACK}`;
      ctx.fillStyle = '#222';
      ctx.fillText(ellipsize(ctx, row.label || '', MAX_LABEL_W), labelX, rowCy);
      if (row.count != null) {
        const cw = ctx.measureText(String(row.count)).width;
        const bx = width - PADDING - cw - 14;
        const by = rowCy - COUNT_FONT * 0.55;
        ctx.beginPath();
        ctx.roundRect(bx, by, cw + 14, COUNT_FONT * 1.1, COUNT_FONT * 0.55);
        ctx.fillStyle = '#e8e8e8';
        ctx.fill();
        ctx.font = `600 ${COUNT_FONT}px ${FONT_STACK}`;
        ctx.fillStyle = '#666';
        ctx.fillText(String(row.count), bx + 7, rowCy);
      }
    } else if (row.kind === 'raster-name') {
      ctx.font = `700 ${LABEL_FONT * 0.8}px ${FONT_STACK}`;
      ctx.fillStyle = '#333';
      ctx.fillText(ellipsize(ctx, row.label || '', MAX_LABEL_W), labelX, rowCy);
    } else {
      drawSymbols(ctx, symbolCx, rowCy, ['Polygon'], row.color || '#999');
      ctx.font = `500 ${LABEL_FONT * 0.85}px ${FONT_STACK}`;
      ctx.fillStyle = '#333';
      ctx.fillText(ellipsize(ctx, row.label || '', MAX_LABEL_W), labelX, rowCy);
    }
    y += ROW_H;
  }

  return canvas;
}

export default renderLegendToCanvas;
