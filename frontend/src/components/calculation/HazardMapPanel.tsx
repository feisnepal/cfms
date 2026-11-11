/**
 * HazardMapPanel — the map switcher for the Hazard & Erosion context
 * (HAZARD_EROSION_CONTEXT_PLAN.md P2).
 *
 * A `<Select>` over the per-forest map list from the summary (primary maps +
 * an "Annex" group for the R/K/LS/C and LSI factor bands), a CF ↔ User-group
 * toggle that swaps to the `…__user_group` sibling, the auth-gated PNG rendered
 * through `mapVariablePreviewObjectUrl` as a blob object URL, and a caveat
 * callout keyed to the active map.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Select, Segmented, Spin, Alert, Button, Space } from 'antd';
import { useT } from '../../i18n/hooks';
import { operationalPlanApi, type HazardErosionMap } from '../../services/api';
import { HazardVarChip } from './HazardVarChip';
import { HazardMapLegend } from './MapLegend';

interface Props {
  calculationId: string;
  maps: HazardErosionMap[];
  hasUserGroup: boolean;
  /** en | ne — picks which label field to show */
  lang?: string;
  /** bump to force a re-fetch of the current image (e.g. after a param save) */
  refreshKey?: number;
}

type Aoi = 'cf' | 'ug';

const caveatKey = (key: string): string => {
  const k = key.replace(/^thememap:/, '');
  if (k.startsWith('hazard__landslide_prone_area')) return 'hazardErosion.caveat.prone';
  if (k.startsWith('hazard__landslide_susceptibility') || k.startsWith('hazard__lsi_factor_'))
    return 'hazardErosion.caveat.lsi';
  if (k.startsWith('hazard__factor_of_safety')) return 'hazardErosion.caveat.fs';
  if (k.startsWith('hh__')) return 'hazardErosion.caveat.household';
  return 'hazardErosion.caveat.soil';
};

export const HazardMapPanel: React.FC<Props> = ({
  calculationId,
  maps,
  hasUserGroup,
  lang = 'en',
  refreshKey = 0,
}) => {
  const t = useT();

  const { primary, annex, ugKeys } = useMemo(() => {
    const ug = new Set(maps.filter((m) => m.is_user_group).map((m) => m.key));
    return {
      primary: maps.filter((m) => !m.is_factor_band && !m.is_user_group),
      annex: maps.filter((m) => m.is_factor_band),
      ugKeys: ug,
    };
  }, [maps]);

  const label = (m: HazardErosionMap) =>
    `${lang === 'ne' ? m.label_ne || m.label_en : m.label_en}${m.available ? '' : ` ${t('hazardErosion.map.noData')}`}`;

  const [selectedKey, setSelectedKey] = useState<string>(
    () => (primary.find((m) => m.available) || primary[0] || annex[0])?.key || '',
  );
  const [aoi, setAoi] = useState<Aoi>('cf');
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);

  const hasUgVariant = ugKeys.has(`${selectedKey}__user_group`);
  const showUgToggle = hasUserGroup && hasUgVariant;
  const effectiveKey =
    aoi === 'ug' && hasUgVariant ? `${selectedKey}__user_group` : selectedKey;

  useEffect(() => {
    if (!effectiveKey) return;
    let live = true;
    let objUrl: string | null = null;
    setLoading(true);
    setFailed(false);
    operationalPlanApi
      .mapVariablePreviewObjectUrl(effectiveKey, calculationId)
      .then((u) => {
        if (!live) {
          URL.revokeObjectURL?.(u);
          return;
        }
        objUrl = u;
        setUrl((prev) => {
          if (prev) URL.revokeObjectURL?.(prev);
          return u;
        });
      })
      .catch(() => {
        if (live) setFailed(true);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
      if (objUrl) URL.revokeObjectURL?.(objUrl);
    };
  }, [effectiveKey, calculationId, nonce, refreshKey]);

  return (
    <div>
      <Space wrap style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 13, color: '#666' }}>{t('hazardErosion.map.label')}</span>
        <Select
          size="small"
          style={{ width: 320 }}
          value={selectedKey}
          onChange={(v) => setSelectedKey(v)}
          options={[
            {
              label: t('hazardErosion.map.primaryGroup'),
              options: primary.map((m) => ({ value: m.key, label: label(m) })),
            },
            {
              label: t('hazardErosion.map.annexGroup'),
              options: annex.map((m) => ({ value: m.key, label: label(m) })),
            },
          ]}
        />
        {showUgToggle && (
          <Segmented
            size="small"
            value={aoi}
            onChange={(v) => setAoi(v as Aoi)}
            options={[
              { label: t('hazardErosion.map.cf'), value: 'cf' },
              { label: t('hazardErosion.map.userGroup'), value: 'ug' },
            ]}
          />
        )}
        {effectiveKey && <HazardVarChip tokenKey={effectiveKey} />}
      </Space>

      <div
        style={{
          position: 'relative',
          minHeight: 260,
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          background: '#fafafa',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          overflow: 'hidden',
        }}
      >
        {url && (
          <img
            src={url}
            alt={effectiveKey}
            style={{ width: '100%', display: 'block', opacity: loading ? 0.5 : 1 }}
          />
        )}
        {loading && (
          <div style={{ position: 'absolute' }}>
            <Spin />
          </div>
        )}
        {failed && !loading && (
          <div style={{ padding: 16, textAlign: 'center' }}>
            <Alert
              type="error"
              message={t('hazardErosion.map.loadFailed')}
              style={{ marginBottom: 8 }}
            />
            <Button size="small" onClick={() => setNonce((n) => n + 1)}>
              {t('hazardErosion.retry')}
            </Button>
          </div>
        )}
      </div>

      {/* The legend lists only what this forest has, with hectares and share: dynamic, just below the map. */}
      {effectiveKey && <HazardMapLegend calculationId={calculationId} mapKey={effectiveKey} lang={lang} refreshKey={refreshKey + nonce} />}

      <Alert
        type="info"
        showIcon
        style={{ marginTop: 8, fontSize: 12 }}
        message={t(caveatKey(effectiveKey))}
      />
    </div>
  );
};

export default HazardMapPanel;
