/**
 * AdminSfmPrescriptionsPage — super-admin editor for the दिगो वन व्यवस्थापन
 * कार्यविधि, २०७९ अनुसूची-१ (`sfm_forest_type_prescriptions`, 14 rows). The
 * guideline stays data: retune a silvicultural system, a felling cycle or a
 * yield step here and the next `build_sfm(force=true)` picks it up.
 *
 * Each row expands to a per-branch editor (क adequate / ख inadequate / default):
 * method, cycle, the `yield_rules.steps` step function, and the NE/EN prose.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  Table,
  Button,
  Typography,
  Spin,
  Alert,
  message,
  Select,
  InputNumber,
  Input,
  Space,
  Tag,
  Divider,
} from 'antd';
import { ReloadOutlined, PlusOutlined, DeleteOutlined, SaveOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  sfmPrescriptionApi,
  type SfmPrescription,
  type SfmBranch,
  type SfmYieldStep,
} from '../services/api';
import { useT } from '../i18n/hooks';

const { Title, Paragraph, Text } = Typography;

const METHODS = [
  'selection_felling_cycle',
  'shelterwood_periodic_block',
  'stem_count',
  'area_coupe',
];
const BASES = ['growing_stock_pct_ge40', 'stem_count', 'area_volume', 'none'];

const StepRow: React.FC<{
  step: SfmYieldStep;
  onChange: (s: SfmYieldStep) => void;
  onRemove: () => void;
}> = ({ step, onChange, onRemove }) => (
  <Space style={{ marginBottom: 6 }}>
    <InputNumber
      size="small"
      placeholder="min"
      style={{ width: 90 }}
      value={step.gs_per_ha_min ?? undefined}
      onChange={(v) => onChange({ ...step, gs_per_ha_min: typeof v === 'number' ? v : null })}
    />
    <span>–</span>
    <InputNumber
      size="small"
      placeholder="max"
      style={{ width: 90 }}
      value={step.gs_per_ha_max ?? undefined}
      onChange={(v) => onChange({ ...step, gs_per_ha_max: typeof v === 'number' ? v : null })}
    />
    <span>→</span>
    <InputNumber
      size="small"
      addonAfter="%"
      style={{ width: 100 }}
      min={0}
      max={100}
      step={0.1}
      value={step.pct}
      onChange={(v) => onChange({ ...step, pct: typeof v === 'number' ? v : 0 })}
    />
    <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={onRemove} />
  </Space>
);

const BranchEditor: React.FC<{
  name: string;
  branch: SfmBranch;
  onChange: (b: SfmBranch) => void;
}> = ({ name, branch, onChange }) => {
  const yr = branch.yield_rules;
  const setYr = (patch: Partial<SfmBranch['yield_rules']>) =>
    onChange({ ...branch, yield_rules: { ...yr, ...patch } });

  return (
    <div style={{ padding: '8px 0' }}>
      <Text strong>{name}</Text>
      <div style={{ marginTop: 6, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <label>
          method{' '}
          <Select
            size="small"
            style={{ width: 220 }}
            value={branch.method}
            options={METHODS.map((m) => ({ value: m, label: m }))}
            onChange={(v) => onChange({ ...branch, method: v as SfmBranch['method'] })}
          />
        </label>
        <label>
          felling cycle (yr){' '}
          <InputNumber
            size="small"
            min={1}
            max={50}
            value={branch.felling_cycle_years ?? undefined}
            onChange={(v) =>
              onChange({ ...branch, felling_cycle_years: typeof v === 'number' ? v : null })
            }
          />
        </label>
        <label>
          regen period (yr){' '}
          <InputNumber
            size="small"
            min={1}
            max={50}
            value={branch.regeneration_period_years ?? undefined}
            onChange={(v) =>
              onChange({
                ...branch,
                regeneration_period_years: typeof v === 'number' ? v : null,
              })
            }
          />
        </label>
      </div>

      <div style={{ marginTop: 8, display: 'flex', gap: 12 }}>
        <Input
          size="small"
          addonBefore="system ne"
          value={branch.system_ne}
          onChange={(e) => onChange({ ...branch, system_ne: e.target.value })}
        />
        <Input
          size="small"
          addonBefore="system en"
          value={branch.system_en}
          onChange={(e) => onChange({ ...branch, system_en: e.target.value })}
        />
      </div>

      <div style={{ marginTop: 8 }}>
        <label>
          yield basis{' '}
          <Select
            size="small"
            style={{ width: 220 }}
            value={yr.basis}
            options={BASES.map((b) => ({ value: b, label: b }))}
            onChange={(v) => setYr({ basis: v as SfmBranch['yield_rules']['basis'] })}
          />
        </label>
        <div style={{ marginTop: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            steps (growing stock ≥40 cm / ha → %) — must not overlap
          </Text>
          {(yr.steps || []).map((s, i) => (
            <StepRow
              key={i}
              step={s}
              onChange={(ns) => {
                const steps = [...yr.steps];
                steps[i] = ns;
                setYr({ steps });
              }}
              onRemove={() => setYr({ steps: yr.steps.filter((_, j) => j !== i) })}
            />
          ))}
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() =>
              setYr({
                steps: [
                  ...(yr.steps || []),
                  { gs_per_ha_min: null, gs_per_ha_max: null, pct: 0 },
                ],
              })
            }
          >
            Add step
          </Button>
        </div>
      </div>

      <div style={{ marginTop: 8, display: 'flex', gap: 12 }}>
        <Input.TextArea
          size="small"
          rows={2}
          placeholder="note ne (अनुसूची-१ row note)"
          value={branch.note_ne}
          onChange={(e) => onChange({ ...branch, note_ne: e.target.value })}
        />
        <Input.TextArea
          size="small"
          rows={2}
          placeholder="note en"
          value={branch.note_en}
          onChange={(e) => onChange({ ...branch, note_en: e.target.value })}
        />
      </div>
    </div>
  );
};

export const RowEditor: React.FC<{
  row: SfmPrescription;
  onSaved: () => void;
}> = ({ row, onSaved }) => {
  const t = useT();
  const [draft, setDraft] = useState<SfmPrescription>(row);
  const [saving, setSaving] = useState(false);
  useEffect(() => setDraft(row), [row]);

  const setBranch = (name: string, b: SfmBranch) =>
    setDraft({ ...draft, branches: { ...draft.branches, [name]: b } });

  const save = async () => {
    setSaving(true);
    try {
      const { type_no: _t, ...body } = draft;
      void _t;
      await sfmPrescriptionApi.put(row.type_no, body);
      message.success('Saved');
      onSaved();
    } catch (e) {
      const status = (e as { response?: { status?: number } })?.response?.status;
      message.error(
        status === 422 ? t('sfm.admin.invalidBranch') : t('common.saveFailed'),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: 8, background: '#fafafa' }}>
      <Space wrap>
        <Input
          size="small"
          addonBefore="name ne"
          style={{ width: 320 }}
          value={draft.name_ne}
          onChange={(e) => setDraft({ ...draft, name_ne: e.target.value })}
        />
        <Input
          size="small"
          addonBefore="name en"
          style={{ width: 320 }}
          value={draft.name_en}
          onChange={(e) => setDraft({ ...draft, name_en: e.target.value })}
        />
        <Input
          size="small"
          addonBefore="orientation"
          style={{ width: 200 }}
          value={draft.orientation}
          onChange={(e) => setDraft({ ...draft, orientation: e.target.value })}
        />
      </Space>
      {Object.entries(draft.branches).map(([name, b]) => (
        <div key={name}>
          <Divider style={{ margin: '8px 0' }} />
          <BranchEditor name={name} branch={b} onChange={(nb) => setBranch(name, nb)} />
        </div>
      ))}
      <Button
        type="primary"
        size="small"
        icon={<SaveOutlined />}
        loading={saving}
        onClick={save}
        style={{ marginTop: 8 }}
      >
        {t('sfm.admin.save')}
      </Button>
    </div>
  );
};

export const AdminSfmPrescriptionsPage: React.FC = () => {
  const t = useT();
  const [rows, setRows] = useState<SfmPrescription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRows = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await sfmPrescriptionApi.list());
    } catch {
      setError('Failed to load prescriptions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  const columns: ColumnsType<SfmPrescription> = [
    { title: 'सि.नं.', dataIndex: 'type_no', width: 70 },
    {
      title: 'Forest type',
      render: (_, r) => (
        <span>
          {r.name_ne} <Text type="secondary">/ {r.name_en}</Text>
        </span>
      ),
    },
    { title: 'Orientation', dataIndex: 'orientation', width: 130 },
    {
      title: 'Branches',
      width: 200,
      render: (_, r) =>
        Object.entries(r.branches).map(([k, b]) => (
          <Tag key={k}>
            {k}: {b.method.replace(/_.*/, '')}
          </Tag>
        )),
    },
    {
      title: 'Steps',
      width: 70,
      render: (_, r) =>
        Object.values(r.branches).reduce(
          (n, b) => n + (b.yield_rules.steps?.length || 0),
          0,
        ),
    },
  ];

  return (
    <div style={{ padding: 24, maxWidth: 1100 }}>
      <Title level={3}>{t('sfm.admin.pageTitle')}</Title>
      <Paragraph type="secondary">
        The दिगो वन व्यवस्थापन कार्यविधि, २०७९ अनुसूची-१ as editable data. Expand a
        row to retune its silvicultural system, felling cycle or yield step
        function. Changes take effect on the next classification rebuild — no
        deploy.
      </Paragraph>
      <Button icon={<ReloadOutlined />} onClick={fetchRows} style={{ marginBottom: 12 }}>
        Refresh
      </Button>

      {error && <Alert type="error" message={error} style={{ marginBottom: 12 }} />}
      {loading ? (
        <Spin />
      ) : (
        <Table
          rowKey="type_no"
          size="small"
          columns={columns}
          dataSource={rows}
          pagination={false}
          expandable={{
            expandedRowRender: (r) => <RowEditor row={r} onSaved={fetchRows} />,
          }}
        />
      )}
    </div>
  );
};

export default AdminSfmPrescriptionsPage;
