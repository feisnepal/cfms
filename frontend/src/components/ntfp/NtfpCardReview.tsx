/**
 * NtfpCardReview — the super admin's review of the provisional method cards (owner, 2026-10-22).
 *
 * A provisional card was made by rules (growth form and part harvested), not from a document about the species. The reviewer confirms it as it stands,
 * or corrects the growth form, method, plot size, individuals to weigh or allowable harvest and saves. Either way the card becomes expert-confirmed under the
 * reviewer's name; the value it replaces stays on the card as history.
 */
import { useCallback, useEffect, useState } from 'react';
import { Alert, Button, InputNumber, Popconfirm, Select, Space, Table, Tag } from 'antd';
import { useT } from '../../i18n/hooks';
import { ntfpApi, type NtfpReviewCard, type NtfpReviewEdits } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import { reviewRow } from '../../lib/ntfp';

const GROWTH = ['tree', 'shrub', 'climber', 'herb', 'fungus', 'lichen'];
const METHOD_KEY: Record<string, string> = {
  destructive: 'ntfp.species.methodDestructive',
  semi_destructive: 'ntfp.species.methodSemi',
  non_destructive: 'ntfp.species.methodNon',
};
type NumField = 'plot_min_sqm' | 'plot_max_sqm' | 'n_individuals_min' | 'n_individuals_max' | 'aah_pct_min' | 'aah_pct_max';

export default function NtfpCardReview() {
  const t = useT();
  const [cards, setCards] = useState<NtfpReviewCard[]>([]);
  const [drafts, setDrafts] = useState<Record<string, NtfpReviewEdits>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCards((await ntfpApi.reviewQueue()).cards);
    } catch (err) {
      setError(apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const setDraft = (key: string, patch: NtfpReviewEdits) => setDrafts((d) => ({ ...d, [key]: { ...d[key], ...patch } }));
  const rowOf = (c: NtfpReviewCard) => reviewRow(c, drafts[c.species_key] ?? {});

  const submit = async (rows: ReturnType<typeof reviewRow>[], key: string) => {
    setSaving(key);
    setError(null);
    try {
      const out = await ntfpApi.review(rows);
      setDone((n) => n + out.cards_confirmed);
      const gone = new Set(rows.map((r) => r.species_key));
      setCards((cs) => cs.filter((c) => !gone.has(c.species_key)));
      setDrafts((d) => Object.fromEntries(Object.entries(d).filter(([k]) => !gone.has(k))));
    } catch (err) {
      setError(apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setSaving(null);
    }
  };

  // cards whose growth form is not a guess and that the reviewer has not touched: safe to confirm together
  const sure = cards.filter((c) => !c.growth_guessed && rowOf(c).confirmed);
  const num = (c: NtfpReviewCard, field: NumField) => (
    <InputNumber size="small" min={0} style={{ width: 72 }} value={(drafts[c.species_key]?.[field] ?? c[field]) as number | null}
      onChange={(v) => setDraft(c.species_key, { [field]: v } as NtfpReviewEdits)} aria-label={`${t(`ntfp.review.${field}`)} ${c.species_key}`} />
  );

  return (
    <div>
      <p style={{ maxWidth: 820 }}>{t('ntfp.review.intro')}</p>
      {error && <Alert type="error" showIcon closable style={{ marginBottom: 12 }} title={error} onClose={() => setError(null)} />}
      {done > 0 && <Alert type="success" showIcon style={{ marginBottom: 12 }} title={t('ntfp.review.done', { count: done })} />}
      <Space style={{ marginBottom: 12 }}>
        <Tag>{t('ntfp.review.waiting', { count: cards.length })}</Tag>
        <Popconfirm title={t('ntfp.review.confirmSurePrompt', { count: sure.length })} okText={t('ntfp.review.confirm')} cancelText={t('common.cancel')} disabled={!sure.length}
          onConfirm={() => void submit(sure.map((c) => reviewRow(c, {})), 'bulk')}>
          <Button disabled={!sure.length} loading={saving === 'bulk'}>{t('ntfp.review.confirmSure', { count: sure.length })}</Button>
        </Popconfirm>
      </Space>
      {!loading && cards.length === 0 && !error && <Alert type="success" showIcon title={t('ntfp.review.none')} />}
      <Table<NtfpReviewCard> size="small" rowKey="species_key" loading={loading} dataSource={cards} pagination={{ pageSize: 25, showSizeChanger: false }} scroll={{ x: 1100 }}
        columns={[
          {
            title: t('ntfp.species.colName'), key: 'name', width: 200,
            render: (_: unknown, c) => <div><div>{c.nepali_name}</div><div style={{ fontSize: 12, fontStyle: 'italic' }}>{c.scientific_name}</div><div style={{ fontSize: 12 }}>{c.part_ne}</div></div>,
          },
          {
            title: t('ntfp.review.growth'), key: 'growth', width: 150,
            render: (_: unknown, c) => (
              <div>
                <Select size="small" style={{ width: 120 }} value={drafts[c.species_key]?.growth_class ?? c.growth_class ?? undefined} aria-label={`${t('ntfp.review.growth')} ${c.species_key}`}
                  options={GROWTH.map((g) => ({ value: g, label: t(`ntfp.growth.${g}`) }))} onChange={(v) => setDraft(c.species_key, { growth_class: v })} />
                {c.growth_guessed && <Tag color="orange" style={{ marginTop: 4 }}>{t('ntfp.review.guessed')}</Tag>}
              </div>
            ),
          },
          {
            title: t('ntfp.species.colMethod'), key: 'method', width: 150,
            render: (_: unknown, c) => (
              <Select size="small" style={{ width: 130 }} value={drafts[c.species_key]?.sampling_method ?? c.sampling_method ?? undefined} aria-label={`${t('ntfp.species.colMethod')} ${c.species_key}`}
                options={Object.keys(METHOD_KEY).map((m) => ({ value: m, label: t(METHOD_KEY[m]) }))} onChange={(v) => setDraft(c.species_key, { sampling_method: v })} />
            ),
          },
          { title: t('ntfp.review.plot'), key: 'plot', width: 170, render: (_: unknown, c) => <Space size={4}>{num(c, 'plot_min_sqm')}{num(c, 'plot_max_sqm')}</Space> },
          { title: t('ntfp.review.individuals'), key: 'n', width: 170, render: (_: unknown, c) => <Space size={4}>{num(c, 'n_individuals_min')}{num(c, 'n_individuals_max')}</Space> },
          {
            title: t('ntfp.review.aah'), key: 'aah', width: 200,
            render: (_: unknown, c) => (
              <div><Space size={4}>{num(c, 'aah_pct_min')}{num(c, 'aah_pct_max')}</Space>{c.aah_source_key && <div style={{ fontSize: 12 }}>{c.aah_source_key}</div>}</div>
            ),
          },
          {
            title: '', key: 'act', width: 150, fixed: 'right' as const,
            render: (_: unknown, c) => {
              const row = rowOf(c);
              return (
                <Button size="small" type={row.confirmed ? 'default' : 'primary'} loading={saving === c.species_key} onClick={() => void submit([row], c.species_key)}>
                  {row.confirmed ? t('ntfp.review.confirm') : t('ntfp.review.saveCorrection')}
                </Button>
              );
            },
          },
        ]}
      />
    </div>
  );
}
