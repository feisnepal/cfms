/**
 * NtfpHarvestPanel — the owner's annual harvest of each surveyed species and part (NTFP inventory, phase 5b).
 *
 * The guideline gives no harvest rule, so nothing here proposes a quantity: the owner types it (or a share of the stock, which fills it in). The saved
 * plan is what the cost-benefit analysis reads on its next re-populate, and one button makes the yearly plan's NTFP collection line from its total.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, Button, InputNumber, Select, Space, Table, Tag, Tooltip, message } from 'antd';
import { useInRouterContext, useNavigate } from 'react-router-dom';
import { useT } from '../../i18n/hooks';
import { formatDecimal } from '../../i18n/numberFormat';
import { ntfpHarvestApi, type NtfpHarvestPlan, type NtfpHarvestRow } from '../../services/api';
import { apiErrorText } from '../../lib/apiErrorText';
import {
  aahQuantity, errorKey, harvestDirty, harvestKey, harvestPayload, harvestProblem, initialEdit, partKey, quantityFromShare, shareFromQuantity, sourceLine, stockOf, valueOf,
  type HarvestEdit, type WeightBasis,
} from '../../lib/ntfp';

interface Props {
  calculationId: string;
  /** bump to re-read after the survey records change */
  refreshKey: number;
  /** told whenever the plan is read or saved (the page's steps strip shows whether a harvest is planned) */
  onPlan?: (plan: NtfpHarvestPlan) => void;
}

/** The link to another page of the workspace. `useNavigate` needs a Router: without one (tests, embeds) the link is not offered. */
function PageLink({ calculationId, surface, children }: { calculationId: string; surface: string; children: string }) {
  const inRouter = useInRouterContext();
  return inRouter ? <RoutedLink calculationId={calculationId} surface={surface}>{children}</RoutedLink> : <span>{children}</span>;
}
function RoutedLink({ calculationId, surface, children }: { calculationId: string; surface: string; children: string }) {
  const navigate = useNavigate();
  return <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/calculations/${calculationId}?surface=${surface}`)}>{children}</Button>;
}

export default function NtfpHarvestPanel({ calculationId, refreshKey, onPlan }: Props) {
  const t = useT();
  const [plan, setPlan] = useState<NtfpHarvestPlan | null>(null);
  const [edits, setEdits] = useState<Record<string, HarvestEdit>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [linking, setLinking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linked, setLinked] = useState<{ created: boolean; quantity: number } | null>(null);
  const [needsDesign, setNeedsDesign] = useState(false);

  const planCallback = useRef(onPlan);   // a ref: a new inline callback from the parent must not make `adopt` (and so the loading effect) change every render
  planCallback.current = onPlan;
  const adopt = useCallback((p: NtfpHarvestPlan) => {
    setPlan(p);
    planCallback.current?.(p);
    const next: Record<string, HarvestEdit> = {};
    p.rows.forEach((r) => { next[harvestKey(r)] = initialEdit(r); });
    setEdits(next);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      adopt(await ntfpHarvestApi.get(calculationId));
      setNeedsDesign(false);
    } catch (err: any) {
      setPlan(null);
      if (err?.response?.data?.detail?.code === 'no_design') setNeedsDesign(true);
      else setError(apiErrorText(err, t('ntfp.error.generic')));
    } finally {
      setLoading(false);
    }
  }, [calculationId, adopt, t]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const fail = (err: any) => {
    const key = errorKey(err?.response?.data?.detail?.code);
    setError(key ? t(key) : apiErrorText(err, t('ntfp.error.generic')));
  };

  const edit = (row: NtfpHarvestRow, patch: Partial<HarvestEdit>) => {
    const k = harvestKey(row);
    setEdits((cur) => ({ ...cur, [k]: { ...(cur[k] ?? initialEdit(row)), ...patch } }));
  };

  const rows = plan?.rows ?? [];
  const problems = rows.filter((r) => {
    const e = edits[harvestKey(r)];
    return e && harvestProblem(stockOf(r, e.basis), e.quantity, e.unit) !== null;
  });
  const dirty = harvestDirty(rows, edits);

  const save = async () => {
    setSaving(true);
    setError(null);
    setLinked(null);
    try {
      adopt(await ntfpHarvestApi.save(calculationId, harvestPayload(rows, edits)));
      message.success(t('ntfp.harvest.saved'));
    } catch (err) {
      fail(err);
    } finally {
      setSaving(false);
    }
  };

  const toYearly = async () => {
    setLinking(true);
    setError(null);
    try {
      const r = await ntfpHarvestApi.toYearlyPlan(calculationId);
      setLinked({ created: r.created, quantity: r.quantity });
    } catch (err) {
      fail(err);
    } finally {
      setLinking(false);
    }
  };

  if (loading && !plan) return null;
  if (needsDesign) return <Alert type="info" showIcon title={t('ntfp.results.needDesign')} />;
  if (!plan) return error ? <Alert type="error" showIcon title={error} /> : null;
  if (rows.length === 0) return <Alert type="info" showIcon title={t('ntfp.harvest.noRows')} />;

  const n = (v: number | null | undefined, d = 0) => (v == null ? '—' : formatDecimal(v, d));

  return (
    <div>
      <p style={{ maxWidth: 860 }}>{t('ntfp.harvest.intro')}</p>
      <Alert type="info" showIcon style={{ margin: '8px 0 12px' }} title={t('ntfp.harvest.basisNote')} />
      {error && <Alert type="error" showIcon style={{ marginBottom: 12 }} title={error} closable onClose={() => setError(null)} />}
      <Table<NtfpHarvestRow> size="small" pagination={false} rowKey={harvestKey} dataSource={rows}
        columns={[
          { title: t('ntfp.species.colName'), key: 'n', render: (_: unknown, r) => (
            <div><strong>{r.nepali_name}</strong><div style={{ fontStyle: 'italic', fontSize: 12 }}>{r.scientific_name ?? ''}</div></div>
          ) },
          { title: t('ntfp.results.colPart'), dataIndex: 'part_group', render: (g: string) => t(`ntfp.part.${partKey(g)}`) },
          { title: t('ntfp.harvest.colStock'), key: 's', render: (_: unknown, r) => (
            <div style={{ fontSize: 12 }}>
              <div>{t('ntfp.results.dry')}: {n(r.stock_dry_kg)} kg</div>
              <div>{t('ntfp.results.fresh')}: {n(r.stock_fresh_kg)} kg</div>
            </div>
          ) },
          { title: t('ntfp.harvest.colBasis'), key: 'b', render: (_: unknown, r) => {
            const e = edits[harvestKey(r)] ?? initialEdit(r);
            return <Select size="small" style={{ width: 90 }} value={e.basis} onChange={(v: WeightBasis) => edit(r, { basis: v })} aria-label={t('ntfp.harvest.colBasis')}
              options={[{ value: 'dry', label: t('ntfp.results.dry'), disabled: r.stock_dry_kg == null }, { value: 'fresh', label: t('ntfp.results.fresh') }]} />;
          } },
          { title: t('ntfp.harvest.colAah'), key: 'aah', render: (_: unknown, r) => {
            const e = edits[harvestKey(r)] ?? initialEdit(r);
            const q = aahQuantity(stockOf(r, e.basis), r.aah);
            if (!r.aah) return <span style={{ fontSize: 12 }}>{t('ntfp.harvest.noAah')}</span>;
            const pct = r.aah.pct_max !== r.aah.pct_min ? `${r.aah.pct_min}-${r.aah.pct_max}` : String(r.aah.pct_min);
            return (
              <div style={{ fontSize: 12 }}>
                <Tooltip title={[r.aah.source_title, r.aah.note].filter(Boolean).join(' — ')}><span>{pct} % <Tag>{sourceLine({ source_key: r.aah.source_key, source_year: null, locator: r.aah.locator })}</Tag></span></Tooltip>
                {q && e.unit === 'kg' && (
                  <div><Button size="small" type="link" style={{ padding: 0 }} aria-label={t('ntfp.harvest.useAah')} onClick={() => edit(r, { quantity: q.low })}>
                    {t('ntfp.harvest.useAah')} ({q.low}{q.high !== q.low ? `-${q.high}` : ''} kg)
                  </Button></div>
                )}
              </div>
            );
          } },
          { title: t('ntfp.harvest.colShare'), key: 'sh', render: (_: unknown, r) => {
            const e = edits[harvestKey(r)] ?? initialEdit(r);
            return <InputNumber size="small" style={{ width: 84 }} min={0} max={100} step={1} suffix="%" aria-label={t('ntfp.harvest.colShare')}
              value={shareFromQuantity(stockOf(r, e.basis), e.quantity) ?? undefined}
              onChange={(v) => edit(r, { quantity: v == null ? null : quantityFromShare(stockOf(r, e.basis), Number(v)) })} />;
          } },
          { title: t('ntfp.harvest.colQuantity'), key: 'q', render: (_: unknown, r) => {
            const e = edits[harvestKey(r)] ?? initialEdit(r);
            const problem = harvestProblem(stockOf(r, e.basis), e.quantity, e.unit);
            return <InputNumber size="small" style={{ width: 110 }} min={0} step={10} value={e.quantity ?? undefined} suffix={e.unit === 'piece' ? t('ntfp.harvest.piece') : 'kg'}
              status={problem ? 'error' : undefined} aria-label={t('ntfp.harvest.colQuantity')} onChange={(v) => edit(r, { quantity: v == null ? null : Number(v) })} />;
          } },
          { title: t('ntfp.harvest.colRate'), key: 'r', render: (_: unknown, r) => {
            const e = edits[harvestKey(r)] ?? initialEdit(r);
            const rate = r.price;
            return (
              <div style={{ fontSize: 12 }}>
                {rate ? <Tooltip title={rate.note}><span>Rs {rate.npr_per_unit}/{rate.unit}{rate.estimated && <Tag color="orange" style={{ marginLeft: 4 }}>{t('ntfp.species.estimated')}</Tag>}</span></Tooltip> : '—'}
                <div><InputNumber size="small" style={{ width: 96 }} min={0} placeholder={t('ntfp.harvest.ownPrice')} value={e.price ?? undefined}
                  aria-label={t('ntfp.harvest.ownPrice')} onChange={(v) => edit(r, { price: v == null ? null : Number(v) })} /></div>
              </div>
            );
          } },
          { title: t('ntfp.harvest.colValue'), key: 'v', render: (_: unknown, r) => {
            const e = edits[harvestKey(r)] ?? initialEdit(r);
            const price = e.price ?? r.price?.npr_per_unit ?? null;
            const problem = harvestProblem(stockOf(r, e.basis), e.quantity, e.unit);
            return problem ? <Tag color="red">{t(problem === 'exceedsStock' ? 'ntfp.harvest.exceedsStock' : 'ntfp.harvest.negative')}</Tag> : n(valueOf(e.quantity, price));
          } },
        ]} />
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', marginTop: 12 }}>
        <span>{t('ntfp.harvest.totals', { kg: n(plan.totals.kg_per_year), npr: n(plan.totals.value_npr_per_year), rows: plan.totals.rows_planned })}</span>
        <Space style={{ marginLeft: 'auto' }}>
          <Button type="primary" onClick={save} loading={saving} disabled={!dirty || problems.length > 0}>{t('ntfp.harvest.save')}</Button>
          <Tooltip title={dirty ? t('ntfp.harvest.saveFirst') : undefined}>
            <Button onClick={toYearly} loading={linking} disabled={dirty || plan.totals.kg_per_year <= 0}>{t('ntfp.harvest.toYearly')}</Button>
          </Tooltip>
        </Space>
      </div>
      {linked && (
        <Alert type={linked.created ? 'success' : 'warning'} showIcon style={{ marginTop: 12 }}
          title={t(linked.created ? 'ntfp.harvest.yearlyMade' : 'ntfp.harvest.yearlyExists', { kg: n(linked.quantity) })} />
      )}
      <p style={{ marginTop: 16, fontSize: 13 }}>
        {t('ntfp.harvest.cbaNote')} <PageLink calculationId={calculationId} surface="analysis/cba">{t('ntfp.harvest.openCba')}</PageLink>
        {' · '}<PageLink calculationId={calculationId} surface="plan/yearly">{t('ntfp.harvest.openYearly')}</PageLink>
      </p>
    </div>
  );
}
