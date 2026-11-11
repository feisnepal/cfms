/**
 * What the user group step still needs from the user (owner, 2026-10-11): the household data (a list, or just the totals) and the
 * committee. The step is only useful when the user pays attention to entering them, so the system reminds instead of waiting
 * silently. Advisory only: nothing here blocks anything, and once everything is there it shrinks to one line.
 */
import React from 'react';
import { Alert, Button } from 'antd';
import { useT } from '../../i18n/hooks';

export interface UserGroupChecklistProps {
  /** household rows OR a totals-only summary exist */
  hasHouseholds: boolean;
  /** members of the main user committee (the committee's own name list) */
  mainCommitteeCount: number;
  /** members of the advisory + financial committees (informational: not every group has them) */
  otherCommitteeCount: number;
  /** null until the committees have loaded, so the reminder does not flash before the answer is known */
  committeesLoaded: boolean;
  onGoHouseholds: () => void;
  onGoCommittee: () => void;
}

export function UserGroupChecklist(p: UserGroupChecklistProps) {
  const t = useT();
  if (!p.committeesLoaded) return null;

  const missing: { key: string; text: string; go: () => void }[] = [];
  if (!p.hasHouseholds) missing.push({ key: 'households', text: t('household.checklist.households'), go: p.onGoHouseholds });
  if (p.mainCommitteeCount === 0) missing.push({ key: 'committee', text: t('household.checklist.committee'), go: p.onGoCommittee });
  const otherMissing = p.mainCommitteeCount > 0 && p.otherCommitteeCount === 0;

  if (missing.length === 0 && !otherMissing) {
    return <div className="text-xs text-green-700 mb-2" data-testid="user-group-checklist-done">{t('household.checklist.allDone')}</div>;
  }

  return (
    <Alert
      type={missing.length > 0 ? 'warning' : 'info'}
      showIcon
      style={{ marginBottom: 12 }}
      data-testid="user-group-checklist"
      message={t('household.checklist.title')}
      description={
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {missing.map((m) => (
            <li key={m.key} data-testid={`checklist-${m.key}`}>
              {m.text}{' '}
              <Button type="link" size="small" style={{ padding: 0 }} onClick={m.go}>{t('household.checklist.enter')}</Button>
            </li>
          ))}
          {otherMissing && (
            <li data-testid="checklist-other">
              {t('household.checklist.otherCommittees')}{' '}
              <Button type="link" size="small" style={{ padding: 0 }} onClick={p.onGoCommittee}>{t('household.checklist.enter')}</Button>
            </li>
          )}
        </ul>
      }
    />
  );
}

export default UserGroupChecklist;
