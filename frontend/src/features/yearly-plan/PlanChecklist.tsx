import React from 'react';
import { Button, Collapse, Tag, Typography } from 'antd';
import { useT } from '../../i18n/hooks';
import type { PlanHealthItem } from '../../services/api';
import { describeIssue } from './planMessages';

const { Text } = Typography;

const STATE_COLOR: Record<PlanHealthItem['state'], string> = {
  needs_location: 'blue',
  needs_numbers: 'orange',
  needs_review: 'gold',
  ready: 'green',
};

interface Props {
  items: PlanHealthItem[];
  onOpen: (activityId: string) => void;
}

/** Every activity that still needs something, each with the reason in one line and a way to fix it. */
export const PlanChecklist: React.FC<Props> = ({ items, onOpen }) => {
  const t = useT();
  const open = items.filter((item) => item.state !== 'ready' && item.issues.length > 0);

  const body =
    open.length === 0 ? (
      <Text type="secondary">{t('yearlyPlan.guidance.allGood')}</Text>
    ) : (
      <div data-testid="plan-checklist" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {open.map((item) => {
          const view = describeIssue(item.issues[0], item.activity_id, item.activity, t);
          return (
            <div
              key={item.activity_id}
              data-testid="plan-checklist-row"
              style={{ display: 'flex', gap: 12, alignItems: 'flex-start', justifyContent: 'space-between' }}
            >
              <div style={{ minWidth: 0 }}>
                <Tag color={STATE_COLOR[item.state]}>{t(`yearlyPlan.state.${item.state}`)}</Tag>
                <Text strong>{item.activity}</Text>
                <div style={{ fontSize: 12, color: '#666', marginTop: 2 }}>{view.text}</div>
              </div>
              <Button size="small" onClick={() => onOpen(item.activity_id)}>
                {t('yearlyPlan.guidance.open')}
              </Button>
            </div>
          );
        })}
      </div>
    );

  return (
    <Collapse
      size="small"
      ghost
      defaultActiveKey={open.length > 0 ? ['list'] : []}
      items={[{ key: 'list', label: `${t('yearlyPlan.guidance.checklistTitle')} (${open.length})`, children: body }]}
    />
  );
};

export default PlanChecklist;
