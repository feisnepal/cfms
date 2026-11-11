/**
 * SfmPrescriptionCard — the statutory prescription for the selected block's
 * felling series (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4).
 *
 * Silvicultural system, felling / rotation cycle, regeneration method + period,
 * mother-tree target, N/C/R structuring, and the yield line
 * (GS≥40 → matched step → % → annual harvest) with the full अनुसूची note.
 */
import { SfmTypeTag } from './SfmTypeTag';
import React from 'react';
import { Card, Descriptions, Empty, Tag } from 'antd';
import { useT } from '../../i18n/hooks';
import type { SfmBlock, SfmFellingSeries } from '../../services/api';

interface Props {
  block: SfmBlock | null;
  series: SfmFellingSeries | null;
  lang: string;
}

const fmt = (n: number | null | undefined, dp = 1): string =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : n.toFixed(dp);

const motherTarget = (v: number[] | number | null | undefined): string => {
  if (v == null) return '—';
  if (Array.isArray(v)) return `${v[0]}–${v[1]}`;
  return String(v);
};

export const SfmPrescriptionCard: React.FC<Props> = ({ block, series, lang }) => {
  const t = useT();
  const ne = lang.startsWith('ne');

  // A block with no type (not forest land, or no sample plots of its own) has nothing to prescribe: say why
  if (block && !block.prescription) {
    return (
      <Card size="small" title={`${t('sfm.card.heading')} · ${block.block_name}`}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t(block.state === 'non_forest' ? 'sfm.card.noTypeNonForest' : 'sfm.card.noTypeMissing')}
        />
      </Card>
    );
  }

  if (!block || !block.prescription) {
    return (
      <Card size="small" title={t('sfm.card.heading')}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t('sfm.card.pickBlock')}
        />
      </Card>
    );
  }

  const p = block.prescription;
  const gs = series?.gs_ge40_m3_per_ha ?? p.gs_ge40_m3_per_ha ?? null;
  const pct = series?.pct ?? p.yield_pct ?? null;
  const harvest = series?.annual_harvest_m3 ?? null;

  return (
    <Card
      size="small"
      title={
        <span>
          {t('sfm.card.heading')} · {block.block_name}
          <Tag style={{ marginInlineStart: 8 }}>
            {block.effective_type_no != null ? <SfmTypeTag n={block.effective_type_no} /> : t(`sfm.state.${block.state === 'non_forest' ? 'nonForest' : 'inventoryMissing'}`)}
          </Tag>
        </span>
      }
    >
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {ne ? p.type_name_ne : p.type_name_en}
      </div>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label={t('sfm.card.system')}>
          {ne ? p.system_ne : p.system_en}
        </Descriptions.Item>
        <Descriptions.Item label={t('sfm.card.branch')}>
          {t(`sfm.branch.${p.branch}`, p.branch)}
        </Descriptions.Item>
        {(p.felling_cycle_years ?? null) !== null && (
          <Descriptions.Item label={t('sfm.card.fellingCycle')}>
            {p.felling_cycle_years} {t('sfm.unit.yr')}
          </Descriptions.Item>
        )}
        {(p.regeneration_period_years ?? null) !== null && (
          <Descriptions.Item label={t('sfm.card.regenPeriod')}>
            {p.regeneration_period_years} {t('sfm.unit.yr')}
          </Descriptions.Item>
        )}
        {(p.rotation_years ?? null) !== null && (
          <Descriptions.Item label={t('sfm.card.rotation')}>
            {p.rotation_years} {t('sfm.unit.yr')}
          </Descriptions.Item>
        )}
        {(p.regen_method_ne || p.regen_method_en) && (
          <Descriptions.Item label={t('sfm.card.regenMethod')}>
            {ne ? p.regen_method_ne : p.regen_method_en}
          </Descriptions.Item>
        )}
        {p.method === 'shelterwood_periodic_block' && (
          <Descriptions.Item label={t('sfm.card.motherTrees')}>
            {motherTarget(p.mother_tree_target)} / {t('sfm.unit.ha')}
          </Descriptions.Item>
        )}
        {series && (
          <Descriptions.Item label={t('sfm.card.structuring')}>
            {[
              series.N != null ? `N ${series.N}` : null,
              series.C != null ? `C ${series.C}` : null,
              series.R != null ? `R ${series.R}` : null,
              series.annual_felling_area_ha != null
                ? `${fmt(series.annual_felling_area_ha)} ${t('sfm.unit.haPerYear')}`
                : null,
            ]
              .filter(Boolean)
              .join(' · ') || '—'}
          </Descriptions.Item>
        )}
        <Descriptions.Item label={t('sfm.card.yieldLine')}>
          {t('sfm.card.yieldFormula', {
            gs: fmt(gs, 1),
            pct: pct == null ? '—' : `${pct}`,
            harvest: fmt(harvest, 1),
          })}
        </Descriptions.Item>
      </Descriptions>
      {(ne ? p.note_ne : p.note_en) && (
        <p style={{ marginTop: 10, fontSize: 12, color: '#666' }}>
          {ne ? p.note_ne : p.note_en}
        </p>
      )}
    </Card>
  );
};

export default SfmPrescriptionCard;
