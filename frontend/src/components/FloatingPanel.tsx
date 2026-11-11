/** A panel that floats over its positioned parent: drag it by the header, collapse it, close it. Clicking anywhere on it
 *  raises it above every other floating panel. Controlled (position / collapsed come from the caller), so the caller
 *  decides where the state is kept. */
import { useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { clampPosition, type PanelPosition } from '../lib/forestSummary';

// One counter for every floating panel: the one touched last is on top. Above Leaflet's controls (1000) and the
// workspace banners (500), below modal dialogs.
let topZ = 1100;
const nextZ = (): number => (topZ += 1);

export interface FloatingPanelProps {
  title: ReactNode;
  position: PanelPosition;
  onPositionChange: (p: PanelPosition) => void;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onClose: () => void;
  children: ReactNode;
  testId?: string;
  width?: number;
  labels?: { collapse: string; expand: string; close: string; move: string };
  /** Float over the whole window (rendered in the page body, above every other panel) instead of inside the map area. */
  viewport?: boolean;
  /** Fixed height (px) once the user has dragged the corner; with `onResize` a grip appears in the bottom-right corner. */
  height?: number | null;
  onResize?: (size: { width: number; height: number }) => void;
  resizeLabel?: string;
}

const DEFAULT_LABELS = { collapse: 'Collapse', expand: 'Expand', close: 'Close', move: 'Move (drag, or use the arrow keys)' };
const KEY_STEP = 16;

export function FloatingPanel({
  title, position, onPositionChange, collapsed, onCollapsedChange, onClose, children, testId = 'floating-panel',
  width = 372, labels = DEFAULT_LABELS, viewport = false, height = null, onResize, resizeLabel,
}: FloatingPanelProps) {
  const ref = useRef<HTMLDivElement>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ startX: number; startY: number; origin: PanelPosition } | null>(null);
  const [z, setZ] = useState(() => nextZ());

  const clamp = (p: PanelPosition): PanelPosition => {
    const parent = ref.current?.offsetParent as HTMLElement | null;
    if (!viewport && !parent) return p;
    return clampPosition(
      p, viewport ? { width: window.innerWidth, height: window.innerHeight } : { width: parent!.clientWidth, height: parent!.clientHeight }, { width: ref.current?.offsetWidth ?? width },
      headerRef.current?.offsetHeight ?? 40,
    );
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('button')) return;
    drag.current = { startX: e.clientX, startY: e.clientY, origin: position };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    onPositionChange(clamp({ x: d.origin.x + e.clientX - d.startX, y: d.origin.y + e.clientY - d.startY }));
  };
  const endDrag = () => {
    drag.current = null;
  };
  const grip = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const onGripDown = (e: PointerEvent<HTMLDivElement>) => {
    e.stopPropagation();
    grip.current = { x: e.clientX, y: e.clientY, w: ref.current?.offsetWidth ?? width, h: ref.current?.offsetHeight ?? 300 };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const onGripMove = (e: PointerEvent<HTMLDivElement>) => {
    const g = grip.current;
    if (!g || !onResize) return;
    const maxW = (viewport ? window.innerWidth : ref.current?.offsetParent?.clientWidth ?? window.innerWidth) - position.x - 8;
    const maxH = (viewport ? window.innerHeight : ref.current?.offsetParent?.clientHeight ?? window.innerHeight) - position.y - 8;
    onResize({ width: Math.max(300, Math.min(maxW, g.w + e.clientX - g.x)), height: Math.max(160, Math.min(maxH, g.h + e.clientY - g.y)) });
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: [-KEY_STEP, 0], ArrowRight: [KEY_STEP, 0], ArrowUp: [0, -KEY_STEP], ArrowDown: [0, KEY_STEP] }[e.key];
    if (!step) return;
    e.preventDefault();
    onPositionChange(clamp({ x: position.x + step[0], y: position.y + step[1] }));
  };

  const panel = (
    <div
      ref={ref}
      className={`floating-panel${collapsed ? ' floating-panel--collapsed' : ''}${height && !collapsed ? ' floating-panel--sized' : ''}`}
      style={{ left: position.x, top: position.y, width, ...(height && !collapsed ? { height } : {}), zIndex: viewport ? z + 1000 : z, ...(viewport ? { position: 'fixed' as const } : {}) }}
      data-testid={testId}
      role="dialog"
      aria-label={typeof title === 'string' ? title : undefined}
      onPointerDownCapture={() => setZ(nextZ())}
    >
      <div
        ref={headerRef}
        className="floating-panel__header"
        tabIndex={0}
        title={labels.move}
        data-testid={`${testId}-header`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={onKeyDown}
      >
        <button
          type="button"
          className="floating-panel__icon"
          aria-expanded={!collapsed}
          aria-label={collapsed ? labels.expand : labels.collapse}
          onClick={() => onCollapsedChange(!collapsed)}
        >
          <span aria-hidden="true" className="floating-panel__chevron">▾</span>
        </button>
        <div className="floating-panel__title">{title}</div>
        <button type="button" className="floating-panel__icon" aria-label={labels.close} onClick={onClose}>
          <span aria-hidden="true">✕</span>
        </button>
      </div>
      {!collapsed && <div className="floating-panel__body">{children}</div>}
      {!collapsed && onResize && (
        <div
          className="floating-panel__grip"
          data-testid={`${testId}-grip`}
          role="separator"
          aria-label={resizeLabel}
          title={resizeLabel}
          onPointerDown={onGripDown}
          onPointerMove={onGripMove}
          onPointerUp={() => { grip.current = null; }}
          onPointerCancel={() => { grip.current = null; }}
        />
      )}
    </div>
  );
  return viewport ? createPortal(panel, document.body) : panel;
}
