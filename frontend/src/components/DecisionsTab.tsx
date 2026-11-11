/** The "Decisions needed" tab: the human choices the plan needs, who made each one and when. Titles and explanations are
 *  translation keys (an admin can reword them); the server decides whether answering is allowed (HTTP 423 once the map is
 *  approved or being calculated). */
import { useState } from 'react';
import { useT } from '../i18n/hooks';
import { ORIENTATIONS, localDigits, type DecisionItem, type DecisionsResponse, type NumeralLang } from '../lib/forestSummary';
import type { LoadStatus } from '../hooks/useForestSummary';

interface Props {
  lang: NumeralLang;
  data: DecisionsResponse | null;
  status: LoadStatus;
  saving: boolean;
  saveError: 'locked' | 'invalid' | 'error' | null;
  answer: (key: string, body: { choice: string; scope?: string | null; value?: string | null }) => Promise<boolean>;
}

const itemId = (d: DecisionItem) => `${d.key}:${d.scope ?? ''}`;

function DecisionCard({ item, closed, saving, answer, lang }: { item: DecisionItem; closed: boolean; saving: boolean; answer: Props['answer']; lang: NumeralLang }) {
  const t = useT();
  const [picking, setPicking] = useState(false);
  const [value, setValue] = useState<string>(item.suggested ?? ORIENTATIONS[0]);
  const params = { block: item.block_name ?? '', suggested: item.suggested ?? '', current: item.current ?? '—' };
  const base = `forestSummary.decisions.${item.key}`;

  const pick = (choice: string) => {
    if (choice === 'custom') {
      setPicking(true);
      return;
    }
    void answer(item.key, { choice, scope: item.scope });
  };

  return (
    <div className={`fs-decision${item.state === 'answered' ? ' fs-decision--done' : ''}`} data-testid={`decision-${itemId(item)}`}>
      <h4>{t(`${base}.title`, params)}</h4>
      <p>{t(`${base}.text`, params)}</p>
      <div className="fs-decision__choices" role="group" aria-label={t(`${base}.title`, params)}>
        {item.choices.map((c) => (
          <button
            key={c}
            type="button"
            aria-pressed={item.choice === c}
            disabled={closed || saving}
            onClick={() => pick(c)}
          >
            {t(`${base}.choice.${c}`, params)}
          </button>
        ))}
      </div>
      {picking && !closed && (
        <div className="fs-decision__custom">
          <select aria-label={t(`${base}.title`, params)} value={value} onChange={(e) => setValue(e.target.value)}>
            {ORIENTATIONS.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              if (await answer(item.key, { choice: 'custom', scope: item.scope, value })) setPicking(false);
            }}
          >
            {t('common.save', { defaultValue: 'Save' })}
          </button>
        </div>
      )}
      <div className="fs-decision__stamp">
        {item.decided_by && item.decided_at
          ? t('forestSummary.decisions.decidedBy', {
              name: item.decided_by.name,
              kind: t(`forestSummary.decisions.kind.${item.decided_by.kind}`),
              date: localDigits(item.decided_at.slice(0, 10), lang),
            })
          : t('forestSummary.decisions.open')}
      </div>
    </div>
  );
}

export function DecisionsTab({ lang, data, status, saving, saveError, answer }: Props) {
  const t = useT();
  if (status === 'forbidden') return <div className="fs-note" role="alert">{t('forestSummary.forbidden', { defaultValue: 'You cannot open this forest.' })}</div>;
  if (!data) return <div className="fs-note" role="status">{status === 'error' ? t('forestSummary.failed', { defaultValue: 'Could not load.' }) : t('forestSummary.loading', { defaultValue: 'Loading…' })}</div>;
  const closed = data.locked;
  return (
    <div className="fs-decisions" data-testid="decisions-tab">
      {data.locked_reason === 'locked' && <div className="fs-lock" role="status">{t('forestSummary.decisions.locked')}</div>}
      {data.locked_reason === 'calculating' && <div className="fs-lock" role="status">{t('forestSummary.decisions.calculating')}</div>}
      {saveError && (
        <div className="fs-lock fs-lock--error" role="alert">
          {saveError === 'locked'
            ? t('forestSummary.decisions.locked')
            : t('forestSummary.saveFailed', { defaultValue: 'The answer was not saved. Try again.' })}
        </div>
      )}
      {data.items.map((item) => (
        <DecisionCard key={itemId(item)} item={item} closed={closed} saving={saving} answer={answer} lang={lang} />
      ))}
      <div className="fs-note" data-testid="decisions-footer">
        {data.open_count > 0 ? t('forestSummary.decisions.openCount', { count: data.open_count, n: localDigits(data.open_count, lang) }) : t('forestSummary.decisions.allDone')}
      </div>
    </div>
  );
}
