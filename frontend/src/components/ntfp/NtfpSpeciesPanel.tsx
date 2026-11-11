/** NtfpSpeciesPanel — choose the NTFP species to inventory and, if wanted, change their plot size and intensity. */
import { useMemo, useState } from 'react';
import { Alert, Button, Input, InputNumber, Select, Switch, Table, Tag, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useT } from '../../i18n/hooks';
import type { NtfpSpecies } from '../../services/api';
import { cardStatusColour, cardStatusKey, emptyPick, GROWTH_CLASSES, matchesCardFilter, needsGrowthClass, partKey, type CardFilter, type NtfpPick } from '../../lib/ntfp';
import NtfpCardDetail from './NtfpCardDetail';

interface Props {
  calculationId: string;
  species: NtfpSpecies[];
  loading: boolean;
  forestAreaHa: number | null;
  picks: Record<string, NtfpPick>;
  onPicks: (next: Record<string, NtfpPick>) => void;
  query: string;
  onQuery: (q: string) => void;
  onlyWithCard: boolean;
  onOnlyWithCard: (v: boolean) => void;
  onNext: () => void;
  locked: boolean;
}

const METHOD_COLOUR: Record<string, string> = { destructive: 'red', semi_destructive: 'orange', non_destructive: 'green' };
const METHOD_KEY: Record<string, string> = {
  destructive: 'ntfp.species.methodDestructive',
  semi_destructive: 'ntfp.species.methodSemi',
  non_destructive: 'ntfp.species.methodNon',
};

export default function NtfpSpeciesPanel({ calculationId, species, loading, forestAreaHa, picks, onPicks, query, onQuery, onlyWithCard, onOnlyWithCard, onNext, locked }: Props) {
  const t = useT();
  const selected = useMemo(() => Object.keys(picks), [picks]);
  const [cardFilter, setCardFilter] = useState<CardFilter>('all');
  const shown = useMemo(() => species.filter((sp) => matchesCardFilter(sp, cardFilter)), [species, cardFilter]);

  const setPick = (key: string, patch: Partial<NtfpPick>) => onPicks({ ...picks, [key]: { ...(picks[key] ?? emptyPick()), ...patch } });

  const columns: ColumnsType<NtfpSpecies> = [
    {
      title: t('ntfp.species.colName'),
      key: 'name',
      render: (_: unknown, sp) => (
        <div>
          <strong>{sp.nepali_name}</strong>
          {sp.priority_serial != null && <Tag color="gold" style={{ marginLeft: 6 }}>{t('ntfp.species.priority')}</Tag>}
          <div style={{ fontStyle: 'italic', fontSize: 12 }}>
            {sp.scientific_name ?? '—'}
            {sp.aliases.length > 0 && (
              <Tooltip title={t('ntfp.species.aliasHint', { names: sp.aliases.join(', ') })}>
                <span style={{ marginLeft: 6, cursor: 'help' }}>ⓘ</span>
              </Tooltip>
            )}
          </div>
        </div>
      ),
    },
    {
      title: t('ntfp.species.colForm'),
      key: 'form',
      render: (_: unknown, sp) => (
        <div>
          {sp.growth_class ? <Tag>{t(`ntfp.growth.${sp.growth_class}`)}</Tag> : <Tag color="default">{t('ntfp.species.noCard')}</Tag>}
          <div style={{ fontSize: 12 }}>{sp.part_ne ?? ''}</div>
        </div>
      ),
    },
    {
      title: t('ntfp.species.colMethod'),
      key: 'method',
      render: (_: unknown, sp) => (sp.sampling_method ? <Tag color={METHOD_COLOUR[sp.sampling_method]}>{t(METHOD_KEY[sp.sampling_method])}</Tag> : '—'),
    },
    {
      title: t('ntfp.species.colCard'),
      key: 'card',
      render: (_: unknown, sp) => (
        <div>
          <Tag color={cardStatusColour(sp.card_status)}>{t(cardStatusKey(sp.card_status))}</Tag>
          {sp.aah.length > 0 && (
            <Tooltip title={sp.aah.map((a) => `${a.source_key}${a.locator ? `, ${a.locator}` : ''}`).join('; ')}>
              <div style={{ fontSize: 12 }}>{t('ntfp.species.aahShort', { pct: sp.aah.map((a) => (a.value_num2 != null && a.value_num2 !== a.value_num ? `${a.value_num}-${a.value_num2}` : String(a.value_num))).join(' / ') })}</div>
            </Tooltip>
          )}
        </div>
      ),
    },
    {
      title: t('ntfp.species.colDefaults'),
      key: 'defaults',
      render: (_: unknown, sp) =>
        sp.default_plot_sqm != null ? (
          <span>
            {t('ntfp.species.plotSqm', { n: sp.default_plot_sqm })}
            {sp.default_intensity_pct != null && <> · {t('ntfp.species.intensityPct', { n: sp.default_intensity_pct })}</>}
          </span>
        ) : '—',
    },
    {
      title: t('ntfp.species.colPrice'),
      key: 'price',
      render: (_: unknown, sp) =>
        sp.prices.length === 0 ? '—' : (
          <div>
            {sp.prices.map((p) => (
              <div key={p.group} style={{ fontSize: 12 }}>
                {t('ntfp.species.priceLine', { part: t(`ntfp.part.${partKey(p.group)}`), price: p.price, unit: p.unit })}
                {p.estimated && (
                  <Tooltip title={p.basis_note}>
                    <Tag color="orange" style={{ marginLeft: 4 }}>{t('ntfp.species.estimated')}</Tag>
                  </Tooltip>
                )}
              </div>
            ))}
          </div>
        ),
    },
    {
      title: t('ntfp.species.colYours'),
      key: 'yours',
      width: 300,
      render: (_: unknown, sp) => {
        const pick = picks[sp.species_key];
        if (!pick) return null;
        return (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {needsGrowthClass(sp, pick) || !sp.growth_class ? (
              <Select
                size="small" style={{ width: 110 }} value={pick.growth_class ?? undefined} placeholder={t('ntfp.species.growthPlaceholder')}
                status={needsGrowthClass(sp, pick) ? 'error' : undefined}
                options={GROWTH_CLASSES.map((g) => ({ value: g, label: t(`ntfp.growth.${g}`) }))}
                onChange={(v) => setPick(sp.species_key, { growth_class: v })} aria-label={t('ntfp.species.growthPlaceholder')}
              />
            ) : null}
            <InputNumber size="small" style={{ width: 96 }} min={1} step={1} value={pick.plot_sqm ?? undefined} placeholder={String(sp.default_plot_sqm ?? 25)}
              suffix="m²" onChange={(v) => setPick(sp.species_key, { plot_sqm: v == null ? null : Number(v) })} aria-label={t('ntfp.species.plotSize')} />
            <InputNumber size="small" style={{ width: 96 }} min={0.001} max={100} step={0.05} value={pick.intensity_pct ?? undefined}
              placeholder={String(sp.default_intensity_pct ?? '')} suffix="%"
              onChange={(v) => setPick(sp.species_key, { intensity_pct: v == null ? null : Number(v) })} aria-label={t('ntfp.species.intensity')} />
          </div>
        );
      },
    },
  ];

  return (
    <div>
      <p style={{ marginBottom: 12 }}>{t('ntfp.species.intro')}</p>
      {forestAreaHa != null && <Alert type="info" showIcon style={{ marginBottom: 12 }} title={t('ntfp.species.areaNote', { ha: Math.round(forestAreaHa * 10) / 10 })} />}
      {locked && <Alert type="warning" showIcon style={{ marginBottom: 12 }} title={t('ntfp.species.locked')} />}
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <Input.Search allowClear style={{ maxWidth: 320 }} placeholder={t('ntfp.species.search')} defaultValue={query} onSearch={onQuery} aria-label={t('ntfp.species.search')} />
        <span><Switch checked={onlyWithCard} onChange={onOnlyWithCard} aria-label={t('ntfp.species.onlyCards')} /> {t('ntfp.species.onlyCards')}</span>
        <Select<CardFilter> style={{ width: 190 }} value={cardFilter} onChange={setCardFilter} aria-label={t('ntfp.species.cardFilter')}
          options={[
            { value: 'all', label: t('ntfp.species.filterAll') }, { value: 'documented', label: t('ntfp.card.statusDocumented') },
            { value: 'provisional', label: t('ntfp.card.statusProvisional') }, { value: 'expert_confirmed', label: t('ntfp.card.statusConfirmed') },
            { value: 'none', label: t('ntfp.species.filterNone') },
          ]} />
        <span style={{ marginLeft: 'auto' }}>{t('ntfp.species.selectedCount', { n: selected.length })}</span>
        <Button type="primary" disabled={selected.length === 0} onClick={onNext}>{t('ntfp.species.toDesign')}</Button>
      </div>
      <Table<NtfpSpecies>
        rowKey="species_key" size="small" loading={loading} columns={columns} dataSource={shown}
        expandable={{ expandedRowRender: (sp) => <NtfpCardDetail calculationId={calculationId} speciesKey={sp.species_key} />, rowExpandable: (sp) => sp.has_method_card || sp.aah.length > 0 || sp.season.length > 0 }}
        pagination={{ pageSize: 15, showSizeChanger: false }}
        rowSelection={{
          selectedRowKeys: selected,
          preserveSelectedRowKeys: true,
          getCheckboxProps: () => ({ disabled: locked }),
          onChange: (keys) => {
            const next: Record<string, NtfpPick> = {};
            for (const k of keys as string[]) next[k] = picks[k] ?? emptyPick();
            onPicks(next);
          },
        }}
        locale={{ emptyText: t('ntfp.species.empty') }}
      />
    </div>
  );
}
