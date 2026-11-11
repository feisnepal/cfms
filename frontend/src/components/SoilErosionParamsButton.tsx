/**
 * SoilErosionParamsButton — a button + modal to view and tune this forest's
 * RUSLE soil-loss parameters. Shows the resolved values with their provenance
 * (default ▸ profile ▸ this forest), lets an owner / DFO override a subset, and
 * reset back to the inherited values. Backed by
 * GET/PATCH/DELETE /calculations/{id}/soil-erosion-params.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Button, Modal, Tag, Spin, message, Space, Typography } from 'antd';
import { ExperimentOutlined } from '@ant-design/icons';
import {
  soilErosionApi,
  type SoilErosionParamsResponse,
} from '../services/api';
import SoilErosionParamsFields, { type ParamPatch } from './SoilErosionParamsFields';
import { useT } from '../i18n/hooks';

const { Text, Paragraph } = Typography;

interface Props {
  calculationId: string;
  /** Called after a successful save/reset so a parent can refresh a map. */
  onChanged?: () => void;
  size?: 'small' | 'middle' | 'large';
}

export const SoilErosionParamsButton: React.FC<Props> = ({
  calculationId,
  onChanged,
  size = 'small',
}) => {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resp, setResp] = useState<SoilErosionParamsResponse | null>(null);
  const [patch, setPatch] = useState<ParamPatch>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await soilErosionApi.get(calculationId);
      setResp(r);
      // seed the editable patch from whatever is already forest-scoped
      const forestKeys = Object.entries(r.provenance)
        .filter(([, v]) => v === 'forest')
        .map(([k]) => k);
      const seed: ParamPatch = {};
      for (const k of forestKeys) seed[k] = (r.params as ParamPatch)[k];
      setPatch(seed);
    } catch {
      message.error('Could not load soil-loss parameters');
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await soilErosionApi.patch(calculationId, patch);
      setResp(r);
      message.success('Soil-loss parameters updated');
      onChanged?.();
      setOpen(false);
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      message.error(status === 422 ? t('common.paramOutOfRange') : t('common.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    setSaving(true);
    try {
      const r = await soilErosionApi.reset(calculationId);
      setResp(r);
      setPatch({});
      message.success('Reverted to the inherited parameters');
      onChanged?.();
    } catch {
      message.error('Reset failed');
    } finally {
      setSaving(false);
    }
  };

  const customised = resp?.customised;

  return (
    <>
      <Button
        size={size}
        icon={<ExperimentOutlined />}
        onClick={() => setOpen(true)}
      >
        RUSLE parameters{customised ? ' •' : ''}
      </Button>
      <Modal
        title="RUSLE soil-loss parameters"
        open={open}
        onCancel={() => setOpen(false)}
        width={620}
        footer={[
          <Button key="reset" danger onClick={reset} loading={saving} disabled={!customised}>
            Reset to default
          </Button>,
          <Button key="cancel" onClick={() => setOpen(false)}>
            Cancel
          </Button>,
          <Button key="save" type="primary" onClick={save} loading={saving}>
            Save
          </Button>,
        ]}
      >
        {loading || !resp ? (
          <Spin />
        ) : (
          <>
            <Paragraph type="secondary" style={{ fontSize: 12 }}>
              Values resolve as <b>code default → physiography profile → this forest</b>.
              Set only what you want to override; clear a field (×) to inherit it again.
            </Paragraph>
            <Space size={[4, 4]} wrap style={{ marginBottom: 12 }}>
              {Object.entries(resp.provenance)
                .filter(([, v]) => v !== 'default')
                .map(([k, v]) => (
                  <Tag key={k} color={v === 'forest' ? 'blue' : 'geekblue'}>
                    {k}: {v}
                  </Tag>
                ))}
              {!customised && <Text type="secondary">all defaults</Text>}
            </Space>
            <SoilErosionParamsFields value={patch} onChange={setPatch} disabled={saving} />
          </>
        )}
      </Modal>
    </>
  );
};

export default SoilErosionParamsButton;
