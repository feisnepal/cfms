import { useState } from 'react';
import { Modal } from 'antd';
import { useT } from '../i18n/hooks';
import { readDetail } from '../hooks/useErrorHandler';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useDimensionLabels } from '../hooks/useDimensionLabels';
import { DfoReviewPanel } from './DfoReviewPanel';
import { ExportButton } from './ExportButton';
import { UnsavedEditBar } from './UnsavedEditBar';
import AddDataButton from './AddDataButton';
import DownloadTemplateButton from './DownloadTemplateButton';
import { authHeaders } from '../lib/geometryUndo';

interface WorkspaceHeaderProps {
  forestName: string;
  dimensionMode: 'compartment' | 'block';
  onDimensionToggle: () => void;
  panels?: { id: string; label: string; icon?: string; visible: boolean }[];
  onTogglePanel?: (id: string) => void;
  /** Whether the forest already has a boundary — drives the "Add data" gate. */
  hasBoundary?: boolean;
  /** Open the Yearly plan table (a button is shown when this is given). Works without the Activity Features layer. */
  onOpenYearlyPlan?: () => void;
}

const PANELS_OPEN_KEY = 'cfms.workspace.headerPanelsOpen';

const STATUS_COLORS: Record<string, string> = {
  draft: '#6b7280',
  submitted: '#f59e0b',
  calculating: '#3b82f6',
  retrying: '#f97316',
  failed: '#ef4444',
  completed: '#22c55e',
  locked: '#8b5cf6',
};

export function WorkspaceHeader({ forestName, dimensionMode, onDimensionToggle, panels = [], onTogglePanel, hasBoundary = false, onOpenYearlyPlan }: WorkspaceHeaderProps) {
  const t = useT();
  const labels = useDimensionLabels({ hasCompartments: dimensionMode === 'compartment' });
  const mapLifecycleStatus = useWorkspaceStore((s) => s.mapLifecycleStatus);
  const setMapLifecycleStatus = useWorkspaceStore((s) => s.setMapLifecycleStatus);
  const setStructureLocked = useWorkspaceStore((s) => s.setStructureLocked);
  const structureLocked = useWorkspaceStore((s) => s.structureLocked);
  const calculationId = useWorkspaceStore((s) => s.calculationId);
  const focusMode = useWorkspaceStore((s) => s.focusMode);
  const toggleFocusMode = useWorkspaceStore((s) => s.toggleFocusMode);
  const [dfoPanelOpen, setDfoPanelOpen] = useState(false);
  // The panel buttons (Basemap, Imported Layers, Raster Layers, Attribute Table, Legend, Yearly plan) sit behind the single
  // "Layers" button: they took a lot of header space for things used now and then. Remembered per browser, closed by default.
  const [panelsOpen, setPanelsOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem(PANELS_OPEN_KEY) === '1';
    } catch {
      return false;
    }
  });
  const togglePanelButtons = () => {
    const next = !panelsOpen;
    setPanelsOpen(next);
    try {
      localStorage.setItem(PANELS_OPEN_KEY, next ? '1' : '0');
    } catch {
      /* storage unavailable: the choice just is not remembered */
    }
    // If the Layers panel itself was hidden, this is also the way back to it.
    const layers = panels.find((p) => p.id === 'layers');
    if (layers && !layers.visible) onTogglePanel?.('layers');
  };
  const layersPanel = panels.find((p) => p.id === 'layers');
  const otherPanels = panels.filter((p) => p.id !== 'layers');

  const statusLabels: Record<string, string> = {
    draft: t('status.lifecycle.draft'),
    submitted: t('status.lifecycle.submitted'),
    calculating: t('status.lifecycle.calculating'),
    retrying: t('status.lifecycle.retrying'),
    failed: t('status.lifecycle.failed'),
    completed: t('status.lifecycle.completed'),
    locked: t('status.lifecycle.locked'),
  };

  // H-SUBMIT B2. Submitting freezes the map, and a consequence the user is not
  // told about is one they will experience as the app breaking. The dialog
  // names what becomes true rather than asking "are you sure?" — a
  // confirmation that does not state its consequence just trains people to
  // click through it.
  const [confirmOpen, setConfirmOpen] = useState(false);

  const doSubmit = async () => {
    setConfirmOpen(false);
    await handleSubmit();
  };

  const handleSubmit = async () => {
    if (!calculationId) return;
    try {
      const res = await fetch(`/api/calculations/${calculationId}/submit-for-calculation`, { method: 'POST', headers: authHeaders() });
      if (!res.ok) { const err = await res.json(); alert(readDetail(err.detail, err.correlation_id) || t('workspace.header.submitFailed')); return; }
      const data = await res.json();
      setMapLifecycleStatus(data.map_lifecycle_status);
      // The server froze the map; reflect it immediately rather than waiting
      // for the next refetch, or the toolbar stays enabled and the first edit
      // fails with a 423 instead of being disabled.
      if (data.structure_locked) setStructureLocked(true);
    } catch { alert(t('generalErrors.networkError')); }
  };

  // H-SUBMIT A3. Submitting now freezes the map, so the owner needs a way back
  // while analysis has not started. Shown only at `submitted`; the server
  // refuses with 409 once the state moves on, which is the authority — this
  // button is the convenience, not the guard.
  const handleWithdraw = async () => {
    if (!calculationId) return;
    try {
      const res = await fetch(`/api/calculations/${calculationId}/withdraw-submission`, { method: 'POST', headers: authHeaders() });
      if (!res.ok) { const err = await res.json(); alert(readDetail(err.detail, err.correlation_id) || t('workspace.header.withdrawFailed')); return; }
      const data = await res.json();
      setMapLifecycleStatus(data.map_lifecycle_status);
      setStructureLocked(false);
    } catch { alert(t('generalErrors.networkError')); }
  };

  const handleUnlock = async () => {
    if (!calculationId) return;
    const reason = prompt(t('workspace.header.unlockReasonPrompt'));
    if (reason === null) return;
    try {
      const res = await fetch(`/api/calculations/${calculationId}/super-admin-unlock`, { method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/x-www-form-urlencoded' }, body: `reason=${encodeURIComponent(reason)}` });
      if (!res.ok) { const err = await res.json(); alert(readDetail(err.detail, err.correlation_id) || t('workspace.header.unlockFailed')); return; }
      setMapLifecycleStatus('draft');
    } catch { alert(t('generalErrors.networkError')); }
  };

  // H-SUBMIT B3. Which sentence depends on WHY it is frozen: at `submitted`
  // the owner can undo it themselves, from `calculating` onward they cannot.
  // A banner that says only "read-only" leaves them with nowhere to go.
  const frozenMessage = !structureLocked
    ? null
    : mapLifecycleStatus === 'submitted'
      ? t('workspace.header.frozenSubmitted')
      : mapLifecycleStatus === 'calculating' || mapLifecycleStatus === 'retrying'
        ? t('workspace.header.frozenCalculating')
        : mapLifecycleStatus === 'locked'
          ? t('workspace.header.frozenLocked')
          : t('workspace.header.frozenGeneric');

  // Inside the revealed group when there are panel buttons; on its own when the host passes none.
  const yearlyPlanButton = onOpenYearlyPlan ? (
    <button
      type="button"
      className="panel-toggle-btn"
      data-testid="open-yearly-plan"
      onClick={onOpenYearlyPlan}
      title={t('yearlyPlan.planTable.openButtonTitle') as string}
      aria-label={t('yearlyPlan.planTable.openButtonTitle') as string}
      style={{ marginRight: panels.length === 0 ? 8 : 0, whiteSpace: 'nowrap' }}
    >
      <span className="panel-toggle-label">{t('yearlyPlan.planTable.openButton')}</span>
    </button>
  ) : null;

  return (
    <div className="workspace-header" role="banner">
      <div className="workspace-header-left">
        <h1 className="workspace-title">{forestName}</h1>
        <button
          className="dimension-toggle-btn"
          onClick={onDimensionToggle}
          aria-label={t('workspace.header.switchToDimension', { name: labels.other })}
          title={t('workspace.header.dimensionToggleTitle', { current: labels.current, other: labels.other })}
        >
          {labels.current}
        </button>
        <span
          className="lifecycle-badge"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 4,
            padding: '2px 10px',
            borderRadius: 12,
            fontSize: 12,
            fontWeight: 600,
            color: '#fff',
            backgroundColor: STATUS_COLORS[mapLifecycleStatus] ?? '#6b7280',
            marginLeft: 12,
          }}
        >
          {statusLabels[mapLifecycleStatus] ?? mapLifecycleStatus}
        </span>
      </div>
      <div className="workspace-header-right">
        {frozenMessage && (
          <div className="workspace-frozen-banner" role="status" aria-live="polite"
               data-testid="frozen-banner"
               style={{
                 background: '#fff7e6', border: '1px solid #ffd591', color: '#874d00',
                 padding: '6px 12px', borderRadius: 4, fontSize: 13, marginRight: 8,
               }}>
            🔒 {frozenMessage}
          </div>
        )}

        <UnsavedEditBar />
        {panels.length > 0 && (
          <div className="workspace-panel-toggles" role="group" aria-label={t('workspace.header.togglePanelsLabel')}>
            <button
              type="button"
              className={`panel-toggle-btn ${layersPanel?.visible ? 'active' : ''}`}
              data-testid="panel-toggles-disclosure"
              onClick={togglePanelButtons}
              aria-expanded={panelsOpen}
              title={panelsOpen ? t('workspace.header.lessPanels') : t('workspace.header.morePanels')}
              aria-label={`${layersPanel?.label ?? t('workspace.layers')} — ${panelsOpen ? t('workspace.header.lessPanels') : t('workspace.header.morePanels')}`}
            >
              <span className="panel-toggle-icon" aria-hidden="true">{layersPanel?.icon ?? '▤'}</span>
              <span className="panel-toggle-label">{layersPanel?.label ?? t('workspace.layers')}</span>
              <span className="panel-toggle-icon" aria-hidden="true">{panelsOpen ? '◂' : '▸'}</span>
            </button>
            {panelsOpen && otherPanels.map((panel) => (
              <button
                key={panel.id}
                type="button"
                className={`panel-toggle-btn ${panel.visible ? 'active' : ''}`}
                onClick={() => onTogglePanel?.(panel.id)}
                aria-pressed={panel.visible}
                title={panel.visible ? t('workspace.header.hidePanel', { name: panel.label }) : t('workspace.header.showPanel', { name: panel.label })}
                aria-label={panel.visible ? t('workspace.header.hidePanel', { name: panel.label }) : t('workspace.header.showPanel', { name: panel.label })}
              >
                {panel.icon && <span className="panel-toggle-icon" aria-hidden="true">{panel.icon}</span>}
                <span className="panel-toggle-label">{panel.label}</span>
              </button>
            ))}
            {panelsOpen && yearlyPlanButton}
          </div>
        )}
        {panels.length === 0 && yearlyPlanButton}
        {calculationId && !structureLocked && (
          <div className="add-data-action" style={{ marginRight: 8 }}>
            <AddDataButton
              calculationId={calculationId}
              hasBoundary={hasBoundary}
              buttonType="default"
              size="small"
            />
          </div>
        )}
        {calculationId && !structureLocked && (
          <div className="download-template-action" style={{ marginRight: 8 }}>
            <DownloadTemplateButton />
          </div>
        )}
        <ExportButton forestName={forestName} />
        <div className="lifecycle-actions" style={{ display: 'flex', gap: 6, marginRight: 8 }}>
          {mapLifecycleStatus === 'draft' && (
            <button
              className="action-btn"
              onClick={() => setConfirmOpen(true)}
              title={t('workspace.header.submitForReviewTitle')}
              aria-label={t('workspace.header.submit')}
            >
              📤
            </button>
          )}
          {mapLifecycleStatus === 'submitted' && (
            <>
              <button
                className="action-btn"
                onClick={handleWithdraw}
                title={t('workspace.header.withdrawTitle')}
                aria-label={t('workspace.header.withdraw')}
              >
                ↩
              </button>
              <button
                className="action-btn"
                onClick={() => setDfoPanelOpen(true)}
                title={t('workspace.header.openReviewTitle')}
                aria-label={t('workspace.header.review')}
              >
                👁
              </button>
            </>
          )}
          {mapLifecycleStatus === 'locked' && (
            <button
              className="action-btn unlock-btn"
              onClick={handleUnlock}
              title={t('workspace.header.unlockTitle')}
              aria-label={t('workspace.header.unlock')}
            >
              🔓
            </button>
          )}
        </div>
        <button
          className={`focus-mode-btn ${focusMode ? 'active' : ''}`}
          onClick={toggleFocusMode}
          aria-label={focusMode ? t('workspace.header.exitFocusMode') : t('workspace.header.enterFocusMode')}
          title={focusMode ? t('workspace.header.exitFocusModeTitle') : t('workspace.header.enterFocusModeTitle')}
          aria-pressed={focusMode}
        >
          {focusMode ? '⛶' : '⛶'}
        </button>
        <button className="close-btn" onClick={() => window.history.back()} aria-label={t('workspace.header.closeWorkspace')}>
          ×
        </button>
      </div>

      {calculationId && (
        <DfoReviewPanel
          open={dfoPanelOpen}
          onClose={() => setDfoPanelOpen(false)}
          calculationId={calculationId}
        />
      )}

      <Modal
        open={confirmOpen}
        title={t('workspace.header.confirmTitle')}
        width={520}
        okText={t('workspace.header.confirmOk')}
        cancelText={t('workspace.header.confirmCancel')}
        onOk={doSubmit}
        onCancel={() => setConfirmOpen(false)}
        data-testid="submit-confirm"
      >
        <p>{t('workspace.header.confirmLead')}</p>
        <ul style={{ paddingLeft: 18, margin: '8px 0' }}>
          <li>{t('workspace.header.confirmFreeze')}</li>
          <li>{t('workspace.header.confirmViewable')}</li>
          <li>{t('workspace.header.confirmWithdraw')}</li>
        </ul>
      </Modal>
    </div>
  );
}