/**
 * SfmMapPanel — the thematic-map switcher for the Sustainable Forest Management
 * context (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P5).
 *
 * A `<Segmented>` over the three `sustainable_fm` thematic specs
 * (forest type / orientation / growing stock vs the step edges), the auth-gated
 * PNG rendered through `mapVariablePreviewObjectUrl` as a blob object URL, and, just below it,
 * the dynamic legend (only the classes this forest has, with units and hectares).
 */
import React, { useEffect, useState } from 'react';
import { Segmented, Spin, Alert, Button, Space, Tag } from 'antd';
import { useT } from '../../i18n/hooks';
import {
  operationalPlanApi,
  type SfmVariant,
} from '../../services/api';
import { SfmVarChip } from './SfmVarChip';
import { SfmMapLegend } from './MapLegend';

interface Props {
  calculationId: string;
  /** bump to force a re-fetch (e.g. after a block override) */
  refreshKey?: number;
  /** SV-1.10 — which SFM result the thematic PNGs are rendered from. */
  variant?: SfmVariant;
}

type SpecKey = 'sfm__forest_type' | 'sfm__orientation' | 'sfm__gs_vs_threshold';

const SPEC_KEYS: SpecKey[] = ['sfm__forest_type', 'sfm__orientation', 'sfm__gs_vs_threshold'];

export const SfmMapPanel: React.FC<Props> = ({ calculationId, refreshKey = 0, variant }) => {
  const t = useT();
  const [specKey, setSpecKey] = useState<SpecKey>('sfm__forest_type');
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let live = true;
    let objUrl: string | null = null;
    setLoading(true);
    setFailed(false);
    operationalPlanApi
      .mapVariablePreviewObjectUrl(`thememap:${specKey}`, calculationId, variant)
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
  }, [specKey, calculationId, nonce, refreshKey, variant]);

  return (
    <div>
      <Space wrap style={{ marginBottom: 10 }}>
        <span style={{ fontSize: 13, color: '#666' }}>{t('sfm.map.label')}</span>
        <Tag color={variant === 'user' ? 'blue' : 'default'} style={{ fontSize: 11 }}>
          {variant === 'user' ? t('sfm.variantUser') : t('sfm.variantBaseline')}
        </Tag>
        <Segmented<SpecKey>
          size="small"
          value={specKey}
          onChange={(v) => setSpecKey(v)}
          options={SPEC_KEYS.map((k) => ({
            value: k,
            label: t(`sfm.map.spec.${k}`),
          }))}
        />
        <SfmVarChip tokenKey={`thememap:${specKey}`} />
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
            alt={specKey}
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
            <Alert type="error" message={t('sfm.map.loadFailed')} style={{ marginBottom: 8 }} />
            <Button size="small" onClick={() => setNonce((n) => n + 1)}>
              {t('sfm.retry')}
            </Button>
          </div>
        )}
      </div>

      {/* The legend lists only what this forest has, with units and hectares: dynamic, not the whole palette. */}
      <SfmMapLegend calculationId={calculationId} specKey={specKey} variant={variant} refreshKey={refreshKey + nonce} />
      <p style={{ marginTop: 6, fontSize: 12, color: '#888' }}>{t('sfm.map.note')}</p>
    </div>
  );
};

export default SfmMapPanel;
