import React, { useCallback, useState } from 'react';
import { Button, Modal, Tag, Typography } from 'antd';
import type { TFunction } from 'i18next';
import { useT } from '../../i18n/hooks';
import { yearlyPlanApi, type PlanHealthItem, type YearlyPlanHealth } from '../../services/api';
import { isYearlyPlanGuidanceEnabled } from '../../config/featureFlags';
import { describeIssue } from './planMessages';

const { Text } = Typography;

/** What is being done when the check runs: it only changes the words on the buttons and the title. */
export type PlanCheckAction = 'create' | 'export';

export interface PlanCheckRow {
  key: string;
  /** the activity the row is about; null for a row about the whole plan */
  activityId: string | null;
  activity: string | null;
  state?: PlanHealthItem['state'];
  text: string;
}

/**
 * The things worth a second look before the plan is turned into a document or a file (plan §4.3): every activity
 * that still needs something, an empty plan, and a cost-benefit analysis that no longer matches the plan. The same
 * server health document the Next-step card and the checklist read, so the three can never disagree.
 */
export function planCheckRows(health: YearlyPlanHealth, t: TFunction): PlanCheckRow[] {
  const rows: PlanCheckRow[] = [];
  if (health.items.length === 0) {
    rows.push({ key: 'empty', activityId: null, activity: null, text: t('yearlyPlan.check.emptyPlan') as string });
  }
  for (const item of health.items) {
    if (item.state === 'ready' || item.issues.length === 0) continue;
    rows.push({
      key: item.activity_id,
      activityId: item.activity_id,
      activity: item.activity,
      state: item.state,
      text: describeIssue(item.issues[0], item.activity_id, item.activity, t).text,
    });
  }
  const subAreaIssue = health.plan_issues.find((issue) => issue.code === 'SUB_AREA_NO_PLAN');
  if (subAreaIssue) {
    const count = Number((subAreaIssue.params as { count?: number } | undefined)?.count ?? 0);
    rows.push({ key: 'sub-areas', activityId: null, activity: null, text: t('yearlyPlan.check.subAreasNoPlan', { count }) as string });
  }
  if (health.plan_issues.some((issue) => issue.code === 'CBA_OUT_OF_DATE')) {
    rows.push({ key: 'cba', activityId: null, activity: null, text: t('yearlyPlan.check.cbaOutOfDate') as string });
  }
  return rows;
}

interface DialogProps {
  open: boolean;
  action: PlanCheckAction;
  rows: PlanCheckRow[];
  onFix: (row: PlanCheckRow) => void;
  onCancel: () => void;
  onContinue: () => void;
}

/** The check, shown. It warns and links to the fixes; it never blocks — the person decides (D24). */
export const PlanCheckDialog: React.FC<DialogProps> = ({ open, action, rows, onFix, onCancel, onContinue }) => {
  const t = useT();
  return (
    <Modal
      open={open}
      onCancel={onCancel}
      title={t(action === 'export' ? 'yearlyPlan.check.titleExport' : 'yearlyPlan.check.titleCreate', { n: rows.length })}
      width={560}
      footer={[
        <Button key="back" onClick={onCancel} data-testid="plan-check-back">
          {t('yearlyPlan.check.goBack')}
        </Button>,
        <Button key="go" type="primary" onClick={onContinue} data-testid="plan-check-continue">
          {t(action === 'export' ? 'yearlyPlan.check.continueExport' : 'yearlyPlan.check.continueCreate')}
        </Button>,
      ]}
      destroyOnHidden
    >
      <div data-testid="plan-check">
        <Text type="secondary">{t('yearlyPlan.check.intro')}</Text>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
          {rows.map((row) => (
            <div key={row.key} data-testid="plan-check-row" style={{ display: 'flex', gap: 12, justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0 }}>
                {row.state && <Tag color="orange">{t(`yearlyPlan.state.${row.state}`)}</Tag>}
                {row.activity && <Text strong>{row.activity}</Text>}
                <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>{row.text}</div>
              </div>
              {row.activityId && (
                <Button size="small" onClick={() => onFix(row)} data-testid="plan-check-fix">
                  {t('yearlyPlan.guidance.open')}
                </Button>
              )}
            </div>
          ))}
        </div>
      </div>
    </Modal>
  );
};

interface Options {
  /** the person chose to fix a row: take them there (the dialog has already closed) */
  onFix?: (calculationId: string, activityId: string) => void;
}

interface Pending {
  calculationId: string;
  action: PlanCheckAction;
  rows: PlanCheckRow[];
  proceed: () => void | Promise<void>;
}

/**
 * Runs the plan check before an action. `guard(calculationId, proceed, action)` reads the plan health: with nothing
 * to check — or when it cannot be read, or the guidance is switched off — `proceed` runs at once; otherwise the
 * dialog is shown and `proceed` runs only if the person goes on. Render `dialog` once in the host.
 */
export function usePlanCheck({ onFix }: Options = {}) {
  const t = useT();
  const [pending, setPending] = useState<Pending | null>(null);

  const guard = useCallback(
    async (calculationId: string, proceed: () => void | Promise<void>, action: PlanCheckAction = 'create') => {
      if (!isYearlyPlanGuidanceEnabled()) {
        await proceed();
        return;
      }
      let rows: PlanCheckRow[];
      try {
        rows = planCheckRows(await yearlyPlanApi.getHealth(calculationId), t);
      } catch {
        // a check that cannot run must never stand in the way: the server refuses what it must refuse anyway
        await proceed();
        return;
      }
      if (rows.length === 0) {
        await proceed();
        return;
      }
      setPending({ calculationId, action, rows, proceed });
    },
    [t],
  );

  const dialog = (
    <PlanCheckDialog
      open={pending !== null}
      action={pending?.action ?? 'create'}
      rows={pending?.rows ?? []}
      onCancel={() => setPending(null)}
      onFix={(row) => {
        const current = pending;
        setPending(null);
        if (current && row.activityId) onFix?.(current.calculationId, row.activityId);
      }}
      onContinue={() => {
        const current = pending;
        setPending(null);
        if (current) void current.proceed();
      }}
    />
  );

  return { guard, dialog };
}
