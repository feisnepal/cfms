/**
 * HazardErosionTab — the dedicated "Hazard & Erosion" context in the calc
 * shell (HAZARD_EROSION_CONTEXT_PLAN.md P1).
 *
 * P1 is the shell: fetch the aggregator summary, render the header (physiography
 * zone + prereq pills + Recompute) and the empty-state. The map panel /
 * parameter panel / tables / narration mount below in P2–P5.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Tag, Button, Spin, Alert, Result, Tooltip, Space, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { useT } from '../../i18n/hooks';
import {
  hazardErosionApi,
  type HazardErosionSummary,
  type HazardErosionPrereq,
} from '../../services/api';
import HazardMapPanel from './HazardMapPanel';
import HazardParamsPanel from './HazardParamsPanel';
import HazardTables from './HazardTables';
import HazardNarration from './HazardNarration';
import HazardChartsPanel from './HazardChartsPanel';
import { HazardVarChip, HazardVarCopyMenu } from './HazardVarChip';

// P4 — the ordered token block the "Copy variables ▾" menu emits, mirroring
// the analysis-page layout (also what P5 lays into the seed template).
const VAR_MENU_GROUPS = [
  {
    labelKey: 'hazardErosion.varChip.grpNumbers',
    keys: [
      'hazard_erosion_mean_t_ha', 'hazard_erosion_pct_above_tolerable', 'hazard_erosion_dominant_factor',
      'hazard_landslide_prone_area_pct', 'hazard_landslide_high_units',
      'hazard_slope_unstable_pct', 'hazard_slope_marginal_pct',
      'hazard_household_count', 'hazard_household_priority_count', 'hazard_household_coord_source',
    ],
  },
  {
    labelKey: 'hazardErosion.varChip.grpMaps',
    keys: [
      'thememap:soil__annual_loss', 'thememap:hazard__landslide_susceptibility',
      'thememap:hazard__landslide_prone_area', 'thememap:hazard__factor_of_safety',
      'thememap:hh__vulnerability',
    ],
  },
  {
    labelKey: 'hazardErosion.varChip.grpTables',
    keys: [
      'hazard_erosion_by_unit_table', 'hazard_erosion_aoi_comparison_table',
      'hazard_landslide_area_by_class_table', 'hazard_landslide_by_unit_table',
      'hazard_slope_by_unit_table', 'hazard_landslide_aoi_comparison_table',
      'hazard_household_priority_table', 'hazard_household_settlement_rollup_table',
      'hazard_household_driver_counts_table',
    ],
  },
  {
    labelKey: 'hazardErosion.varChip.grpCharts',
    keys: [
      'chart:hazard_landslide_area_by_class', 'chart:hazard_slope_class_split',
      'chart:hazard_household_driver_split', 'chart:hazard_erosion_aoi_comparison',
    ],
  },
  {
    labelKey: 'hazardErosion.varChip.grpNarration',
    keys: [
      'hazard_erosion_full_narration',
      'hazard_erosion_methodology_narration', 'hazard_erosion_findings_narration',
      'hazard_erosion_prescription_narration',
      'hazard_methodology_narration', 'hazard_findings_narration', 'hazard_prescription_narration',
    ],
  },
];

interface Props {
  calculationId: string;
}

const PILL_COLOR: Record<HazardErosionPrereq['status'], string> = {
  available: 'green',
  partial: 'orange',
  unavailable: 'red',
};

const PrereqPill: React.FC<{ p: HazardErosionPrereq; label: string }> = ({ p, label }) => (
  <Tooltip title={p.met ? undefined : p.reason_en || p.hint_en}>
    <Tag color={PILL_COLOR[p.status]} style={{ marginInlineEnd: 4 }}>
      {label}
      {p.met ? ' ✓' : ''}
    </Tag>
  </Tooltip>
);

const num = (v: number | null, dp = 1): string =>
  v === null || v === undefined ? '—' : v.toFixed(dp);

export const HazardErosionTab: React.FC<Props> = ({ calculationId }) => {
  const t = useT();
  const { i18n } = useTranslation();
  const [summary, setSummary] = useState<HazardErosionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [recomputing, setRecomputing] = useState(false);
  const [paramsNonce, setParamsNonce] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      setSummary(await hazardErosionApi.summary(calculationId));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    load();
  }, [load]);

  const recompute = async () => {
    setRecomputing(true);
    try {
      await hazardErosionApi.recompute(calculationId);
      message.success(t('hazardErosion.recomputeDone'));
      await load();
    } catch {
      message.error(t('hazardErosion.recomputeFailed'));
    } finally {
      setRecomputing(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Spin tip={t('hazardErosion.loading')} />
      </div>
    );
  }

  if (error || !summary) {
    return (
      <div style={{ padding: 24 }}>
        <Alert
          type="error"
          message={t('hazardErosion.loadFailed')}
          action={
            <Button size="small" onClick={load}>
              {t('hazardErosion.retry')}
            </Button>
          }
        />
      </div>
    );
  }

  const { soil, hazard, prereqs, maps } = summary;
  const anyPrereqMet = prereqs.some((p) => p.met);

  return (
    <div style={{ padding: 20, maxWidth: 1100 }}>
      {/* ── header ─────────────────────────────────────────────── */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          flexWrap: 'wrap',
          marginBottom: 12,
        }}
      >
        <div>
          <h3 style={{ margin: 0 }}>{t('hazardErosion.title')}</h3>
          <span style={{ fontSize: 12, color: '#888' }}>
            {summary.forest_name}
            {' · '}
            {summary.physiography_zone || t('hazardErosion.zoneUnknown')}
          </span>
        </div>
        <Space size={4} wrap>
          {prereqs.map((p) => (
            <PrereqPill
              key={p.tag}
              p={p}
              label={t(`hazardErosion.prereq.${p.tag}`)}
            />
          ))}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={recomputing}
            onClick={recompute}
          >
            {recomputing ? t('hazardErosion.recomputing') : t('hazardErosion.recompute')}
          </Button>
          <HazardVarCopyMenu groups={VAR_MENU_GROUPS} />
        </Space>
      </div>

      {/* ── body ───────────────────────────────────────────────── */}
      {!anyPrereqMet ? (
        <Result
          status="info"
          title={t('hazardErosion.empty.title')}
          subTitle={
            <div style={{ textAlign: 'left', maxWidth: 640, margin: '0 auto' }}>
              <p>{t('hazardErosion.empty.body')}</p>
              <ul style={{ fontSize: 13, color: '#666' }}>
                {prereqs
                  .filter((p) => !p.met)
                  .map((p) => (
                    <li key={p.tag}>
                      <b>{t(`hazardErosion.prereq.${p.tag}`)}</b> — {p.reason_en}{' '}
                      <i>{p.hint_en}</i>
                    </li>
                  ))}
              </ul>
            </div>
          }
        />
      ) : (
        <>
          <Space direction="vertical" size={4} style={{ marginBottom: 16 }}>
            {soil.available ? (
              <span>
                {t('hazardErosion.soilLine', {
                  mean: num(soil.mean_t_ha, 2),
                  pct: num(soil.pct_above_tolerable),
                })}
                {soil.customised ? ' •' : ''}
                <HazardVarChip tokenKey="hazard_erosion_mean_t_ha" />
                <HazardVarChip tokenKey="hazard_erosion_pct_above_tolerable" />
                <HazardVarChip tokenKey="hazard_erosion_dominant_factor" />
              </span>
            ) : (
              <span style={{ color: '#999' }}>
                RUSLE — {t('hazardErosion.notComputed')}
              </span>
            )}
            {hazard.available ? (
              <>
                <span>
                  {t('hazardErosion.hazardLine', {
                    prone: num(hazard.lsi_prone_pct),
                    marginal: num(hazard.fs_marginal_pct),
                    priority: hazard.hh_priority_count,
                    total: hazard.hh_count,
                  })}
                  {hazard.customised ? ' •' : ''}
                  <HazardVarChip tokenKey="hazard_landslide_prone_area_pct" />
                  <HazardVarChip tokenKey="hazard_slope_marginal_pct" />
                  <HazardVarChip tokenKey="hazard_household_priority_count" />
                  <HazardVarChip tokenKey="hazard_household_count" />
                  <HazardVarChip tokenKey="hazard_household_coord_source" />
                </span>
                {hazard.hh_count > 0 &&
                  !hazard.hazard_layer_informative &&
                  hazard.hh_coord_source !== 'building_footprint' &&
                  hazard.hh_coord_source !== 'settlement_centroid' &&
                  hazard.hh_coord_source !== 'mixed' && (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ fontSize: 12 }}
                      message={t('hazardErosion.hazardNotInformative')}
                    />
                  )}
                {(hazard.hh_coord_source === 'building_footprint' ||
                  hazard.hh_coord_source === 'settlement_centroid' ||
                  hazard.hh_coord_source === 'mixed') && (
                  <Alert
                    type="info"
                    showIcon
                    style={{ fontSize: 12 }}
                    message={t(hazard.hh_basis === 'buildings' ? 'hazardErosion.hazardFromBuildings' : hazard.hh_coord_source === 'mixed' ? 'hazardErosion.hazardFromMixed' : 'hazardErosion.hazardFromFootprints')}
                  />
                )}
              </>
            ) : (
              <span style={{ color: '#999' }}>
                LSI / FS / {t('hazardErosion.title')} — {t('hazardErosion.notComputed')}
              </span>
            )}
          </Space>

          {/* P3 — parameter panel */}
          <div style={{ marginBottom: 16 }}>
            <HazardParamsPanel
              calculationId={calculationId}
              onSaved={() => {
                setParamsNonce((n) => n + 1);
                load();
              }}
            />
          </div>

          {/* P2 — map panel */}
          <HazardMapPanel
            calculationId={calculationId}
            maps={maps}
            hasUserGroup={summary.has_user_group}
            lang={i18n.language}
            refreshKey={paramsNonce}
          />

          {/* P4 — tables */}
          <HazardTables calculationId={calculationId} refreshKey={paramsNonce} />

          {/* charts (HAZARD_EROSION_VARIABLE_COVERAGE_PLAN P4) */}
          <HazardChartsPanel calculationId={calculationId} refreshKey={paramsNonce} />

          {/* P5 — narration + OP insert */}
          <HazardNarration calculationId={calculationId} lang={i18n.language} />
        </>
      )}
    </div>
  );
};

export default HazardErosionTab;
