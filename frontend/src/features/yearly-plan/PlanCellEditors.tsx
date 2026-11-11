import React, { useEffect, useRef, useState } from 'react';
import { Button, Input, Popover, Typography } from 'antd';
import { useT } from '../../i18n/hooks';
import { parseLocaleNumber } from '../../i18n/numberFormat';
import { changedFields, checkAmount, type PlanField } from './planEdit';
import type { YearCell } from './planTableRules';

const { Text } = Typography;

/** A bare button that looks like the text it wraps: a cell you can press to change. */
const cellButton: React.CSSProperties = {
  background: 'none',
  border: 0,
  padding: 0,
  margin: 0,
  font: 'inherit',
  color: 'inherit',
  cursor: 'pointer',
  textAlign: 'inherit',
  width: '100%',
  borderBottom: '1px dotted #9ca3af',
};

interface DefaultProps {
  testId: string;
  field: PlanField;
  /** the value as text for an editor to start from (plain digits) */
  value: number;
  /** what the cell shows when it is not being edited */
  display: React.ReactNode;
  readOnly?: boolean;
  /** save the typed value; resolves false when the save failed (the editor stays open with what was typed) */
  onCommit: (value: number) => Promise<boolean>;
}

/** The line's usual quantity or budget: press, type, Enter (or leave the field) to save; Esc to cancel. */
export const DefaultCellEditor: React.FC<DefaultProps> = ({ testId, field, value, display, readOnly, onCommit }) => {
  const t = useT();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const [invalid, setInvalid] = useState(false);
  const busy = useRef(false);

  if (readOnly) return <>{display}</>;

  const open = () => {
    setText(String(value));
    setInvalid(false);
    setEditing(true);
  };

  const commit = async () => {
    if (busy.current) return;
    const check = checkAmount(field, 'default', text, parseLocaleNumber);
    if (!check.ok) {
      setInvalid(true);
      return;
    }
    if (check.value === value) {
      setEditing(false);
      return;
    }
    busy.current = true;
    try {
      const saved = await onCommit(check.value);
      if (saved) setEditing(false);
    } finally {
      busy.current = false;
    }
  };

  if (!editing) {
    return (
      <button type="button" data-testid={testId} style={cellButton} onClick={open} title={t('yearlyPlan.planTable.editTip') as string}>
        {display}
      </button>
    );
  }
  return (
    <div>
      <Input
        autoFocus
        size="small"
        data-testid={`${testId}-input`}
        aria-label={t(field === 'quantity' ? 'yearlyPlan.planTable.editQuantity' : 'yearlyPlan.planTable.editBudget') as string}
        status={invalid ? 'error' : undefined}
        value={text}
        inputMode="decimal"
        onChange={(e) => {
          setText(e.target.value);
          setInvalid(false);
        }}
        onPressEnter={() => void commit()}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === 'Escape') setEditing(false);
        }}
        style={{ width: 96, textAlign: 'right' }}
      />
      {invalid && (
        <div>
          <Text type="danger" style={{ fontSize: 11 }} data-testid={`${testId}-invalid`}>
            {t(field === 'quantity' ? 'yearlyPlan.planTable.editInvalidQuantity' : 'yearlyPlan.planTable.editInvalid')}
          </Text>
        </div>
      )}
    </div>
  );
};

interface YearProps {
  testId: string;
  year: number;
  cell: YearCell;
  /** how the cell looks when it is not being edited */
  children: React.ReactNode;
  readOnly?: boolean;
  /** save the changed fields of this year; resolves false when the save failed (the panel stays open) */
  onCommit: (changes: { quantity?: number; budget?: number }) => Promise<boolean>;
  /** shade the cell: the year was just filled by the first value */
  filled?: boolean;
}

/** One year of a plan line: a small panel with its quantity and budget (both 0 = nothing planned that year). */
export const YearCellEditor: React.FC<YearProps> = ({ testId, year, cell, children, readOnly, onCommit, filled }) => {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [quantity, setQuantity] = useState('');
  const [budget, setBudget] = useState('');
  const [invalid, setInvalid] = useState(false);
  const [saving, setSaving] = useState(false);
  const shade = filled ? { background: '#fffbe6', boxShadow: '0 0 0 2px #fffbe6' } : undefined;

  useEffect(() => {
    if (open) {
      setQuantity(String(cell.quantity));
      setBudget(String(cell.budget));
      setInvalid(false);
    }
    // the panel starts from the numbers as they were when it opened; later refreshes must not overwrite typing
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (readOnly) return <span style={shade}>{children}</span>;

  const save = async () => {
    const q = checkAmount('quantity', 'year', quantity, parseLocaleNumber);
    const b = checkAmount('budget', 'year', budget, parseLocaleNumber);
    if (!q.ok || !b.ok) {
      setInvalid(true);
      return;
    }
    const changes = changedFields(cell, { quantity: q.value, budget: b.value });
    if (Object.keys(changes).length === 0) {
      setOpen(false);
      return;
    }
    setSaving(true);
    try {
      if (await onCommit(changes)) setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') void save();
    if (e.key === 'Escape') setOpen(false);
  };

  const panel = (
    <div style={{ width: 230 }} data-testid={`${testId}-panel`}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('yearlyPlan.planTable.editYearTitle', { n: year })}</div>
      <label style={{ display: 'block', fontSize: 12, marginBottom: 6 }}>
        {t('yearlyPlan.planTable.editQuantity')}
        <Input
          autoFocus
          size="small"
          data-testid={`${testId}-quantity`}
          status={invalid ? 'error' : undefined}
          value={quantity}
          inputMode="decimal"
          onChange={(e) => {
            setQuantity(e.target.value);
            setInvalid(false);
          }}
          onKeyDown={onKey}
        />
      </label>
      <label style={{ display: 'block', fontSize: 12, marginBottom: 6 }}>
        {t('yearlyPlan.planTable.editBudget')}
        <Input
          size="small"
          data-testid={`${testId}-budget`}
          status={invalid ? 'error' : undefined}
          value={budget}
          inputMode="decimal"
          onChange={(e) => {
            setBudget(e.target.value);
            setInvalid(false);
          }}
          onKeyDown={onKey}
        />
      </label>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 6 }}>
        {t('yearlyPlan.planTable.editZeroHint')}
      </Text>
      {invalid && (
        <Text type="danger" style={{ fontSize: 11, display: 'block', marginBottom: 6 }} data-testid={`${testId}-invalid`}>
          {t('yearlyPlan.planTable.editInvalid')}
        </Text>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <Button size="small" onClick={() => setOpen(false)} data-testid={`${testId}-cancel`}>
          {t('yearlyPlan.table.yearsCancel')}
        </Button>
        <Button size="small" type="primary" loading={saving} onClick={() => void save()} data-testid={`${testId}-save`}>
          {t('yearlyPlan.wizard.save')}
        </Button>
      </div>
    </div>
  );

  return (
    <Popover content={panel} trigger="click" open={open} onOpenChange={(next) => (next ? setOpen(true) : undefined)} placement="bottom" destroyOnHidden>
      <button
        type="button"
        data-testid={testId}
        aria-haspopup="dialog"
        aria-expanded={open}
        style={{ ...cellButton, borderBottom: 0, ...shade }}
        title={t('yearlyPlan.planTable.editTip') as string}
      >
        {children}
      </button>
    </Popover>
  );
};
