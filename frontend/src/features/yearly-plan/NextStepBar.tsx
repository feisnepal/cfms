import React, { useState } from 'react';
import { Button, Typography } from 'antd';
import { ArrowRightOutlined, CheckCircleFilled, CloseOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { describeNextStep, type StepView } from './planMessages';
import { usePlanHealth } from './usePlanHealth';

const { Text } = Typography;

const HIDDEN_KEY = 'cfms.yearlyPlan.mapBarHidden';

function readHidden(): boolean {
  try {
    return window.localStorage.getItem(HIDDEN_KEY) === '1';
  } catch {
    return false;
  }
}

function writeHidden(hidden: boolean): void {
  try {
    if (hidden) window.localStorage.setItem(HIDDEN_KEY, '1');
    else window.localStorage.removeItem(HIDDEN_KEY);
  } catch {
    /* storage blocked: the bar simply comes back next time */
  }
}

interface Props {
  calculationId: string;
  /** bump after the map changes the plan (a place drawn, a year edited) so the bar re-reads it */
  refreshKey?: number | string;
  /** turn on the Activity Features layer (steps that are done on the map) */
  onShowLayer: () => void;
  /** fix the step where it is asked for (the wizard opened at that activity's place); falls back to onShowLayer */
  onFixStep?: (step: StepView) => void;
  /** open the add-activity wizard */
  onAddActivity?: () => void;
  /** open the yearly-plan page (steps that are not done on the map: numbers, review) */
  onOpenPlan: () => void;
}

/**
 * The ONE next step of the yearly plan, on the map (plan §4.9). Sits over the map so a person drawing places
 * always sees what is still missing, in the same words as the yearly-plan page; it can be folded away and
 * comes back as a small pill.
 */
export const NextStepBar: React.FC<Props> = ({ calculationId, refreshKey = 0, onShowLayer, onFixStep, onAddActivity, onOpenPlan }) => {
  const t = useT();
  const { health } = usePlanHealth(calculationId, refreshKey);
  const [hidden, setHidden] = useState(readHidden);

  if (!health) return null;
  const step = describeNextStep(health, t);
  const ready = step.key === 'ALL_READY';
  const onMap = step.action === 'show_on_map' || step.action === 'add_first_activity';
  const primaryLabel = !onMap
    ? t('yearlyPlan.bar.openPlan')
    : step.action === 'add_first_activity' && onFixStep
      ? t('yearlyPlan.wizard.addButton')
      : onFixStep
        ? t('yearlyPlan.wizard.where.map')
        : t('yearlyPlan.bar.showLayer');

  const fold = (value: boolean) => {
    setHidden(value);
    writeHidden(value);
  };

  if (hidden) {
    return (
      <Button
        data-testid="next-step-pill"
        size="small"
        onClick={() => fold(false)}
        style={{ position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)', zIndex: 450 }}
      >
        {t('yearlyPlan.bar.show')}
      </Button>
    );
  }

  return (
    <div
      data-testid="next-step-bar"
      data-step={step.key}
      role="status"
      style={{
        position: 'absolute',
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: 450,
        width: 'min(620px, 88%)',
        background: '#ffffff',
        border: `1px solid ${ready ? '#b7eb8f' : '#91caff'}`,
        borderLeft: `4px solid ${ready ? '#52c41a' : '#1677ff'}`,
        borderRadius: 8,
        boxShadow: '0 4px 16px rgba(0,0,0,0.12)',
        padding: '8px 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      <span aria-hidden="true" style={{ color: ready ? '#52c41a' : '#1677ff', fontSize: 16 }}>
        {ready ? <CheckCircleFilled /> : <ArrowRightOutlined />}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Text type="secondary" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          {t('yearlyPlan.bar.title')}
        </Text>
        <div
          title={step.text}
          data-testid="next-step-bar-text"
          style={{
            fontSize: 13,
            lineHeight: 1.45,
            overflowWrap: 'anywhere',
            display: '-webkit-box',
            WebkitLineClamp: 2,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
          }}
        >
          {step.text}
        </div>
      </div>
      {!ready && (
        <Button
          type="primary"
          size="small"
          onClick={() => (onMap ? (onFixStep ? onFixStep(step) : onShowLayer()) : onOpenPlan())}
          data-testid="next-step-bar-action"
        >
          {primaryLabel}
        </Button>
      )}
      {onAddActivity && step.action !== 'add_first_activity' && (
        <Button size="small" onClick={onAddActivity} data-testid="next-step-bar-add">
          {t('yearlyPlan.wizard.addButton')}
        </Button>
      )}
      <Button
        type="text"
        size="small"
        icon={<CloseOutlined />}
        aria-label={t('yearlyPlan.bar.hide') as string}
        title={t('yearlyPlan.bar.hide') as string}
        onClick={() => fold(true)}
        data-testid="next-step-bar-hide"
      />
    </div>
  );
};

export default NextStepBar;
