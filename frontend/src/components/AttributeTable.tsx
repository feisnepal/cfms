import { availableAnalysisGroups, availableThemes, columnsForTheme, type AttributeTheme } from '../lib/attributeThemes';
import { AttributeToolbar } from './AttributeToolbar';
import type { AnalysisGroup } from '../lib/analysisFields';

import { useState, useEffect, useLayoutEffect, useRef, useCallback } from 'react';
import { createPortal } from 'react-dom';
import type { GeoJSON } from 'geojson';
import { X, MoreVertical } from 'lucide-react';
import { useWorkspaceStore, type EditEntry } from '../store/workspaceStore';
import { getLayerConfig } from '../lib/layerRegistry';
import type { ColumnDef, LayerTypeId } from '../lib/layerRegistry';
import type { PasteState } from '../lib/layerMenu';
import SymbolPicker from './SymbolPicker';
import { getSymbolEmoji, fuzzyMatchSymbol, detectSymbolColumn, SYMBOL_SOURCE_COLUMNS } from '../lib/pointSymbols';
import { purposeColumnsForFeatures } from '../lib/purposeColumns';
import { tableToCsv, tableToTsv, tableToGeoJson, downloadText } from '../lib/exportAttributeTable';
import { YearsCell } from '../features/yearly-plan/YearsCell';
import { featureYears } from '../lib/activityFeatureLabel';
import { matchFeature, suggestFilterValues, FILTER_OPS, type FilterOp } from '../lib/attributeFilter';
import { useT } from '../i18n/hooks';

import { selectedIdsForLayer } from '../lib/selectionScope';
/** A popover (row ⋮ menu, swatch grid) rendered to <body> so it is never
 *  clipped by the table's `overflow` — anchored under a trigger rect. */
function PortalPopover({ rect, onClose, children }: { rect: DOMRect; onClose: () => void; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: rect.bottom + 2, left: rect.left });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    let left = rect.left;
    let top = rect.bottom + 2;
    if (left + r.width > window.innerWidth - 8) left = Math.max(8, window.innerWidth - r.width - 8);
    if (top + r.height > window.innerHeight - 8) top = Math.max(8, rect.top - r.height - 2);
    setPos({ top, left });
  }, [rect]);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const t = setTimeout(() => document.addEventListener('mousedown', close), 0);
    return () => { clearTimeout(t); document.removeEventListener('mousedown', close); };
  }, [onClose]);
  return createPortal(
    <div ref={ref} style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 4000 }} onClick={(e) => e.stopPropagation()}>
      {children}
    </div>,
    document.body,
  );
}

interface AttributeTableProps {
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  features: GeoJSON.Feature[] | null;
  /** E3: per-row delete for any layer — wired to guard → confirm → restore-aware undo */
  onDeleteFeature?: (feature: GeoJSON.Feature, index: number) => void;
  /** Feature clipboard, from the row menu. `pasteState`: null = a paste lands in this layer now;
   *  'never' or undefined = the Paste command is not offered; else why it cannot right now. */
  onCopyFeature?: (feature: GeoJSON.Feature, index: number) => void;
  onPasteFeatures?: () => void;
  onPasteAsLayer?: () => void;
  pasteState?: PasteState;
  clipboardCount?: number;
  /** E3: per-row zoom-to-feature on the map */
  onZoomToFeature?: (feature: GeoJSON.Feature) => void;
  /** GD 1.5.1: persist builtin-layer property edits (sub-areas category/name) via dataSource.update + refresh */
  onSaveProperty?: (feature: GeoJSON.Feature, colKey: string, value: string) => void;
  /** Extra controls next to the view exports (the yearly-plan Export menu on the activity-features layer). */
  extraToolbar?: React.ReactNode;
  /** P4.6: fit the map to the union of the current selection. */
  onZoomToSelection?: () => void;
  /** P4.6: select every active-layer feature intersecting the current view. */
  onSelectInView?: () => void;
}

/** P2.1 — one leading column holding a ⋮ menu (Zoom / Delete / …). Replaces the
 *  two trailing icon columns that forced a scroll-right on any wide layer. */
const ACTIONS_COL: ColumnDef = {
  key: '__actions__',
  label: '',
  width: 34,
  align: 'center',
  getValue: () => '',
};

/** action columns are never editable / renamable / draggable / resizable */
const ACTION_COL_KEYS = new Set(['__actions__']);

const ROW_HEIGHT = 40;
const OVERSCAN_COUNT = 10;
const MIN_COL_WIDTH = 90;

function buildDynamicColumns(
  features: GeoJSON.Feature[],
  onSymbolChange: (featureIndex: number, symbolId: string) => void,
  columnLabels?: Record<string, string>,
): ColumnDef[] {
  if (!features || features.length === 0) return [];
  const keys = new Set<string>();
  features.forEach((f) => {
    if (f.properties) Object.keys(f.properties).forEach((k) => keys.add(k));
  });
  // `_`-prefixed keys (`_source`, `_<Label>_code`) are internal — written by
  // `layer_features` purely for map-styling (ramp position, source-keyed
  // lookups), never meant as a visible column. Filtered here rather than at
  // the source so every caller of this generic builder benefits, not just
  // Auto-Block layers. Union (RS-10.5) is what actually surfaces this: 8 of
  // its ~20 raw keys are `_code` companions to its 8 real classification
  // columns, so without this filter they would silently crowd out real
  // columns (Land Cover, Sub-area) past the slice(0, N) cap below.
  const keyList = Array.from(keys).filter((k) => !k.startsWith('_'));

  const symbolSourceCol = keyList.find((k) => {
    const displayLabel = columnLabels?.[k] || k;
    return SYMBOL_SOURCE_COLUMNS.has(k) || SYMBOL_SOURCE_COLUMNS.has(displayLabel);
  });

  const firstCol: ColumnDef = { key: '#', label: '#', labelKey: 'attributeTable.col.rowNumber', width: 40, align: 'center', getValue: (_, i) => i + 1 };
  // Raised from 10 to 20 (RS-10.5): Union legitimately has ~12 real columns
  // (Name, Area, 8 classifications, Sub-area, Sub-area excluded) once the
  // `_`-prefixed internal keys above are filtered out — the old 10-column
  // cap would still have cut it off even after that filter.
  const propCols: ColumnDef[] = keyList.slice(0, 20).map((k) => {
    const displayLabel = columnLabels?.[k] || k;
    const isSymbolCol = k === 'symbol' || (k === symbolSourceCol && k !== 'symbol');
    const col: ColumnDef = {
      key: k,
      label: displayLabel,
      width: isSymbolCol ? 80 : 'flex' as const,
      editable: !isSymbolCol,
      getValue: (f) => {
        if (isSymbolCol) {
          const symId = f.properties?.symbol || fuzzyMatchSymbol(f.properties?.[k]);
          return symId ? getSymbolEmoji(symId) : '📍';
        }
        return f.properties?.[k] ?? '-';
      },
    };
    if (isSymbolCol) {
      col.editable = false;
      col.render = (_, f) => {
        const idx = features.indexOf(f);
        const symId = f.properties?.symbol || fuzzyMatchSymbol(f.properties?.[k]);
        return (
          <SymbolPicker
            value={symId}
            onChange={(newId) => { if (idx >= 0) onSymbolChange(idx, newId); }}
          />
        );
      };
    }
    return col;
  });
  return [firstCol, ...propCols];
}

const CHAR_W = 7.2;
const CELL_PADDING = 18;
const SORT_ICON_WIDTH = 14;
const MIN_AUTO_COL = 100;
const MAX_AUTO_COL = 320;

function estimateColumnWidth(col: ColumnDef, features: GeoJSON.Feature[]): number {
  const headerLen = Math.max((col.label?.length || 0), col.key.length);
  let contentLen = headerLen;
  if (features && features.length > 0) {
    for (const f of features) {
      const v = col.getValue ? col.getValue(f, 0) : f.properties?.[col.key];
      if (v != null) {
        const len = String(v).length;
        if (len > contentLen) contentLen = len;
      }
    }
  }
  const extra = CELL_PADDING + (col.sortable ? SORT_ICON_WIDTH : 0);
  return Math.max(MIN_AUTO_COL, Math.min(MAX_AUTO_COL, Math.ceil(contentLen * CHAR_W + extra)));
}

function buildColumns(
  baseCols: ColumnDef[],
  features: GeoJSON.Feature[],
  savedOrder: string[] | undefined,
  savedWidths: Record<string, number> | undefined,
): ColumnDef[] {
  let cols = baseCols;
  if (savedOrder && savedOrder.length > 0) {
    const keyToCol = new Map(baseCols.map((c) => [c.key, c]));
    const seen = new Set<string>();
    const ordered: ColumnDef[] = [];
    for (const k of savedOrder) {
      const c = keyToCol.get(k);
      if (c && !seen.has(k)) {
        ordered.push(c);
        seen.add(k);
      }
    }
    for (const c of baseCols) {
      if (!seen.has(c.key)) ordered.push(c);
    }
    cols = ordered;
  }
  return cols.map((c) => {
    if (savedWidths && typeof savedWidths[c.key] === 'number') {
      return { ...c, width: Math.max(MIN_COL_WIDTH, savedWidths[c.key]) };
    }
    if (typeof c.width === 'number') return c;
    return { ...c, width: estimateColumnWidth(c, features) };
  });
}

export function AttributeTable({ onDeleteFeature, onCopyFeature, onPasteFeatures, onPasteAsLayer, pasteState, clipboardCount = 0, onZoomToFeature, onSaveProperty, onZoomToSelection, onSelectInView, extraToolbar, ...props }: AttributeTableProps) {
  const store = useWorkspaceStore();
  const t = useT();
  const [searchQuery, setSearchQuery] = useState('');
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  // A one-time snapshot of feature ids in sorted order, captured when the
  // user clicks a header (owner request, 2026-09-15: "let us keep it in the
  // same position of row"). Editing a value in the sorted column used to
  // reshuffle that row to its new sorted position the moment the edit's
  // refetch landed -- surprising mid-edit. Row order now only re-derives on
  // an explicit header click (see handleSort); an edit just updates the
  // value shown at that row's frozen position. A row not in the snapshot
  // (newly created since the last sort) sorts after every known row.
  const [sortedOrder, setSortedOrder] = useState<string[] | null>(null);
  const [editingCell, setEditingCell] = useState<{ row: number; col: string } | null>(null);
  const [editingHeader, setEditingHeader] = useState<string | null>(null);
  const [dragColKey, setDragColKey] = useState<string | null>(null);
  const [dropColKey, setDropColKey] = useState<string | null>(null);
  const [rowMenu, setRowMenu] = useState<string | null>(null); // featureId whose ⋮ menu is open
  const [rowMenuRect, setRowMenuRect] = useState<DOMRect | null>(null);
  // Owner request, 2026-09-24: the generic table-utility tools (search, undo/
  // redo, columns chooser, CSV/GeoJSON export, copy view, zoom-to-selection,
  // select-in-view, "selected only") are noise most of the time — hidden
  // behind one toggle by default, remembered per-browser so a user who opens
  // it once doesn't have to again. Layer-specific controls (extraToolbar, the
  // bulk-colour swatch, the filter row itself) are unaffected.
  // When the table sits in a dock panel that reserved a title-bar slot (`#dock-toolbar-attributeTable`), the toolbar is rendered there
  // instead of as a bar of its own above the rows; anywhere else (tests, other pages) it stays inline.
  const [toolbarSlot, setToolbarSlot] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    setToolbarSlot(document.getElementById('dock-toolbar-attributeTable'));
  }, []);
  const toolbarHost = (node: React.ReactElement) => (toolbarSlot ? createPortal(node, toolbarSlot) : node);
  const [toolsOpen, setToolsOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem('cfms.attributeTable.toolsOpen') === '1';
    } catch {
      return false;
    }
  });
  const toggleTools = useCallback(() => {
    setToolsOpen((v) => {
      const next = !v;
      try { localStorage.setItem('cfms.attributeTable.toolsOpen', next ? '1' : '0'); } catch { /* private window etc. */ }
      return next;
    });
  }, []);
  // P3.6 — featureId whose "Set colour…" swatch panel is open, or '__bulk__'
  // for the toolbar "Set colour for N selected" panel.
  const [colourFor, setColourFor] = useState<string | null>(null);
  const [colourRect, setColourRect] = useState<DOMRect | null>(null);
  // P4.6 — one-row attribute filter.
  const [filterField, setFilterField] = useState('');
  const [filterOp, setFilterOp] = useState<FilterOp>('eq');
  const [filterValue, setFilterValue] = useState('');
  const [filterOnMap, setFilterOnMap] = useState(false);
  // P2b — row virtualization: only render the rows near the viewport.
  const gridRef = useRef<HTMLDivElement | null>(null);
  // The grid div only mounts after the early returns (loading / empty / error), so an
  // effect run once at mount saw a null ref and never attached: the table then stayed
  // frozen at the 400px fallback (~20 rows) however far the user scrolled.
  const [gridEl, setGridEl] = useState<HTMLDivElement | null>(null);
  const setGridRef = useCallback((el: HTMLDivElement | null) => { gridRef.current = el; setGridEl(el); }, []);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(400);
  // P5.3 — the keyboard-focused grid cell (absolute row index + column key).
  const [focusedCell, setFocusedCell] = useState<{ row: number; colKey: string } | null>(null);

  const { isLoading, error, onRetry, features } = props;
  const activeLayer = store.activeLayerId;
  const activeImported = store.activeImportedLayerId;
  const activeRaster = store.activeRasterLayerId;
  const isImported = !activeLayer && activeImported != null;
  // Owner directive 2026-10-01: an Auto-Block layer's table is built the
  // same way an imported-layer-with-no-purpose's is — dynamic columns
  // derived straight from whatever properties its own features carry
  // (`layer_features` on the backend already limits that to this layer's
  // one classification column, never the other eight `dominant_*` fields).
  const isRasterLayer = !activeLayer && !activeImported && activeRaster != null;
  const [saveError, setSaveError] = useState<string | null>(null);

  const showSaveError = useCallback((msg: string) => {
    setSaveError(msg);
    setTimeout(() => setSaveError(null), 6000);
  }, []);

  const colHeader = (col: ColumnDef) => (col.labelKey ? t(col.labelKey) : col.label);

  const handleSymbolChange = useCallback(async (featureIndex: number, symbolId: string) => {
    if (store.activeImportedLayerId == null || !store.calculationId || !features) return;
    try {
      const baseUrl = import.meta.env.VITE_API_URL ?? '';
      const token = localStorage.getItem('access_token');
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const res = await fetch(
        `${baseUrl}/api/v1/workspace/${store.calculationId}/import-layers/${store.activeImportedLayerId}/features/${featureIndex}`,
        { method: 'PATCH', headers, credentials: 'include', body: JSON.stringify({ properties: { symbol: symbolId } }) },
      );
      if (res.ok) {
        const data = await res.json();
        if (store.activeImportedLayerId != null) {
          const updated = [...features];
          updated[featureIndex] = {
            ...updated[featureIndex],
            properties: { ...updated[featureIndex].properties, ...data.properties },
          };
          store.setImportedLayerFeatures(store.activeImportedLayerId, updated);
        }
      } else {
        showSaveError(t('attributeTable.failedSaveSymbol', { status: res.status }));
      }
    } catch (err) {
      console.error('Failed to save symbol:', err);
      showSaveError(t('attributeTable.networkErrorSymbol'));
    }
  }, [store, features, showSaveError]);

  const columnLabels = isImported && activeImported != null
    ? store.columnLabels[activeImported]
    : undefined;

 
   // P2b — track the scroll position + viewport height of the grid so the row
  // list can be windowed. clientHeight is 0 in jsdom → the 400 fallback keeps
  // virtualization deterministic in tests.
  //
  // Owner report 2026-10-02: a 356-row Field Book layer only ever showed ~20
  // rows no matter how far the user scrolled -- 400px fallback / 40px
  // ROW_HEIGHT + 10 OVERSCAN = exactly 20, so this measured BEFORE the dock
  // panel had settled into its real (taller) height, and nothing ever
  // re-measured it afterward because the panel's size never changed again
  // (a ResizeObserver only fires on an actual size CHANGE, not "size is
  // still wrong from last time"). `useLayoutEffect` measures synchronously
  // after layout instead of in a post-paint `useEffect`, and the rAF
  // fallback covers one more render pass some dock-panel/resize libraries
  // need before they report their final size.
  useLayoutEffect(() => {
    const el = gridEl;
    if (!el) return;
    const onScroll = () => setScrollTop(el.scrollTop);
    const measure = () => setViewportH(el.clientHeight || 400);
    el.addEventListener('scroll', onScroll, { passive: true });
    measure();
    const raf = requestAnimationFrame(measure);
    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure);
      ro.observe(el);
    }
    return () => { el.removeEventListener('scroll', onScroll); cancelAnimationFrame(raf); ro?.disconnect(); };
  }, [gridEl]);

  const handleHeaderRename = useCallback((originalKey: string, newLabel: string) => {
    setEditingHeader(null);
    if (activeImported == null || !newLabel.trim()) return;
    const oldLabel = columnLabels?.[originalKey] || originalKey;
    store.setColumnLabel(activeImported, originalKey, newLabel.trim());
    store.pushEdit({ type: 'column_label', layerId: activeImported, key: originalKey, oldLabel, newLabel: newLabel.trim() });
  }, [activeImported, store, columnLabels]);

  const getFeatureId = useCallback((f: GeoJSON.Feature): string => {
    return f.properties?.id || f.properties?.featureId || (f as any).id || '';
  }, []);

  const scopeKey = activeLayer
    ? activeLayer
    : isImported && activeImported != null
      ? `imported:${activeImported}`
      : isRasterLayer && activeRaster != null
        ? `raster:${activeRaster}`
        : null;

  // "Show only selected" (owner request, 2026-09-15) -- persisted per-layer in workspaceStore.
  const showOnlySelected = scopeKey ? store.showOnlySelected[scopeKey] ?? false : false;
  const setShowOnlySelected = useCallback((value: boolean) => {
    if (scopeKey) store.setShowOnlySelected(scopeKey, value);
  }, [scopeKey, store]);

  const featureList: GeoJSON.Feature[] = features || [];
  const activeImportedLayer = activeImported != null
    ? store.importedLayers.find((l) => l.id === activeImported)
    : undefined;
  const baseColumns = activeLayer
    ? getLayerConfig(activeLayer as LayerTypeId)?.columns ?? []
    : isImported
      ? activeImportedLayer?.purpose
        ? purposeColumnsForFeatures(activeImportedLayer.purpose, features || [], columnLabels)
        : buildDynamicColumns(features || [], handleSymbolChange, columnLabels)
      : isRasterLayer
        ? buildDynamicColumns(features || [], handleSymbolChange, columnLabels)
        : [];
  const orderedColumns = scopeKey
    ? buildColumns(baseColumns, featureList, store.columnOrder[scopeKey], store.columnWidths[scopeKey])
    : baseColumns;
  // Every column shows unless the user has explicitly hidden it in the
  // Columns… chooser. Owner report, 2026-09-30: "Not all value are under the
  // table some field are missing. Whether it is small in size, regardless of
  // this all table value should be presented."
  //
  // This used to consult a per-column `defaultHidden` / `hideIfEmpty` policy
  // that made a field DISAPPEAR when it had no value. Both flags are gone from
  // ColumnDef. The reason they had to go is a trap they created: the 4
  // Auto-Block class columns are `hideIfEmpty`, and only the source a forest
  // was actually carved by ever has values -- so on a slope-carved forest the
  // NASA/aspect/canopy columns were not merely blank, they were ABSENT, and a
  // column you cannot see is a value you cannot set. An empty cell is a
  // truthful "not classified yet" with a usable dropdown in it; a missing
  // header is indistinguishable from a field that does not exist.
  //
  // Note this evaluates the chooser state only, so it is also correct for a
  // layer whose feature list is still loading: a column must not blink out
  // just because the features have not arrived yet.
  const colVis = scopeKey ? store.columnVisibility[scopeKey] : undefined;
  // Thematic views (unit layers only): the same columns, one subject at a time.
  const isUnitLayerTable = activeLayer === 'blocks' || activeLayer === 'sub_blocks' || activeLayer === 'compartments' || activeLayer === 'sub_compartments';
  const [theme, setTheme] = useState<AttributeTheme>('all');
  const themes = isUnitLayerTable ? availableThemes(orderedColumns) : ['all' as AttributeTheme];
  const activeTheme: AttributeTheme = themes.includes(theme) ? theme : 'all';
  // Under "Raster analysis" the ~70 analysis columns are split by subject (terrain, climate, soil, ...).
  const [rasterGroup, setRasterGroup] = useState<AnalysisGroup | 'all'>('all');
  const rasterGroups = isUnitLayerTable ? availableAnalysisGroups(orderedColumns) : [];
  const activeGroup: AnalysisGroup | 'all' = rasterGroup === 'all' || rasterGroups.includes(rasterGroup) ? rasterGroup : 'all';
  const columns = columnsForTheme(
    orderedColumns.filter((c) => colVis?.[c.key] ?? true),
    isUnitLayerTable ? activeTheme : 'all',
    activeGroup,
  );
  const hasRowActions = !!(onDeleteFeature || onZoomToFeature || onCopyFeature);
  const tableColumns = hasRowActions ? [ACTIONS_COL, ...columns] : columns;

  const selectionKey = activeLayer ?? (isImported && activeImported != null ? `imported:${activeImported}` : (isRasterLayer && activeRaster != null ? `raster:${activeRaster}` : null));
  const selectedFeatureIds = selectedIdsForLayer(store.selection, selectionKey);

  // Search + attribute filter + selection filter + sort. Computed before the
  // early returns so the virtualization + scroll-into-view effects below can
  // be plain hooks.
  const filterActive = !!(filterField && filterValue);
  const sortOrderIndex = sortedOrder ? new Map(sortedOrder.map((id, i) => [id, i])) : null;
  const filteredFeatures = featureList
    .filter((f) => {
      if (!searchQuery) return true;
      const props = f.properties || {};
      return Object.values(props).some((v) =>
        String(v).toLowerCase().includes(searchQuery.toLowerCase()));
    })
    .filter((f) => !filterActive || matchFeature(f, filterField, filterOp, filterValue))
.filter((f) => !showOnlySelected || selectedFeatureIds.includes(getFeatureId(f)))
    .sort((a, b) => {
      // Order comes from the frozen sortedOrder snapshot (set by handleSort
      // on a header click), not a live re-comparison of current values --
      // see the sortedOrder declaration above for why. A row absent from
      // the snapshot (created since the last sort) sorts last.
      if (sortedOrder) {
        const aPos = sortOrderIndex!.get(getFeatureId(a)) ?? Number.MAX_SAFE_INTEGER;
        const bPos = sortOrderIndex!.get(getFeatureId(b)) ?? Number.MAX_SAFE_INTEGER;
        return aPos - bPos;
      }
      // Stable default sort: by index (blocks/compartments) or featureId fallback
      // so rows don't jump on re-fetch after edits (bumpGeometryVersion).
      const aIdx = a.properties?.index ?? 0;
      const bIdx = b.properties?.index ?? 0;
      if (aIdx !== bIdx) return aIdx - bIdx;
      return String(getFeatureId(a)).localeCompare(String(getFeatureId(b)));
    });
 
  // Hotkey handler: Ctrl+Z (undo/redo), Ctrl+Shift+S (toggle show only selected)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault();
        if (e.shiftKey) {
          store.redoEdit();
        } else {
          store.undoEdit();
        }
      }
      // Ctrl+Shift+S → toggle "Show only selected"
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'S') {
        e.preventDefault();
        if (selectedFeatureIds.length > 0 && scopeKey) {
          const current = store.showOnlySelected[scopeKey] ?? false;
          store.setShowOnlySelected(scopeKey, !current);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [store, selectedFeatureIds.length, scopeKey]);
 
  // P2b — window the row list. Below the threshold everything renders (keeps
  // small tables — and their tests — untouched); above it only the rows near
  // the viewport are in the DOM, with spacer divs preserving scroll height.
  const VIRTUALIZE_THRESHOLD = 80;
  const totalRows = filteredFeatures.length;
  const virtualize = totalRows > VIRTUALIZE_THRESHOLD;
  const startIdx = virtualize ? Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN_COUNT) : 0;
  const endIdx = virtualize
    ? Math.min(totalRows, Math.ceil((scrollTop + viewportH) / ROW_HEIGHT) + OVERSCAN_COUNT)
    : totalRows;

  // Bring the (single) selected row into view — selection can arrive from the
  // map, and a windowed row list would otherwise not have it mounted. The
  // index is resolved during render so the effect depends only on a primitive.
  const selectedRowIndex = virtualize && selectionKey && selectedFeatureIds.length === 1
    ? filteredFeatures.findIndex(
        (f) => String(f.properties?.id ?? f.properties?.featureId ?? '') === selectedFeatureIds[0],
      )
    : -1;
  useEffect(() => {
    const el = gridRef.current;
    if (!el || selectedRowIndex < 0) return;
    const rowTop = selectedRowIndex * ROW_HEIGHT;
    if (rowTop < el.scrollTop || rowTop + ROW_HEIGHT > el.scrollTop + el.clientHeight) {
      el.scrollTop = Math.max(0, rowTop - el.clientHeight / 2);
    }
  }, [selectedRowIndex]);

  // P4.6 — publish the filter to the store so MapCanvas can hide non-matching
  // features while "show only matches" is on. Cleared on unmount / toggle-off.
  const setTableFilter = store.setTableFilter;
  useEffect(() => {
    if (filterOnMap && scopeKey && filterField && filterValue) {
      setTableFilter({ layerId: scopeKey, field: filterField, op: filterOp, value: filterValue });
    } else {
      setTableFilter(null);
    }
    return () => setTableFilter(null);
  }, [filterOnMap, scopeKey, filterField, filterOp, filterValue, setTableFilter]);

  if (!activeLayer && !isImported && !isRasterLayer) {
    return (
      <div className="attribute-table" data-testid="attribute-table" role="region" aria-label={t('attributeTable.loading')} aria-busy="true">
        <div className="table-header">
          {columns.map((col) => (
            <div key={col.key} className="skeleton-cell" style={{ width: typeof col.width === 'number' ? col.width : 100 }}>
              <div className="skeleton-line" />
            </div>
          ))}
        </div>
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="table-row-skeleton">
            {columns.map((col) => (
              <div key={col.key} className="skeleton-cell" style={{ width: typeof col.width === 'number' ? col.width : 100 }}>
                <div className="skeleton-line short" />
              </div>
            ))}
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="attribute-table attribute-table-error" role="alert">
        <p className="error-message">{error}</p>
        <button onClick={onRetry} className="retry-btn">{t('attributeTable.retry')}</button>
      </div>
    );
  }

  const handleSort = (key: string) => {
    const nextDir: 'asc' | 'desc' = sortKey === key ? (sortDir === 'asc' ? 'desc' : 'asc') : 'asc';
    // sortValue (when the column defines one) reads the raw underlying value
    // -- the sort key doesn't always match the properties field it displays
    // (e.g. 'area' shows properties.area_hectares), and getValue often
    // formats a number into a display string, which then sorts
    // lexicographically ("10" < "5"). Falls back to the old raw lookup for
    // every column that doesn't need the override.
    const col = tableColumns.find((c) => c.key === key);
    const readValue = col?.sortValue ?? ((f: GeoJSON.Feature) => f.properties?.[key]);
    const snapshot = [...featureList].sort((a, b) => {
      const aVal = readValue(a);
      const bVal = readValue(b);
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      const cmp = typeof aVal === 'number' ? aVal - bVal : String(aVal).localeCompare(String(bVal));
      return nextDir === 'asc' ? cmp : -cmp;
    });
    setSortedOrder(snapshot.map((f) => getFeatureId(f)));
    if (sortKey === key) {
      setSortDir((d) => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  };

  const startColumnResize = (e: React.MouseEvent, colKey: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!scopeKey) return;
    const cellEl = (e.currentTarget as HTMLElement).closest('.table-header-cell') as HTMLElement | null;
    const startWidth = cellEl ? cellEl.getBoundingClientRect().width : 150;
    const startX = e.clientX;
    const onMove = (ev: MouseEvent) => {
      const next = Math.max(MIN_COL_WIDTH, startWidth + (ev.clientX - startX));
      store.setColumnWidth(scopeKey, colKey, next);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  const handleColumnDragStart = (e: React.DragEvent, colKey: string) => {
    setDragColKey(colKey);
    e.dataTransfer.effectAllowed = 'move';
    try {
      e.dataTransfer.setData('text/plain', colKey);
    } catch {
      /* ignore */
    }
  };

  const handleColumnDrop = (colKey: string) => {
    if (!dragColKey || dragColKey === colKey || !scopeKey) return;
    const order = columns.map((c) => c.key);
    const fromIdx = order.indexOf(dragColKey);
    const toIdx = order.indexOf(colKey);
    if (fromIdx === -1 || toIdx === -1) return;
    const next = [...order];
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, dragColKey);
    store.setColumnOrder(scopeKey, next);
    setDragColKey(null);
    setDropColKey(null);
  };

  const featById = (featureId: string, all = filteredFeatures) =>
    all.find((x) => (x.properties?.id ?? x.properties?.featureId ?? '') === featureId);
  const zoomToId = (featureId: string) => {
    const f = featById(featureId);
    if (f) onZoomToFeature?.(f);
  };

  // P3.6 — "Set colour…" (one row) + "Set colour for N selected" (bulk). Both
  // reuse the P3.4 `onSaveProperty(feature, 'style_fill' | 'style_clear', …)`
  // pathway, which is undo-wired via P3.5.
  const styleColKey = tableColumns.some((c) => c.editControl === 'color') ? 'style_fill' : null;
  const setColourOnRow = (feature: GeoJSON.Feature, hex: string | null) => {
    onSaveProperty?.(feature, hex ? 'style_fill' : 'style_clear', hex ?? '');
    setColourFor(null);
    setRowMenu(null);
  };
  const setColourOnSelected = (hex: string | null) => {
    for (const id of selectedFeatureIds) {
      const f = featById(id);
      if (f) onSaveProperty?.(f, hex ? 'style_fill' : 'style_clear', hex ?? '');
    }
    setColourFor(null);
  };

  // P2.5 — export / copy the current (filtered + sorted + visible-column) view.
  const exportCsv = () => {
    const name = (activeLayer || activeImportedLayer?.name || 'layer').replace(/\s+/g, '_');
    downloadText(`${name}_view.csv`, 'text/csv;charset=utf-8', tableToCsv(columns, filteredFeatures));
  };
  const exportGeoJson = () => {
    const name = (activeLayer || activeImportedLayer?.name || 'layer').replace(/\s+/g, '_');
    downloadText(`${name}_view.geojson`, 'application/geo+json', tableToGeoJson(filteredFeatures));
  };
  const copyView = async () => {
    try {
      await navigator.clipboard.writeText(tableToTsv(columns, filteredFeatures));
    } catch {
      showSaveError(t('attributeTable.copyFailed'));
    }
  };

  // P2.2 — the Columns… chooser toggles a base column's visibility. Everything
  // is visible by default now, so "shown" is just the stored override, or true
  // when the user has never touched this column.
  const isColumnShown = (colKey: string): boolean => colVis?.[colKey] ?? true;
  const toggleColumn = (colKey: string) => {
    if (!scopeKey) return;
    store.setColumnVisibility(scopeKey, colKey, !isColumnShown(colKey));
  };

  const handleRowClick = (e: React.MouseEvent, featureId: string) => {
    if (!selectionKey) return;
    if (e.shiftKey) {
      // Shift-click selects the range between the last-selected row and this
      // one, in the table's own current (sorted/filtered) order — same
      // range-select convention as a spreadsheet, using the store's existing
      // 'range' mode (already relied on by keyboard range-select elsewhere).
      const rowOrder = filteredFeatures.map((f) => getFeatureId(f));
      store.selectFeatures(selectionKey, [featureId], 'range', rowOrder);
    } else if (e.ctrlKey || e.metaKey) {
      // Ctrl/⌘-click toggles this row in or out of the selection — same as the
      // map, so a mistaken pick can be undone without clearing everything.
      store.toggleFeatureSelection(selectionKey, featureId);
    } else {
      store.selectFeatures(selectionKey, [featureId], 'replace');
    }
  };

  // P0.6: a plain double-click on the row (not on an editable cell / control)
  // zooms to that feature — so the map centres without hunting for the button.
  const handleRowDoubleClick = (e: React.MouseEvent, featureId: string) => {
    if ((e.target as HTMLElement).closest('.editable, input, select, button, textarea')) return;
    zoomToId(featureId);
  };

  const handleRowKeyDown = (e: React.KeyboardEvent, featureId: string) => {
    // With a focused cell the grid-level handler (P5.3) owns Enter / arrows.
    if (focusedCell) return;
    if (e.key === 'Enter') {
      e.preventDefault();
      if (selectionKey) store.selectFeatures(selectionKey, [featureId], 'replace');
      zoomToId(featureId);
    } else if (e.key === ' ') {
      e.preventDefault();
      if (selectionKey) store.selectFeatures(selectionKey, [featureId], 'replace');
    }
  };

  // P5.3 — arrow keys move the focused cell; Enter / F2 edit it (QGIS feel).
  const navCols = columns.filter((c) => c.key !== '#' && !c.key.startsWith('__'));
  const handleGridKeyDown = (e: React.KeyboardEvent) => {
    if (editingCell || !focusedCell) return;
    const colIdx = navCols.findIndex((c) => c.key === focusedCell.colKey);
    if (colIdx < 0) return;
    let { row } = focusedCell;
    let nextColIdx = colIdx;
    if (e.key === 'ArrowDown') row = Math.min(totalRows - 1, row + 1);
    else if (e.key === 'ArrowUp') row = Math.max(0, row - 1);
    else if (e.key === 'ArrowRight') nextColIdx = Math.min(navCols.length - 1, colIdx + 1);
    else if (e.key === 'ArrowLeft') nextColIdx = Math.max(0, colIdx - 1);
    else if (e.key === 'Enter' || e.key === 'F2') {
      const col = navCols[colIdx];
      if (col?.editable) { e.preventDefault(); setEditingCell({ row: focusedCell.row, col: col.key }); }
      return;
    } else {
      return;
    }
    e.preventDefault();
    const nextKey = navCols[nextColIdx]?.key ?? focusedCell.colKey;
    setFocusedCell({ row, colKey: nextKey });
    // keep the row on screen when the list is windowed
    const el = gridRef.current;
    if (el && virtualize) {
      const rowTop = row * ROW_HEIGHT;
      if (rowTop < el.scrollTop) el.scrollTop = rowTop;
      else if (rowTop + ROW_HEIGHT > el.scrollTop + el.clientHeight) el.scrollTop = rowTop - el.clientHeight + ROW_HEIGHT;
    }
  };

  const handleInlineRename = (feature: GeoJSON.Feature, newVal: string, colKey?: string) => {
    setEditingCell(null);
    // Builtin *and* imported layers persist through the host handler now — for
    // imported it resolves the feature index and pushes an undoable
    // `AttributeEditOperation` (imported branch). See MapWorkspace.
    if (onSaveProperty && colKey) {
      onSaveProperty(feature, colKey, newVal);
      return;
    }
    if (isImported) {
      showSaveError(t('attributeTable.saveContextLost'));
      return;
    }
    console.warn('[Save] Aborted: not in imported layer context', { activeLayer, activeImported });
    showSaveError(t('attributeTable.saveContextLost'));
  };

  if (filteredFeatures.length === 0 && !filterActive && !showOnlySelected) {
    return (
      <div className="attribute-table" data-testid="attribute-table" role="region" aria-label={t('attributeTable.aria')}>
        <TableToolbar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          canUndo={store.editHistory.length > 0}
          onUndo={() => store.undoEdit()}
          canRedo={store.editFuture.length > 0}
          onRedo={() => store.redoEdit()}
          toolsOpen={toolsOpen}
          onToggleTools={toggleTools}
        />
        <div className="table-empty">
          <p>{searchQuery ? t('attributeTable.noFeaturesMatch', { query: searchQuery }) : t('attributeTable.noFeaturesInLayer')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="attribute-table" data-testid="attribute-table" role="region" aria-label={t('attributeTable.ariaForLayer', { name: activeLayer })}>
        {saveError && (
          <div className="attribute-table-save-error" role="alert" style={{
            padding: '6px 12px', background: '#fff0f0', color: '#c00',
            borderBottom: '1px solid #fcc', fontSize: 13,
          }}>
            {saveError}
          </div>
        )}
        {toolbarHost(
        <AttributeToolbar
          toolsOpen={toolsOpen}
          onToggleTools={toggleTools}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          canUndo={store.editHistory.length > 0}
          onUndo={() => store.undoEdit()}
          canRedo={store.editFuture.length > 0}
          onRedo={() => store.redoEdit()}
          selectionCount={selectedFeatureIds.length}
          showOnlySelected={showOnlySelected}
          onToggleShowOnlySelected={() => setShowOnlySelected(!showOnlySelected)}
          onZoomToSelection={onZoomToSelection}
          onSelectInView={onSelectInView}
          filter={{
            field: filterField,
            op: filterOp,
            value: filterValue,
            active: filterActive,
            onField: setFilterField,
            onOp: setFilterOp,
            onValue: setFilterValue,
            onClear: () => { setFilterField(''); setFilterValue(''); },
            onMap: filterOnMap,
            onOnMap: setFilterOnMap,
            columns: columns
              .filter((c) => c.key !== '#' && !c.key.startsWith('__'))
              .map((c) => ({ key: c.key, label: colHeader(c) || c.key })),
            suggestions: suggestFilterValues(featureList, filterField, filterOp, filterValue),
          }}
          view={isUnitLayerTable ? {
            themes,
            active: activeTheme,
            onPick: setTheme,
            groups: rasterGroups,
            activeGroup,
            onPickGroup: setRasterGroup,
          } : undefined}
          onUpdateAttribute={isUnitLayerTable ? () => window.dispatchEvent(new CustomEvent('open-update-attribute')) : undefined}
          columnsChooser={{
            rows: orderedColumns.map((c) => ({ key: c.key, label: colHeader(c) || c.key, shown: isColumnShown(c.key) })),
            onToggle: toggleColumn,
          }}
          colour={styleColKey && onSaveProperty && selectedFeatureIds.length > 0 ? {
            count: selectedFeatureIds.length,
            open: colourFor === '__bulk__',
            onClick: (e) => {
              setColourRect(e.currentTarget.getBoundingClientRect());
              setColourFor((v) => (v === '__bulk__' ? null : '__bulk__'));
            },
          } : undefined}
          downloads={{ onCsv: exportCsv, onGeoJson: exportGeoJson, onCopy: copyView }}
          extra={extraToolbar}
        />,
        )}
        {colourFor === '__bulk__' && colourRect && (
          <PortalPopover rect={colourRect} onClose={() => setColourFor(null)}>
            <SwatchGrid onPick={(hex) => setColourOnSelected(hex)} onClear={() => setColourOnSelected(null)} />
          </PortalPopover>
        )}

      <div className="table-grid" role="grid" ref={setGridRef} onKeyDown={handleGridKeyDown} aria-label={t('attributeTable.featuresAria', { name: activeLayer })}>
        <div className="table-header" role="row">
          {tableColumns.map((col) => {
            const isAction = ACTION_COL_KEYS.has(col.key);
            const isEditingHdr = isImported && !ACTION_COL_KEYS.has(col.key) && col.key !== '#' && editingHeader === col.key;
            return (
              <div
                key={col.key}
                className={`table-header-cell ${col.sortable ? 'sortable' : ''} ${isImported && !isAction && col.key !== '#' ? 'header-editable' : ''} ${dragColKey === col.key ? 'dragging' : ''} ${dropColKey === col.key && dragColKey !== col.key ? 'drop-target' : ''}`}
                data-frozen={isAction ? '1' : undefined}
                style={{
                  width: typeof col.width === 'number' ? col.width : undefined,
                  flex: typeof col.width === 'number' ? '0 0 auto' : 1,
                  textAlign: col.align || 'left',
                }}
                onClick={() => !isEditingHdr && col.sortable && handleSort(col.key)}
                onDoubleClick={() => isImported && !isAction && col.key !== '#' && setEditingHeader(col.key)}
                role="columnheader"
                aria-sort={sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                tabIndex={0}
                title={colHeader(col)}
                draggable={!isAction}
                onDragStart={(e) => !isAction && handleColumnDragStart(e, col.key)}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.dataTransfer.dropEffect = 'move';
                  if (!isAction && dropColKey !== col.key) setDropColKey(col.key);
                }}
                onDragLeave={() => {
                  if (dropColKey === col.key) setDropColKey(null);
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (!isAction) handleColumnDrop(col.key);
                }}
                onDragEnd={() => {
                  setDragColKey(null);
                  setDropColKey(null);
                }}
              >
                {isEditingHdr ? (
                  <InlineEditor
                    initialValue={col.label}
                    onSave={(newVal) => handleHeaderRename(col.key, newVal)}
                    onCancel={() => setEditingHeader(null)}
                  />
                ) : (
                  <>
                    {colHeader(col)}
                    {sortKey === col.key && <span className="sort-arrow">{sortDir === 'asc' ? ' ▲' : ' ▼'}</span>}
                  </>
                )}
                {!isAction && (
                  <div
                    className="col-resize-handle"
                    onMouseDown={(e) => startColumnResize(e, col.key)}
                    role="separator"
                    aria-label={t('attributeTable.resizeColAria', { col: colHeader(col) })}
                    aria-orientation="vertical"
                    title={t('attributeTable.resizeCol')}
                  />
                )}
              </div>
            );
          })}
        </div>

        <div className="table-body" role="rowgroup">
          {virtualize && startIdx > 0 && (
            <div aria-hidden style={{ height: startIdx * ROW_HEIGHT, flex: '0 0 auto' }} />
          )}
          {(virtualize ? filteredFeatures.slice(startIdx, endIdx) : filteredFeatures).map((feature, i) => {
            const index = startIdx + i;
            const featureId = feature.properties?.id || feature.properties?.featureId || `feat-${index}`;
            const isSelected = selectedFeatureIds.includes(featureId);

            return (
              <div
                key={featureId}
                className={`table-row ${isSelected ? 'selected' : ''}`}
                role="row"
                aria-selected={isSelected}
                onClick={(e) => handleRowClick(e, featureId)}
                onDoubleClick={(e) => handleRowDoubleClick(e, featureId)}
                onKeyDown={(e) => handleRowKeyDown(e, featureId)}
                tabIndex={0}
                style={{ height: ROW_HEIGHT }}
              >
                {tableColumns.map((col) => {
                  const value = col.getValue ? col.getValue(feature, index) : feature.properties?.[col.key];
                  const isEditing = editingCell?.row === index && editingCell?.col === col.key;

                  if (col.key === '__actions__') {
                    const open = rowMenu === featureId;
                    return (
                      <div
                        key={col.key}
                        className="table-cell table-cell-actions"
                        style={{ width: 34, flex: '0 0 34px', justifyContent: 'center' }}
                        role="gridcell"
                        data-frozen="1"
                      >
                        <button
                          type="button"
                          className="row-actions-btn"
                          aria-haspopup="menu"
                          aria-expanded={open}
                          title={t('attributeTable.rowActions')}
                          aria-label={t('attributeTable.rowActions')}
                          onClick={(e) => {
                            e.stopPropagation();
                            setRowMenuRect(e.currentTarget.getBoundingClientRect());
                            setRowMenu(open ? null : featureId);
                          }}
                        >
                          ⋮
                        </button>
                        {open && rowMenuRect && (
                          <PortalPopover rect={rowMenuRect} onClose={() => setRowMenu(null)}>
                            <div className="row-actions-menu" role="menu">
                              {onZoomToFeature && (
                                <button type="button" role="menuitem" onClick={() => { setRowMenu(null); onZoomToFeature(feature); }}>
                                  🧭 {t('attributeTable.zoomToFeature')}
                                </button>
                              )}
                              {onCopyFeature && (
                                <button type="button" role="menuitem" onClick={() => { setRowMenu(null); onCopyFeature(feature, index); }}>
                                  📄 {selectedFeatureIds.length > 1 && selectedFeatureIds.includes(featureId)
                                    ? t('layerPanel.copySelected', { count: selectedFeatureIds.length })
                                    : t('attributeTable.copyFeature')}
                                </button>
                              )}
                              {onPasteFeatures && pasteState !== undefined && pasteState !== 'never' && (
                                <button
                                  type="button" role="menuitem"
                                  disabled={pasteState !== null}
                                  title={pasteState ? String(t(pasteState.reasonKey, pasteState.params)) : undefined}
                                  onClick={() => { setRowMenu(null); onPasteFeatures(); }}
                                >
                                  📋 {t('layerPanel.pasteHere', { count: clipboardCount })}
                                </button>
                              )}
                              {onPasteAsLayer && (
                                <button
                                  type="button" role="menuitem"
                                  disabled={clipboardCount === 0}
                                  title={clipboardCount === 0 ? String(t('editing.paste.reason.empty_clipboard')) : undefined}
                                  onClick={() => { setRowMenu(null); onPasteAsLayer(); }}
                                >
                                  🗂 {t('layerPanel.pasteAsLayer')}
                                </button>
                              )}
                              {styleColKey && onSaveProperty && (
                                <button type="button" role="menuitem" onClick={() => { setColourRect(rowMenuRect); setRowMenu(null); setColourFor(featureId); }}>
                                  🎨 {t('attributeTable.setColour')}
                                </button>
                              )}
                              {activeLayer && (
                                <button type="button" role="menuitem" onClick={() => { setRowMenu(null); store.toggleFeatureHidden(activeLayer, featureId); }}>
                                  {(store.hiddenFeatureIds[`${store.calculationId ?? 'nc'}::${activeLayer}`] ?? []).includes(featureId)
                                    ? `👁 ${t('attributeTable.showOnMap')}`
                                    : `🚫 ${t('attributeTable.hideOnMap')}`}
                                </button>
                              )}
                              {onDeleteFeature && (
                                <button type="button" role="menuitem" className="danger" onClick={() => { setRowMenu(null); onDeleteFeature(feature, index); }}>
                                  🗑 {t('attributeTable.deleteFeature')}
                                </button>
                              )}
                            </div>
                          </PortalPopover>
                        )}
                        {colourFor === featureId && colourRect && (
                          <PortalPopover rect={colourRect} onClose={() => setColourFor(null)}>
                            <SwatchGrid
                              onPick={(hex) => setColourOnRow(feature, hex)}
                              onClear={() => setColourOnRow(feature, null)}
                            />
                          </PortalPopover>
                        )}
                      </div>
                    );
                  }

                  return (
                    <div
                      key={col.key}
                      className={`table-cell ${col.editable ? 'editable' : ''} ${focusedCell?.row === index && focusedCell?.colKey === col.key ? 'cell-focused' : ''}`}
                      style={{
                        width: typeof col.width === 'number' ? col.width : undefined,
                        flex: typeof col.width === 'number' ? '0 0 auto' : 1,
                        justifyContent:
                          col.align === 'right' ? 'flex-end' :
                          col.align === 'center' ? 'center' :
                          'flex-start',
                        textAlign: col.align || 'left',
                      }}
                      role="gridcell"
                      onClick={() => !ACTION_COL_KEYS.has(col.key) && col.key !== '#' && setFocusedCell({ row: index, colKey: col.key })}
                      onDoubleClick={() => col.editable && setEditingCell({ row: index, col: col.key })}
                    >
{isEditing && col.editable ? (
                          <InlineEditor
                            initialValue={String(value ?? '')}
                            onSave={(newVal) => handleInlineRename(feature, newVal, col.key)}
                            onCancel={() => setEditingCell(null)}
                          />
                        ) : col.select ? (
                          <select
                            className="subarea-category-select"
                            value={String(col.selectValue ? col.selectValue(feature) : (value ?? ''))}
                            aria-label={t('attributeTable.selectColAria', { col: colHeader(col) })}
                            onChange={(e) => onSaveProperty?.(feature, col.key, e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <option value="">{col.emptyLabelKey ? t(col.emptyLabelKey) : '-'}</option>
                            {col.select.map((opt) => (
                              <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                          </select>
                        ) : col.editControl === 'color' ? (
                          <span className="style-cell" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="color"
                              className="style-color-input"
                              value={typeof value === 'string' && value ? value : '#3388ff'}
                              aria-label={t('attributeTable.styleFillAria')}
                              onChange={(e) => onSaveProperty?.(feature, col.key, e.target.value)}
                            />
                            {value ? (
                              <button
                                type="button"
                                className="style-clear"
                                title={t('attributeTable.clearStyle')}
                                aria-label={t('attributeTable.clearStyle')}
                                onClick={() => onSaveProperty?.(feature, 'style_clear', '')}
                              >
                                ×
                              </button>
                            ) : null}
                          </span>
                        ) : col.editControl === 'opacity' ? (
                          <select
                            className="subarea-category-select"
                            value={value == null || value === '' ? '' : String(value)}
                            aria-label={t('attributeTable.styleOpacityAria')}
                            onChange={(e) => onSaveProperty?.(feature, col.key, e.target.value)}
                            onClick={(e) => e.stopPropagation()}
                          >
                            <option value="">{'-'}</option>
                            <option value="0">0%</option>
                            <option value="0.25">25%</option>
                            <option value="0.5">50%</option>
                            <option value="0.75">75%</option>
                            <option value="1">100%</option>
                          </select>
                        ) : col.editControl === 'years' ? (
                          <YearsCell
                            years={featureYears(feature.properties)}
                            disabled={!onSaveProperty}
                            onSave={(ys) => onSaveProperty?.(feature, 'years', ys.join(','))}
                          />
                        ) : col.render ? (
                          col.render(value, feature)
                        ) : (
                          <span>{typeof value === 'object' && value !== null ? JSON.stringify(value) : (value ?? '-')}</span>
                        )}
                    </div>
                  );
                })}
              </div>
            );
          })}
          {virtualize && endIdx < totalRows && (
            <div aria-hidden style={{ height: (totalRows - endIdx) * ROW_HEIGHT, flex: '0 0 auto' }} />
          )}
        </div>
      </div>

      <div className="table-status-bar">
        <span>{t('attributeTable.featuresCount', { count: filteredFeatures.length })}</span>
        {selectedFeatureIds.length > 0 && (
          <span>{t('workspace.statusSelection', { count: selectedFeatureIds.length })}</span>
        )}
      </div>
    </div>
  );
}

// P3.6 — a compact colour picker: 8 presets + a native colour input + Clear.
const PRESET_SWATCHES = ['#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4', '#42d4f4', '#a9a9a9', '#000000'];

function SwatchGrid({ onPick, onClear }: { onPick: (hex: string) => void; onClear: () => void }) {
  const t = useT();
  return (
    <div className="swatch-grid" role="group" aria-label={t('attributeTable.setColour')} onClick={(e) => e.stopPropagation()}>
      {PRESET_SWATCHES.map((hex) => (
        <button
          key={hex}
          type="button"
          className="swatch"
          style={{ background: hex }}
          aria-label={hex}
          onClick={() => onPick(hex)}
        />
      ))}
      <input
        type="color"
        className="swatch-custom"
        aria-label={t('attributeTable.styleFillAria')}
        onChange={(e) => onPick(e.target.value)}
      />
      <button type="button" className="swatch-clear" onClick={onClear}>{t('attributeTable.clearStyle')}</button>
    </div>
  );
}

function InlineEditor({
  initialValue, onSave, onCancel,
}: {
  initialValue: string;
  onSave: (value: string) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  return (
    <input
      ref={inputRef}
      className="inline-editor"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onSave(value);
        if (e.key === 'Escape') onCancel();
      }}
      onBlur={() => onSave(value)}
      aria-label={t('attributeTable.editValue')}
    />
  );
}

function TableToolbar({
  searchQuery, onSearchChange, activeLayer, selectionCount,
  canUndo, onUndo, canRedo, onRedo, toolsOpen, onToggleTools, showOnlySelected,
}: {
  searchQuery: string;
  onSearchChange: (q: string) => void;
  activeLayer?: string;
  selectionCount?: number;
  canUndo?: boolean;
  onUndo?: () => void;
  canRedo?: boolean;
  onRedo?: () => void;
  toolsOpen: boolean;
  onToggleTools: () => void;
  showOnlySelected?: boolean;
}) {
  const t = useT();
  // A collapsed panel can still have an active search or "selected only" —
  // flag it on the toggle so "why did my rows disappear" always has a
  // visible answer.
  const hasHiddenActiveSearch = !toolsOpen && (searchQuery.length > 0 || !!showOnlySelected);
  return (
    <div className="table-toolbar">
      <button
        type="button"
        className="toolbar-icon-btn tools-toggle-btn"
        aria-haspopup="true"
        aria-expanded={toolsOpen}
        title={t('attributeTable.moreTools')}
        aria-label={t('attributeTable.moreTools')}
        onClick={onToggleTools}
      >
        <MoreVertical size={15} />
        {hasHiddenActiveSearch && <span className="toolbar-dot" aria-hidden="true" />}
      </button>
      {toolsOpen && (
        <input
          type="search"
          className="table-search"
          placeholder={t('attributeTable.search')}
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          aria-label={t('attributeTable.search')}
        />
      )}
      <div className="table-toolbar-actions">
        {toolsOpen && onUndo && (
          <button
            type="button"
            className="toolbar-btn"
            onClick={onUndo}
            disabled={!canUndo}
            title={t('attributeTable.undoTitle')}
            aria-label={t('attributeTable.undo')}
          >
            ↩
          </button>
        )}
        {toolsOpen && onRedo && (
          <button
            type="button"
            className="toolbar-btn"
            onClick={onRedo}
            disabled={!canRedo}
            title={t('attributeTable.redoTitle')}
            aria-label={t('attributeTable.redo')}
          >
            ↪
          </button>
        )}
        {selectionCount && selectionCount > 0 ? (
          <span className="selection-count">{t('attributeTable.selected', { count: selectionCount })}</span>
        ) : null}
      </div>
    </div>
  );
}
