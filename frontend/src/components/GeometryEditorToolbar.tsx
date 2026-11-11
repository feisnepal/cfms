import { useMemo, type ComponentType, type CSSProperties } from 'react';
import {
  Bolt, Circle, ClipboardPaste, Copy, CopyPlus, Merge, MousePointer2, Move, Redo2,
  Route, Scissors, Spline, Square, Tag, Trash2, Undo2,
} from 'lucide-react';
import { geometryTypesForPurpose } from '../lib/purposeGeometryRules';
import { useT } from '../i18n/hooks';

// === DIAGNOSTIC: Module execution proof (DEV only) ===
const TOOLBAR_MARKER = 'TB_V10_' + Math.random().toString(36).slice(2, 6);
if (import.meta.env.DEV) {
  (window as any).__moduleMarkers = (window as any).__moduleMarkers || {};
  (window as any).__moduleMarkers['GeometryEditorToolbar'] = {
    marker: TOOLBAR_MARKER,
    time: Date.now(),
    url: import.meta.url,
  };
}

type ToolbarMode = 'select' | 'split' | 'merge' | 'move' | 'draw_polygon' | 'draw_point' | 'draw_line' | 'vertex_edit' | 'subarea_category' | null;

/** Tool + geometry pairing — represents which geometry types a feature may use. */
export type GeometryTypeId = 'Point' | 'LineString' | 'LineString' | 'Polygon' | 'MultiPolygon' | 'MultiLineString' | 'GeometryCollection';

/**
 * GD 2.2.1: draw toolbar modes a digitize purpose may use. Mirrors the
 * geometry-rule SSOT via `geometryTypesForPurpose` (inventory → point only,
 * roads → line only, water → line+polygon, other → all three).
 */
export function toolbarModesForPurpose(purpose: string): Array<Exclude<ToolbarMode, null>> {
  return geometryTypesForPurpose(purpose).map((m) =>
    m === 'point' ? 'draw_point' : m === 'line' ? 'draw_line' : 'draw_polygon',
  );
}

/**
 * UE-0.2 resolver: a button applies when the ACTIVE layer's geometry types
 * intersect the button's allowed geometry types. Empty `buttonTypes` = universal
 * (Select / Undo / Redo / Duplicate / Delete apply on every geometry layer).
 * Replaces the OLD `TOOLBAR_BUTTONS[].layerTypes` hard-coded per-layer list.
 */
export function geomAllow(geometryTypes: string[], buttonTypes: string[]): boolean {
  if (buttonTypes.length === 0) return true;
  return buttonTypes.some((g) => geometryTypes.includes(g));
}

/**
 * UE-0.2: single-point mapping of each tool id → geometry types it applies to
 * (the geometry-version of the capability matrix). Keeps button configs small.
 */
export function geometryTypesForTool(id: string): string[] {
  switch (id) {
    case 'select': return [];
    case 'split': return ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'];
    case 'merge': return ['Polygon', 'MultiPolygon'];
    // Point-only by design: dragging a whole polygon / line body is too easy to
    // do by accident and too destructive (a block, compartment or sub-area
    // silently jumps off its neighbours). Only point features can be moved.
    case 'move': return ['Point', 'MultiPoint'];
    case 'draw_polygon': return ['Polygon', 'MultiPolygon'];
    case 'draw_point': return ['Point'];
    case 'draw_line': return ['LineString', 'MultiLineString'];
    case 'vertex_edit': return ['Polygon', 'MultiPolygon', 'LineString', 'MultiLineString'];
    case 'subarea_category': return ['Polygon', 'MultiPolygon'];
    default: return [];
  }
}

interface GeometryEditorToolbarProps {
  /** Geometry types of the ACTIVE layer — ALL button visibility derives from this (UE-0.2). */
  geometryTypes: string[];
  /** Active layer identity (built-in id or `imported:<n>`) — used ONLY for the few
   * domain-specific tools (e.g. sub-area Category) that are layer-scoped, not geometry-scoped. */
  layerId?: string | null;
  toolbarMode: ToolbarMode;
  onModeChange: (mode: ToolbarMode) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  isLocked?: boolean;
  /** Why the whole structure is locked; shown instead of each tool's own
   *  tooltip (H-SUBMIT B4). Distinct from `VertexLockReason`, which is about
   *  one layer. */
  structureLockReason?: string;
  isTouchDevice?: boolean;
  selectionCount?: number;
  onFeatureTypeSelect?: (type: 'point' | 'line' | 'polygon') => void;
  onSnapToggle?: () => void;
  snapEnabled?: boolean;
  /** GD 2.2.1: purpose of the active digitize draft layer — filters draw buttons */
  activePurpose?: string | null;
  /** GD 2.2.1: true when a digitize draft/append context is active */
  isDigitizeContext?: boolean;
  /** VR-4.1: why the vertex tool is unavailable on this layer (Rule A). */
  vertexLockReason?: VertexLockReason;
  /** Copy / Paste / Paste-as-layer / Delete (feature clipboard). Wired by MapWorkspace. */
  onCopy?: () => void;
  onPaste?: () => void;
  onPasteAsLayer?: () => void;
  onDeleteSelected?: () => void;
  /** Copying is not an edit, so it stays available on a locked structure. */
  canCopy?: boolean;
  /** Tooltip for Copy, e.g. "Copy 3 selected features" / "Copy all 12 features". */
  copyTooltip?: string;
  /** Why Paste / Paste-as-layer cannot run right now (already translated); null/undefined = enabled. */
  pasteDisabledReason?: string | null;
  pasteAsLayerDisabledReason?: string | null;
  /** False = the selection cannot be deleted (nothing selected, layer not deletable, locked). */
  canDelete?: boolean;
  children?: React.ReactNode;
}

interface ToolbarButtonConfig {
  id: string;
  /** lucide icon component used for rendering (QGIS-style colored suite).
   *  Required — the old ASCII `icon` fallback was unreachable (every button
   *  defines an `Icon`, and the render always took that branch), so its
   *  glyphs had silently drifted: a PENCIL on `select`, an EJECT symbol on
   *  `move`, and a stray `'⊞s'` typo on `category`. */
  Icon: ComponentType<{ size?: number; strokeWidth?: number; className?: string; style?: CSSProperties }>;
  /** Accent color for the icon + active/hover state. */
  color: string;
  label: string;
  tooltip: string;
  shortcut?: string;
  mode: ToolbarMode;
  isToggle: boolean;
  order: number;
  /** Allowed geometry types; use `geometryTypesForTool(id)` to stay in sync. */
  geometryTypes: string[];
  /** Optional domain carve-out — only render on these layer ids (sub-area Category). */
  layerOnly?: string[];
  requiresSelection?: boolean;
  minSelection?: number;
}

/**
 * Why the vertex tool cannot be used on the active layer, or null when it can.
 *
 * `boundary_locked` is Rule A: the forest boundary is only editable while NO
 * block / compartment / sub-compartment exists.  Greying the button out with a
 * reason beats arming it onto an empty map and explaining afterwards.
 */
export type VertexLockReason = 'boundary_locked' | null;

/** i18n key for the vertex tooltip, given the active layer + lock state. */
export function vertexTooltipKey(
  layerId: string | null | undefined,
  lockReason: VertexLockReason,
): string {
  if (lockReason === 'boundary_locked') return 'editing.toolbar.editVertexTooltipLocked';
  if (layerId === 'boundary') return 'editing.toolbar.editVertexTooltipBoundary';
  if (layerId === 'blocks' || layerId === 'sub_blocks' || layerId === 'compartments' || layerId === 'sub_compartments') {
    return 'editing.toolbar.editVertexTooltipShared';
  }
  if (layerId === 'sub_areas') return 'editing.toolbar.editVertexTooltipFree';
  return 'editing.toolbar.editVertexTooltip';
}

const TOOLBAR_BUTTONS: ToolbarButtonConfig[] = [
  { id: 'select', Icon: MousePointer2, color: '#607d8b', label: 'editing.toolbar.select', tooltip: 'editing.toolbar.selectTooltip', shortcut: 'Esc', mode: 'select', isToggle: true, order: 1, geometryTypes: geometryTypesForTool('select') },
  { id: 'split', Icon: Scissors, color: '#e53935', label: 'editing.toolbar.split', tooltip: 'editing.toolbar.splitTooltip', shortcut: 'S', mode: 'split', isToggle: true, order: 10, geometryTypes: geometryTypesForTool('split'), requiresSelection: true, minSelection: 1 },
  { id: 'merge', Icon: Merge, color: '#1e88e5', label: 'editing.toolbar.merge', tooltip: 'editing.toolbar.mergeTooltip', shortcut: 'M', mode: 'merge', isToggle: true, order: 20, geometryTypes: geometryTypesForTool('merge'), requiresSelection: true, minSelection: 2 },
  { id: 'move', Icon: Move, color: '#8e24aa', label: 'editing.toolbar.move', tooltip: 'editing.toolbar.moveTooltip', shortcut: 'G', mode: 'move', isToggle: true, order: 25, geometryTypes: geometryTypesForTool('move'), requiresSelection: true, minSelection: 1 },
  { id: 'draw_polygon', Icon: Square, color: '#43a047', label: 'editing.toolbar.draw', tooltip: 'editing.toolbar.drawPolygonTooltip', shortcut: 'D', mode: 'draw_polygon', isToggle: true, order: 30, geometryTypes: geometryTypesForTool('draw_polygon') },
  { id: 'draw_point', Icon: Circle, color: '#43a047', label: 'editing.toolbar.point', tooltip: 'editing.toolbar.pointTooltip', shortcut: '1', mode: 'draw_point', isToggle: true, order: 40, geometryTypes: geometryTypesForTool('draw_point') },
  { id: 'draw_line', Icon: Route, color: '#00897b', label: 'editing.toolbar.line', tooltip: 'editing.toolbar.lineTooltip', shortcut: '2', mode: 'draw_line', isToggle: true, order: 50, geometryTypes: geometryTypesForTool('draw_line') },
  // `Spline` (a path with control handles) is the digitizing convention for a
  // node tool.  `SquarePen` — a square with a pencil — is the universal
  // "edit / rename this record" glyph and sat two buttons from draw_polygon's
  // `Square`, so the toolbar showed two near-identical square icons.
  { id: 'vertex_edit', Icon: Spline, color: '#fb8c00', label: 'editing.toolbar.vertices', tooltip: 'editing.toolbar.editVertexTooltip', shortcut: 'V', mode: 'vertex_edit', isToggle: true, order: 60, geometryTypes: geometryTypesForTool('vertex_edit') },
  { id: 'category', Icon: Tag, color: '#f9a825', label: 'editing.toolbar.category', tooltip: 'editing.toolbar.categoryTooltip', mode: 'subarea_category', isToggle: true, order: 70, geometryTypes: geometryTypesForTool('subarea_category'), layerOnly: ['sub_areas'], requiresSelection: true, minSelection: 1 },
  // Feature clipboard. Copy needs no selection (nothing selected = the whole layer);
  // Paste's availability is decided by the target layer's rules, not the selection.
  { id: 'copy', Icon: Copy, color: '#00acc1', label: 'editing.toolbar.copy', tooltip: 'editing.toolbar.copyTooltip', shortcut: 'Ctrl+C', mode: 'select', isToggle: false, order: 100, geometryTypes: geometryTypesForTool('select') },
  { id: 'paste', Icon: ClipboardPaste, color: '#00acc1', label: 'editing.toolbar.paste', tooltip: 'editing.toolbar.pasteTooltip', shortcut: 'Ctrl+V', mode: 'select', isToggle: false, order: 101, geometryTypes: geometryTypesForTool('select') },
  { id: 'paste_layer', Icon: CopyPlus, color: '#00acc1', label: 'editing.toolbar.pasteAsLayer', tooltip: 'editing.toolbar.pasteAsLayerTooltip', shortcut: 'Ctrl+Shift+V', mode: 'select', isToggle: false, order: 102, geometryTypes: geometryTypesForTool('select') },
  { id: 'delete', Icon: Trash2, color: '#d81b60', label: 'common.delete', tooltip: 'editing.toolbar.deleteTooltip', shortcut: 'Del', mode: 'select', isToggle: false, order: 110, geometryTypes: geometryTypesForTool('select'), requiresSelection: true, minSelection: 1 },
  { id: 'undo', Icon: Undo2, color: '#78909c', label: 'editing.toolbar.undo', tooltip: 'editing.toolbar.undoTooltip', shortcut: 'Ctrl+Z', mode: 'select', isToggle: false, order: 1000, geometryTypes: geometryTypesForTool('select') },
  { id: 'redo', Icon: Redo2, color: '#78909c', label: 'editing.toolbar.redo', tooltip: 'editing.toolbar.redoTooltip', shortcut: 'Ctrl+Shift+Z', mode: 'select', isToggle: false, order: 1010, geometryTypes: geometryTypesForTool('select') },
];

export function GeometryEditorToolbar(props: GeometryEditorToolbarProps) {
  const {
    geometryTypes, layerId = null, toolbarMode, onModeChange,
    canUndo, canRedo, onUndo, onRedo,
    isLocked = false, structureLockReason, isTouchDevice = false,
    selectionCount = 0, onFeatureTypeSelect,
    onSnapToggle, snapEnabled = false,
    activePurpose = null, isDigitizeContext = false,
    vertexLockReason = null,
    onCopy, onPaste, onPasteAsLayer, onDeleteSelected,
    canCopy = false, copyTooltip, pasteDisabledReason, pasteAsLayerDisabledReason, canDelete,
    children,
  } = props;

  const t = useT();

  const buttons = useMemo(() => {
    if (isDigitizeContext) {
      // GD 2.2.1: digitize drafts offer only the draw modes the purpose allows
      // (no split/merge/vertex/category — those are domain-layer tools).
      const modeSet = new Set<ToolbarMode>(toolbarModesForPurpose(activePurpose || ''));
      return TOOLBAR_BUTTONS
        .filter((btn) => modeSet.has(btn.mode))
        .sort((a, b) => a.order - b.order);
    }
    // UE-0.2: geometry-driven — replace the old `layerTypes.includes(...)` gate
    // with `geomAllow` (capability based, layer-agnostic). A rare domain carve-out
    // (`layerOnly`) still applies for sub-area Category.
    return TOOLBAR_BUTTONS
      .filter((btn) => geomAllow(geometryTypes, btn.geometryTypes))
      .filter((btn) => !btn.layerOnly || (layerId ? btn.layerOnly.includes(layerId) : false))
      .sort((a, b) => a.order - b.order);
  }, [geometryTypes, activePurpose, isDigitizeContext, layerId]);

  const isDisabled = (btn: ToolbarButtonConfig): boolean => {
    // Copying changes nothing, so it must keep working on a locked structure.
    if (btn.id === 'copy') return !canCopy;
    if (isLocked) return true;
    if (btn.id === 'paste') return !onPaste || !!pasteDisabledReason;
    if (btn.id === 'paste_layer') return !onPasteAsLayer || !!pasteAsLayerDisabledReason;
    if (btn.id === 'delete' && (!onDeleteSelected || canDelete === false)) return true;
    // Rule A — the boundary is locked once any structural layer exists.
    if (btn.id === 'vertex_edit' && vertexLockReason) return true;
    if (btn.requiresSelection && selectionCount < (btn.minSelection || 1)) return true;
    if (btn.id === 'undo' && !canUndo) return true;
    if (btn.id === 'redo' && !canRedo) return true;
    return false;
  };

  /** Tooltip text + shortcut.  The shortcut is appended here and MUST NOT be
   *  baked into the i18n string as well — `selectTooltip` used to carry its
   *  own "(Esc)" and rendered as "… (Esc) (Esc)". */
  const tooltipOf = (btn: ToolbarButtonConfig): string => {
    // A disabled control that does not say why is just a broken one. When the
    // whole structure is frozen, the reason is the same for every tool and it
    // is more useful than "Draw polygon".
    // Paste explains itself: the reason is about the *target layer's* rules
    // (or an empty clipboard), which a generic "structure locked" would hide.
    if (btn.id === 'paste' && pasteDisabledReason) return pasteDisabledReason;
    if (btn.id === 'paste_layer' && pasteAsLayerDisabledReason) return pasteAsLayerDisabledReason;
    if (btn.id === 'copy' && copyTooltip) return `${copyTooltip} (${btn.shortcut})`;
    if (btn.id !== 'copy' && structureLockReason && isDisabled(btn)) return structureLockReason;
    const key = btn.id === 'vertex_edit' ? vertexTooltipKey(layerId, vertexLockReason) : btn.tooltip;
    const text = t(key);
    return btn.shortcut ? `${text} (${btn.shortcut})` : text;
  };

  const handleClick = (btn: ToolbarButtonConfig) => {
    if (isDisabled(btn)) return;
    if (btn.id === 'undo') { onUndo(); return; }
    if (btn.id === 'redo') { onRedo(); return; }
    if (btn.id === 'copy') { onCopy?.(); return; }
    if (btn.id === 'paste') { onPaste?.(); return; }
    if (btn.id === 'paste_layer') { onPasteAsLayer?.(); return; }
    if (btn.id === 'delete') { onDeleteSelected?.(); return; }
    if (btn.isToggle) {
      onModeChange(toolbarMode === btn.mode ? null : btn.mode);
    }
    if (['draw_point', 'draw_line', 'draw_polygon'].includes(btn.id) && onFeatureTypeSelect) {
      const typeMap: Record<string, 'point' | 'line' | 'polygon'> = {
        draw_point: 'point',
        draw_line: 'line',
        draw_polygon: 'polygon',
      };
      onFeatureTypeSelect(typeMap[btn.id] || 'polygon');
    }
  };

  return (
    <div
      className={`geometry-toolbar ${isTouchDevice ? 'toolbar-vertical' : ''}`}
      role="toolbar"
      aria-label={isDigitizeContext ? t('editing.toolbar.digitizeAria') : t('editing.toolbar.editAria', { types: geometryTypes.join('/') })}
    >
      {buttons.map(btn => (
        <button
          key={btn.id}
          className={`toolbar-btn ${toolbarMode === btn.mode ? 'active' : ''} ${isDisabled(btn) ? 'disabled' : ''}`}
          onClick={() => handleClick(btn)}
          disabled={isDisabled(btn)}
          aria-label={t(btn.label)}
          aria-pressed={btn.isToggle ? toolbarMode === btn.mode : undefined}
          title={tooltipOf(btn)}
          style={{ '--tool-accent': btn.color } as CSSProperties}
        >
          <btn.Icon size={18} strokeWidth={2} className="toolbar-icon" style={{ color: btn.color }} />
          <span className="toolbar-label">{t(btn.label)}</span>
        </button>
      ))}
      {onSnapToggle && geometryTypes.some((g) => g === 'LineString' || g === 'MultiLineString') && (
        <button
          className={`toolbar-btn ${snapEnabled ? 'active' : ''}`}
          onClick={onSnapToggle}
          aria-label={t(snapEnabled ? 'editing.toolbar.snapAriaEnabled' : 'editing.toolbar.snapAriaDisabled')}
          aria-pressed={snapEnabled}
          title={t('editing.toolbar.snapTitle')}
          style={{ '--tool-accent': '#f9a825' } as CSSProperties}
        >
          <Bolt size={18} strokeWidth={2} className="toolbar-icon" style={{ color: '#f9a825' }} />
          <span className="toolbar-label">{t(snapEnabled ? 'editing.toolbar.snapOn' : 'editing.toolbar.snapOff')}</span>
        </button>
      )}
      {children && <span className="toolbar-separator" />}
      {children}
    </div>
  );
}

export default GeometryEditorToolbar;