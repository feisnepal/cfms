/**
 * HazardVulnParamsButton — a button + modal to view and tune this forest's
 * landslide-hazard + household-vulnerability parameters. Shows per-group
 * provenance (default ▸ profile ▸ this forest), lets an owner / DFO override a
 * subset, and reset back to the inherited values. Backed by
 * GET/PATCH/DELETE /calculations/{id}/hazard-vuln-params.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Button, Modal, Tag, Spin, message, Space, Typography } from 'antd';
import { WarningOutlined } from '@ant-design/icons';
import {
  hazardVulnApi,
  type HazardVulnParamsResponse,
} from '../services/api';
import HazardVulnParamsFields, { type ParamPatch } from './HazardVulnParamsFields';
import { useT } from '../i18n/hooks';

const { Text, Paragraph } = Typography;

interface Props {
  calculationId: string;
  /** Called after a successful save/reset so a parent can refresh a map. */
  onChanged?: () => void;
  size?: 'small' | 'middle' | 'large';
}

export const HazardVulnParamsButton: React.FC<Props> = ({
  calculationId,
  onChanged,
  size = 'small',
}) => {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resp, setResp] = useState<HazardVulnParamsResponse | null>(null);
  const [patch, setPatch] = useState<ParamPatch>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setResp(await hazardVulnApi.get(calculationId));
      // the API returns the resolved set + per-group provenance, not the raw
      // override — start from an empty patch; PATCH merges onto the stored one.
      setPatch({});
    } catch {
      message.error('Could not load hazard / vulnerability parameters');
    } finally {
      setLoading(false);
    }
  }, [calculationId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const save = async () => {
    if (Object.keys(patch).length === 0) {
      setOpen(false);
      return;
    }
    setSaving(true);
    try {
      const r = await hazardVulnApi.patch(calculationId, patch);
      setResp(r);
      message.success('Hazard / vulnerability parameters updated');
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
      const r = await hazardVulnApi.reset(calculationId);
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
      <Button size={size} icon={<WarningOutlined />} onClick={() => setOpen(true)}>
        Hazard parameters{customised ? ' •' : ''}
      </Button>
      <Modal
        title="Landslide hazard & household-vulnerability parameters"
        open={open}
        onCancel={() => setOpen(false)}
        width={640}
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
            <HazardVulnParamsFields value={patch} onChange={setPatch} disabled={saving} />
          </>
        )}
      </Modal>
    </>
  );
};

export default HazardVulnParamsButton;
