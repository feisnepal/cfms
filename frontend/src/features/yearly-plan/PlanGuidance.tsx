import React, { useCallback, useState } from 'react';
import { message, Typography } from 'antd';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';
import { yearlyPlanApi } from '../../services/api';
import NextStepCard from './NextStepCard';
import PlanChecklist from './PlanChecklist';
import { describeNextStep, type StepView } from './planMessages';
import { planSaveErrorMessage } from './planErrors';
import { usePlanHealth } from './usePlanHealth';

const { Text, Title } = Typography;

interface Props {
  calculationId: string;
  /** bump after the host saves, so the guidance re-reads the plan */
  refreshKey?: number | string;
  /** open an activity so its problem can be fixed (the host knows how: a drawer, a table row, the map) */
  onOpenActivity: (activityId: string, action: string) => void;
  /** the plan is empty: take the user to the activity list */
  onAddFirst?: () => void;
  /** everything is ready: go on to the plan document (omit to hide the button's effect) */
  onCreatePlan?: () => void;
  /** called after the guidance itself changed the plan (a Confirm) so the host can reload */
  onPlanChanged?: () => void;
}

/**
 * "Your plan": how far along it is, the ONE next thing to do, and what else needs attention.
 * The same component sits on both legacy screens and, later, on the map (plan §4.9).
 */
export const PlanGuidance: React.FC<Props> = ({
  calculationId,
  refreshKey = 0,
  onOpenActivity,
  onAddFirst,
  onCreatePlan,
  onPlanChanged,
}) => {
  const t = useT();
  const { health, error, refresh } = usePlanHealth(calculationId, refreshKey);
  const [busy, setBusy] = useState(false);

  const confirm = useCallback(
    async (activityId: string) => {
      setBusy(true);
      try {
        await yearlyPlanApi.confirmLine(calculationId, activityId);
        message.success(t('yearlyPlan.confirm.done'));
        await refresh();
        onPlanChanged?.();
      } catch (err) {
        message.error(planSaveErrorMessage(err, t));
      } finally {
        setBusy(false);
      }
    },
    [calculationId, refresh, onPlanChanged, t],
  );

  const act = useCallback(
    (step: StepView) => {
      switch (step.action) {
        case 'add_first_activity':
          onAddFirst?.();
          break;
        case 'create_plan':
          onCreatePlan?.();
          break;
        case 'confirm':
          if (step.activityId) void confirm(step.activityId);
          break;
        default:
          if (step.activityId) onOpenActivity(step.activityId, step.action);
      }
    },
    [confirm, onAddFirst, onCreatePlan, onOpenActivity],
  );

  if (error && !health) {
    return (
      <div data-testid="plan-guidance-error" style={{ padding: '8px 0' }}>
        <Text type="secondary">{t('yearlyPlan.error.loadFailed')}</Text>
      </div>
    );
  }
  if (!health) return null;

  const { summary } = health;
  const step = describeNextStep(health, t);
  return (
    <div data-testid="plan-guidance" style={{ margin: '12px 0 16px' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
        <Title level={5} style={{ margin: 0 }}>
          {t('yearlyPlan.guidance.title')}
        </Title>
        {summary.total > 0 && (
          <Text type="secondary" data-testid="plan-progress">
            {t('yearlyPlan.guidance.progress', {
              ready: formatNumber(summary.ready),
              total: formatNumber(summary.total),
            })}
          </Text>
        )}
      </div>
      <NextStepCard step={step} onAction={act} onConfirm={confirm} busy={busy} />
      {summary.total > 0 && <PlanChecklist items={health.items} onOpen={(id) => onOpenActivity(id, 'open')} />}
    </div>
  );
};

export default PlanGuidance;
