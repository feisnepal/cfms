/**
 * NtfpStagesStrip — the survey's five stages as a guided strip at the top of the NTFP page (owner, 2026-10-22).
 *
 * Each stage shows where it stands (done, the one to do next, waiting) and one line on what it needs. A click takes the person to that stage's tab. Nothing is locked: a stage that is
 * waiting for an earlier one says what it is waiting for, and can still be opened. The survey is optional, and the strip says so.
 */
import { Steps } from 'antd';
import { useT } from '../../i18n/hooks';
import type { Stage, StageKey } from '../../lib/ntfp';

interface Props {
  stages: Stage[];
  active: StageKey | string;
  onSelect: (key: StageKey) => void;
}

const STATUS: Record<Stage['status'], 'finish' | 'process' | 'wait'> = { done: 'finish', current: 'process', todo: 'wait', locked: 'wait' };

export default function NtfpStagesStrip({ stages, active, onSelect }: Props) {
  const t = useT();
  const current = Math.max(0, stages.findIndex((s) => s.key === active));
  return (
    <div data-testid="ntfp-stages" style={{ marginBottom: 12 }}>
      <p style={{ margin: '0 0 8px', fontSize: 13 }}>{t('ntfp.stage.optional')}</p>
      <Steps
        size="small"
        current={current}
        responsive
        onChange={(i) => onSelect(stages[i].key)}
        items={stages.map((s) => ({
          title: t(`ntfp.stage.${s.key}`),
          description: <span data-testid={`ntfp-stage-${s.key}`} data-status={s.status}>{t(s.detailKey, s.params)}</span>,
          status: STATUS[s.status],
          disabled: false,
        }))}
      />
    </div>
  );
}
