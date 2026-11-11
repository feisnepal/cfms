/**
 * CalculationHeader — forest identity, lifecycle status badge, structure-lock
 * badge, and conditionally-rendered actions (Phase 3, Tabbed Calculation Detail).
 *
 * Actions are rendered only when the corresponding `can.*` boolean is true; the
 * underlying pieces never hide via CSS.
 */
/* eslint-disable react/prop-types -- typed via CalculationHeaderProps (React.FC generic); the rule is a false positive for TS function components */
import { Badge, Tag, Space } from 'antd';
import { Keyboard, ChevronUp } from 'lucide-react';
import type { Calculation } from '../types';
import type { PermissionGateCan } from '../hooks/usePermissionGate';
import { useT } from '../i18n/hooks';

const STATUS_LABELS: Record<string, string> = {
  draft: 'status.lifecycle.draft',
  submitted: 'status.lifecycle.submitted',
  calculating: 'status.lifecycle.calculating',
  retrying: 'status.lifecycle.retrying',
  failed: 'status.lifecycle.failed',
  completed: 'status.lifecycle.completed',
  locked: 'status.lifecycle.locked',
};

const STATUS_COLORS: Record<string, string> = {
  draft: 'default',
  submitted: 'gold',
  calculating: 'blue',
  retrying: 'orange',
  failed: 'red',
  completed: 'green',
  locked: 'purple',
};

export interface CalculationHeaderProps {
  calculation: Pick<Calculation, 'id' | 'forest_name' | 'block_name' | 'status'> | null;
  can: PermissionGateCan;
  isLocked: boolean;
  lifecycleStatus?: string;
  onEdit?: () => void;
  onDelete?: () => void;
  onReanalyze?: () => void;
  onShowShortcuts?: () => void;
  /** Fold the shell header into a slim strip. */
  onToggleChrome?: () => void;
  /**
   * Drop the identity line (name + status) — used on a map surface where
   * `WorkspaceHeader` already shows it, so the shell doesn't stack it twice.
   */
  titleHidden?: boolean;
}

export const CalculationHeader: React.FC<CalculationHeaderProps> = ({
  calculation,
  can,
  isLocked,
  lifecycleStatus = 'draft',
  onEdit,
  onDelete,
  onReanalyze,
  onShowShortcuts,
  onToggleChrome,
  titleHidden = false,
}) => {
  const t = useT();
  const name = calculation?.forest_name || calculation?.block_name || t('calc.untitledCalculation');
  const blockName = calculation?.block_name;

  return (
    <header className={`calc-header${titleHidden ? ' calc-header--actions-only' : ''}`}>
      {!titleHidden && (
        <div className="calc-header-title">
          <h1>{name}</h1>
          <Space size={6}>
            <Tag color={STATUS_COLORS[lifecycleStatus] || 'default'}>
              {STATUS_LABELS[lifecycleStatus] ? t(STATUS_LABELS[lifecycleStatus]) : lifecycleStatus}
            </Tag>
            {isLocked && <Badge status="processing" text={t('calc.structureLocked')} />}
            {blockName && name !== blockName && <Tag>{blockName}</Tag>}
          </Space>
        </div>
      )}

      <div className="calc-header-actions">
        {onToggleChrome && (
          <button
            type="button"
            className="calc-action-btn calc-action-btn--icon"
            onClick={onToggleChrome}
            aria-label={t('calc.chrome.collapse')}
            title={t('calc.chrome.collapse')}
          >
            <ChevronUp size={15} aria-hidden="true" />
          </button>
        )}
        {onShowShortcuts && (
          <button
            type="button"
            className="calc-action-btn calc-action-btn--icon"
            onClick={onShowShortcuts}
            aria-label={t('workspace.shortcuts.title')}
            title={t('workspace.shortcuts.title')}
          >
            <Keyboard size={15} aria-hidden="true" />
          </button>
        )}
        {onReanalyze && (
          <button
            type="button"
            className="calc-action-btn"
            onClick={onReanalyze}
            aria-label={t('calc.reanalyze.action')}
          >
            {t('calc.reanalyze.action')}
          </button>
        )}
        {can.showEditTools && onEdit && (
          <button
            type="button"
            className="calc-action-btn"
            onClick={onEdit}
            aria-label={t('calc.editCalculation')}
          >
            {t('common.edit')}
          </button>
        )}
        {can.showDeleteButton && onDelete && (
          <button
            type="button"
            className="calc-action-btn calc-action-btn--danger"
            onClick={onDelete}
            aria-label={t('calc.deleteCalculation')}
          >
            {t('common.delete')}
          </button>
        )}
      </div>
    </header>
  );
};

export default CalculationHeader;
