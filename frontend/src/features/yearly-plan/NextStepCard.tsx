import React from 'react';
import { Button, Space, Typography } from 'antd';
import { CheckCircleOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import type { StepView } from './planMessages';

const { Text } = Typography;

interface Props {
  step: StepView;
  /** runs the step's action (open the activity, go to the list, create the plan …) */
  onAction: (step: StepView) => void;
  /** "these numbers are right" — offered next to a starting-value / unusual / no-budget warning */
  onConfirm?: (activityId: string) => void;
  busy?: boolean;
}

/**
 * Exactly ONE thing to do now, in plain words, with one button (plan §4.3). The system never leaves the
 * user to work out the next step from a table.
 */
export const NextStepCard: React.FC<Props> = ({ step, onAction, onConfirm, busy }) => {
  const t = useT();
  const ready = step.key === 'ALL_READY';
  return (
    <div
      data-testid="next-step-card"
      data-step={step.key}
      style={{
        border: `1px solid ${ready ? '#b7eb8f' : '#91caff'}`,
        background: ready ? '#f6ffed' : '#f0f7ff',
        borderRadius: 8,
        padding: '12px 16px',
      }}
    >
      <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {ready ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <ArrowRightOutlined />}{' '}
        {t('yearlyPlan.guidance.nextStep')}
      </Text>
      <div style={{ margin: '6px 0 10px', fontSize: 15, lineHeight: 1.5 }}>{step.text}</div>
      <Space wrap>
        <Button type="primary" loading={busy} onClick={() => onAction(step)}>
          {step.button}
        </Button>
        {step.confirmable && step.activityId && onConfirm && step.action !== 'confirm' && (
          <Button loading={busy} onClick={() => onConfirm(step.activityId as string)}>
            {t('yearlyPlan.confirm.button')}
          </Button>
        )}
      </Space>
    </div>
  );
};

export default NextStepCard;
