import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  BoxSelect, Braces, ChevronDown, ChevronUp, Columns3, Copy, FileText, Filter, Frame, GripVertical, LayoutGrid, ListFilter, MoreHorizontal,
  MoreVertical, Palette, Redo2, RefreshCw, Settings2, Table2, Undo2, X,
  Info, Mountain, ClipboardList, Trees, ShieldAlert, Tags,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useT } from '../i18n/hooks';
import { FILTER_OPS, type FilterOp } from '../lib/attributeFilter';
import type { AttributeTheme } from '../lib/attributeThemes';
import type { AnalysisGroup } from '../lib/analysisFields';
import {
  DEFAULT_LAYOUT, ITEM_SIDE, barItems, isDefaultLayout, menuItems, moveItem, reorderItem, setHidden, type ToolbarItemId,
} from '../lib/toolbarLayout';
import { useToolbarLayout, type ToolbarLayoutStore } from '../hooks/useToolbarLayout';

const THEME_ICON: Record<AttributeTheme, LucideIcon> = {
  all: Table2, basic: Info, raster: Mountain, inventory: ClipboardList, sfm: Trees, hazard: ShieldAlert, classification: Tags,
};

/**
 * A pop-up under its button, rendered at page level (position: fixed). The toolbar can sit in a dock panel's title bar, and a dock
 * panel clips its overflow, so an absolutely positioned pop-up would be cut off at the panel edge. Closes on Escape or a press outside
 * both the pop-up and its button (the button's own click toggles it).
 */
function Pop({ open, anchorRef, onClose, align = 'left', className = '', children, ...aria }: {
  open: boolean;
  anchorRef: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  align?: 'left' | 'right';
  className?: string;
  children: React.ReactNode;
  role?: string;
  'aria-label'?: string;
}) {
  const popRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useLayoutEffect(() => {
    if (!open) return;
    const a = anchorRef.current?.getBoundingClientRect();
    if (!a) return;
    const box = popRef.current?.getBoundingClientRect();
    const w = box?.width ?? 200;
    const h = box?.height ?? 120;
    let left = align === 'right' ? a.right - w : a.left;
    left = Math.min(Math.max(8, left), Math.max(8, window.innerWidth - w - 8));
    let top = a.bottom + 2;
    if (top + h > window.innerHeight - 8) top = Math.max(8, a.top - h - 2);
    setPos({ top, left });
  }, [open, align, anchorRef]);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      const target = e.target as Node;
      if (popRef.current?.contains(target) || anchorRef.current?.contains(target)) return;
      onClose();
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', esc);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', esc);
    };
  }, [open, onClose, anchorRef]);

  if (!open) return null;
  return createPortal(
    <div ref={popRef} className={`tb-pop ${className}`} style={{ position: 'fixed', top: pos.top, left: pos.left, zIndex: 4000 }} {...aria}>
      {children}
    </div>,
    document.body,
  );
}

export interface ToolbarFilter {
  field: string;
  op: FilterOp;
  value: string;
  active: boolean;
  onField: (v: string) => void;
  onOp: (v: FilterOp) => void;
  onValue: (v: string) => void;
  onClear: () => void;
  onMap: boolean;
  onOnMap: (v: boolean) => void;
  columns: { key: string; label: string }[];
  suggestions: { value: string; count: number }[];
}

export interface ToolbarView {
  themes: AttributeTheme[];
  active: AttributeTheme;
  onPick: (t: AttributeTheme) => void;
  groups: AnalysisGroup[];
  activeGroup: AnalysisGroup | 'all';
  onPickGroup: (g: AnalysisGroup | 'all') => void;
}

export interface AttributeToolbarProps {
  toolsOpen: boolean;
  onToggleTools: () => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  canUndo?: boolean;
  onUndo?: () => void;
  canRedo?: boolean;
  onRedo?: () => void;
  selectionCount: number;
  showOnlySelected: boolean;
  onToggleShowOnlySelected: () => void;
  onZoomToSelection?: () => void;
  onSelectInView?: () => void;
  filter: ToolbarFilter;
  view?: ToolbarView;
  onUpdateAttribute?: () => void;
  columnsChooser: { rows: { key: string; label: string; shown: boolean }[]; onToggle: (key: string) => void };
  /** the "Set colour for N selected" button; the swatch panel itself is the parent's */
  colour?: { count: number; open: boolean; onClick: (e: React.MouseEvent<HTMLButtonElement>) => void };
  downloads: { onCsv: () => void; onGeoJson: () => void; onCopy: () => void };
  extra?: React.ReactNode;
  /** where the layout is kept; the default is the per-user store (tests pass a plain one) */
  layoutStore?: ToolbarLayoutStore;
}

const ITEM_LABEL: Record<ToolbarItemId, string> = {
  filter: 'attributeTable.filterButton',
  view: 'attributeUpdate.theme.label',
  selection: 'attributeToolbar.item.selection',
  columns: 'attributeTable.columnsChooser',
  colour: 'attributeToolbar.item.colour',
  update: 'attributeUpdate.title',
  download: 'attributeTable.downloadMenu',
  history: 'attributeToolbar.item.history',
};
const ITEM_ICON: Record<ToolbarItemId, LucideIcon> = {
  filter: Filter, view: LayoutGrid, selection: ListFilter, columns: Columns3, colour: Palette, update: RefreshCw, download: FileText, history: Undo2,
};

/**
 * The attribute table's toolbar, in ONE row (owner request 2026-10-11: four bars took about 155px of a panel's height).
 *
 *   [⋮] [search] [Filter ▾ + chip] [View ▾] | N selected [only] [zoom] [in view] ........ [Columns] [colour] [Update] [Download ▾] [undo] [redo] [⚙]
 *
 * The filter, the view choice and the downloads are small pop-ups instead of permanent bars; an active filter stays visible as a chip so
 * "why are rows missing" always has an answer. The toggle, search, the selection count and the customise button are fixed; every other
 * item can be reordered (within its side of the bar) or taken off the bar into the "More" menu from the customise pop-up, and the choice
 * is kept per user (`useToolbarLayout`). On a narrow panel the row wraps rather than hiding anything.
 */
export function AttributeToolbar(p: AttributeToolbarProps) {
  const t = useT();
  const own = useToolbarLayout();
  const { layout, setLayout } = p.layoutStore ?? own;
  const [filterOpen, setFilterOpen] = useState(false);
  const [viewOpen, setViewOpen] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [customOpen, setCustomOpen] = useState(false);
  const filterRef = useRef<HTMLSpanElement | null>(null);
  const viewRef = useRef<HTMLSpanElement | null>(null);
  const downloadRef = useRef<HTMLSpanElement | null>(null);
  const columnsRef = useRef<HTMLSpanElement | null>(null);
  const moreRef = useRef<HTMLSpanElement | null>(null);
  const customRef = useRef<HTMLSpanElement | null>(null);
  const dragId = useRef<ToolbarItemId | null>(null);
  const closeFilter = React.useCallback(() => setFilterOpen(false), []);
  const closeView = React.useCallback(() => setViewOpen(false), []);
  const closeDownload = React.useCallback(() => setDownloadOpen(false), []);
  const closeColumns = React.useCallback(() => setColumnsOpen(false), []);
  const closeMore = React.useCallback(() => setMoreOpen(false), []);
  const closeCustom = React.useCallback(() => setCustomOpen(false), []);

  const hasHiddenActiveSearch = !p.toolsOpen && (p.searchQuery.length > 0 || p.showOnlySelected);
  const fieldLabel = p.filter.columns.find((c) => c.key === p.filter.field)?.label ?? p.filter.field;
  const opSymbol = FILTER_OPS.find((o) => o.op === p.filter.op)?.symbol ?? '';
  const ViewIcon = p.view ? THEME_ICON[p.view.active] ?? LayoutGrid : LayoutGrid;

  // what this layer's toolbar has at all, and what is usable right now (some items only exist with the tools open)
  const exists = new Set<ToolbarItemId>(['filter', 'selection', 'columns', 'download']);
  if (p.view) exists.add('view');
  if (p.colour) exists.add('colour');
  if (p.onUpdateAttribute) exists.add('update');
  if (p.onUndo || p.onRedo) exists.add('history');
  const available = new Set<ToolbarItemId>([...exists].filter((id) => p.toolsOpen || !(id === 'columns' || id === 'download' || id === 'history')));
  const left = barItems(layout, 'left', available);
  const right = barItems(layout, 'right', available);
  const inMenu = menuItems(layout, available).filter((id) => id !== 'selection' || p.toolsOpen);
  const pinned = (id: ToolbarItemId) => left.includes(id) || right.includes(id);

  // a pop-up opens under its own button, or under "More" when the item has been taken off the bar
  const anchor = (id: ToolbarItemId, own: React.RefObject<HTMLSpanElement | null>) => (pinned(id) ? own : moreRef);

  const chip = p.filter.active && (
    <span className="tb-chip" data-testid="tb-filter-chip" title={`${fieldLabel} ${opSymbol} ${p.filter.value}`}>
      <span className="tb-chip-text">{`${fieldLabel} ${opSymbol} ${p.filter.value}`}</span>
      <button type="button" className="tb-chip-x" title={t('attributeTable.filterClear')} aria-label={t('attributeTable.filterClear')} onClick={p.filter.onClear}>
        <X size={12} />
      </button>
    </span>
  );
  const countEl = p.selectionCount > 0 && <span className="selection-count">{t('attributeTable.selected', { count: p.selectionCount })}</span>;

  const selectionButtons = (
    <>
      <button
        type="button"
        className="toolbar-icon-btn"
        aria-pressed={p.showOnlySelected}
        disabled={p.selectionCount === 0 && !p.showOnlySelected}
        title={t('attributeTable.showOnlySelected')}
        aria-label={t('attributeTable.showOnlySelectedShort')}
        onClick={p.onToggleShowOnlySelected}
      >
        <ListFilter size={15} />
      </button>
      {p.onZoomToSelection && (
        <button type="button" className="toolbar-icon-btn" disabled={p.selectionCount === 0} title={t('attributeTable.zoomToSelection')} aria-label={t('attributeTable.zoomToSelection')} onClick={p.onZoomToSelection}>
          <Frame size={15} />
        </button>
      )}
      {p.onSelectInView && (
        <button type="button" className="toolbar-icon-btn" title={t('attributeTable.selectInView')} aria-label={t('attributeTable.selectInView')} onClick={p.onSelectInView}>
          <BoxSelect size={15} />
        </button>
      )}
    </>
  );

  const renderItem = (id: ToolbarItemId): React.ReactNode => {
    switch (id) {
      case 'filter':
        return (
          <React.Fragment key={id}>
            <span className="tb-anchor" ref={filterRef}>
              <button
                type="button"
                className={`toolbar-icon-btn${p.filter.active ? ' active' : ''}`}
                aria-haspopup="dialog"
                aria-expanded={filterOpen}
                title={t('attributeTable.filterButton')}
                aria-label={t('attributeTable.filterButton')}
                data-testid="tb-filter"
                onClick={() => setFilterOpen((v) => !v)}
              >
                <Filter size={15} />
              </button>
            </span>
            {chip}
          </React.Fragment>
        );
      case 'view':
        return (
          <span key={id} className="tb-anchor" ref={viewRef}>
            <button
              type="button"
              className="toolbar-icon-btn tb-view-btn"
              aria-haspopup="menu"
              aria-expanded={viewOpen}
              title={t('attributeUpdate.theme.label')}
              aria-label={t('attributeUpdate.theme.label')}
              data-testid="tb-view"
              onClick={() => setViewOpen((v) => !v)}
            >
              <ViewIcon size={14} />
              {p.view && p.view.active !== 'all' && (
                <span className="tb-view-name">
                  {t(`attributeUpdate.theme.${p.view.active}`)}
                  {p.view.active === 'raster' && p.view.activeGroup !== 'all' ? ` · ${t(`attributeUpdate.group.${p.view.activeGroup}`)}` : ''}
                </span>
              )}
            </button>
          </span>
        );
      case 'selection':
        return (
          <React.Fragment key={id}>
            {(p.selectionCount > 0 || p.toolsOpen) && <span className="tb-sep" aria-hidden="true" />}
            {countEl}
            {p.toolsOpen && selectionButtons}
          </React.Fragment>
        );
      case 'columns':
        return (
          <span key={id} className="tb-anchor" ref={columnsRef}>
            <button
              type="button"
              className="toolbar-icon-btn column-chooser-toggle"
              aria-haspopup="dialog"
              aria-expanded={columnsOpen}
              title={t('attributeTable.columnsChooser')}
              aria-label={t('attributeTable.columnsChooser')}
              onClick={() => setColumnsOpen((v) => !v)}
            >
              <Columns3 size={15} />
            </button>
          </span>
        );
      case 'colour':
        return p.colour ? (
          <button
            key={id}
            type="button"
            className="toolbar-icon-btn set-colour-btn"
            aria-haspopup="dialog"
            aria-expanded={p.colour.open}
            title={t('attributeTable.setColourBulk', { count: p.colour.count })}
            aria-label={t('attributeTable.setColourBulk', { count: p.colour.count })}
            onClick={p.colour.onClick}
          >
            <Palette size={15} />
            <span className="toolbar-badge">{p.colour.count}</span>
          </button>
        ) : null;
      case 'update':
        return p.onUpdateAttribute ? (
          <button key={id} type="button" className="toolbar-icon-btn" title={t('attributeUpdate.title')} aria-label={t('attributeUpdate.title')} data-testid="tb-update-attribute" onClick={p.onUpdateAttribute}>
            <RefreshCw size={14} />
          </button>
        ) : null;
      case 'download':
        return (
          <span key={id} className="tb-anchor" ref={downloadRef}>
            <button
              type="button"
              className="toolbar-icon-btn"
              aria-haspopup="menu"
              aria-expanded={downloadOpen}
              title={t('attributeTable.downloadMenu')}
              aria-label={t('attributeTable.downloadMenu')}
              data-testid="tb-download"
              onClick={() => setDownloadOpen((v) => !v)}
            >
              <FileText size={15} />
            </button>
          </span>
        );
      case 'history':
        return (
          <React.Fragment key={id}>
            {p.onUndo && (
              <button type="button" className="toolbar-btn" onClick={p.onUndo} disabled={!p.canUndo} title={t('attributeTable.undoTitle')} aria-label={t('attributeTable.undo')}>↩</button>
            )}
            {p.onRedo && (
              <button type="button" className="toolbar-btn" onClick={p.onRedo} disabled={!p.canRedo} title={t('attributeTable.redoTitle')} aria-label={t('attributeTable.redo')}>↪</button>
            )}
          </React.Fragment>
        );
      default:
        return null;
    }
  };

  /** One entry of the "More" menu: an item taken off the bar. Pop-up items open their pop-up under "More". */
  const renderMenuEntry = (id: ToolbarItemId): React.ReactNode => {
    const done = () => setMoreOpen(false);
    const entry = (key: string, label: string, Icon: LucideIcon, onClick: (e: React.MouseEvent<HTMLButtonElement>) => void, disabled = false) => (
      <button key={key} type="button" role="menuitem" disabled={disabled} data-testid={`tb-more-${key}`} onClick={(e) => { onClick(e); done(); }}>
        <Icon size={13} /> {label}
      </button>
    );
    switch (id) {
      case 'filter': return entry('filter', t('attributeTable.filterButton'), Filter, () => setFilterOpen(true));
      case 'view': return entry('view', t('attributeUpdate.theme.label'), LayoutGrid, () => setViewOpen(true));
      case 'columns': return entry('columns', t('attributeTable.columnsChooser'), Columns3, () => setColumnsOpen(true));
      case 'download': return entry('download', t('attributeTable.downloadMenu'), FileText, () => setDownloadOpen(true));
      case 'colour': return p.colour ? entry('colour', t('attributeTable.setColourBulk', { count: p.colour.count }), Palette, (e) => p.colour!.onClick(e)) : null;
      case 'update': return p.onUpdateAttribute ? entry('update', t('attributeUpdate.title'), RefreshCw, () => p.onUpdateAttribute!()) : null;
      case 'selection':
        return (
          <React.Fragment key={id}>
            {entry('only-selected', t('attributeTable.showOnlySelected'), ListFilter, p.onToggleShowOnlySelected, p.selectionCount === 0 && !p.showOnlySelected)}
            {p.onZoomToSelection && entry('zoom', t('attributeTable.zoomToSelection'), Frame, () => p.onZoomToSelection!(), p.selectionCount === 0)}
            {p.onSelectInView && entry('in-view', t('attributeTable.selectInView'), BoxSelect, () => p.onSelectInView!())}
          </React.Fragment>
        );
      case 'history':
        return (
          <React.Fragment key={id}>
            {p.onUndo && entry('undo', t('attributeTable.undo'), Undo2, () => p.onUndo!(), !p.canUndo)}
            {p.onRedo && entry('redo', t('attributeTable.redo'), Redo2, () => p.onRedo!(), !p.canRedo)}
          </React.Fragment>
        );
      default: return null;
    }
  };

  const customRows = (side: 'left' | 'right') =>
    layout.order
      .filter((id) => ITEM_SIDE[id] === side && exists.has(id))
      .map((id, i, all) => {
        const Icon = ITEM_ICON[id];
        const label = t(ITEM_LABEL[id]);
        return (
          <div
            key={id}
            className="tb-cust-row"
            data-testid={`tb-cust-${id}`}
            draggable
            onDragStart={(e) => {
              dragId.current = id;
              e.dataTransfer?.setData('text/plain', id);
            }}
            onDragOver={(e) => {
              if (dragId.current && ITEM_SIDE[dragId.current] === side) e.preventDefault();
            }}
            onDrop={(e) => {
              e.preventDefault();
              const from = dragId.current;
              dragId.current = null;
              if (!from) return;
              const r = e.currentTarget.getBoundingClientRect();
              setLayout(reorderItem(layout, from, id, e.clientY > r.top + r.height / 2 ? 'after' : 'before'));
            }}
          >
            <span className="tb-cust-grip" data-testid={`tb-cust-drag-${id}`} title={t('attributeToolbar.drag')} aria-hidden="true"><GripVertical size={13} /></span>
            <label className="tb-cust-name">
              <input
                type="checkbox"
                checked={!layout.hidden.includes(id)}
                data-testid={`tb-cust-show-${id}`}
                aria-label={t('attributeToolbar.showInToolbar', { name: label })}
                onChange={(e) => setLayout(setHidden(layout, id, !e.target.checked))}
              />
              <Icon size={13} /> <span>{label}</span>
            </label>
            <button type="button" className="tb-cust-move" data-testid={`tb-cust-up-${id}`} disabled={i === 0} title={t('attributeToolbar.moveUp', { name: label })} aria-label={t('attributeToolbar.moveUp', { name: label })} onClick={() => setLayout(moveItem(layout, id, -1))}>
              <ChevronUp size={13} />
            </button>
            <button type="button" className="tb-cust-move" data-testid={`tb-cust-down-${id}`} disabled={i === all.length - 1} title={t('attributeToolbar.moveDown', { name: label })} aria-label={t('attributeToolbar.moveDown', { name: label })} onClick={() => setLayout(moveItem(layout, id, 1))}>
              <ChevronDown size={13} />
            </button>
          </div>
        );
      });

  return (
    <div className="table-toolbar table-toolbar-one" data-testid="attribute-toolbar">
      <button
        type="button"
        className="toolbar-icon-btn tools-toggle-btn"
        aria-haspopup="true"
        aria-expanded={p.toolsOpen}
        title={t('attributeTable.moreTools')}
        aria-label={t('attributeTable.moreTools')}
        onClick={p.onToggleTools}
      >
        <MoreVertical size={15} />
        {hasHiddenActiveSearch && <span className="toolbar-dot" aria-hidden="true" />}
      </button>

      {p.toolsOpen && (
        <input
          type="search"
          className="table-search tb-search"
          placeholder={t('attributeTable.search')}
          value={p.searchQuery}
          onChange={(e) => p.onSearchChange(e.target.value)}
          aria-label={t('attributeTable.search')}
        />
      )}

      {left.map(renderItem)}
      {/* the fixed parts survive a customised bar: an active filter and the selection count are always visible */}
      {!pinned('filter') && chip}
      {!pinned('selection') && countEl && (
        <>
          <span className="tb-sep" aria-hidden="true" />
          {countEl}
        </>
      )}

      <span className="tb-spacer" />

      {right.map(renderItem)}

      {inMenu.length > 0 && (
        <span className="tb-anchor" ref={moreRef}>
          <button
            type="button"
            className="toolbar-icon-btn"
            aria-haspopup="menu"
            aria-expanded={moreOpen}
            title={t('attributeToolbar.more')}
            aria-label={t('attributeToolbar.more')}
            data-testid="tb-more"
            onClick={() => setMoreOpen((v) => !v)}
          >
            <MoreHorizontal size={15} />
          </button>
        </span>
      )}
      <span className="tb-anchor" ref={customRef}>
        <button
          type="button"
          className="toolbar-icon-btn"
          aria-haspopup="dialog"
          aria-expanded={customOpen}
          title={t('attributeToolbar.customize')}
          aria-label={t('attributeToolbar.customize')}
          data-testid="tb-customize"
          onClick={() => setCustomOpen((v) => !v)}
        >
          <Settings2 size={14} />
        </button>
      </span>
      {p.extra}

      {/* ---- pop-ups (portaled): each opens under its own button, or under "More" when its item is off the bar ---- */}
      <Pop open={moreOpen} anchorRef={moreRef} onClose={closeMore} align="right" className="tb-menu" role="menu" aria-label={t('attributeToolbar.more')}>
        <>{inMenu.map(renderMenuEntry)}</>
      </Pop>

      <Pop open={customOpen} anchorRef={customRef} onClose={closeCustom} align="right" className="tb-cust" role="dialog" aria-label={t('attributeToolbar.customize')}>
        <>
          <div className="tb-cust-hint">{t('attributeToolbar.customizeHint')}</div>
          {customRows('left')}
          <div className="tb-cust-divider" aria-hidden="true" />
          {customRows('right')}
          <div className="tb-cust-foot">
            <button type="button" data-testid="tb-cust-reset" disabled={isDefaultLayout(layout)} onClick={() => setLayout(DEFAULT_LAYOUT)}>
              {t('attributeToolbar.reset')}
            </button>
            <button type="button" data-testid="tb-cust-done" onClick={closeCustom}>{t('attributeToolbar.done')}</button>
          </div>
        </>
      </Pop>

      <Pop open={filterOpen} anchorRef={anchor('filter', filterRef)} onClose={closeFilter} className="tb-filter-pop" role="dialog" aria-label={t('attributeTable.filterButton')}>
        <>
          <select className="filter-field" aria-label={t('attributeTable.filterField')} value={p.filter.field} onChange={(e) => p.filter.onField(e.target.value)}>
            <option value="">{t('attributeTable.filterNoField')}</option>
            {p.filter.columns.map((c) => (
              <option key={c.key} value={c.key}>{c.label}</option>
            ))}
          </select>
          <select className="filter-op" aria-label={t('attributeTable.filterOp')} value={p.filter.op} onChange={(e) => p.filter.onOp(e.target.value as FilterOp)}>
            {FILTER_OPS.map((o) => <option key={o.op} value={o.op}>{o.symbol}</option>)}
          </select>
          <input
            className="filter-value"
            aria-label={t('attributeTable.filterValue')}
            placeholder={t('attributeTable.filterValue')}
            value={p.filter.value}
            onChange={(e) => p.filter.onValue(e.target.value)}
            list="attr-filter-values"
            autoComplete="off"
          />
          <datalist id="attr-filter-values">
            {p.filter.suggestions.map((sg) => (
              <option key={sg.value} value={sg.value}>{`${sg.value} (${sg.count.toLocaleString()})`}</option>
            ))}
          </datalist>
          <label className="filter-on-map" title={t('attributeTable.filterOnMap')}>
            <input type="checkbox" checked={p.filter.onMap} onChange={(e) => p.filter.onOnMap(e.target.checked)} />
            <span>{t('attributeTable.filterOnMapShort')}</span>
          </label>
        </>
      </Pop>

      {p.view && (
        <Pop open={viewOpen} anchorRef={anchor('view', viewRef)} onClose={closeView} className="tb-menu" role="menu" aria-label={t('attributeUpdate.theme.label')}>
          <>
            {p.view.themes.map((th) => {
              const Icon = THEME_ICON[th];
              return (
                <React.Fragment key={th}>
                  <button
                    type="button"
                    role="menuitemradio"
                    aria-checked={th === p.view!.active}
                    className={th === p.view!.active ? 'on' : ''}
                    data-testid={`tb-view-${th}`}
                    onClick={() => {
                      p.view!.onPick(th);
                      if (th !== 'raster') setViewOpen(false);
                    }}
                  >
                    <Icon size={13} /> {t(`attributeUpdate.theme.${th}`)}
                  </button>
                  {th === 'raster' && p.view!.groups.length > 0 && (
                    <div className="tb-submenu" data-testid="analysis-groups">
                      {(['all', ...p.view!.groups] as Array<AnalysisGroup | 'all'>).map((g) => (
                        <button
                          key={g}
                          type="button"
                          role="menuitemradio"
                          aria-checked={th === p.view!.active && g === p.view!.activeGroup}
                          className={th === p.view!.active && g === p.view!.activeGroup ? 'on' : ''}
                          data-testid={`analysis-group-${g}`}
                          onClick={() => {
                            p.view!.onPick('raster');
                            p.view!.onPickGroup(g);
                            setViewOpen(false);
                          }}
                        >
                          {t(`attributeUpdate.group.${g}`)}
                        </button>
                      ))}
                    </div>
                  )}
                </React.Fragment>
              );
            })}
          </>
        </Pop>
      )}

      <Pop open={columnsOpen} anchorRef={anchor('columns', columnsRef)} onClose={closeColumns} align="right" className="column-chooser-popover" role="dialog" aria-label={t('attributeTable.columnsChooser')}>
        <>
          {p.columnsChooser.rows.map((c) => (
            <label key={c.key} className="column-chooser-row">
              <input type="checkbox" checked={c.shown} onChange={() => p.columnsChooser.onToggle(c.key)} />
              <span>{c.label}</span>
            </label>
          ))}
        </>
      </Pop>

      <Pop open={downloadOpen} anchorRef={anchor('download', downloadRef)} onClose={closeDownload} align="right" className="tb-menu" role="menu" aria-label={t('attributeTable.downloadMenu')}>
        <>
          <button type="button" onClick={() => { p.downloads.onCsv(); setDownloadOpen(false); }} title={t('attributeTable.exportCsvTitle')} aria-label={t('attributeTable.exportCsvTitle')}>
            <FileText size={13} /> {t('attributeTable.downloadCsv')}
          </button>
          <button type="button" onClick={() => { p.downloads.onGeoJson(); setDownloadOpen(false); }} title={t('attributeTable.exportGeoJsonTitle')} aria-label={t('attributeTable.exportGeoJsonTitle')}>
            <Braces size={13} /> {t('attributeTable.downloadGeoJson')}
          </button>
          <button type="button" onClick={() => { p.downloads.onCopy(); setDownloadOpen(false); }} title={t('attributeTable.copyView')} aria-label={t('attributeTable.copyView')}>
            <Copy size={13} /> {t('attributeTable.downloadCopy')}
          </button>
        </>
      </Pop>
    </div>
  );
}
