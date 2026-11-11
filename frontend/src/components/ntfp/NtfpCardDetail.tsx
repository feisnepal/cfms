/**
 * NtfpCardDetail — one species' method card with the SOURCE of every value (owner requirement 2026-10-22).
 *
 * Each fact shows its chosen value, the document it comes from (key, year, table or page, a link when the document is online), and a status tag: documented,
 * derived by a rule, provisional (needs a person) or expert-confirmed. Where other sources give a different value they are listed beside it, so a reader sees the
 * disagreement instead of one number that hides it.
 */
import { useEffect, useState } from 'react';
import { Alert, Spin, Table, Tag, Tooltip } from 'antd';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpCard, type NtfpFact, type NtfpFactValue } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { cardStatusColour, cardStatusKey, factFieldKey, partKey, rangeText, sourceLine } from '../../lib/ntfp';

interface Props {
  calculationId: string;
  speciesKey: string;
}

const ENUM_KEYS: Record<string, string> = {
  tree: 'ntfp.growth.tree', shrub: 'ntfp.growth.shrub', climber: 'ntfp.growth.climber', herb: 'ntfp.growth.herb', fungus: 'ntfp.growth.fungus', lichen: 'ntfp.growth.lichen',
  destructive: 'ntfp.species.methodDestructive', semi_destructive: 'ntfp.species.methodSemi', non_destructive: 'ntfp.species.methodNon',
};

export default function NtfpCardDetail({ calculationId, speciesKey }: Props) {
  const t = useT();
  const [card, setCard] = useState<NtfpCard | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setCard(null);
    setError(null);
    ntfpApi.card(calculationId, speciesKey)
      .then((c) => { if (!cancelled) setCard(c); })
      .catch((err) => { if (!cancelled) setError(apiErrorText(err, t('ntfp.error.generic'))); });
    return () => { cancelled = true; };
  }, [calculationId, speciesKey, t]);

  if (error) return <Alert type="error" showIcon title={error} />;
  if (!card) return <Spin size="small" />;
  if (card.facts.length === 0) return <Alert type="info" showIcon title={t('ntfp.card.noFacts')} />;

  const valueText = (v: NtfpFactValue, field: string): string => {
    if (field === 'season' && v.value_num != null) {
      const cal = v.calendar === 'BS' ? 'bs' : 'ad';
      const a = t(`ntfp.month.${cal}.${v.value_num}`);
      const b = v.value_num2 != null ? t(`ntfp.month.${cal}.${v.value_num2}`) : null;
      return `${b && b !== a ? `${a} – ${b}` : a} (${v.calendar ?? 'AD'})`;
    }
    if (v.value_text != null && v.value_num == null) {
      if (field === 'part_groups') return v.value_text.split(',').map((g) => t(`ntfp.part.${partKey(g)}`)).join(', ');
      return ENUM_KEYS[v.value_text] ? t(ENUM_KEYS[v.value_text]) : v.value_text;
    }
    return rangeText(v.value_num, v.value_num2, v.unit);
  };

  const sourceCell = (v: NtfpFactValue) => {
    const line = sourceLine(v);
    const text = v.source_url ? <a href={v.source_url} target="_blank" rel="noopener noreferrer">{line}</a> : <span>{line}</span>;
    return (
      <Tooltip title={[v.source_title, v.note].filter(Boolean).join(' — ')}>
        {text}
      </Tooltip>
    );
  };

  const rows = card.facts.map((f: NtfpFact, i: number) => ({ key: `${f.field}-${f.part_group}-${i}`, f }));

  return (
    <div data-testid="ntfp-card">
      <div style={{ marginBottom: 8 }}>
        <Tag color={cardStatusColour(card.card_status)}>{t(cardStatusKey(card.card_status))}</Tag>
        {card.card_status === 'provisional' && <span style={{ fontSize: 12 }}>{t('ntfp.card.provisionalHint')}</span>}
      </div>
      <Table size="small" pagination={false} dataSource={rows} showHeader
        columns={[
          { title: t('ntfp.card.colFact'), key: 'fact', width: 200, render: (_: unknown, r) => (
            <span>{t(factFieldKey(r.f.field))}{r.f.part_group ? <span style={{ opacity: 0.7 }}> · {t(`ntfp.part.${partKey(r.f.part_group)}`)}</span> : null}</span>
          ) },
          { title: t('ntfp.card.colValue'), key: 'value', render: (_: unknown, r) => (
            <div>
              {r.f.chosen ? <strong>{valueText(r.f.chosen, r.f.field)}</strong> : '—'}
              {r.f.conflict && <Tag color="gold" style={{ marginLeft: 6 }}>{t('ntfp.card.sourcesDiffer')}</Tag>}
              {r.f.others.length > 0 && (
                <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12 }}>
                  {r.f.others.map((o) => (
                    <li key={o.id}>{valueText(o, r.f.field)} — {sourceCell(o)} <Tag color={cardStatusColour(o.status)}>{t(cardStatusKey(o.status))}</Tag></li>
                  ))}
                </ul>
              )}
            </div>
          ) },
          { title: t('ntfp.card.colSource'), key: 'source', render: (_: unknown, r) => (r.f.chosen ? sourceCell(r.f.chosen) : '—') },
          { title: t('ntfp.card.colStatus'), key: 'status', width: 120, render: (_: unknown, r) => (
            r.f.chosen ? <Tag color={cardStatusColour(r.f.chosen.status)}>{t(cardStatusKey(r.f.chosen.status))}</Tag> : null
          ) },
        ]} />
    </div>
  );
}
