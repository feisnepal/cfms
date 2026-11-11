/**
 * SfmSummaryBar — forest-level roll-up for the SFM tab
 * (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P4).
 *
 * Dominant type, source badge, production / protection area, and the
 * growing-stock allowable harvest (label: उत्पादन नियमन अनुसारको वार्षिक कटान
 * परिमाण). This number is NOT the MAI→AAH figure — it sits beside it.
 */
import { SfmTypeTag } from './SfmTypeTag';
import React from 'react';
import { Tag } from 'antd';
import { useT } from '../../i18n/hooks';
import type { SfmSummaryResponse } from '../../services/api';
import { SfmVarChip } from './SfmVarChip';

interface Props {
  summary: SfmSummaryResponse;
}

const SOURCE_COLOR: Record<string, string> = {
  stem_mapping: 'green',
  field_inventory: 'blue',
  prior: 'orange',
  mixed: 'purple',
};

const fmt = (n: number | null | undefined, dp = 1): string =>
  n === null || n === undefined || Number.isNaN(n) ? '—' : n.toFixed(dp);

const Stat: React.FC<{ label: string; value: React.ReactNode; tokenKey?: string }> = ({
  label,
  value,
  tokenKey,
}) => (
  <div style={{ minWidth: 140 }}>
    <div style={{ fontSize: 11, color: '#888', textTransform: 'uppercase', letterSpacing: 0.4 }}>
      {label}
      {tokenKey && <SfmVarChip tokenKey={tokenKey} />}
    </div>
    <div style={{ fontSize: 18, fontWeight: 600 }}>{value}</div>
  </div>
);

export const SfmSummaryBar: React.FC<Props> = ({ summary }) => {
  const t = useT();
  const fs = summary.forest_summary;
  const source = summary.source ?? 'prior';

  return (
    <div
      style={{
        display: 'flex',
        gap: 24,
        flexWrap: 'wrap',
        alignItems: 'flex-start',
        padding: 16,
        background: '#fafafa',
        border: '1px solid #f0f0f0',
        borderRadius: 8,
      }}
    >
      <Stat
        label={t('sfm.summary.dominantType')}
        tokenKey="sfm_dominant_type_ne"
        value={
          fs.dominant_type_no ? (
            <>
              <SfmTypeTag n={fs.dominant_type_no} />
            </>
          ) : (
            '—'
          )
        }
      />
      <Stat
        label={t('sfm.summary.source')}
        value={
          <Tag color={SOURCE_COLOR[source] ?? 'default'}>
            {t(`sfm.source.${source}`, source)}
          </Tag>
        }
      />
      <Stat
        label={t('sfm.summary.productionArea')}
        tokenKey="sfm_production_area_ha"
        value={`${fmt(fs.production_area_ha)} ${t('sfm.unit.ha')}`}
      />
      <Stat
        label={t('sfm.summary.protectionArea')}
        tokenKey="sfm_protection_area_ha"
        value={`${fmt(fs.protection_area_ha)} ${t('sfm.unit.ha')}`}
      />
      <Stat
        label={t('sfm.summary.allowableHarvest')}
        tokenKey="sfm_total_annual_harvest_m3"
        value={
          <span>
            {fmt(fs.total_annual_harvest_m3)} {t('sfm.unit.m3PerYear')}
          </span>
        }
      />
    </div>
  );
};

export default SfmSummaryBar;
