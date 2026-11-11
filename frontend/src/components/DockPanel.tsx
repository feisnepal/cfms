import { forwardRef, useImperativeHandle, type ReactNode } from 'react';
import { useT } from '../i18n/hooks';
import { Panel, usePanelRef } from 'react-resizable-panels';
import type { PanelSize } from 'react-resizable-panels';

export interface DockPanelHandle {
  collapse: () => void;
  expand: () => void;
  isCollapsed: () => boolean;
}

interface DockPanelProps {
  id: string;
  title: string;
  icon?: string;
  actions?: ReactNode;
  /** Reserve a slot in the title bar that a child can fill with a portal (`#dock-toolbar-<id>`), e.g. the attribute table's toolbar. */
  toolbarSlot?: boolean;
  defaultSize?: number | string;
  minSize?: number | string;
  collapsible?: boolean;
  className?: string;
  bodyClassName?: string;
  onResize?: (size: PanelSize, id: string) => void;
  onCollapseChange?: (id: string, collapsed: boolean) => void;
  onCollapseToggle?: (id: string) => void;
  children: ReactNode;
}

/**
 * A single resizable dock panel: title bar with collapse toggle + body.
 * Wraps react-resizable-panels' Panel and exposes an imperative handle so
 * the workspace header can show/hide it.
 */
export const DockPanel = forwardRef<DockPanelHandle, DockPanelProps>(function DockPanel(
  {
    id,
    title,
    icon,
    actions,
    toolbarSlot,
    defaultSize,
    minSize = 10,
    collapsible = true,
    className,
    bodyClassName,
    onResize,
    onCollapseChange,
    onCollapseToggle,
    children,
  },
  ref,
) {
  const panelRef = usePanelRef();
  const t = useT();

  useImperativeHandle(
    ref,
    () => ({
      collapse: () => panelRef.current?.collapse(),
      expand: () => panelRef.current?.expand(),
      isCollapsed: () => panelRef.current?.isCollapsed() ?? false,
    }),
    [panelRef],
  );

  const handleResize = (
    size: PanelSize,
    panelId: string | number | undefined,
    _prev?: PanelSize,
  ) => {
    if (panelId === undefined) return;
    const idStr = String(panelId);
    if (onResize) onResize(size, idStr);
    if (onCollapseChange) onCollapseChange(idStr, size.asPercentage <= 0.5);
  };

  return (
    <Panel
      id={id}
      collapsible={collapsible}
      collapsedSize={0}
      defaultSize={defaultSize}
      minSize={minSize}
      panelRef={panelRef}
      onResize={handleResize}
      className={`dock-panel ${className ?? ''}`}
    >
      <div className="dock-panel-inner">
        <div className="dock-panel-header">
          {icon && (
            <span className="dock-panel-icon" aria-hidden="true">
              {icon}
            </span>
          )}
          <span className="dock-panel-title">{title}</span>
          {toolbarSlot && <span className="dock-panel-toolbar" id={`dock-toolbar-${id}`} />}
          {actions && <span className="dock-panel-actions">{actions}</span>}
          <button
            type="button"
            className="dock-panel-collapse-btn"
            onClick={(e) => {
              e.stopPropagation();
              if (onCollapseToggle) {
                onCollapseToggle(id);
                return;
              }
              const handle = panelRef.current;
              if (!handle) return;
              const wasCollapsed = handle.isCollapsed();
              if (wasCollapsed) handle.expand();
              else handle.collapse();
              onCollapseChange?.(id, !wasCollapsed);
            }}
            aria-label={t('workspace.dock.collapseToggle', { panel: title })}
            title={t('workspace.dock.collapsePanel')}
          >
            ‒
          </button>
        </div>
        <div className={`dock-panel-body ${bodyClassName ?? ''}`}>{children}</div>
      </div>
    </Panel>
  );
});

export default DockPanel;
