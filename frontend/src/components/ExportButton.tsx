import { useState } from 'react';
import { useT } from '../i18n/hooks';
import html2canvas from 'html2canvas';
import { fitA5Size, A5_150DPI_WIDTH } from '../lib/exportSizing';
import { getMapRef } from '../lib/mapRef';
import { renderMapToCanvas } from '../lib/exportMapRenderer';
import { renderLegendToCanvas } from '../lib/exportLegend';

type ExportFormat = 'png' | 'jpeg';
type ExportScope = 'map' | 'map-legend' | 'map-legend-table';

const SCOPE_LABEL_KEYS: Record<ExportScope, string> = {
  map: 'export.scopeMap',
  'map-legend': 'export.scopeMapLegend',
  'map-legend-table': 'export.scopeMapLegendTable',
};

const CAPTURE_OPTIONS = {
  scale: 2,
  backgroundColor: '#fff',
  allowTaint: false,
  useCORS: true,
  proxy: '/api/image-proxy',
  logging: false,
} as any;

const TEXT_SCALE = 3;

function stitch(parts: { c: HTMLCanvasElement; x: number; y: number }[], w: number, h: number): HTMLCanvasElement {
  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const ctx = out.getContext('2d');
  if (ctx) {
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, w, h);
    for (const p of parts) ctx.drawImage(p.c, p.x, p.y);
  }
  return out;
}

function queryEl(selector: string): HTMLElement | null {
  return document.querySelector(selector) as HTMLElement | null;
}

export function ExportButton({ forestName }: { forestName?: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>('png');
  const [exportError, setExportError] = useState<string | null>(null);

  async function capture(el: HTMLElement, scale = CAPTURE_OPTIONS.scale): Promise<HTMLCanvasElement> {
    return html2canvas(el, { ...CAPTURE_OPTIONS, scale });
  }

  async function handleExport(scope: ExportScope, fmt: ExportFormat) {
    setOpen(false);
    setExportError(null);
    const mapEl = queryEl('.workspace-map-area');
    if (!mapEl) {
      setExportError(t('export.mapNotFound'));
      return;
    }

    try {
      const map = getMapRef();
      if (map && typeof map.invalidateSize === 'function') {
        map.invalidateSize();
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
      let canvas: HTMLCanvasElement;
      if (scope === 'map') {
        canvas = map ? await renderMapToCanvas(map, mapEl, CAPTURE_OPTIONS.scale) : await capture(mapEl);
      } else {
        const legendCanvas = renderLegendToCanvas();
        const legendW = legendCanvas.width;
        const legendH = legendCanvas.height;
        if (scope === 'map-legend') {
          let mapScale = CAPTURE_OPTIONS.scale;
          if (map) {
            const mapDomW = mapEl.clientWidth || 662;
            const budget = A5_150DPI_WIDTH - legendW;
            mapScale = budget > 0
              ? Math.min(CAPTURE_OPTIONS.scale, Math.max(0.4, budget / mapDomW))
              : Math.max(0.4, CAPTURE_OPTIONS.scale * 0.6);
          }
          const m = map ? await renderMapToCanvas(map, mapEl, mapScale) : await capture(mapEl);
          canvas = stitch(
            [
              { c: m, x: 0, y: 0 },
              { c: legendCanvas, x: m.width, y: 0 },
            ],
            m.width + legendW,
            Math.max(m.height, legendH),
          );
        } else {
          const tableEl = queryEl('.right-panel-table');
          if (!tableEl) {
            setExportError(t('export.tableNotFound'));
            return;
          }
          const m = map ? await renderMapToCanvas(map, mapEl, CAPTURE_OPTIONS.scale) : await capture(mapEl);
          const tableCanvas = await capture(tableEl, TEXT_SCALE);
          const rightW = Math.max(legendW, tableCanvas.width);
          canvas = stitch(
            [
              { c: m, x: 0, y: 0 },
              { c: legendCanvas, x: m.width, y: 0 },
              { c: tableCanvas, x: m.width, y: legendH },
            ],
            m.width + rightW,
            Math.max(m.height, legendH + tableCanvas.height),
          );
        }
      }

      const mimeType = fmt === 'png' ? 'image/png' : 'image/jpeg';
      const quality = fmt === 'jpeg' ? 0.92 : undefined;
      const size = fitA5Size(canvas.width, canvas.height);
      if (size.width !== canvas.width || size.height !== canvas.height) {
        const down = document.createElement('canvas');
        down.width = size.width;
        down.height = size.height;
        const ctx = down.getContext('2d');
        if (ctx) {
          ctx.imageSmoothingEnabled = true;
          ctx.imageSmoothingQuality = 'high';
          ctx.drawImage(canvas, 0, 0, down.width, down.height);
        }
        canvas = down;
      }
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob((b) => resolve(b), mimeType, quality));
      if (!blob) {
        setExportError(t('export.imageFailed'));
        return;
      }

      const date = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const name = (forestName || 'Forest').replace(/\s+/g, '_');
      const scopeTag = scope === 'map' ? 'Map' : scope === 'map-legend' ? 'Map_Legend' : 'Map_Legend_Table';
      const filename = `${name}_${scopeTag}_${date}.${fmt}`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      const revoke = () => {
        if (a.parentNode) document.body.removeChild(a);
        URL.revokeObjectURL(url);
        window.removeEventListener('pagehide', revoke);
      };
      window.addEventListener('pagehide', revoke);
      setTimeout(revoke, 10000);
    } catch (err: any) {
      setExportError(err?.message || t('export.failed'));
    }
  }

  return (
    <div className="export-btn-wrapper">
      <button
        className="toolbar-btn export-trigger"
        onClick={() => setOpen((o) => !o)}
        aria-label={t('export.ariaExport')}
        title={t('export.titleExport')}
      >
        <span className="toolbar-icon" aria-hidden="true">⬇</span>
        <span className="export-btn-label">{t('export.button')}</span>
      </button>
      {open && (
        <>
          <div className="export-backdrop" onClick={() => setOpen(false)} />
          <div className="export-dropdown">
            <div className="export-format-row" role="radiogroup" aria-label={t('export.format')}>
              <button
                type="button"
                className={`export-format-btn ${format === 'png' ? 'active' : ''}`}
                onClick={() => setFormat('png')}
                role="radio"
                aria-checked={format === 'png'}
              >
                PNG
              </button>
              <button
                type="button"
                className={`export-format-btn ${format === 'jpeg' ? 'active' : ''}`}
                onClick={() => setFormat('jpeg')}
                role="radio"
                aria-checked={format === 'jpeg'}
              >
                JPG
              </button>
            </div>
            {(Object.keys(SCOPE_LABEL_KEYS) as ExportScope[]).map((scope) => (
              <button key={scope} type="button" onClick={() => handleExport(scope, format)}>
                {t(SCOPE_LABEL_KEYS[scope])}
              </button>
            ))}
            {exportError && <div className="export-error">{exportError}</div>}
          </div>
        </>
      )}
    </div>
  );
}

export default ExportButton;
