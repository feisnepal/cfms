import React, { useMemo, useState } from 'react';
import { Select } from 'antd';
import { useT } from '../../i18n/hooks';
import type { RawPotentialActivity } from '../../lib/activitySearch';

const nameOf = (a: RawPotentialActivity): string => (a.activity ?? a.activities ?? a.name_en ?? '').trim();

/**
 * The always-empty last row of the yearly plan (owner, 2026-10-15): pick an activity and it joins the plan as a new line whose
 * numbers are then typed in the table above. Activities already in the plan are not offered again.
 */
export const InlineAddRow: React.FC<{
  activities: RawPotentialActivity[];
  inPlan: ReadonlySet<number>;
  onPick: (activityId: number) => Promise<boolean>;
}> = ({ activities, inPlan, onPick }) => {
  const t = useT();
  const [busy, setBusy] = useState(false);
  const [value, setValue] = useState<number | null>(null);

  const options = useMemo(
    () =>
      activities
        .filter((a) => !inPlan.has(a.id) && nameOf(a))
        .map((a) => ({
          value: a.id,
          label: `${nameOf(a)}${a.unit ? ` (${a.unit})` : ''}`,
          search: [nameOf(a), a.name_en, a.search_terms, a.program ?? a.progarms].filter(Boolean).join(' ').toLowerCase(),
        })),
    [activities, inPlan],
  );

  return (
    <div style={{ padding: '6px 8px' }} data-testid="plan-inline-add">
      <Select<number>
        showSearch
        allowClear
        style={{ width: 'min(560px, 100%)' }}
        value={value}
        loading={busy}
        disabled={busy}
        placeholder={t('yearlyPlan.planTable.addRowPlaceholder') as string}
        options={options}
        optionFilterProp="label"
        filterOption={(input, option) => {
          const q = input.trim().toLowerCase();
          return !q || String((option as { search?: string })?.search ?? '').includes(q);
        }}
        onChange={async (id) => {
          if (id == null) return setValue(null);
          setBusy(true);
          const ok = await onPick(id);
          setBusy(false);
          setValue(null); // ready for the next row
          return ok;
        }}
        data-testid="plan-inline-add-select"
      />
    </div>
  );
};
