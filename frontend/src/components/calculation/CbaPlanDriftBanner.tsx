import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, message } from 'antd';
import { useT } from '../../i18n/hooks';
import { cbaApi, yearlyPlanApi, type CbaPlanDrift } from '../../services/api';
import { usePlanHealth } from '../../features/yearly-plan/usePlanHealth';
import { planSaveErrorMessage } from '../../features/yearly-plan/planErrors';

interface Props {
  calculationId: string;
  /** the base scenario: the one the OP document reads */
  baseScenarioId: string;
  /** called after the analysis was updated from the plan, so the tab reloads its numbers */
  onUpdated: () => void;
}

/**
 * The cost-benefit analysis is a snapshot of the yearly plan: it is only refreshed when someone presses
 * Auto-populate. So it can quietly fall behind a plan that is edited from two screens
 * (YEARLY_ACTIVITIES_WORKSPACE_PLAN §5.8). This says so, and offers the one button that fixes it — it
 * never updates by itself, because the user may have tuned rates and manual rows.
 *
 * It also says when the costs still include the starting numbers (1 and NPR 5,000), which are not a plan.
 */
export const CbaPlanDriftBanner: React.FC<Props> = ({ calculationId, baseScenarioId, onUpdated }) => {
  const t = useT();
  const [drift, setDrift] = useState<CbaPlanDrift | null>(null);
  const [busy, setBusy] = useState(false);
  const { health } = usePlanHealth(calculationId, baseScenarioId);

  const load = useCallback(async () => {
    try {
      setDrift(await yearlyPlanApi.getCbaPlanDrift(baseScenarioId));
    } catch {
      setDrift(null); // the banner is a convenience: never break the tab for it
    }
  }, [baseScenarioId]);

  useEffect(() => {
    void load();
    const onFocus = () => void load();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [load]);

  const update = async () => {
    setBusy(true);
    try {
      const result = await cbaApi.autoPopulate(baseScenarioId);
      message.success(t('yearlyPlan.cba.updated'));
      (result.warnings ?? []).forEach((w) => message.warning(w, 8));
      await load();
      onUpdated();
    } catch (err) {
      message.error(planSaveErrorMessage(err, t));
    } finally {
      setBusy(false);
    }
  };

  const hasPlaceholders = (health?.items ?? []).some((item) =>
    item.issues.some((issue) => issue.code === 'PLACEHOLDER_NUMBERS'),
  );

  if (!drift?.out_of_date && !hasPlaceholders) return null;
  return (
    <div data-testid="cba-plan-banner" style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
      {drift?.out_of_date && (
        <Alert
          type="warning"
          showIcon
          message={t('yearlyPlan.cba.outOfDate')}
          action={
            <Button size="small" type="primary" loading={busy} onClick={update}>
              {t('yearlyPlan.cba.update')}
            </Button>
          }
        />
      )}
      {hasPlaceholders && <Alert type="info" showIcon message={t('yearlyPlan.cba.placeholderNote')} />}
    </div>
  );
};

export default CbaPlanDriftBanner;
