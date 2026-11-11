import React, { useState } from 'react';
import { Button, Popover, Space, Typography } from 'antd';
import { EditOutlined } from '@ant-design/icons';
import { useT } from '../../i18n/hooks';
import { formatNumber } from '../../i18n/numberFormat';
import { formatYears } from '../../lib/activityFeatureLabel';

const { Text } = Typography;

/** The plan has ten years. */
export const PLAN_YEARS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];

interface Props {
  /** The years the place applies to. */
  years: number[];
  /** Called with the new, sorted, non-empty list. Not called when nothing changed. */
  onSave: (years: number[]) => void;
  disabled?: boolean;
}

/**
 * The Years cell of the activity-features table: shows the years ("1–3, 7") and opens a chooser of the ten
 * plan years. At least one year must stay ticked; nothing is saved until "Apply".
 */
export const YearsCell: React.FC<Props> = ({ years, onSave, disabled }) => {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<number[]>(years);

  const shown = years.length > 0 ? formatYears(years, formatNumber) : (t('yearlyPlan.table.yearsNone') as string);

  const toggle = (y: number) =>
    setDraft((cur) => (cur.includes(y) ? cur.filter((x) => x !== y) : [...cur, y].sort((a, b) => a - b)));

  const apply = () => {
    if (draft.length === 0) return;
    const same = draft.length === years.length && draft.every((y, i) => y === [...years].sort((a, b) => a - b)[i]);
    setOpen(false);
    if (!same) onSave(draft);
  };

  const content = (
    <div data-testid="years-chooser" style={{ width: 250 }} onClick={(e) => e.stopPropagation()}>
      <Text strong>{t('yearlyPlan.table.yearsTitle')}</Text>
      <div role="group" aria-label={t('yearlyPlan.table.yearsTitle') as string} style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0' }}>
        {PLAN_YEARS.map((y) => {
          const on = draft.includes(y);
          return (
            <button
              key={y}
              type="button"
              aria-pressed={on}
              aria-label={t('yearlyPlan.table.yearLabel', { n: formatNumber(y) }) as string}
              data-testid={`year-chip-${y}`}
              onClick={() => toggle(y)}
              style={{
                minWidth: 40,
                minHeight: 36,
                borderRadius: 18,
                border: `1px solid ${on ? '#1677ff' : '#d9d9d9'}`,
                background: on ? '#e6f4ff' : '#fff',
                color: on ? '#0958d9' : 'inherit',
                fontWeight: on ? 600 : 400,
                cursor: 'pointer',
              }}
            >
              {formatNumber(y)}
            </button>
          );
        })}
      </div>
      {draft.length === 0 && (
        <div role="alert" style={{ color: '#cf1322', fontSize: 12, marginBottom: 6 }}>
          {t('yearlyPlan.table.yearsPick')}
        </div>
      )}
      <Space>
        <Button type="primary" size="small" disabled={draft.length === 0} onClick={apply} data-testid="years-apply">
          {t('yearlyPlan.table.yearsApply')}
        </Button>
        <Button size="small" onClick={() => setOpen(false)} data-testid="years-cancel">
          {t('yearlyPlan.table.yearsCancel')}
        </Button>
      </Space>
    </div>
  );

  return (
    <Popover
      open={open && !disabled}
      onOpenChange={(next) => {
        if (next) setDraft(years);
        setOpen(next);
      }}
      trigger="click"
      content={content}
      destroyOnHidden
    >
      <button
        type="button"
        disabled={disabled}
        data-testid="years-cell"
        aria-label={t('yearlyPlan.table.yearsEdit') as string}
        title={t('yearlyPlan.table.yearsEdit') as string}
        onClick={(e) => e.stopPropagation()}
        style={{ border: 0, background: 'none', cursor: disabled ? 'default' : 'pointer', display: 'inline-flex', gap: 4, alignItems: 'center', padding: '2px 4px' }}
      >
        <span>{shown}</span>
        {!disabled && <EditOutlined aria-hidden="true" style={{ fontSize: 11, color: '#8c8c8c' }} />}
      </button>
    </Popover>
  );
};

export default YearsCell;
