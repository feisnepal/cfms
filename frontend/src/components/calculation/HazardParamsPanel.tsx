/**
 * HazardParamsPanel — the parameter tuning surface for the Hazard & Erosion
 * context (HAZARD_EROSION_CONTEXT_PLAN.md P3).
 *
 * A `Collapse` with the RUSLE field group and the (already-sectioned) hazard /
 * vulnerability field group. Both are driven by `useResolvedParams`; Save
 * PATCHes only the dirty side(s), Reset drops both per-forest overrides. On any
 * change it calls `onSaved` so the parent can re-fetch the summary and force
 * the map panel to re-render.
 */
import React from 'react';
import { Collapse, Button, Tag, Space, Spin, Alert, message, Typography } from 'antd';
import { useT } from '../../i18n/hooks';
import {
  soilErosionApi,
  hazardVulnApi,
  type SoilErosionParams,
  type HazardVulnParams,
} from '../../services/api';
import { useResolvedParams } from '../../hooks/useResolvedParams';
import SoilErosionParamsFields from '../SoilErosionParamsFields';
import HazardVulnParamsFields from '../HazardVulnParamsFields';

const { Text } = Typography;

interface Props {
  calculationId: string;
  /** called after a successful Save / Reset */
  onSaved?: () => void;
}

const ProvenanceTags: React.FC<{
  provenance: Record<string, 'default' | 'profile' | 'forest'>;
  allDefaultsLabel: string;
}> = ({ provenance, allDefaultsLabel }) => {
  const entries = Object.entries(provenance).filter(([, v]) => v !== 'default');
  if (entries.length === 0) return <Text type="secondary">{allDefaultsLabel}</Text>;
  return (
    <Space size={[4, 4]} wrap>
      {entries.map(([k, v]) => (
        <Tag key={k} color={v === 'forest' ? 'blue' : 'geekblue'}>
          {k}: {v}
        </Tag>
      ))}
    </Space>
  );
};

export const HazardParamsPanel: React.FC<Props> = ({ calculationId, onSaved }) => {
  const t = useT();

  const soil = useResolvedParams<SoilErosionParams>(
    soilErosionApi,
    calculationId,
    () => ({}),
  );
  const hazard = useResolvedParams<HazardVulnParams>(
    hazardVulnApi,
    calculationId,
    () => ({}),
  );

  const loading = soil.loading || hazard.loading;
  const saving = soil.saving || hazard.saving;
  const dirty = soil.dirty || hazard.dirty;
  const customised = soil.customised || hazard.customised;

  const save = async () => {
    try {
      if (soil.dirty) await soil.save();
      if (hazard.dirty) await hazard.save();
      message.success(t('hazardErosion.params.saved'));
      onSaved?.();
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      message.error(
        status === 422 ? t('common.paramOutOfRange') : t('common.saveFailed'),
      );
    }
  };

  const reset = async () => {
    try {
      await Promise.all([soil.reset(), hazard.reset()]);
      message.success(t('hazardErosion.params.saved'));
      onSaved?.();
    } catch {
      message.error(t('common.saveFailed'));
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 16, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (soil.error && hazard.error) {
    return <Alert type="error" message={t('hazardErosion.params.loadFailed')} />;
  }

  return (
    <div>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {t('hazardErosion.params.resolveNote')}
      </Text>
      <Collapse
        size="small"
        style={{ marginTop: 8 }}
        defaultActiveKey={[]}
        items={[
          {
            key: 'rusle',
            label: (
              <Space>
                <b>{t('hazardErosion.params.rusle')}</b>
                {soil.resp && (
                  <ProvenanceTags
                    provenance={soil.resp.provenance}
                    allDefaultsLabel={t('hazardErosion.params.allDefaults')}
                  />
                )}
              </Space>
            ),
            children: (
              <SoilErosionParamsFields
                value={soil.patch}
                onChange={soil.setPatch}
                disabled={saving}
              />
            ),
          },
          {
            key: 'hazard',
            label: (
              <Space>
                <b>{t('hazardErosion.params.hazard')}</b>
                {hazard.resp && (
                  <ProvenanceTags
                    provenance={hazard.resp.provenance}
                    allDefaultsLabel={t('hazardErosion.params.allDefaults')}
                  />
                )}
              </Space>
            ),
            children: (
              <HazardVulnParamsFields
                value={hazard.patch}
                onChange={hazard.setPatch}
                disabled={saving}
              />
            ),
          },
        ]}
      />
      <Space style={{ marginTop: 10 }}>
        <Button
          type="primary"
          size="small"
          loading={saving}
          disabled={!dirty}
          onClick={save}
        >
          {t('hazardErosion.params.save')}
        </Button>
        <Button size="small" danger loading={saving} disabled={!customised} onClick={reset}>
          {t('hazardErosion.params.reset')}
        </Button>
      </Space>
    </div>
  );
};

export default HazardParamsPanel;
