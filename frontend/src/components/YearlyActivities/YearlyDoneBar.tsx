import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Button, Space, Switch, message } from 'antd';
import { yearlyPlanApi, type YearlyPlanStatus } from '../../services/api';
import { useT } from '../../i18n/hooks';

/**
 * "Need to add more yearly activities, or done?" - shown until the owner answers Done; then a switch that opens it again.
 * `onChange` lets another page refresh its own progress when the answer changes.
 */
export const YearlyDoneBar: React.FC<{
  calculationId: string;
  /** how "Add more" gets the user to the place where activities are entered; defaults to scrolling to the plan on this page */
  onAddMore?: () => void;
  onChange?: (status: YearlyPlanStatus) => void;
  /** on pages other than the step itself: once the owner has said Done, show nothing (the switch lives on the step) */
  quietWhenDone?: boolean;
}> = ({ calculationId, onAddMore, onChange, quietWhenDone = false }) => {
  const t = useT();
  const [status, setStatus] = useState<YearlyPlanStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    yearlyPlanApi
      .getStatus(calculationId)
      .then((s) => !cancelled && setStatus(s))
      .catch(() => !cancelled && setStatus(null));
    return () => {
      cancelled = true;
    };
  }, [calculationId]);

  const setDone = useCallback(
    async (done: boolean) => {
      setBusy(true);
      try {
        const next = await yearlyPlanApi.setDone(calculationId, done);
        setStatus(next);
        onChange?.(next);
      } catch {
        message.error(t('yearlyStep.saveFailed'));
      } finally {
        setBusy(false);
      }
    },
    [calculationId, onChange, t],
  );

  const addMore = () => {
    if (onAddMore) return onAddMore();
    document.getElementById('yearly-plan-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  if (!status) return null;

  if (status.done) {
    if (quietWhenDone) return null;
    return (
      <div className="px-3 py-2 border-b border-gray-200 bg-green-50" data-testid="yearly-done-bar">
        <Space>
          <Switch checked onChange={(v) => setDone(v)} loading={busy} data-testid="yearly-done-switch" />
          <span className="text-sm text-green-800">{t('yearlyStep.doneOn')}</span>
        </Space>
      </div>
    );
  }

  return (
    <Alert
      type="info"
      showIcon
      className="m-2"
      data-testid="yearly-done-bar"
      message={t('yearlyStep.question')}
      description={status.reopened_reason === 'plan_changed' ? t('yearlyStep.reopened') : undefined}
      action={
        <Space>
          <Button size="small" onClick={addMore} data-testid="yearly-add-more">
            {t('yearlyStep.addMore')}
          </Button>
          <Button size="small" type="primary" loading={busy} onClick={() => setDone(true)} data-testid="yearly-mark-done">
            {t('yearlyStep.done')}
          </Button>
        </Space>
      }
    />
  );
};
