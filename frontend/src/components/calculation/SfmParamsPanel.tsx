/**
 * SfmParamsPanel — per-forest SfmParams tuning for the Sustainable Forest
 * Management tab (SUSTAINABLE_FOREST_MANAGEMENT_PLAN.md P7). Mirrors
 * `HazardParamsPanel`.
 *
 * One `Collapse` panel driven by `useResolvedParams(sfmParamsApi, …)`. Save
 * PATCHes only the changed keys; Reset drops the per-forest override (revert to
 * physiography profile / code default). On any change it calls `onSaved` so the
 * parent can re-fetch the classification and force the map panel to re-render.
 */
import React from 'react';
import { Collapse, Button, Tag, Space, Spin, Alert, message, Typography } from 'antd';
import { useT } from '../../i18n/hooks';
import { sfmParamsApi, type SfmParamPatch } from '../../services/api';
import { useResolvedParams } from '../../hooks/useResolvedParams';
import SfmParamsFields from '../SfmParamsFields';

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

export const SfmParamsPanel: React.FC<Props> = ({ calculationId, onSaved }) => {
  const t = useT();
  const p = useResolvedParams<SfmParamPatch>(sfmParamsApi, calculationId, () => ({}));

  const save = async () => {
    try {
      await p.save();
      message.success(t('sfm.params.saved'));
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
      await p.reset();
      message.success(t('sfm.params.saved'));
      onSaved?.();
    } catch {
      message.error(t('common.saveFailed'));
    }
  };

  if (p.loading) {
    return (
      <div style={{ padding: 12, textAlign: 'center' }}>
        <Spin />
      </div>
    );
  }
  if (p.error) {
    return <Alert type="error" message={t('sfm.params.loadFailed')} />;
  }

  return (
    <div>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {t('sfm.params.resolveNote')}
      </Text>
      <Collapse
        size="small"
        style={{ marginTop: 8 }}
        defaultActiveKey={[]}
        items={[
          {
            key: 'sfm',
            label: (
              <Space>
                <b>{t('sfm.params.title')}</b>
                {p.resp && (
                  <ProvenanceTags
                    provenance={p.resp.provenance}
                    allDefaultsLabel={t('sfm.params.allDefaults')}
                  />
                )}
              </Space>
            ),
            children: (
              <SfmParamsFields value={p.patch} onChange={p.setPatch} disabled={p.saving} />
            ),
          },
        ]}
      />
      <Space style={{ marginTop: 10 }}>
        <Button
          type="primary"
          size="small"
          loading={p.saving}
          disabled={!p.dirty}
          onClick={save}
        >
          {t('sfm.params.save')}
        </Button>
        <Button
          size="small"
          danger
          loading={p.saving}
          disabled={!p.customised}
          onClick={reset}
        >
          {t('sfm.params.reset')}
        </Button>
      </Space>
    </div>
  );
};

export default SfmParamsPanel;
