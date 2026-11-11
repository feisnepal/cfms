import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Drawer, message, Segmented } from 'antd';
import L from 'leaflet';
import * as turf from '@turf/turf';
import type { GeoJSON } from 'geojson';
import { forestApi, type DivideRequest } from '../services/api';
import { getLayerConfig } from '../lib/layerRegistry';
import { readDetail } from '../hooks/useErrorHandler';
import { allocateIslandCounts, UNDERSIZED_REL } from '../lib/islandApportionment';
import { useT } from '../i18n/hooks';
import { formatDecimal, formatNumber, parseLocaleNumber } from '../i18n/numberFormat';

type DivideLayerType = 'blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments';

interface EqualAreaDividePanelProps {
  map: L.Map | null;
  calculationId: string;
  layerType: DivideLayerType;
  /**
   * The resolved target feature id, OR '' for a ROOT divide (FS-4a.5/4a.17):
   * `blocks`/`compartments` with nothing of either branch yet carve the
   * forest's first top-level set straight from the boundary — the legacy
   * "mint a boundary-mirror block first" hack this used to need is gone.
   * `sub_blocks`/`sub_compartments` never root-divide (a sub-level always
   * needs a real parent one level up).
   */
  featureId: string;
  onClose: () => void;
  /** Fired after a successful divide (caller bumps geometry version + refetch). */
  onCommitted: () => void;
}

/**
 * Candidate layers to look the resolved `featureId` up in, in priority order —
 * a parent-kept-carve target (one level up) comes first, a self-divide target
 * (the layer itself) second, so the Drawer title / multi-island detection
 * shows whichever one actually matches. `blocks`/`compartments` have no
 * "level up" candidate — self-divide only; a ROOT divide (empty `featureId`)
 * is resolved separately, against the boundary.
 */
const PARENT_CANDIDATES: Record<DivideLayerType, ('blocks' | 'sub_blocks' | 'compartments' | 'sub_compartments')[]> = {
  blocks: ['blocks'],
  sub_blocks: ['blocks', 'sub_blocks'],
  compartments: ['blocks', 'compartments'],
  sub_compartments: ['compartments', 'sub_compartments'],
};

interface DivideConfig {
  /** 'count' = N pieces (strips/grid); 'area' = fixed area per piece, the last
   *  piece receives the remainder (strips only). */
  mode: 'count' | 'area';
  method: 'strips' | 'grid';
  count: number;
  rows: number;
  cols: number;
  direction: 'vertical' | 'horizontal';
  /** When set, overrides `direction` with a split angle in degrees (0=N-S, 90=E-W). */
  directionAngle: number | null;
  namingPattern: string;
  reassignTrees: boolean;
  /** Raw text of the per-piece area field for `mode==='area'` (kept as text so a
   *  half-typed "1." / "1.5" survives a keystroke — a numeric value swallows the
   *  decimal point and forces whole-number entry). */
  pieceAreaInput: string;
}

/** Legacy virtual directions mapped to degree angles (mirrors backend). */
const VIRTUAL_ANGLE: Record<'vertical' | 'horizontal', number> = { vertical: 90, horizontal: 0 };

/** Hard ceiling on total pieces per division (mirrors backend
 * `geometry_edit_service.MAX_DIVIDE_PIECES`) — a huge entered value used to
 * run the full per-piece division unbounded (user report, 2026-09-13:
 * "if user enter large number it may get hanged"). Enforced here too so the
 * input never lets the user type past it in the first place, not just as a
 * server-side rejection after the fact. */
const MAX_DIVIDE_PIECES = 20;

const DEFAULT_PATTERN: Record<DivideLayerType, string> = {
  blocks: 'Block-{index}',
  sub_blocks: '{parent_name}-SB{index}',
  compartments: '{block_name}-C{index}',
  sub_compartments: '{parent_name}-SC{index}',
};

/** Divide ghost overlay visuals (B.5). */
const GHOST_FILL = '#7AA6D9';
const GHOST_OPACITY = 0.32;

function featureProps(f: GeoJSON.Feature): Record<string, any> {
  return (f.properties ?? {}) as Record<string, any>;
}

export function EqualAreaDividePanel({
  map,
  calculationId,
  layerType,
  featureId,
  onClose,
  onCommitted,
}: EqualAreaDividePanelProps) {
  const [parentFeature, setParentFeature] = useState<GeoJSON.Feature | null>(null);
  const [parentLoading, setParentLoading] = useState(true);
  const t = useT();

  const parentProps = featureProps(parentFeature ?? ({} as GeoJSON.Feature));
  const parentName: string =
    (parentProps.name as string) ??
    (parentProps.block_name as string) ??
    (featureId || t('editing.divide.theBoundary'));

  const [config, setConfig] = useState<DivideConfig>({
    mode: 'count',
    method: 'strips',
    count: 8,
    rows: 4,
    cols: 2,
    direction: 'vertical',
    directionAngle: null,
    namingPattern: DEFAULT_PATTERN[layerType],
    reassignTrees: true,
    pieceAreaInput: '1',
  });
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof forestApi.dividePreview>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [committing, setCommitting] = useState(false);
  const geoLayerRef = useRef<L.GeoJSON | null>(null);
  const labelGroupRef = useRef<L.LayerGroup | null>(null);

  // ── Multi-island (MultiPolygon parent) — MULTI_ISLAND_DIVIDE_PLAN.md P3 ────
  // Each detached parcel is divided into a whole number of pieces (>= 1); a
  // compartment never spans two parcels. The "piece count" becomes N total; a
  // per-island table shows the apportioned counts, editable per row.
  const parentGeom = parentFeature?.geometry;
  const islandRings = useMemo<GeoJSON.Position[][][]>(
    () =>
      parentGeom?.type === 'MultiPolygon' && parentGeom.coordinates.length > 1
        ? parentGeom.coordinates
        : [],
    [parentGeom],
  );
  const isMultiIsland = islandRings.length > 1;
  const islandAreasHa = useMemo<number[]>(
    () =>
      islandRings.map(
        (rings) => turf.area({ type: 'Polygon', coordinates: rings }) / 10000,
      ),
    [islandRings],
  );
  const totalAreaHa = islandAreasHa.reduce((s, a) => s + a, 0);

  const parentAreaHa = useMemo<number>(() => {
    if (!parentGeom) return 0;
    try {
      return turf.area(parentGeom as GeoJSON.Geometry) / 10000;
    } catch {
      return 0;
    }
  }, [parentGeom]);
  /** Total selectable parent area in ha (union of parcels) — 0 until loaded. */
  const parentTotalHa = isMultiIsland ? totalAreaHa : parentAreaHa;

  const areaMode = config.mode === 'area';
  // NaN when the field is empty or a half-typed decimal ("1." parses to 1 until
  // the user finishes the fraction, which is what we want — the text is kept so
  // they CAN finish it, unlike a number-backed input).
  const pieceHa = areaMode ? parseLocaleNumber(config.pieceAreaInput) : NaN;
  const pieceAreaValid =
    Number.isFinite(pieceHa) && pieceHa >= 1 && (parentTotalHa <= 0 || pieceHa < parentTotalHa);
  // Backend cuts full pieces of ~pieceHa and appends the remainder as the last
  // piece, so the expected total is ceil(total/pieceHa) (per parcel for
  // multi-island parents — each parcel keeps its own remainder).
  const pieceEstimate =
    areaMode && pieceHa > 0 && parentTotalHa > 0
      ? (isMultiIsland
          ? islandAreasHa.reduce((s, a) => s + Math.max(1, Math.ceil(a / pieceHa)), 0)
          : Math.max(1, Math.ceil(parentTotalHa / pieceHa)))
      : 0;
  const pieceTooMany = areaMode && pieceEstimate > MAX_DIVIDE_PIECES;
  const blockAreaPreview = areaMode && (!pieceAreaValid || pieceTooMany);

  // Stepper for the by-area input: nudge the per-piece area up/down by 0.1 ha.
  // Kept on the TEXT value (like the field itself) so a typed "1." / "1.5"
  // survives, and the result is rounded to 4 dp to shed float noise (53.4075 +
  // 0.1 == 53.5074999…). Clamped so the value never drops below 1 ha.
  const nudgePieceArea = useCallback((delta: number) => {
    setConfig((c) => {
      const cur = parseLocaleNumber(c.pieceAreaInput);
      const next = (Number.isFinite(cur) ? cur : 1) + delta;
      const clamped = Math.max(1, next);
      return { ...c, pieceAreaInput: String(Math.round(clamped * 10000) / 10000) };
    });
  }, []);

  const stepArea = useCallback(
    (delta: number) => (e: React.KeyboardEvent | React.MouseEvent) => {
      // Shift held = 10× step (1 ha instead of 0.1 ha), a common spinner convention.
      e.preventDefault();
      nudgePieceArea(e.shiftKey ? delta * 10 : delta);
    },
    [nudgePieceArea],
  );

  const [islandCounts, setIslandCounts] = useState<number[] | null>(null);
  const islandUserSet = useRef(false);

  // (Re)seed the per-island counts from N whenever N changes and the user has
  // not hand-edited the table, or the parcel set changed under us.
  useEffect(() => {
    if (!isMultiIsland || islandAreasHa.length === 0) {
      setIslandCounts(null);
      islandUserSet.current = false;
      return;
    }
    const lenMismatch = !islandCounts || islandCounts.length !== islandAreasHa.length;
    if (lenMismatch || !islandUserSet.current) {
      try {
        setIslandCounts(
          allocateIslandCounts(islandAreasHa, Math.max(2, config.count)).counts,
        );
        islandUserSet.current = false;
      } catch {
        setIslandCounts(islandAreasHa.map(() => 1));
      }
    }
    // islandCounts intentionally out of deps — this seeds it, it must not loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMultiIsland, islandAreasHa, config.count]);

  const islandTotal = (islandCounts ?? []).reduce((s, c) => s + c, 0);
  const islandTarget = islandTotal > 0 ? totalAreaHa / islandTotal : 0;
  const setIslandCount = (i: number, value: number) => {
    setIslandCounts((prev) => {
      if (!prev) return prev;
      const next = prev.slice();
      const othersTotal = prev.reduce((s, c, j) => (j === i ? s : s + c), 0);
      const requested = Math.max(1, Math.trunc(value) || 1);
      // Cap this parcel's own share so the SUM across every parcel (what
      // actually gets committed) never exceeds the total-pieces ceiling.
      next[i] = Math.max(1, Math.min(requested, MAX_DIVIDE_PIECES - othersTotal));
      return next;
    });
    islandUserSet.current = true;
  };

  const buildRequest = useCallback((): DivideRequest => {
    // By-area is strips-only on the backend (a grid target is ignored there),
    // so force strips and never send a count when `mode === 'area'`.
    const grid = config.mode === 'count' && config.method === 'grid' && !isMultiIsland;
    const req: DivideRequest = {
      layer_type: layerType,
      feature_id: featureId,
      method: grid ? 'grid' : 'strips',
      count: grid ? null : config.mode === 'area' ? null : config.count,
      rows: grid ? config.rows : null,
      cols: grid ? config.cols : null,
      direction: config.direction,
      naming_pattern: config.namingPattern,
      reassign_trees: config.reassignTrees,
    };
    if (config.mode === 'area') req.target_area_sqm = pieceHa * 10000;
    if (config.directionAngle !== null) req.direction_angle = config.directionAngle;
    if (
      config.mode !== 'area' &&
      isMultiIsland &&
      islandCounts &&
      islandCounts.length === islandAreasHa.length
    ) {
      req.island_counts = islandCounts;
      req.count = islandCounts.reduce((s, c) => s + c, 0);
    }
    return req;
  }, [config, layerType, featureId, isMultiIsland, islandCounts, islandAreasHa.length]);

  // Resolve the parent/self feature (geometry + name) for the Drawer title and
  // multi-island detection. A ROOT divide (empty featureId, blocks/compartments
  // only — FS-4a.5/4a.17) has no parent row: reference the boundary instead, so
  // a multi-part boundary still gets the per-island table. Otherwise try each
  // candidate layer in priority order (parent-kept-carve target first,
  // self-divide target second) until one actually contains the id — which one
  // matches is exactly what tells the rest of the panel nothing more than a
  // Drawer title / multi-island hint needs to know; the divide itself is
  // resolved server-side regardless.
  useEffect(() => {
    let cancelled = false;
    setParentLoading(true);
    if (!featureId) {
      getLayerConfig('boundary')?.dataSource
        .fetch(calculationId)
        .then((features) => { if (!cancelled) setParentFeature(features[0] ?? null); })
        .finally(() => { if (!cancelled) setParentLoading(false); });
      return () => { cancelled = true; };
    }
    (async () => {
      for (const candidate of PARENT_CANDIDATES[layerType]) {
        const cfg = getLayerConfig(candidate);
        if (!cfg) continue;
        try {
          const features = await cfg.dataSource.fetch(calculationId);
          const found = features.find((f: GeoJSON.Feature) => {
            const id = featureProps(f).id ?? featureProps(f).featureId;
            return String(id ?? '') === featureId;
          });
          if (found) {
            if (!cancelled) setParentFeature(found);
            if (!cancelled) setParentLoading(false);
            return;
          }
        } catch { /* try the next candidate */ }
      }
      if (!cancelled) { setParentFeature(null); setParentLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [calculationId, layerType, featureId]);

  // Fetch labelled preview on every config change (P13 ghost overlay).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    if (blockAreaPreview) {
      // Local validation of the by-area mode — don't hit the API with a target
      // that cannot produce a valid split (backend also rejects it, but the
      // point is to guide the user before they wait on the request).
      setLoading(false);
      setPreview(null);
      setError(
        !Number.isFinite(pieceHa)
          ? null
          : pieceTooMany
            ? t('editing.divide.errPieceAreaTooMany', { max: formatNumber(MAX_DIVIDE_PIECES) })
            : pieceHa < 1
              ? t('editing.divide.errPieceAreaTooSmall')
              : t('editing.divide.errPieceAreaTooLarge'),
      );
      return () => { cancelled = true; };
    }
    forestApi
      .dividePreview(calculationId, buildRequest())
      .then((res) => {
        if (cancelled) return;
        setPreview(res);
      })
      .catch((err) => {
        if (cancelled) return;
        // The compartment/sub-compartment divide path raises structured
        // {code, message, message_np} details (resolve_service_detail on the
        // backend) — e.g. "already divided", "±5% tolerance exceeded",
        // "another block already has compartments". readDetail() picks the
        // right language; a plain string or a generic axios message both
        // still fall through it unchanged.
        setError(readDetail(err?.response?.data?.detail) ?? err?.message ?? t('editing.divide.previewFailed'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [calculationId, buildRequest, blockAreaPreview, pieceTooMany, pieceHa]);

  // Render ghost overlay pieces + labels on the map.
  useEffect(() => {
    if (!map) return;
    if (geoLayerRef.current) { map.removeLayer(geoLayerRef.current); geoLayerRef.current = null; }
    if (labelGroupRef.current) { map.removeLayer(labelGroupRef.current); labelGroupRef.current = null; }
    if (!preview || !preview.success || preview.pieces.length === 0) return;

    const features = preview.pieces.map((p) => ({ type: 'Feature', geometry: p.geometry, properties: { name: p.name, area_hectares: p.area_hectares } })) as GeoJSON.Feature[];
    const layer = L.geoJSON(features as any, {
      style: {
        color: '#FFFFFF',
        weight: 3,
        opacity: 0.95,
        fillColor: GHOST_FILL,
        fillOpacity: GHOST_OPACITY,
        dashArray: '8, 4',
      },
      interactive: false,
    }).addTo(map);
    const labels = L.layerGroup();
    for (const p of preview.pieces) {
      try {
        const b = L.geoJSON(p.geometry as any).getBounds();
        labels.addLayer(L.marker(b.getCenter(), {
          interactive: false,
          icon: L.divIcon({
            className: 'divide-preview-label',
            html: `<span class="divide-preview-label-text">${p.name}<br/>${formatDecimal(p.area_hectares)} ${t('units.hectare')}</span>`,
          }),
        }));
      } catch { /* degenerate piece */ }
    }
    labels.addTo(map);
    geoLayerRef.current = layer;
    labelGroupRef.current = labels;
    return () => {
      if (geoLayerRef.current) { map.removeLayer(geoLayerRef.current); geoLayerRef.current = null; }
      if (labelGroupRef.current) { map.removeLayer(labelGroupRef.current); labelGroupRef.current = null; }
    };
  }, [map, preview]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (map && geoLayerRef.current) { map.removeLayer(geoLayerRef.current); geoLayerRef.current = null; }
      if (map && labelGroupRef.current) { map.removeLayer(labelGroupRef.current); labelGroupRef.current = null; }
    };
  }, [map]);

  const piecesCount = preview?.total_pieces ?? 0;
  const gridPieces = config.rows * config.cols;

  const handleAccept = async () => {
    setCommitting(true);
    setError(null);
    try {
      const res = await forestApi.divideEqualAreas(calculationId, buildRequest());
      const MSG_KEY: Record<DivideLayerType, string> = {
        blocks: 'editing.divide.msgCreatedBlocks',
        sub_blocks: 'editing.divide.msgCreatedSubBlocks',
        compartments: 'editing.divide.msgCreatedCompartments',
        sub_compartments: 'editing.divide.msgCreatedSubCompartments',
      };
      const created = t(MSG_KEY[layerType], { count: formatNumber(res.n_children) });
      message.success(
        res.trees_reassigned > 0
          ? `${created} ${t('editing.divide.msgTreesReassigned', { count: formatNumber(res.trees_reassigned) })}`
          : created,
      );
      onCommitted();
      onClose();
    } catch (err) {
      setError(readDetail((err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail) ?? (err as { message?: string })?.message ?? t('editing.divide.failed'));
    } finally {
      setCommitting(false);
    }
  };

  const hasFloatButton = false;

  return (
    <Drawer
      open
      title={t('editing.divide.title', { name: parentName })}
      onClose={() => { if (!committing) onClose(); }}
      placement="right"
      size={440}
      mask={{ closable: false }}
      keyboard={false}
    >
      <div className="equal-area-divide-panel" data-testid="equal-area-divide-panel">
        <div className="divide-config-block">
          <label className="divide-field-label">{t('editing.divide.mode')}</label>
          <Segmented
            size="small"
            value={config.mode}
            onChange={(v) => setConfig((c) => ({ ...c, mode: v as 'count' | 'area' }))}
            options={[
              { label: t('editing.divide.modeCount'), value: 'count' },
              { label: t('editing.divide.modeArea'), value: 'area' },
            ]}
            disabled={committing}
            data-testid="divide-mode"
          />
        </div>

        {config.mode === 'area' ? (
          <div className="divide-config-block">
            <label className="divide-field-label" htmlFor="divide-piece-area">
              {t('editing.divide.pieceAreaHa')}
            </label>
            <div className="divide-stepper" data-testid="divide-area-stepper">
              <button
                type="button"
                className="divide-step-btn"
                aria-label={t('editing.divide.stepDown')}
                disabled={committing || !Number.isFinite(pieceHa) || pieceHa <= 1}
                onMouseDown={(e) => e.preventDefault()}
                onClick={stepArea(-0.1)}
              >−</button>
              <input
                id="divide-piece-area"
                type="text"
                inputMode="decimal"
                className="divide-stepper__input"
                min={1}
                max={MAX_DIVIDE_PIECES}
                value={config.pieceAreaInput}
                onChange={(e) => setConfig((c) => ({ ...c, pieceAreaInput: e.target.value }))}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowUp') { stepArea(0.1)(e); return; }
                  if (e.key === 'ArrowDown') { stepArea(-0.1)(e); return; }
                }}
                disabled={committing}
              />
              <button
                type="button"
                className="divide-step-btn"
                aria-label={t('editing.divide.stepUp')}
                disabled={committing || (parentTotalHa > 0 && pieceHa >= parentTotalHa)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={stepArea(0.1)}
              >+</button>
            </div>
            <div className="divide-pattern-hint">{t('editing.divide.pieceAreaHint')}</div>
            {parentTotalHa > 0 && pieceHa > 0 && (
              <div className="divide-grid-total" data-testid="divide-piece-estimate">
                {t('editing.divide.estPieces', { count: formatNumber(pieceEstimate) })}
              </div>
            )}
          </div>
        ) : isMultiIsland ? (
          <div className="divide-config-block divide-island-note" data-testid="divide-island-note">
            {t('editing.divide.islandNote', { count: formatNumber(islandRings.length) })}
          </div>
        ) : (
          <div className="divide-config-block">
            <label className="divide-field-label">{t('editing.divide.method')}</label>
            <Segmented
              size="small"
              value={config.method}
              onChange={(v) => setConfig((c) => ({ ...c, method: v as 'strips' | 'grid' }))}
              options={[
                { label: t('editing.divide.methodStrips'), value: 'strips' },
                { label: t('editing.divide.methodGrid'), value: 'grid' },
              ]}
              disabled={committing}
            />
          </div>
        )}

        <div className="divide-config-block">
          <label className="divide-field-label" htmlFor="divide-direction">
            {t('editing.divide.direction')}
          </label>
          <Segmented
            id="divide-direction"
            size="small"
            value={config.directionAngle !== null ? 'custom' : config.direction}
            onChange={(v) => {
              const value = v as string;
              setConfig((c) =>
                value === 'custom'
                  ? { ...c, directionAngle: VIRTUAL_ANGLE[c.direction] }
                  : { ...c, direction: value as 'vertical' | 'horizontal', directionAngle: null },
              );
            }}
            options={[
              { label: t('editing.divide.dirVertical'), value: 'vertical' },
              { label: t('editing.divide.dirHorizontal'), value: 'horizontal' },
              { label: t('editing.divide.dirCustom'), value: 'custom' },
            ]}
            disabled={committing}
          />
          {config.directionAngle !== null && (
            <div className="divide-angle-row">
              <input
                id="divide-angle"
                type="text" inputMode="decimal"
                min={0}
                max={180}
                step={1}
                value={config.directionAngle}
                onChange={(e) => {
                  const v = parseLocaleNumber(e.target.value);
                  if (!Number.isNaN(v)) {
                    const clamped = Math.max(0, Math.min(180, v));
                    setConfig((c) => ({ ...c, directionAngle: clamped }));
                  }
                }}
                disabled={committing}
              />
              <span className="divide-angle-unit">{t('editing.divide.angleHint')}</span>
            </div>
          )}
        </div>

        {config.mode === 'count' ? (
          isMultiIsland ? (
          <div className="divide-config-block">
            <label className="divide-field-label" htmlFor="divide-count">
              {t('editing.divide.totalCompartments')}
            </label>
            <input
              id="divide-count"
              type="text" inputMode="decimal"
              min={2}
              max={MAX_DIVIDE_PIECES}
              value={config.count}
              onChange={(e) => {
                const v = Math.trunc(parseLocaleNumber(e.target.value));
                if (!Number.isNaN(v) && v >= 0) {
                  islandUserSet.current = false;
                  setConfig((c) => ({ ...c, count: Math.min(v, MAX_DIVIDE_PIECES) }));
                }
              }}
              disabled={committing}
            />
            <div className="divide-max-pieces-hint">{t('editing.divide.maxPiecesHint', { max: formatNumber(MAX_DIVIDE_PIECES) })}</div>
            <table className="divide-island-table" data-testid="divide-island-table">
              <thead>
                <tr>
                  <th>{t('editing.divide.islandCol.island')}</th>
                  <th>{t('editing.divide.islandCol.area')}</th>
                  <th>{t('editing.divide.islandCol.pieces')}</th>
                  <th>{t('editing.divide.islandCol.avg')}</th>
                </tr>
              </thead>
              <tbody>
                {(islandCounts ?? []).map((c, i) => {
                  const avg = c > 0 ? islandAreasHa[i] / c : 0;
                  const under = islandTarget > 0 && avg < UNDERSIZED_REL * islandTarget;
                  return (
                    <tr key={i} className={under ? 'divide-island-row--undersized' : undefined}>
                      <td>{formatNumber(i + 1)}</td>
                      <td>{formatDecimal(islandAreasHa[i])}</td>
                      <td>
                        <input
                          type="text" inputMode="numeric"
                          className="divide-island-count"
                          aria-label={t('editing.divide.islandCol.piecesForIsland', { n: formatNumber(i + 1) })}
                          value={c}
                          onChange={(e) => {
                            const v = Math.trunc(parseLocaleNumber(e.target.value));
                            if (!Number.isNaN(v)) setIslandCount(i, v);
                          }}
                          disabled={committing}
                        />
                      </td>
                      <td>
                        {formatDecimal(avg)}
                        {under && <span className="divide-island-warn" title={t('editing.divide.undersizedHint')}> ⚠</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td>{t('editing.divide.islandCol.total')}</td>
                  <td>{formatDecimal(totalAreaHa)}</td>
                  <td>{formatNumber(islandTotal)}</td>
                  <td>{t('editing.divide.targetPiece', { ha: formatDecimal(islandTarget) })}</td>
                </tr>
              </tfoot>
            </table>
            {islandTotal !== config.count && (
              <div className="divide-pattern-hint">
                {t('editing.divide.islandTotalDiffers', { total: formatNumber(islandTotal) })}
              </div>
            )}
            {(islandCounts ?? []).some(
              (c, i) => c > 0 && islandTarget > 0 && islandAreasHa[i] / c < UNDERSIZED_REL * islandTarget,
            ) && (
              <div className="divide-pattern-hint divide-island-undersized-hint">
                {t('editing.divide.undersizedHint')}
              </div>
            )}
          </div>
        ) : config.method === 'strips' ? (
          <div className="divide-config-block">
            <label className="divide-field-label" htmlFor="divide-count">
              {t('editing.divide.pieceCount')}
            </label>
            <input
              id="divide-count"
              type="number"
              step={1}
              min={2}
              max={MAX_DIVIDE_PIECES}
              value={config.count}
              onChange={(e) => {
                const v = Math.trunc(Number(e.target.value));
                if (!Number.isNaN(v) && v >= 0) {
                  setConfig((c) => ({ ...c, count: Math.min(v, MAX_DIVIDE_PIECES) }));
                }
              }}
              disabled={committing}
            />
            <div className="divide-max-pieces-hint">{t('editing.divide.maxPiecesHint', { max: formatNumber(MAX_DIVIDE_PIECES) })}</div>
          </div>
        ) : (
          <div className="divide-config-block">
            <div className="divide-grid-grid">
              <div>
                <label className="divide-field-label" htmlFor="divide-rows">{t('editing.divide.rows')}</label>
                <input
                  id="divide-rows"
                  type="number"
                  step={1}
                  min={1}
                  max={MAX_DIVIDE_PIECES}
                  value={config.rows}
                  onChange={(e) => {
                    const v = Math.trunc(Number(e.target.value));
                    if (!Number.isNaN(v) && v >= 1) {
                      setConfig((c) => ({
                        ...c,
                        rows: v,
                        cols: Math.max(1, Math.min(c.cols, Math.floor(MAX_DIVIDE_PIECES / v))),
                      }));
                    }
                  }}
                  disabled={committing}
                />
              </div>
              <div>
                <label className="divide-field-label" htmlFor="divide-cols">{t('editing.divide.cols')}</label>
                <input
                  id="divide-cols"
                  type="number"
                  step={1}
                  min={1}
                  max={MAX_DIVIDE_PIECES}
                  value={config.cols}
                  onChange={(e) => {
                    const v = Math.trunc(Number(e.target.value));
                    if (!Number.isNaN(v) && v >= 1) {
                      setConfig((c) => ({
                        ...c,
                        cols: v,
                        rows: Math.max(1, Math.min(c.rows, Math.floor(MAX_DIVIDE_PIECES / v))),
                      }));
                    }
                  }}
                  disabled={committing}
                />
              </div>
            </div>
            <div className="divide-grid-total" data-testid="divide-grid-total">
              {t('editing.divide.pieces')} <strong>{formatNumber(gridPieces)}</strong>
            </div>
          </div>
          )
        ) : null}

        <div className="divide-config-block">
          <label className="divide-field-label" htmlFor="divide-pattern">
            {t('editing.divide.namingPattern')}
          </label>
          <input
            id="divide-pattern"
            type="text"
            value={config.namingPattern}
            onChange={(e) => setConfig((c) => ({ ...c, namingPattern: e.target.value }))}
            disabled={committing}
          />
          <div className="divide-pattern-hint">
            {config.namingPattern.includes('{index}') && (
              <>{t('editing.divide.placeholders')} <code>{'{block_name}'}</code> <code>{'{parent_name}'}</code> <code>{'{index}'}</code></>
            )}
          </div>
        </div>

        <div className="divide-config-block">
          <label className="divide-check-row">
            <input
              type="checkbox"
              checked={config.reassignTrees}
              onChange={(e) => setConfig((c) => ({ ...c, reassignTrees: e.target.checked }))}
              disabled={committing}
            />
            {t('editing.divide.reassignTrees')}
          </label>
        </div>

        {loading && <div className="divide-loading">{t('editing.divide.computing')}</div>}
        {error && <div className="divide-error" role="alert">{error}</div>}

        {!loading && !error && preview?.success && (
          <div className="divide-preview-summary" data-testid="divide-preview-summary">
            {t('editing.divide.previewed', { count: formatNumber(piecesCount) })}
            {preview.warnings.length > 0 && (
              <span className="divide-warnings">({preview.warnings.join(', ')})</span>
            )}
            <span className="divide-area-check">
              {t('editing.divide.tolerance')}
            </span>
          </div>
        )}

        {!loading && !error && preview && !preview.success && (
          <div className="divide-error" role="alert">
            {preview.reason === 'TOO_FEW_PIECES'
              ? t('editing.divide.errTooFewPieces')
              : t('editing.divide.errTolerance')}
          </div>
        )}
      </div>

      <div className="equal-area-divide-footer">
        <button type="button" onClick={onClose} disabled={committing} className="divide-btn divide-btn--secondary">
          {t('common.cancel')}
        </button>
        <button
          type="button"
          onClick={handleAccept}
          disabled={loading || !!error || piecesCount < 2 || committing}
          className="divide-btn divide-btn--primary"
        >
          {committing ? t('editing.divide.dividing') : t('editing.divide.divide')}
        </button>
      </div>
    </Drawer>
  );
}

export default EqualAreaDividePanel;