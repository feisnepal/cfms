/**
 * AdminHazardVulnProfilesPage — super-admin CRUD for the org-wide
 * landslide-hazard + household-vulnerability parameter presets
 * (`hazard_vuln_profiles`, migration 078). A forest with no per-forest override
 * auto-picks the profile whose physiography_hint matches its dominant
 * admin.physiography zone. Each profile's `params` is a *nested* sparse patch
 * (landslide / factor_of_safety / household) — same shape as the per-forest
 * override.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Table,
  Button,
  Typography,
  Spin,
  Alert,
  message,
  Modal,
  Form,
  Input,
  InputNumber,
  Switch,
  Tag,
  Popconfirm,
  Space,
} from 'antd';
import { ReloadOutlined, PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  hazardVulnProfileApi,
  type HazardVulnProfile,
} from '../services/api';
import HazardVulnParamsFields, { type ParamPatch } from '../components/HazardVulnParamsFields';
import { useT } from '../i18n/hooks';

const { Title, Paragraph, Text } = Typography;

interface EditState {
  key: string;
  label_ne: string;
  label_en: string;
  physiography_hint: string;
  is_active: boolean;
  sort_order: number;
  params: ParamPatch;
  isNew: boolean;
}

/** count of leaf overrides across the nested groups */
const paramCount = (p: ParamPatch): number =>
  Object.values(p || {}).reduce(
    (n, group) => n + Object.keys(group || {}).length,
    0,
  );

export const AdminHazardVulnProfilesPage: React.FC = () => {
  const t = useT();
  const [rows, setRows] = useState<HazardVulnProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await hazardVulnProfileApi.list());
    } catch {
      setError('Failed to load profiles');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  const openEdit = (p?: HazardVulnProfile) =>
    setEdit(
      p
        ? {
            key: p.key,
            label_ne: p.label_ne,
            label_en: p.label_en,
            physiography_hint: p.physiography_hint ?? '',
            is_active: p.is_active,
            sort_order: p.sort_order,
            params: { ...(p.params as ParamPatch) },
            isNew: false,
          }
        : {
            key: '',
            label_ne: '',
            label_en: '',
            physiography_hint: '',
            is_active: true,
            sort_order: 0,
            params: {},
            isNew: true,
          },
    );

  const save = async () => {
    if (!edit) return;
    if (!edit.key.trim() || !edit.label_ne.trim() || !edit.label_en.trim()) {
      message.error('Key and both labels are required');
      return;
    }
    setSaving(true);
    try {
      await hazardVulnProfileApi.upsert(edit.key.trim(), {
        label_ne: edit.label_ne.trim(),
        label_en: edit.label_en.trim(),
        physiography_hint: edit.physiography_hint.trim() || null,
        is_active: edit.is_active,
        sort_order: edit.sort_order,
        params: edit.params,
      });
      message.success('Saved');
      setEdit(null);
      fetchRows();
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      message.error(status === 422 ? t('common.paramOutOfRange') : t('common.saveFailed'));
    } finally {
      setSaving(false);
    }
  };

  const remove = async (key: string) => {
    try {
      await hazardVulnProfileApi.remove(key);
      message.success('Deleted');
      fetchRows();
    } catch {
      message.error('Delete failed');
    }
  };

  const columns: ColumnsType<HazardVulnProfile> = useMemo(
    () => [
      { title: 'Key', dataIndex: 'key', width: 130 },
      {
        title: 'Label',
        render: (_, r) => (
          <span>
            {r.label_ne} <Text type="secondary">/ {r.label_en}</Text>
          </span>
        ),
      },
      { title: 'Physiography', dataIndex: 'physiography_hint', width: 170, render: (v) => v || <Text type="secondary">—</Text> },
      {
        title: 'Params',
        width: 110,
        render: (_, r) => {
          const n = paramCount(r.params as ParamPatch);
          return n ? <Tag color="geekblue">{n} set</Tag> : <Text type="secondary">defaults</Text>;
        },
      },
      { title: 'Active', dataIndex: 'is_active', width: 80, render: (v) => (v ? <Tag color="green">yes</Tag> : <Tag>no</Tag>) },
      { title: 'Sort', dataIndex: 'sort_order', width: 70 },
      {
        title: '',
        width: 110,
        render: (_, r) => (
          <Space>
            <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
            <Popconfirm title={t('common.deleteNameConfirm', { name: r.key })} onConfirm={() => remove(r.key)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [],
  );

  return (
    <div style={{ padding: 24, maxWidth: 1000 }}>
      <Title level={3}>{t('hazardErosion.profilesPageTitle')}</Title>
      <Paragraph type="secondary">
        Org-wide presets for the landslide-susceptibility, Factor-of-Safety and
        household-vulnerability analysis. A forest with no per-forest override
        picks the profile whose physiography matches its dominant zone. Empty{' '}
        <code>params</code> = code defaults.
      </Paragraph>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<PlusOutlined />} type="primary" onClick={() => openEdit()}>
          New profile
        </Button>
        <Button icon={<ReloadOutlined />} onClick={fetchRows}>
          Refresh
        </Button>
      </Space>

      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {loading ? (
        <Spin />
      ) : (
        <Table rowKey="key" size="small" columns={columns} dataSource={rows} pagination={false} />
      )}

      <Modal
        title={edit?.isNew ? 'New profile' : `Edit ${edit?.key}`}
        open={!!edit}
        onCancel={() => setEdit(null)}
        onOk={save}
        confirmLoading={saving}
        width={660}
        okText="Save"
      >
        {edit && (
          <Form layout="vertical" size="small">
            <Form.Item label="Key" required>
              <Input
                value={edit.key}
                disabled={!edit.isNew}
                placeholder="chure, mid_hill, …"
                onChange={(e) => setEdit({ ...edit, key: e.target.value })}
              />
            </Form.Item>
            <Space style={{ display: 'flex' }} align="start">
              <Form.Item label="Label (Nepali)" required style={{ flex: 1 }}>
                <Input value={edit.label_ne} onChange={(e) => setEdit({ ...edit, label_ne: e.target.value })} />
              </Form.Item>
              <Form.Item label="Label (English)" required style={{ flex: 1 }}>
                <Input value={edit.label_en} onChange={(e) => setEdit({ ...edit, label_en: e.target.value })} />
              </Form.Item>
            </Space>
            <Space style={{ display: 'flex' }} align="start">
              <Form.Item label="Physiography hint" style={{ flex: 1 }} tooltip="Matched against admin.physiography — e.g. 'Chure Hillslopes', 'Middle Mountain'">
                <Input value={edit.physiography_hint} onChange={(e) => setEdit({ ...edit, physiography_hint: e.target.value })} />
              </Form.Item>
              <Form.Item label="Sort order">
                <InputNumber value={edit.sort_order} onChange={(v) => setEdit({ ...edit, sort_order: Number(v ?? 0) })} />
              </Form.Item>
              <Form.Item label="Active">
                <Switch checked={edit.is_active} onChange={(v) => setEdit({ ...edit, is_active: v })} />
              </Form.Item>
            </Space>
            <Typography.Text strong>{t('common.parameterOverrides')}</Typography.Text>
            <div style={{ marginTop: 8 }}>
              <HazardVulnParamsFields
                value={edit.params}
                onChange={(params) => setEdit({ ...edit, params })}
              />
            </div>
          </Form>
        )}
      </Modal>
    </div>
  );
};

export default AdminHazardVulnProfilesPage;
