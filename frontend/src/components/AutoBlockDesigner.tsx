import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { message, Slider, Tooltip } from 'antd';
import L from 'leaflet';
import type { FeatureCollection } from 'geojson';
import { forestApi, type AutoBlockCommitBlock, type AutoBlockSource } from '../services/api';
import {
  buildMergePlan,
  unionFamily,
  type AutoBlockPiece,
  type AdjacencyEdge,
  type MergePlan,
} from '../lib/autoBlockMerge';
import { useTranslation } from 'react-i18next';
import { useT } from '../i18n/hooks';
import { readDetail } from '../hooks/useErrorHandler';
import { parseLocaleNumber } from '../i18n/numberFormat';
import LocaleInputNumber from './LocaleInputNumber';
import { classificationStyle } from '../lib/autoBlockLayerStyles';

interface AutoBlockDesignerProps {
  map: L.Map | null;
  calculationId: string;
  /**
   * Initial level shown by the designer. The user can switch via a Segmented
   * control inside the modal; preview is re-fetched per level.
   */
  initialLevel: 'blocks' | 'compartments';
  /**
   * Divide ONE existing block / compartment instead of creating the first set of
   * blocks: the same source list, clipped to that feature, saved as its children
   * (block -> compartments, compartment -> sub-compartments). The level choice is
   * then fixed by the parent and hidden.
   */
  parent?: { id: string; name: string } | null;
  onClose: () => void;
  /** Fired after a successful commit (caller bumps geometry version + refetch). */
  onCommitted: () => void;
}

const LEVEL_LABEL: Record<'blocks' | 'compartments', string> = {
  blocks: 'blocks',
  compartments: 'C',
};


// Owner report 2026-10-02: every <Tooltip> in this dialog rendered BEHIND
// it — antd's Tooltip portals to document.body with its own default
// z-index (~1070), far below `.auto-block-float-panel`'s own 10050
// (raised earlier to fix the dialog itself hiding behind the title bar/
// layer panel). Every Tooltip here needs an explicit zIndex above that,
// or it silently reappears any time the dialog's own z-index changes.
const AUTO_BLOCK_TOOLTIP_Z_INDEX = 10060;

// RS-10.3/10.5-fusion: both Union modes share the same 9-attribute-per-piece
// shape (`dominant_*` + `sub_area_*`), so everywhere the Designer treats
// union_zonal specially (no single classification, full attribute copy on
// commit) applies identically to union_fusion.
function isUnionSource(s: AutoBlockSource): boolean {
  return s === 'union_zonal' || s === 'union_fusion';
}

// RS-10.3b: the optional pixel-fused attributes a planner can toggle for
// union_fusion specifically (slope is always on, not listed here — it's the
// gate and can't be deselected). Mirrors
// `union_fusion_vectorize.ALL_OPTIONAL_SOURCE_KEYS` exactly.
const FUSION_OPTIONAL_SOURCES = [
  'aspect', 'forest_type', 'nasa_quality', 'forest_health', 'landcover', 'dem',
] as const;
type FusionOptionalSource = (typeof FUSION_OPTIONAL_SOURCES)[number];

// RS-0.4: maps each fusion-optional key to the raster catalog key
// `GET /raster-coverage/{layer}` understands (`TileService.RASTER_TABLES`).
// Lets the fusion checklist pre-flight coverage and disable a source that
// can't contribute here (e.g. NASA 2020 outside its tile extent) BEFORE the
// user hits `no_union_fusion_coverage` after running Preview.
const FUSION_SOURCE_TO_RASTER_LAYER: Record<FusionOptionalSource, string> = {
  aspect: 'aspect',
  forest_type: 'forest_type',
  nasa_quality: 'nasa_forest_2020',
  forest_health: 'forest_health',
  landcover: 'landcover',
  dem: 'dem',
};

// Property key triples per raster/TIF source: [value key, English label key,
// Nepali label key (absent for aspect/canopy — they fall back to English)].
const SOURCE_PROPERTY_KEYS: Partial<Record<AutoBlockSource, [string, string, string?]>> = {
  slope: ['slope_band', 'slope_band_label_en', 'slope_band_label_ne'],
  aspect: ['aspect_code', 'aspect_label'],
  canopy: ['canopy_class', 'canopy_class_label'],
  // NASA ships a single English vocabulary label (no per-class Nepali), so the
  // NE slot is absent and `extractClassification` falls back to English.
  nasa_quality: ['nasa_quality', 'nasa_quality_label'],
  // RS-9.1/9.2 (P9): same shape, property keys match
  // `_PREVIEW_CLASS_KEYS` in auto_block_service.py exactly.
  forest_health: ['health_class', 'health_class_label'],
  landcover: ['landcover', 'landcover_label'],
  // RS-9.3: elevation band, 1-N depending on `elevation_bands`. Property is
  // `contour_band`, NOT `elevation_zone` — that name is reserved for the
  // unrelated RS-2.19 forest-relative attribute (see api.ts). No Nepali slot
  // — "Low"/"Mid"/"High"/"Zone N" comes from the same EN-only vocabulary the
  // backend's DEM_ELEVATION.label_fn carries.
  dem: ['contour_band', 'contour_band_label'],
  // RS-9.5: FRTC forest type, 1-25 (26 is anonymous — extractClassification
  // returns null for it, same as NASA's 0 falls out of `nasa_quality`).
  forest_type: ['forest_type', 'forest_type_label'],
  // RS-10.2/10.5: Union has 9 attributes, not one, so it has no entry here
  // (same as mmu) — `extractClassification` falls through to null/null/null
  // for it and the preview list falls back to showing natural_name, same as
  // mmu. See `UNION_DOMINANT_KEYS` below for how its full attribute set is
  // actually carried through to commit.
};

// RS-10.2/10.5: the 8 raster-derived `dominant_*` keys plus the 2 sub-area
// keys `preview_union_zonal_blocks` puts on every piece's properties. Copied
// wholesale from the anchor piece on commit (see `handleAccept`) rather than
// run through the single-value `sourceMeta`/`extractClassification` pipeline
// every other source uses — Union has no single value to extract.
const UNION_DOMINANT_KEYS = [
  'dominant_slope_band', 'slope_band_label', 'dominant_aspect', 'dominant_canopy_class',
  'dominant_nasa_quality', 'dominant_health_class', 'dominant_landcover',
  'dominant_forest_type', 'dominant_contour_band',
  'sub_area_category', 'sub_area_excluded',
] as const;

function extractClassification(
  source: AutoBlockSource,
  props: Record<string, unknown>,
): { value: number | null; labelEn: string | null; labelNe: string | null } {
  const keys = SOURCE_PROPERTY_KEYS[source];
  if (!keys) return { value: null, labelEn: null, labelNe: null };
  const [valueKey, enKey, neKey] = keys;
  const labelEn = (props[enKey] as string | null) ?? null;
  return {
    value: (props[valueKey] as number | null) ?? null,
    labelEn,
    labelNe: (neKey ? (props[neKey] as string | null) : null) ?? labelEn,
  };
}

function asPiece(f: GeoJSON.Feature, index: number): AutoBlockPiece {
  const p = (f.properties ?? {}) as Record<string, unknown>;
  return {
    index: Number(p.index ?? index + 1),
    name: String(p.name ?? ''),
    block_name: String(p.block_name ?? ''),
    natural_name: (p.natural_name as string | null) ?? null,
    area_hectares: Number(p.area_hectares ?? 0),
    geometry: f.geometry,
  };
}

/**
 * AutoBlockDesigner — Phase B designer workflow.  Fetches the server-side MMU
 * preview (bas.rs.mmu clip + sliver absorb + natural names), then lets the user
 * pick the target block count N on a slider; the merge plan runs CLIENT-side
 * (parity with backend `_merge_plan`, see lib/autoBlockMerge).  Locked tiles
 * become anchors and raise the minimum N.  Accept → commit → onCommitted().
 */
export function AutoBlockDesigner({
  map,
  calculationId,
  initialLevel,
  parent = null,
  onClose,
  onCommitted,
}: AutoBlockDesignerProps) {
  const t = useT();
  const { i18n } = useTranslation();
  const [level, setLevel] = useState<'blocks' | 'compartments'>(initialLevel);
  const [source, setSource] = useState<AutoBlockSource>('slope');
  const [pieces, setPieces] = useState<AutoBlockPiece[]>([]);
  // Per-piece classification (index into `pieces`) for whichever raster/TIF
  // source is active — slope_band / aspect_code / canopy_class, each with
  // its own label field(s) in the preview response. Kept separate from
  // AutoBlockPiece (shared with the merge-plan library and its own tests)
  // rather than extending that type. Empty for source === 'mmu'.
  const [sourceMeta, setSourceMeta] = useState<
    Record<number, { value: number | null; labelEn: string | null; labelNe: string | null }>
  >({});
  // RS-10.2/10.5: Union's full 9-key attribute set per piece, parallel to
  // `sourceMeta` above but keyed by the raw dominant_*/sub_area_* property
  // names rather than reduced to one value — see `UNION_DOMINANT_KEYS`.
  // Empty for every source other than union_zonal.
  const [unionAttrs, setUnionAttrs] = useState<Record<number, Record<string, unknown>>>({});
  // RS-10.3b: which optional attributes to pixel-fuse for union_fusion —
  // defaults to all of them (the original RS-10.3 behaviour); slope is
  // always included server-side regardless of this list.
  const [fusionSources, setFusionSources] = useState<FusionOptionalSource[]>([...FUSION_OPTIONAL_SOURCES]);
  const [fusionIncludeCanopy, setFusionIncludeCanopy] = useState(true);
  const toggleFusionSource = useCallback((key: FusionOptionalSource) => {
    setFusionSources((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  }, []);
  // RS-0.4 pre-flight: `undefined` = not checked yet, `true`/`false` = this
  // forest's boundary is/isn't actually covered by that raster. Checked only
  // while union_fusion is the active source -- every other source already
  // surfaces its own single `no_<source>_coverage` message.
  const [fusionCoverage, setFusionCoverage] = useState<Partial<Record<FusionOptionalSource, boolean>>>({});
  useEffect(() => {
    if (source !== 'union_fusion') return;
    let cancelled = false;
    setFusionCoverage({});
    Promise.all(
      FUSION_OPTIONAL_SOURCES.map((key) =>
        forestApi
          .rasterCoverage(calculationId, FUSION_SOURCE_TO_RASTER_LAYER[key])
          .then((res) => [key, res.covered] as const)
          .catch(() => [key, true] as const), // probe failure: don't block the checkbox on a diagnostic error
      ),
    ).then((entries) => {
      if (cancelled) return;
      setFusionCoverage(Object.fromEntries(entries));
      // Drop any already-selected source the probe just found has no
      // coverage here, so Preview doesn't re-run straight into
      // `no_union_fusion_coverage` for a source the UI could see coming.
      const uncovered = entries.filter(([, covered]) => !covered).map(([key]) => key);
      if (uncovered.length > 0) {
        setFusionSources((prev) => prev.filter((k) => !uncovered.includes(k)));
      }
    });
    return () => { cancelled = true; };
  }, [source, calculationId]);
  const [edges, setEdges] = useState<AdjacencyEdge[]>([]);
  const [meta, setMeta] = useState<Awaited<ReturnType<typeof forestApi.autoBlocksPreview>>['meta'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [n, setN] = useState(1);
  const [locked, setLocked] = useState<number[]>([]);
  // Owner report 2026-10-01: default to 5 ha (was 1) and force-merge always on
  // (was off) -- both still user-adjustable via the dialog's own controls.
  const [minBlockHa, setMinBlockHa] = useState(5);
  const [forceAbsorbOrphans, setForceAbsorbOrphans] = useState(true);
  const [committing, setCommitting] = useState(false);
  const geoLayerRef = useRef<L.GeoJSON | null>(null);
  // Serial prefix for the map labels: SB-1 / SC-1 when dividing a feature
  // (resolve_divide_scope infers sub_blocks from a block parent, sub_compartments
  // from a compartment parent — FS-4a.6/FS-4a.17, branch-generic), else Block / C
  // for the root auto-create level picker.
  const CHILD_LAYER_LABEL: Record<string, string> = { sub_blocks: 'SB', sub_compartments: 'SC' };
  const unitLabel = parent
    ? CHILD_LAYER_LABEL[(meta as { child_layer?: string } | null)?.child_layer ?? ''] ?? 'SC'
    : LEVEL_LABEL[level];

  // Floating panel state
  const [collapsed, setCollapsed] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const [panelPos, setPanelPos] = useState({ x: -1, y: 80 });
  const [panelSize, setPanelSize] = useState({ w: 400, h: 500 });
  const dragRef = useRef<{ startX: number; startY: number; startPosX: number; startPosY: number } | null>(null);
  const resizeRef = useRef<{ startX: number; startY: number; startW: number; startH: number; startPosX: number; startPosY: number; dir: string } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (maximized) return;
    e.preventDefault();
    dragRef.current = { startX: e.clientX, startY: e.clientY, startPosX: panelPos.x, startPosY: panelPos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      const dx = ev.clientX - dragRef.current.startX;
      const dy = ev.clientY - dragRef.current.startY;
      setPanelPos({ x: dragRef.current.startPosX + dx, y: dragRef.current.startPosY + dy });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [maximized, panelPos]);

  const handleResizeStart = useCallback((e: React.MouseEvent, dir: string) => {
    if (maximized) return;
    e.preventDefault();
    e.stopPropagation();
    resizeRef.current = { startX: e.clientX, startY: e.clientY, startW: panelSize.w, startH: panelSize.h, startPosX: panelPos.x, startPosY: panelPos.y, dir };
    const onMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return;
      const r = resizeRef.current;
      const dx = ev.clientX - r.startX;
      const dy = ev.clientY - r.startY;
      let newW = r.startW, newH = r.startH, newX = r.startPosX, newY = r.startPosY;
      if (r.dir.includes('e')) newW = Math.max(320, r.startW + dx);
      if (r.dir.includes('w')) { newW = Math.max(320, r.startW - dx); newX = r.startPosX + (r.startW - newW); }
      if (r.dir.includes('s')) newH = Math.max(200, r.startH + dy);
      if (r.dir.includes('n')) { newH = Math.max(200, r.startH - dy); newY = r.startPosY + (r.startH - newH); }
      setPanelSize({ w: newW, h: newH });
      setPanelPos({ x: newX, y: newY });
    };
    const onUp = () => {
      resizeRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [maximized, panelSize, panelPos]);

  const toggleMaximize = useCallback(() => {
    if (maximized) {
      setMaximized(false);
      setPanelPos({ x: -1, y: 80 });
      setPanelSize({ w: 420, h: 620 });
    } else {
      setMaximized(true);
      setCollapsed(false);
    }
  }, [maximized]);

  // Fetch preview per level / source / minimum-block-area change.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setLocked([]);
    (parent
      ? forestApi.autoDividePreview(calculationId, parent.id, {
          source,
          sliverAreaM2: minBlockHa * 10000,
          forceAbsorbOrphans,
        })
      : forestApi.autoBlocksPreview(
          calculationId, level, undefined, minBlockHa * 10000, source, forceAbsorbOrphans,
          source === 'union_fusion'
            ? { sources: fusionSources, includeCanopy: fusionIncludeCanopy }
            : undefined,
        )
    )
      .then((res) => {
        if (cancelled) return;
        const fc = res.pieces as FeatureCollection;
        const pcs = fc.features.map((f, i) => asPiece(f, i));
        setPieces(pcs);
        setSourceMeta(
          Object.fromEntries(
            fc.features.map((f, i) => {
              const p = (f.properties ?? {}) as Record<string, unknown>;
              return [i, extractClassification(source, p)];
            }),
          ),
        );
        setUnionAttrs(
          isUnionSource(source)
            ? Object.fromEntries(
                fc.features.map((f, i) => {
                  const p = (f.properties ?? {}) as Record<string, unknown>;
                  const picked: Record<string, unknown> = {};
                  for (const key of UNION_DOMINANT_KEYS) picked[key] = p[key] ?? null;
                  return [i, picked];
                }),
              )
            : {},
        );
        setEdges(res.edges);
        setMeta(res.meta);
        setN(pcs.length); // start with no merging (each piece its own block)
      })
      .catch((err) => {
        if (cancelled) return;
        const detail = err?.response?.data?.detail;
        const code = typeof detail === 'object' ? (detail as { code?: string })?.code : undefined;
        setError(
          code === 'BLOCKS_EXIST'
            ? t('autoBlock.blocksExist')
            : code === 'NO_BOUNDARY'
              ? t('autoBlock.noBoundary')
              : readDetail(detail) ?? err?.message ?? t('autoBlock.failedToLoadPreview')
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [calculationId, level, source, minBlockHa, forceAbsorbOrphans, parent?.id, fusionSources, fusionIncludeCanopy]);

  const plan: MergePlan | null = useMemo(() => {
    if (pieces.length === 0) return null;
    return buildMergePlan({ pieces, edges, n, locked, floorHa: 5 });
  }, [pieces, edges, n, locked]);

  // Effect: when spinning state changes, re-render the preview layer
  // (per merging M, we're re-running the plan by slider).
  useEffect(() => {
    if (!map) return;
    if (geoLayerRef.current) {
      map.removeLayer(geoLayerRef.current);
      geoLayerRef.current = null;
    }
    if (!plan || plan.anchors.length === 0) return;

    // Order anchors by their largest piece for stable serial labels.
    const sortedAnchors = [...plan.anchors].sort(
      (a, b) => pieces[b].area_hectares - pieces[a].area_hectares,
    );
    const byAnchor = new Map<number, number>();
    sortedAnchors.forEach((a, i) => byAnchor.set(a, i + 1));

    const features = [] as GeoJSON.Feature[];
    const labels: Array<{ pos: [number, number]; text: string; slopeText: string | null }> = [];
    for (const anchor of sortedAnchors) {
      const merged = unionFamily(pieces, plan.familyOf, anchor);
      // Owner report 2026-10-02: the preview showed every piece in one flat
      // blue regardless of source, which made it hard to perceive what's
      // about to be created — the COMMITTED layer already colours by
      // dominant property (autoBlockFeatureStyle), so the preview should
      // show the same thing, not a generic placeholder. Same
      // anchor-preferred-else-first-populated heuristic `handleAccept`
      // already uses to decide a merged family's persisted value, reused
      // here purely for colour (not written anywhere).
      const family = pieces.map((p, idx) => ({ p, idx })).filter(({ idx }) => plan.familyOf[idx] === anchor);
      let slopeText: string | null = null;
      if (isUnionSource(source)) {
        const firstUnionMember = family.find(
          ({ idx }) => unionAttrs[idx] && Object.values(unionAttrs[idx]).some((v) => v != null),
        );
        const slopeCode = (unionAttrs[anchor]?.dominant_slope_band
          ?? (firstUnionMember ? unionAttrs[firstUnionMember.idx]?.dominant_slope_band : null)) as number | null;
        merged.properties = { ...merged.properties, __previewCode: slopeCode, __previewLabel: null };
        // Owner report 2026-10-02: slope is the gate attribute and "the
        // most important factor" for Union -- surface it on the map label
        // too, not only the pieces table column.
        slopeText = (unionAttrs[anchor]?.slope_band_label
          ?? (firstUnionMember ? unionAttrs[firstUnionMember.idx]?.slope_band_label : null)) as string | null;
      } else {
        const firstClassedMember = family.find(({ idx }) => sourceMeta[idx]?.value != null);
        const meta = sourceMeta[anchor] ?? (firstClassedMember ? sourceMeta[firstClassedMember.idx] : undefined);
        merged.properties = {
          ...merged.properties,
          __previewCode: meta?.value ?? null,
          __previewLabel: (i18n.language?.startsWith('ne') ? meta?.labelNe : meta?.labelEn) ?? meta?.labelEn ?? null,
        };
        // When the active source IS slope, the classification already
        // extracted above (`meta`) already carries the slope label -- reuse
        // it rather than inventing a second lookup. Every other single-raster
        // source (aspect/canopy/NASA/etc.) has no slope data in this preview
        // response, so the map label stays name-only for those, same as before.
        if (source === 'slope') {
          slopeText = (i18n.language?.startsWith('ne') ? meta?.labelNe : meta?.labelEn) ?? meta?.labelEn ?? null;
        }
      }
      features.push(merged);
      try {
        const b = L.geoJSON(merged as any).getBounds();
        labels.push({
          pos: [b.getCenter().lat, b.getCenter().lng],
          text: `${unitLabel}-${byAnchor.get(anchor)}`,
          slopeText,
        });
      } catch {
        /* degenerate family — no label */
      }
    }

    const layer = L.geoJSON(features as any, {
      style: (feature) => {
        const p = (feature?.properties ?? {}) as Record<string, unknown>;
        const base = classificationStyle(source, p.__previewCode as number | null, p.__previewLabel as string | null);
        return { ...base, color: '#FFFFFF', weight: 3, opacity: 0.95, dashArray: '8, 4' };
      },
      interactive: false,
    }).addTo(map);
    const labelGroup = L.layerGroup();
    for (const l of labels) {
      // Owner report 2026-10-02: showing the slope value beneath the Block/
      // Compartment name on the preview map itself (not only the pieces
      // table) lets the user perceive it without looking away from the map.
      const html = l.slopeText
        ? `${l.text}<span class="auto-block-label-slope">${l.slopeText}</span>`
        : l.text;
      L.marker(l.pos, {
        interactive: false,
        icon: L.divIcon({
          className: 'auto-block-label',
          html,
        }),
      }).addTo(labelGroup);
    }
    labelGroup.addTo(map);
    (layer as any).__autoBlockLabels = labelGroup;
    geoLayerRef.current = layer;
    return () => {
      if (geoLayerRef.current) {
        map.removeLayer(geoLayerRef.current);
        geoLayerRef.current = null;
      }
      if ((layer as any).__autoBlockLabels) {
        map.removeLayer((layer as any).__autoBlockLabels);
      }
    };
  }, [map, plan, pieces, level]);

  // Cleanup on unmount.
  useEffect(() => {
    return () => {
      if (map && geoLayerRef.current) {
        map.removeLayer(geoLayerRef.current);
        geoLayerRef.current = null;
      }
      if (map && (geoLayerRef.current as any)?.__autoBlockLabels) {
        map.removeLayer((geoLayerRef.current as any).__autoBlockLabels);
      }
    };
  }, [map]);

  const minN = plan?.minN ?? 1;
  const maxN = pieces.length || 1;

  const toggleLock = (i: number) => {
    setLocked((prev) => (prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i]));
  };

  const handleMinimize = () => {
    if (meta) setN(meta.minimize_n);
  };

  const handleAccept = async () => {
    if (!plan || plan.anchors.length === 0) return;
    setCommitting(true);
    try {
      const sortedAnchors = [...plan.anchors].sort(
        (a, b) => pieces[b].area_hectares - pieces[a].area_hectares,
      );
      const blocks: AutoBlockCommitBlock[] = sortedAnchors.map((anchor, i) => {
        const family = pieces
          .map((p, idx) => ({ p, idx }))
          .filter(({ idx }) => plan.familyOf[idx] === anchor);
        const totalHa = family.reduce((s, { p }) => s + p.area_hectares, 0);
        // Anchor keeps its natural name (preferred) else first named member.
        const anchorP = pieces[anchor];
        const naturalName =
          anchorP.natural_name ??
          family.find(({ p }) => p.natural_name)?.p.natural_name ??
          null;
        // Same anchor-preferred heuristic for the active source's
        // classification (mmu never populates sourceMeta, so this is always
        // null there). A merge that folds pieces of DIFFERENT classes
        // together keeps the anchor's own value rather than re-deriving a
        // true dominant class from the merged geometry — an approximation,
        // acceptable because the default (no merging) leaves every piece's
        // class exact (the backend itself re-derives per final piece before
        // any client-side merge happens, so this only matters post-merge).
        const firstClassedMember = family.find(({ idx }) => sourceMeta[idx]?.value != null);
        const dominantValue =
          sourceMeta[anchor]?.value ?? (firstClassedMember ? sourceMeta[firstClassedMember.idx].value : null);
        // RS-10.2/10.5: Union has 9 attributes, not one — same
        // anchor-preferred-else-first-populated heuristic as every other
        // source above, just applied to the whole attribute set at once
        // instead of a single `dominantValue`.
        const firstUnionMember = family.find(
          ({ idx }) => unionAttrs[idx] && Object.values(unionAttrs[idx]).some((v) => v != null),
        );
        const unionFields =
          isUnionSource(source)
            ? (unionAttrs[anchor] ?? (firstUnionMember ? unionAttrs[firstUnionMember.idx] : {}))
            : {};
        return {
          index: i + 1,
          name: `${unitLabel}-${i + 1}`,
          block_name: `${unitLabel}-${i + 1}`,
          natural_name: naturalName,
          dominant_slope_band: source === 'slope' ? dominantValue : (unionFields.dominant_slope_band as number | null) ?? null,
          dominant_aspect: source === 'aspect' ? dominantValue : (unionFields.dominant_aspect as number | null) ?? null,
          dominant_canopy_class: source === 'canopy' ? dominantValue : (unionFields.dominant_canopy_class as number | null) ?? null,
          dominant_nasa_quality: source === 'nasa_quality' ? dominantValue : (unionFields.dominant_nasa_quality as number | null) ?? null,
          dominant_health_class: source === 'forest_health' ? dominantValue : (unionFields.dominant_health_class as number | null) ?? null,
          dominant_landcover: source === 'landcover' ? dominantValue : (unionFields.dominant_landcover as number | null) ?? null,
          dominant_contour_band: source === 'dem' ? dominantValue : (unionFields.dominant_contour_band as number | null) ?? null,
          dominant_forest_type: source === 'forest_type' ? dominantValue : (unionFields.dominant_forest_type as number | null) ?? null,
          sub_area_category: (unionFields.sub_area_category as string | null) ?? null,
          sub_area_excluded: (unionFields.sub_area_excluded as boolean) ?? false,
          area_hectares: Math.round(totalHa * 10000) / 10000,
          geometry: (unionFamily(pieces, plan.familyOf, anchor) as GeoJSON.Feature).geometry,
        };
      });
      if (parent) {
        const done = await forestApi.autoDivideCommit(calculationId, parent.id, source, blocks, minBlockHa * 10000);
        if ((done.undivided_blocks ?? 0) > 0) {
          message.warning(t('autoBlock.undividedBlocks', { count: done.undivided_blocks }), 8);
        }
      } else {
        await forestApi.autoBlocksCommit(calculationId, level, blocks, minBlockHa * 10000, source);
      }
      message.success(t('autoBlock.createdSuccess', { count: blocks.length, level: unitLabel }));
      onCommitted();
      onClose();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const code = typeof detail === 'object' ? (detail as { code?: string })?.code : undefined;
      message.error(
        code === 'BLOCKS_EXIST'
          ? t('autoBlock.blocksExistNow')
          : readDetail(detail) ?? ((err as { message?: string })?.message ?? t('autoBlock.commitFailed')),
      );
    } finally {
      setCommitting(false);
    }
  };

  const groupOf = plan?.familyOf ?? {};
  const anchorSet = new Set(plan?.anchors ?? []);
  const anchorSerial = new Map<number, number>();
  [...plan?.anchors ?? []]
    .sort((a, b) => pieces[b]?.area_hectares - pieces[a]?.area_hectares)
    .forEach((a, i) => anchorSerial.set(a, i + 1));

return createPortal(
    <div
      ref={panelRef}
      className={`auto-block-float-panel ${maximized ? 'maximized' : ''} ${collapsed ? 'collapsed' : ''}`}
      style={maximized ? undefined : { left: panelPos.x, top: panelPos.y, width: panelSize.w, height: collapsed ? undefined : panelSize.h }}
      data-testid="auto-block-designer"
    >
      {/* Resize handles */}
      {!maximized && !collapsed && (
        <>
          <div className="ab-resize ab-resize-e" onMouseDown={(e) => handleResizeStart(e, 'e')} />
          <div className="ab-resize ab-resize-s" onMouseDown={(e) => handleResizeStart(e, 's')} />
          <div className="ab-resize ab-resize-se" onMouseDown={(e) => handleResizeStart(e, 'se')} />
          <div className="ab-resize ab-resize-w" onMouseDown={(e) => handleResizeStart(e, 'w')} />
          <div className="ab-resize ab-resize-n" onMouseDown={(e) => handleResizeStart(e, 'n')} />
          <div className="ab-resize ab-resize-ne" onMouseDown={(e) => handleResizeStart(e, 'ne')} />
          <div className="ab-resize ab-resize-sw" onMouseDown={(e) => handleResizeStart(e, 'sw')} />
          <div className="ab-resize ab-resize-nw" onMouseDown={(e) => handleResizeStart(e, 'nw')} />
        </>
      )}

      {/* Drag header */}
      <div className="ab-float-header" onMouseDown={handleDragStart}>
        <span className="ab-float-title">
          {parent ? t('autoBlock.divideTitle', { name: parent.name }) : t('autoBlock.title')}
        </span>
        <div className="ab-float-controls">
          <button className="ab-float-btn" onClick={() => setCollapsed(!collapsed)} title={collapsed ? 'Expand' : 'Collapse'}>
            {collapsed ? '▢' : '─'}
          </button>
          <button className="ab-float-btn" onClick={toggleMaximize} title={maximized ? 'Restore' : 'Maximize'}>
            {maximized ? '❐' : '☐'}
          </button>
          <button className="ab-float-btn ab-float-btn-close" onClick={onClose} title="Close">✕</button>
        </div>
      </div>

      {!collapsed && (
        <div className="ab-float-body">
          <div className="auto-block-designer">
            <div className="auto-block-designer-header">
              <div className="auto-block-meta-row">
                <strong>{t('autoBlock.basisColon')}</strong> {meta?.basis ?? 'rivers & ridges'}
                <span className="auto-block-meta-chip">
                  {t('autoBlock.boundaryArea', { area: meta?.boundary_ha?.toFixed(2) })}
                </span>
                <span className="auto-block-meta-chip">
                  {t('autoBlock.piecesCount', { count: meta?.piece_count ?? pieces.length })}
                </span>
                <span className="auto-block-meta-chip">
                  {t('autoBlock.sliversAbsorbed', { count: meta?.slivers_absorbed ?? 0 })}
                </span>
              </div>

              <div className="auto-block-config-panel">
                <div className="auto-block-config-group auto-block-config-group--source">
                  <span className="auto-block-config-label">{t('autoBlock.sourceLabel')}</span>
                  <div className="auto-block-segmented">
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-mmu"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'mmu'}
                        onChange={() => setSource('mmu')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🌊</span>
                      {t('autoBlock.sourceMmu')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-slope"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'slope'}
                        onChange={() => setSource('slope')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">⛰️</span>
                      {t('autoBlock.sourceSlope')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-aspect"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'aspect'}
                        onChange={() => setSource('aspect')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🧭</span>
                      {t('autoBlock.sourceAspect')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-canopy"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'canopy'}
                        onChange={() => setSource('canopy')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🌲</span>
                      {t('autoBlock.sourceCanopy')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-nasa-quality"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'nasa_quality'}
                        onChange={() => setSource('nasa_quality')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🛰️</span>
                      {t('autoBlock.sourceNasaQuality')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-forest-health"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'forest_health'}
                        onChange={() => setSource('forest_health')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🌿</span>
                      {t('autoBlock.sourceForestHealth')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-landcover"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'landcover'}
                        onChange={() => setSource('landcover')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🗺️</span>
                      {t('autoBlock.sourceLandcover')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-dem"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'dem'}
                        onChange={() => setSource('dem')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">⛰️</span>
                      {t('autoBlock.sourceDem')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-source-forest-type"
                        type="radio"
                        name="auto-block-source"
                        checked={source === 'forest_type'}
                        onChange={() => setSource('forest_type')}
                        disabled={committing}
                      />
                      <span className="auto-block-segment-icon" aria-hidden="true">🌳</span>
                      {t('autoBlock.sourceForestType')}
                    </label>
                    <Tooltip title={t('autoBlock.sourceUnionZonalWhy')} placement="top" zIndex={AUTO_BLOCK_TOOLTIP_Z_INDEX}>
                      <label className="auto-block-segment">
                        <input
                          id="auto-block-source-union-zonal"
                          type="radio"
                          name="auto-block-source"
                          checked={source === 'union_zonal'}
                          onChange={() => setSource('union_zonal')}
                          disabled={committing}
                        />
                        <span className="auto-block-segment-icon" aria-hidden="true">🧩</span>
                        {t('autoBlock.sourceUnionZonal')}
                      </label>
                    </Tooltip>
                    <Tooltip title={t('autoBlock.sourceUnionFusionWhy')} placement="top" zIndex={AUTO_BLOCK_TOOLTIP_Z_INDEX}>
                      <label className="auto-block-segment">
                        <input
                          id="auto-block-source-union-fusion"
                          type="radio"
                          name="auto-block-source"
                          checked={source === 'union_fusion'}
                          onChange={() => setSource('union_fusion')}
                          disabled={committing}
                        />
                        <span className="auto-block-segment-icon" aria-hidden="true">🧬</span>
                        {t('autoBlock.sourceUnionFusion')}
                      </label>
                    </Tooltip>
                  </div>
                </div>

                {source === 'union_fusion' && (
                  <div className="auto-block-config-group">
                    <span className="auto-block-config-label">
                      {t('autoBlock.fusionSourcesLabel')}
                      <Tooltip title={t('autoBlock.fusionSourcesWhy')} zIndex={AUTO_BLOCK_TOOLTIP_Z_INDEX}>
                        <span className="auto-block-info-icon" aria-hidden="true"> ⓘ</span>
                      </Tooltip>
                    </span>
                    <div className="auto-block-fusion-sources">
                      {FUSION_OPTIONAL_SOURCES.map((key) => {
                        const uncovered = fusionCoverage[key] === false;
                        const label = (
                          <label
                            key={key}
                            className="auto-block-fusion-source-check"
                            style={uncovered ? { opacity: 0.5, textDecoration: 'line-through' } : undefined}
                          >
                            <input
                              type="checkbox"
                              checked={fusionSources.includes(key)}
                              onChange={() => toggleFusionSource(key)}
                              disabled={committing || uncovered}
                            />
                            {t(`autoBlock.fusionSource.${key}`)}
                          </label>
                        );
                        return uncovered ? (
                          <Tooltip key={key} title={t('autoBlock.fusionSourceNoCoverage')} zIndex={AUTO_BLOCK_TOOLTIP_Z_INDEX}>
                            {label}
                          </Tooltip>
                        ) : label;
                      })}
                      <label className="auto-block-fusion-source-check">
                        <input
                          type="checkbox"
                          checked={fusionIncludeCanopy}
                          onChange={() => setFusionIncludeCanopy((v) => !v)}
                          disabled={committing}
                        />
                        {t('autoBlock.fusionSource.canopy')}
                      </label>
                    </div>
                    {fusionSources.length === 0 && (
                      <div className="auto-block-fusion-hint">{t('autoBlock.fusionSlopeOnlyHint')}</div>
                    )}
                  </div>
                )}

                {!parent && (
                <div className="auto-block-config-group">
                  <span className="auto-block-config-label">{t('autoBlock.levelLabel')}</span>
                  <div className="auto-block-segmented">
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-level-blocks"
                        type="radio"
                        name="auto-block-level"
                        checked={level === 'blocks'}
                        onChange={() => setLevel('blocks')}
                      />
                      {t('autoBlock.blocks')}
                    </label>
                    <label className="auto-block-segment">
                      <input
                        id="auto-block-level-compartments"
                        type="radio"
                        name="auto-block-level"
                        checked={level === 'compartments'}
                        onChange={() => setLevel('compartments')}
                      />
                      {t('autoBlock.compartments')}
                    </label>
                  </div>
                </div>
                )}

                <div className="auto-block-config-group">
                  <label htmlFor="auto-block-min-area" className="auto-block-config-label">
                    {t('autoBlock.minBlockAreaHa')}
                  </label>
                  <div className="auto-block-stepper">
                    <LocaleInputNumber
                      id="auto-block-min-area"
                      className="auto-block-stepper-input"
                      min={0.1}
                      step={0.1}
                      value={minBlockHa}
                      onChange={(v) => {
                        const num = typeof v === 'number' ? v : parseLocaleNumber(String(v ?? ''));
                        if (!Number.isNaN(num) && num > 0) setMinBlockHa(num);
                      }}
                      disabled={committing}
                      style={{ width: 80 }}
                    />
                    <span className="auto-block-stepper-unit">ha</span>
                  </div>
                </div>

                <div className="auto-block-config-group">
                  <label className="auto-block-config-label checkbox-label">
                    <input
                      type="checkbox"
                      checked={forceAbsorbOrphans}
                      onChange={(e) => setForceAbsorbOrphans(e.target.checked)}
                      disabled={committing}
                    />
                    <span>{t('autoBlock.forceAbsorbOrphans')}</span>
                  </label>
                </div>
              </div>
            </div>

            {loading && <div className="auto-block-loading">{t('autoBlock.computingMmuPieces')}</div>}
            {error && <div className="auto-block-error" role="alert">{error}</div>}

            {!loading && !error && pieces.length > 0 && plan && (
              <>
                <div className="auto-block-slider-row">
                  <div className="auto-block-slider-wrap">
                    <label htmlFor="auto-block-n">
                      {t('autoBlock.numberOf', { level: unitLabel })}:{' '}
                      <strong data-testid="auto-block-n-value">{plan.effectiveN}</strong>
                      {plan.effectiveN < n && (
                        <span className="auto-block-note">{t('autoBlock.raisedToMinimum', { min: plan.minN })}</span>
                      )}
                    </label>
                    <Slider
                      id="auto-block-n"
                      min={1}
                      max={maxN}
                      value={n}
                      onChange={setN}
                      disabled={committing}
                      marks={{
                        [1]: '1',
                        [maxN]: `${maxN}`,
                      }}
                    />
                  </div>
                  <Tooltip
                    zIndex={AUTO_BLOCK_TOOLTIP_Z_INDEX}
                    title={
                      // No 5 ha fallback: until RS-2.9 the API reported a
                      // hardcoded 5.0 that no preview ever applied, and the
                      // designer showed it in this label. The backend now
                      // reports the floor actually in force, so a missing value
                      // renders without a number rather than inventing one.
                      meta?.minimize_floor_ha != null
                        ? t('autoBlock.minimizeTooltip', {
                            floor: meta.minimize_floor_ha,
                          })
                        : undefined
                    }
                  >
                    <button
                      className="auto-block-minimize-btn"
                      onClick={handleMinimize}
                      disabled={committing}
                    >
                      {meta?.minimize_floor_ha != null
                        ? t('autoBlock.minimizeBtn', { floor: meta.minimize_floor_ha })
                        : t('autoBlock.minimizeBtnNoFloor')}
                    </button>
                  </Tooltip>
                </div>

                <div className="auto-block-pieces-header" role="row">
                  <span role="columnheader">{t('autoBlock.colNum')}</span>
                  <span role="columnheader">{t('autoBlock.colPiece')}</span>
                  <span role="columnheader">
                    {source === 'slope'
                      ? t('autoBlock.colSlopeBand')
                      : source === 'aspect'
                        ? t('autoBlock.colAspect')
                        : source === 'canopy'
                          ? t('autoBlock.colCanopyClass')
                          : source === 'nasa_quality'
                            ? t('autoBlock.colNasaQuality')
                            : source === 'forest_health'
                              ? t('autoBlock.colForestHealth')
                              : source === 'landcover'
                                ? t('autoBlock.colLandcover')
                                : source === 'dem'
                                  ? t('autoBlock.colElevationZone')
                                  : source === 'forest_type'
                                    ? t('autoBlock.colForestType')
                                    : isUnionSource(source)
                                      // Owner report 2026-10-02: slope is
                                      // Union's gate attribute and "the most
                                      // important factor" -- show it here
                                      // instead of the natural name, for
                                      // both union_zonal and union_fusion.
                                      ? t('autoBlock.colSlopeBand')
                                      : t('autoBlock.colNaturalName')}
                  </span>
                  <span role="columnheader">{t('autoBlock.colArea')}</span>
                  <span role="columnheader">{t('autoBlock.colBecomes')}</span>
                  <span role="columnheader">{t('autoBlock.colKeepWhole')}</span>
                </div>
                <div className="auto-block-pieces" role="grid" aria-label="Auto-block pieces">
                  {[...pieces]
                    .map((p, i) => ({ p, i }))
                    .sort((a, b) => b.p.area_hectares - a.p.area_hectares)
                    .map(({ p, i }) => {
                      const isAnchor = anchorSet.has(i);
                      return (
                        <div
                          key={i}
                          className={`auto-block-row ${isAnchor ? 'anchor' : ''}`}
                          role="row"
                          data-testid="auto-block-row"
                        >
                          <span role="cell" className="auto-block-col-idx">
                            {isAnchor ? (
                              <span className="auto-block-anchor-badge" title={t('autoBlock.anchorBadge')}>
                                {anchorSerial.get(i)}
                              </span>
                            ) : (
                              <span className="auto-block-merge-badge" title={t('autoBlock.mergeBadge', { level: unitLabel, anchor: anchorSerial.get(groupOf[i]) })}>
                                → {groupOf[i] !== undefined && anchorSerial.get(groupOf[i])}
                              </span>
                            )}
                          </span>
                          <span role="cell" className="auto-block-col-name">{p.name}</span>
                          <span role="cell" className="auto-block-col-natural">
                            {isUnionSource(source)
                              ? (unionAttrs[i]?.slope_band_label as string | null) ?? <span className="muted">—</span>
                              : source !== 'mmu'
                                ? (i18n.language?.startsWith('ne')
                                    ? sourceMeta[i]?.labelNe
                                    : sourceMeta[i]?.labelEn) ?? <span className="muted">—</span>
                                : p.natural_name ?? <span className="muted">—</span>}
                          </span>
                          <span role="cell" className="auto-block-col-area">
                            {p.area_hectares.toFixed(2)} ha
                          </span>
                          <span role="cell" className="auto-block-col-becomes">
                            {isAnchor ? t('autoBlock.stays', { level: unitLabel, anchor: anchorSerial.get(i) }) : t('autoBlock.becomes', { level: unitLabel, anchor: anchorSerial.get(groupOf[i]) })}
                          </span>
                          <span role="cell" className="auto-block-col-lock">
                            <input
                              type="checkbox"
                              checked={locked.includes(i)}
                              onChange={() => toggleLock(i)}
                              aria-label={t('autoBlock.keepAsOwn', { name: p.block_name, level: unitLabel })}
                              disabled={committing}
                            />
                          </span>
                        </div>
                      );
                    })}
                </div>
              </>
            )}

            {!loading && !error && pieces.length === 0 && (
              <div className="auto-block-empty">{t('autoBlock.noMmuPieces')}</div>
            )}
          </div>
          <div className="auto-block-footer">
            <button
              type="button"
              className="auto-block-footer-btn auto-block-footer-btn--cancel"
              onClick={onClose}
              disabled={committing}
            >
              {t('common.cancel')}
            </button>
            <button
              type="button"
              className="auto-block-footer-btn auto-block-footer-btn--primary"
              onClick={handleAccept}
              disabled={loading || !!error || pieces.length === 0 || committing}
            >
              {committing ? t('autoBlock.creating') : t('autoBlock.createBlocks')}
            </button>
          </div>
        </div>
      )}
    </div>,
    document.body,
  );
}

export default AutoBlockDesigner;