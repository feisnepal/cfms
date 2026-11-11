import { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import type { GeoJSON } from 'geojson';
import { useWorkspaceStore } from '../store/workspaceStore';
import type { PathStyleOptions } from '../store/workspaceStore';
import type { ContextMenuPosition } from './LayerContextMenu';
import { useT } from '../i18n/hooks';
import { layerStyleKey } from '../lib/layerStyles';
import { getLayerConfig } from '../lib/layerRegistry';
import type { LayerTypeId } from '../lib/layerRegistry';
import {
  buildCategorizedRenderer,
  buildGraduatedRenderer,
  rendererLegendRows,
  CONDITION_RENDERER,
  SLOPE_BAND_RENDERER,
  ASPECT_RENDERER,
  CANOPY_CLASS_RENDERER,
  type RendererSpec,
} from '../lib/layerRenderers';
import { RAMP_NAMES } from '../lib/colorRamps';

const COLOR_PRESETS = [
  '#FF0000', '#FF6600', '#FFD700', '#90EE90', '#00CED1', '#1E90FF', '#4B0082',
  '#FF1493', '#A0522D', '#808080', '#000000', '#FFFFFF', '#32CD32', '#9370DB',
];

// property keys that are never meaningful to symbolise by
const HIDDEN_FIELDS = new Set(['id', 'featureId', 'colorIndex', 'style', 'geometry', 'part_index', 'part_count']);
const isRealField = (k: string) => !HIDDEN_FIELDS.has(k) && !k.startsWith('geo_') && !k.startsWith('__');

interface LayerStyleDialogProps {
  visible: boolean;
  layerId: string;
  // RS-10.x/P10 follow-up (owner report 2026-10-02): a raster/Auto-Block
  // layer's features live in `store.rasterLayerFeatures`, not reachable
  // through `getLayerConfig` (a raster layer's id is a UUID, never a
  // registered `LayerTypeId`) the way the `'builtin'` branch below assumes
  // — that mismatch, not a missing field on the feature, is why the field
  // dropdown came back empty for every raster layer.
  layerType?: 'builtin' | 'imported' | 'raster';
  onClose: () => void;
  position: ContextMenuPosition;
}

type Mode = 'single' | 'categorized' | 'graduated';

export default function LayerStyleDialog({ visible, layerId, layerType = 'builtin', onClose, position }: LayerStyleDialogProps) {
  const store = useWorkspaceStore();
  const t = useT();
  const styleKey = layerStyleKey(layerId, layerType, store.calculationId);
  const current = store.customLayerStyles[styleKey] || {};

  // Renderer specs are keyed by bare layer id (result_data.layer_renderers, D8).
  const rendererKey = layerType === 'imported'
    ? (layerId.startsWith('imported-') ? layerId : `imported-${layerId}`)
    : layerId;
  const existingRenderer = store.layerRenderers[rendererKey] as RendererSpec | undefined;

  const usesPalette = layerType === 'builtin' && !!getLayerConfig(layerId as never)?.usesPalette;

  const [mode, setMode] = useState<Mode>(existingRenderer?.mode ?? 'single');
  const [fillColor, setFillColor] = useState(current.fillColor || '#1E90FF');
  const [strokeColor, setStrokeColor] = useState(current.color || '#1E90FF');
  const [strokeWidth, setStrokeWidth] = useState(current.weight || 2);
  const [fillOpacity, setFillOpacity] = useState(current.fillOpacity ?? 0.3);
  const [pointRadius, setPointRadius] = useState(current.radius || 8);
  const [flatOverride, setFlatOverride] = useState<boolean>((current as { __flat?: boolean }).__flat === true);
  const [customFillHex, setCustomFillHex] = useState('');
  const [customStrokeHex, setCustomStrokeHex] = useState('');
  const dialogRef = useRef<HTMLDivElement>(null);

  // Position state so the panel can be centered on first open, lifted fully
  // on-screen when it changes size, and dragged by its title bar.
  const center = useCallback(() => ({
    x: Math.max(4, Math.round((window.innerWidth - 470) / 2)),
    y: Math.max(4, Math.round((window.innerHeight - 200) / 2)),
  }), []);
  const [pos, setPos] = useState<ContextMenuPosition>(center);
  const centeredRef = useRef(false);
  const dragOffset = useRef<{ dx: number; dy: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  // After first paint, measure the real panel size and (a) center it on open,
  // then (b) whenever it outgrows the viewport pull it back fully on-screen.
  useLayoutEffect(() => {
    if (!visible) return;
    const el = dialogRef.current;
    if (!el) return;
    const h = el.offsetHeight || 200;
    const w = el.offsetWidth || 470;
    if (!centeredRef.current) {
      const cx = Math.max(4, Math.round((window.innerWidth - w) / 2));
      const cy = Math.max(4, Math.round((window.innerHeight - h) / 2));
      setPos({ x: cx, y: cy });
      centeredRef.current = true;
      return;
    }
    let { x, y } = pos;
    if (y + h > window.innerHeight - 8) y = Math.max(4, window.innerHeight - h - 8);
    if (x + w > window.innerWidth - 8) x = Math.max(4, window.innerWidth - w - 8);
    if (x !== pos.x || y !== pos.y) setPos({ x, y });
  }, [visible, pos]);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (!dragOffset.current) return;
      setPos({
        x: Math.max(4, Math.min(e.clientX - dragOffset.current.dx, window.innerWidth - 470 - 4)),
        y: Math.max(4, Math.min(e.clientY - dragOffset.current.dy, window.innerHeight - 200 - 4)),
      });
    };
    const onUp = () => { dragOffset.current = null; setDragging(false); };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [dragging]);

  // ── P4.3 symbology state ──────────────────────────────────────────────────
  const [features, setFeatures] = useState<GeoJSON.Feature[]>([]);
  // Owner report 2026-10-02: an empty field dropdown gave no indication of
  // WHY — a fetch failure was silently swallowed (`.catch(() => {})` below),
  // so a genuine network/permission error looked identical to "this layer
  // has no fields". Surfaced so the two are distinguishable.
  const [featuresError, setFeaturesError] = useState(false);
  const [field, setField] = useState(existingRenderer?.field ?? '');
  const [ramp, setRamp] = useState<string>((existingRenderer?.mode === 'graduated' && existingRenderer.ramp) || 'blues');
  const [classCount, setClassCount] = useState(existingRenderer?.mode === 'graduated' ? existingRenderer.breaks.length + 1 : 5);
  const [method, setMethod] = useState<'equal' | 'quantile'>(existingRenderer?.mode === 'graduated' ? existingRenderer.method : 'equal');
  const [draftSpec, setDraftSpec] = useState<RendererSpec | null>(existingRenderer ?? null);

  useEffect(() => {
    // Only load features once the user actually needs to classify — the
    // single-symbol path never touches the network.
    if (!visible || mode === 'single') return;
    setFeaturesError(false);
    if (layerType === 'imported') {
      const num = Number(layerId.replace('imported-', ''));
      setFeatures(store.importedLayerFeatures[num] ?? []);
      return;
    }
    if (layerType === 'raster') {
      // A raster/Auto-Block layer's id is a UUID, never a registered
      // `LayerTypeId` — `getLayerConfig` below would always miss it. Its
      // features live in `store.rasterLayerFeatures` instead (the same
      // slice the attribute table and the map's own GeoJSON layer read),
      // fetched on demand if the panel hasn't already loaded them (e.g. the
      // user opened Style… without first opening the attribute table).
      const existing = store.rasterLayerFeatures[layerId];
      if (existing) {
        setFeatures(existing);
        return;
      }
      if (!store.calculationId) return;
      let cancelled = false;
      store.fetchRasterLayerFeatures(store.calculationId, layerId)
        .then(() => {
          if (cancelled) return;
          setFeatures(useWorkspaceStore.getState().rasterLayerFeatures[layerId] ?? []);
        })
        .catch(() => { if (!cancelled) setFeaturesError(true); });
      return () => { cancelled = true; };
    }
    const cfg = getLayerConfig(layerId as LayerTypeId);
    if (!cfg || !store.calculationId) return;
    let cancelled = false;
    cfg.dataSource.fetch(store.calculationId)
      .then((f) => { if (!cancelled) setFeatures(f); })
      .catch(() => { if (!cancelled) setFeaturesError(true); });
    return () => { cancelled = true; };
  }, [visible, mode, layerId, layerType, store.calculationId, store.importedLayerFeatures, store.rasterLayerFeatures]);

  const fieldKeys = (() => {
    const set = new Set<string>();
    for (const f of features) {
      for (const k of Object.keys(f.properties ?? {})) if (isRealField(k)) set.add(k);
    }
    return [...set].sort();
  })();
  const numericFieldKeys = fieldKeys.filter((k) => {
    let num = 0; let seen = 0;
    for (const f of features) {
      const v = f.properties?.[k];
      if (v == null) continue;
      seen++;
      if (typeof v === 'number' || (v !== '' && Number.isFinite(Number(v)))) num++;
    }
    return seen > 0 && num / seen >= 0.6;
  });

  const classify = () => {
    if (!field) return;
    const spec: RendererSpec = mode === 'categorized'
      ? buildCategorizedRenderer(features, field, ramp)
      : buildGraduatedRenderer(features, field, classCount, method, ramp);
    setDraftSpec(spec);
    store.setLayerRenderer(rendererKey, spec); // "Classify" commits the spec immediately
  };

  const isPointLayer = layerType === 'imported'
    ? store.importedLayers.some((l) => String(l.id) === layerId && l.geometryTypes.every((g) => g === 'Point'))
    : ((getLayerConfig(layerId as never)?.geometryTypes.length ?? 0) > 0
        && (getLayerConfig(layerId as never)?.geometryTypes ?? []).every((g) => g === 'Point'));

  const showColourControls = !usesPalette || flatOverride;

  const buildStyle = useCallback((): PathStyleOptions & { __flat?: boolean } => {
    const s: PathStyleOptions & { __flat?: boolean } = { weight: strokeWidth, fillOpacity };
    if (showColourControls) {
      s.fillColor = fillColor;
      s.color = strokeColor;
    }
    if (isPointLayer) s.radius = pointRadius;
    if (usesPalette) s.__flat = flatOverride;
    return s;
  }, [strokeWidth, fillOpacity, showColourControls, fillColor, strokeColor, isPointLayer, pointRadius, usesPalette, flatOverride]);

  // Snapshot both tiers as they were on open, so Cancel / click-away restores them.
  const snapshotRef = useRef<{ style: PathStyleOptions | null; renderer: RendererSpec | null }>({
    style: Object.keys(current).length > 0 ? { ...current } : null,
    renderer: existingRenderer ?? null,
  });
  const committedRef = useRef(false);

  const restore = useCallback(() => {
    if (committedRef.current) return;
    if (snapshotRef.current.style) store.setCustomLayerStyle(styleKey, snapshotRef.current.style);
    else store.removeCustomLayerStyle(styleKey);
    store.setLayerRenderer(rendererKey, snapshotRef.current.renderer);
  }, [store, styleKey, rendererKey]);

  const handleCancel = useCallback(() => { restore(); onClose(); }, [restore, onClose]);
  const handleApply = () => {
    committedRef.current = true;
    if (mode === 'single') {
      store.setCustomLayerStyle(styleKey, buildStyle());
      store.setLayerRenderer(rendererKey, null);
    } else {
      store.setLayerRenderer(rendererKey, draftSpec ?? existingRenderer ?? null);
    }
    onClose();
  };
  const handleReset = () => {
    committedRef.current = true;
    store.removeCustomLayerStyle(styleKey);
    store.setLayerRenderer(rendererKey, null);
    onClose();
  };

  // Live preview.
  useEffect(() => {
    const id = window.setTimeout(() => {
      if (committedRef.current) return;
      if (mode === 'single') {
        store.setLayerRenderer(rendererKey, null);
        store.setCustomLayerStyle(styleKey, buildStyle());
      } else if (draftSpec) {
        store.setLayerRenderer(rendererKey, draftSpec);
      }
    }, 100);
    return () => window.clearTimeout(id);
  }, [store, styleKey, rendererKey, buildStyle, mode, draftSpec]);

  useEffect(() => {
    if (!visible) return;
    const handler = (e: MouseEvent) => {
      if (dialogRef.current && !dialogRef.current.contains(e.target as Node)) handleCancel();
    };
    const timer = setTimeout(() => document.addEventListener('mousedown', handler), 0);
    const escHandler = (e: KeyboardEvent) => { if (e.key === 'Escape') handleCancel(); };
    window.addEventListener('keydown', escHandler);
    return () => {
      clearTimeout(timer);
      document.removeEventListener('mousedown', handler);
      window.removeEventListener('keydown', escHandler);
    };
  }, [visible, handleCancel]);

  // P5.4 — focus management: move focus into the dialog on open, trap Tab
  // inside it, and return focus to the opener on close.
  useEffect(() => {
    if (!visible) return;
    const opener = document.activeElement as HTMLElement | null;
    const dlg = dialogRef.current;
    const focusables = () => Array.from(
      dlg?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((el) => !el.hasAttribute('disabled'));
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    dlg?.addEventListener('keydown', onKey);
    return () => { dlg?.removeEventListener('keydown', onKey); opener?.focus?.(); };
  }, [visible]);

  const handleFillPreset = (c: string) => { setFillColor(c); setCustomFillHex(''); };
  const handleStrokePreset = (c: string) => { setStrokeColor(c); setCustomStrokeHex(''); };

  if (!visible) return null;

  const previewRows = draftSpec ? rendererLegendRows(draftSpec) : [];

  const menu = (
    <div
      ref={dialogRef}
      className={`layer-style-dialog${dragging ? ' dragging' : ''}`}
      role="dialog"
      aria-modal="true"
      aria-label={t('layerPanel.styleDialogAria')}
      style={{ left: pos.x, top: pos.y }}
    >
      <h3
        className="style-dialog-title"
        title={t('layerPanel.styleDragHint')}
        onMouseDown={(e) => {
          if (e.button !== 0) return;
          dragOffset.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
          setDragging(true);
          e.preventDefault();
        }}
      >
        {t('layerPanel.styleTitle')}
      </h3>

      <div className="style-section">
        <label className="style-label" htmlFor="style-mode">{t('layerPanel.symbologyMode')}</label>
        <select
          id="style-mode"
          className="style-hex-input"
          value={mode}
          onChange={(e) => setMode(e.target.value as Mode)}
        >
          <option value="single">{t('layerPanel.symbologySingle')}</option>
          <option value="categorized">{t('layerPanel.symbologyCategorized')}</option>
          <option value="graduated">{t('layerPanel.symbologyGraduated')}</option>
        </select>
      </div>

      {layerType === 'builtin' && (layerId === 'blocks' || layerId === 'compartments') && (
        <button
          className="style-btn-cancel"
          style={{ width: '100%', marginBottom: 8 }}
          onClick={() => {
            setMode('categorized');
            setField(CONDITION_RENDERER.field);
            setDraftSpec(CONDITION_RENDERER);
            store.setLayerRenderer(rendererKey, CONDITION_RENDERER);
          }}
        >
          {t('layerPanel.symbologyByCondition')}
        </button>
      )}

      {/* One-click presets for the 3 Auto-Block source classifications —
          available on every level Auto-Block can write to (blocks,
          compartments, sub_compartments), unlike the condition preset above
          which only ever applies to the top two. */}
      {layerType === 'builtin' && (layerId === 'blocks' || layerId === 'compartments' || layerId === 'sub_compartments') && (
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          {([
            [SLOPE_BAND_RENDERER, 'layerPanel.symbologyBySlope'] as const,
            [ASPECT_RENDERER, 'layerPanel.symbologyByAspect'] as const,
            [CANOPY_CLASS_RENDERER, 'layerPanel.symbologyByCanopy'] as const,
          ]).map(([spec, labelKey]) => (
            <button
              key={spec.field}
              className="style-btn-cancel"
              style={{ flex: 1 }}
              onClick={() => {
                setMode('categorized');
                setField(spec.field);
                setDraftSpec(spec);
                store.setLayerRenderer(rendererKey, spec);
              }}
            >
              {t(labelKey)}
            </button>
          ))}
        </div>
      )}

      {mode !== 'single' && (
        <>
          <div className="style-row">
            <div className="style-section">
              <label className="style-label" htmlFor="style-field">{t('layerPanel.symbologyField')}</label>
              <select
                id="style-field"
                className="style-hex-input"
                value={field}
                onChange={(e) => { setField(e.target.value); setDraftSpec(null); }}
              >
                <option value="">—</option>
                {(mode === 'graduated' ? numericFieldKeys : fieldKeys).map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
              {featuresError && (
                <div className="style-field-error">{t('layerPanel.symbologyFieldsFailed')}</div>
              )}
              {!featuresError && features.length > 0 && fieldKeys.length === 0 && (
                <div className="style-field-error">{t('layerPanel.symbologyNoFields')}</div>
              )}
            </div>

            <div className="style-section">
              <label className="style-label" htmlFor="style-ramp">{t('layerPanel.symbologyRamp')}</label>
              <select id="style-ramp" className="style-hex-input" value={ramp} onChange={(e) => setRamp(e.target.value)}>
                {RAMP_NAMES.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
          </div>

          {mode === 'graduated' && (
            <div className="style-row">
              <div className="style-section">
                <div className="style-slider-label">
                  <span>{t('layerPanel.symbologyClasses')}</span><span>{classCount}</span>
                </div>
                <input type="range" min={3} max={7} step={1} value={classCount}
                  onChange={(e) => setClassCount(Number(e.target.value))} className="style-slider" />
              </div>
              <div className="style-section">
                <label className="style-label" htmlFor="style-method">{t('layerPanel.symbologyMethod')}</label>
                <select id="style-method" className="style-hex-input" value={method}
                  onChange={(e) => setMethod(e.target.value as 'equal' | 'quantile')}>
                  <option value="equal">{t('layerPanel.symbologyEqual')}</option>
                  <option value="quantile">{t('layerPanel.symbologyQuantile')}</option>
                </select>
              </div>
            </div>
          )}

          <button className="style-btn-apply" style={{ width: '100%', marginBottom: 8 }} disabled={!field} onClick={classify}>
            {t('layerPanel.symbologyClassify')}
          </button>

          {previewRows.length > 0 && (
            <div className="style-section symbology-preview">
              {previewRows.map((r, i) => (
                <div key={i} className="symbology-preview-row">
                  <span className="style-swatch" style={{ backgroundColor: r.color }} />
                  <span>{r.label}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {mode === 'single' && (
        <>
          {usesPalette && (
            <label className="style-section" style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <input type="checkbox" checked={flatOverride} onChange={(e) => setFlatOverride(e.target.checked)} />
              <span className="style-label" style={{ margin: 0 }}>{t('layerPanel.styleOverridePalette')}</span>
            </label>
          )}

          {showColourControls && (
            <div className="style-row">
              <div className="style-section">
                <label className="style-label">{t('layerPanel.styleFillColor')}</label>
                <div className="style-color-grid">
                  {COLOR_PRESETS.map((c) => (
                    <button
                      key={`fill-${c}`}
                      className={`style-swatch ${fillColor === c ? 'selected' : ''}`}
                      style={{ backgroundColor: c, border: c === '#FFFFFF' ? '1px solid #ccc' : undefined }}
                      onClick={() => handleFillPreset(c)}
                      aria-label={`${t('layerPanel.styleFillColorAria')} ${c}`}
                      title={c}
                    />
                  ))}
                </div>
                <input
                  type="text"
                  value={customFillHex}
                  onChange={(e) => { setCustomFillHex(e.target.value); if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) setFillColor(e.target.value); }}
                  placeholder="#RRGGBB"
                  className="style-hex-input"
                />
              </div>

              <div className="style-section">
                <label className="style-label">{t('layerPanel.styleStrokeColor')}</label>
                <div className="style-color-grid">
                  {COLOR_PRESETS.map((c) => (
                    <button
                      key={`stroke-${c}`}
                      className={`style-swatch ${strokeColor === c ? 'selected' : ''}`}
                      style={{ backgroundColor: c, border: c === '#FFFFFF' ? '1px solid #ccc' : undefined }}
                      onClick={() => handleStrokePreset(c)}
                      aria-label={`${t('layerPanel.styleStrokeColorAria')} ${c}`}
                      title={c}
                    />
                  ))}
                </div>
                <input
                  type="text"
                  value={customStrokeHex}
                  onChange={(e) => { setCustomStrokeHex(e.target.value); if (/^#[0-9a-fA-F]{6}$/.test(e.target.value)) setStrokeColor(e.target.value); }}
                  placeholder="#RRGGBB"
                  className="style-hex-input"
                />
              </div>
            </div>
          )}

          <div className="style-row">
            <div className="style-section">
              <div className="style-slider-label">
                <span>{t('layerPanel.styleStrokeWidth')}</span>
                <span>{strokeWidth}px</span>
              </div>
              <input type="range" min={1} max={5} step={1} value={strokeWidth}
                onChange={(e) => setStrokeWidth(Number(e.target.value))} className="style-slider" />
            </div>

            <div className="style-section">
              <div className="style-slider-label">
                <span>{t('layerPanel.styleFillOpacity')}</span>
                <span>{fillOpacity.toFixed(1)}</span>
              </div>
              <input type="range" min={0} max={1} step={0.1} value={fillOpacity}
                onChange={(e) => setFillOpacity(Number(e.target.value))} className="style-slider" />
            </div>

            {isPointLayer && (
              <div className="style-section">
                <div className="style-slider-label">
                  <span>{t('layerPanel.stylePointRadius')}</span>
                  <span>{pointRadius}px</span>
                </div>
                <input type="range" min={4} max={20} step={1} value={pointRadius}
                  onChange={(e) => setPointRadius(Number(e.target.value))} className="style-slider" />
              </div>
            )}
          </div>
        </>
      )}

      <div className="style-dialog-actions">
        <button onClick={handleReset} className="style-btn-reset">{t('layerPanel.styleReset')}</button>
        <button onClick={handleCancel} className="style-btn-cancel">{t('common.cancel')}</button>
        <button onClick={handleApply} className="style-btn-apply">{t('layerPanel.styleApply')}</button>
      </div>
    </div>
  );

  return createPortal(menu, document.body);
}
