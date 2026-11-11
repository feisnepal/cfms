/** MyTemplatesPage — template-designer workspace: own templates across every
 *  lifecycle status, with submit / clone / validate / audit actions.
 *  See OP_MULTI_TEMPLATE_PLAN.md §3.10. */
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  List, Tag, Typography, Spin, Empty, Button, message, Modal, Space, Tooltip,
  Popconfirm, Input, Alert, Descriptions, Select, Segmented,
} from 'antd';
import {
  PlusOutlined, EditOutlined, CopyOutlined, DeleteOutlined,
  CheckCircleOutlined, HistoryOutlined, ReloadOutlined, ExperimentOutlined,
} from '@ant-design/icons';
import { operationalPlanApi, forestApi } from '../services/api';
import { useT } from '../i18n/hooks';
import { formatDateTime } from '../i18n/numberFormat';

const { Text } = Typography;
const { TextArea } = Input;

interface Tmpl {
  id: string;
  name: string;
  description: string;
  status: string;
  plan_kind?: string | null;
  plan_regime?: string | null;
  plan_stage?: string | null;
  version?: number;
  published_version?: number | null;
  updated_at: string;
  approval_note?: string;
}

const STATUS_COLOR: Record<string, string> = {
  draft: 'default',
  in_review: 'processing',
  rejected: 'error',
  published: 'success',
  deprecated: 'warning',
  retired: 'default',
};

const MyTemplatesPage: React.FC = () => {
  const t = useT();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<Tmpl[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [auditRows, setAuditRows] = useState<any[]>([]);
  const [validateOpen, setValidateOpen] = useState(false);
  const [validateResult, setValidateResult] = useState<any>(null);

  // "Test with a forest" — renders a template against a real forest's data via
  // the transient preview endpoint; no operational plan is created.
  const [testOpen, setTestOpen] = useState(false);
  const [testTmpl, setTestTmpl] = useState<Tmpl | null>(null);
  const [testCalcs, setTestCalcs] = useState<Array<{ id: string; forest_name?: string; status: string }>>([]);
  const [testCalcId, setTestCalcId] = useState<string | undefined>(undefined);
  const [testMode, setTestMode] = useState<'values' | 'tokens'>('values');
  const [testHtml, setTestHtml] = useState('');
  const [testLoading, setTestLoading] = useState(false);

  const openTest = async (tmpl: Tmpl) => {
    setTestTmpl(tmpl);
    setTestHtml('');
    setTestCalcId(undefined);
    setTestOpen(true);
    try {
      const calcs = await forestApi.listCalculations();
      setTestCalcs((calcs || []).filter(
        (c: { status: string }) => c.status === 'completed' || c.status === 'processing',
      ));
    } catch {
      setTestCalcs([]);
    }
  };

  const runTest = async (calcId: string, mode: 'values' | 'tokens') => {
    if (!testTmpl) return;
    setTestLoading(true);
    try {
      const html = await operationalPlanApi.previewTemplateWithForest(testTmpl.id, calcId, mode);
      setTestHtml(html);
    } catch {
      message.error(t('templates.mine.testFailed'));
    } finally {
      setTestLoading(false);
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await operationalPlanApi.listTemplates('mine');
      setTemplates(res.templates || []);
    } catch {
      message.error(t('templates.mine.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);

  const statusLabel = (s: string) => t(`templates.status.${s}`, { defaultValue: s });

  const handleValidate = async (tmpl: Tmpl) => {
    setBusyId(tmpl.id);
    try {
      const res = await operationalPlanApi.validateTemplate(tmpl.id);
      setValidateResult(res);
      setValidateOpen(true);
    } catch {
      message.error(t('templates.mine.validateFailed'));
    } finally {
      setBusyId(null);
    }
  };

  const handleClone = async (tmpl: Tmpl) => {
    setBusyId(tmpl.id);
    try {
      const c = await operationalPlanApi.cloneTemplate(tmpl.id, `${tmpl.name} (Copy)`);
      message.success(t('templates.mine.msgCloned'));
      navigate(`/templates/designer/${c.id}`);
    } catch {
      message.error(t('templates.mine.cloneFailed'));
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (tmpl: Tmpl) => {
    try {
      await operationalPlanApi.deleteTemplate(tmpl.id);
      message.success(t('templates.mine.msgDeleted'));
      load();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || t('templates.mine.deleteFailed'));
    }
  };

  const handleAudit = async (tmpl: Tmpl) => {
    try {
      const rows = await operationalPlanApi.getTemplateAudit(tmpl.id);
      setAuditRows(rows);
      setAuditOpen(true);
    } catch {
      message.error(t('templates.mine.auditFailed'));
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>{t('templates.mine.title')}</Typography.Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>{t('templates.mine.refresh')}</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/templates/designer/new')}>
            {t('templates.mine.newTemplate')}
          </Button>
        </Space>
      </div>

      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        {t('templates.mine.subtitle')}
      </Text>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>
      ) : templates.length === 0 ? (
        <Empty description={t('templates.mine.empty')} />
      ) : (
        <List
          dataSource={templates}
          renderItem={(tmpl) => (
            <List.Item
              actions={[
                <Tooltip key="edit" title={t('templates.mine.edit')}>
                  <Button size="small" type="link" icon={<EditOutlined />}
                    onClick={() => navigate(`/templates/designer/${tmpl.id}`)} />
                </Tooltip>,
                <Tooltip key="validate" title={t('templates.mine.validate')}>
                  <Button size="small" type="link" icon={<CheckCircleOutlined />}
                    loading={busyId === tmpl.id} onClick={() => handleValidate(tmpl)} />
                </Tooltip>,
                <Tooltip key="test" title={t('templates.mine.testWithForest')}>
                  <Button size="small" type="link" icon={<ExperimentOutlined />}
                    onClick={() => openTest(tmpl)} />
                </Tooltip>,
                <Tooltip key="clone" title={t('templates.mine.clone')}>
                  <Button size="small" type="link" icon={<CopyOutlined />}
                    loading={busyId === tmpl.id} onClick={() => handleClone(tmpl)} />
                </Tooltip>,
                <Tooltip key="audit" title={t('templates.mine.audit')}>
                  <Button size="small" type="link" icon={<HistoryOutlined />} onClick={() => handleAudit(tmpl)} />
                </Tooltip>,
                (tmpl.status === 'draft' || tmpl.status === 'rejected') ? (
                  <Popconfirm key="del" title={t('templates.mine.confirmDelete')}
                    onConfirm={() => handleDelete(tmpl)}>
                    <Button size="small" type="link" danger icon={<DeleteOutlined />} />
                  </Popconfirm>
                ) : null,
              ].filter(Boolean)}
            >
              <List.Item.Meta
                title={
                  <Space wrap>
                    <Text strong>{tmpl.name}</Text>
                    <Tag color={STATUS_COLOR[tmpl.status] || 'default'}>{statusLabel(tmpl.status)}</Tag>
                    {tmpl.plan_kind && <Tag>{tmpl.plan_kind}</Tag>}
                    {tmpl.version !== undefined && <Tag>v{tmpl.version}</Tag>}
                    {tmpl.published_version != null && (
                      <Tag color="green">{t('templates.mine.publishedV', { v: tmpl.published_version })}</Tag>
                    )}
                  </Space>
                }
                description={
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {tmpl.description || t('templates.mine.noDescription')}
                    </Text>
                    {tmpl.status === 'rejected' && tmpl.approval_note && (
                      <div><Text type="danger" style={{ fontSize: 12 }}>
                        {t('templates.mine.rejectedNote', { note: tmpl.approval_note })}
                      </Text></div>
                    )}
                    <div>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t('templates.mine.updated', {
                          when: formatDateTime(tmpl.updated_at, { year: 'numeric', month: 'numeric', day: 'numeric' }),
                        })}
                      </Text>
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}

      <Modal
        title={t('templates.mine.validationTitle')}
        open={validateOpen}
        onCancel={() => setValidateOpen(false)}
        footer={<Button onClick={() => setValidateOpen(false)}>{t('common.close')}</Button>}
        width={640}
      >
        {validateResult && (
          <>
            <Alert
              type={validateResult.ok ? 'success' : 'error'}
              showIcon
              message={validateResult.ok ? t('templates.mine.validationOk') : t('templates.mine.validationFailed')}
              style={{ marginBottom: 12 }}
            />
            {(validateResult.errors || []).length > 0 && (
              <>
                <Text strong>{t('templates.mine.errors')}</Text>
                <ul style={{ marginTop: 4 }}>
                  {validateResult.errors.map((e: any, i: number) => (
                    <li key={i}><Text type="danger" style={{ fontSize: 13 }}>{e.message}{e.token ? ` (${e.token})` : ''}</Text></li>
                  ))}
                </ul>
              </>
            )}
            {(validateResult.warnings || []).length > 0 && (
              <>
                <Text strong>{t('templates.mine.warnings')}</Text>
                <ul style={{ marginTop: 4 }}>
                  {validateResult.warnings.map((w: any, i: number) => (
                    <li key={i}><Text type="warning" style={{ fontSize: 13 }}>{w.message}</Text></li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </Modal>

      <Modal
        title={t('templates.mine.auditTitle')}
        open={auditOpen}
        onCancel={() => setAuditOpen(false)}
        footer={<Button onClick={() => setAuditOpen(false)}>{t('common.close')}</Button>}
        width={640}
      >
        {auditRows.length === 0 ? (
          <Empty description={t('templates.mine.auditEmpty')} />
        ) : (
          <List
            size="small"
            dataSource={auditRows}
            renderItem={(r: any) => (
              <List.Item>
                <Descriptions size="small" column={1} style={{ width: '100%' }}>
                  <Descriptions.Item label={t('templates.mine.auditAction')}>
                    <Tag>{r.action}</Tag>
                    {r.from_status && <Text type="secondary" style={{ fontSize: 12 }}>{r.from_status} → {r.to_status}</Text>}
                  </Descriptions.Item>
                  {r.note && <Descriptions.Item label={t('templates.mine.auditNote')}>{r.note}</Descriptions.Item>}
                  <Descriptions.Item label={t('templates.mine.auditWhen')}>
                    {formatDateTime(r.created_at, { year: 'numeric', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </Descriptions.Item>
                </Descriptions>
              </List.Item>
            )}
          />
        )}
      </Modal>

      <Modal
        title={t('templates.mine.testTitle', { name: testTmpl?.name || '' })}
        open={testOpen}
        onCancel={() => setTestOpen(false)}
        footer={<Button onClick={() => setTestOpen(false)}>{t('common.close')}</Button>}
        width={900}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            style={{ width: 320 }}
            placeholder={t('templates.mine.testPickForest')}
            value={testCalcId}
            onChange={(v) => { setTestCalcId(v); runTest(v, testMode); }}
            options={testCalcs.map((c) => ({
              value: c.id, label: c.forest_name || c.id,
            }))}
          />
          <Segmented
            size="small"
            value={testMode}
            onChange={(v) => {
              const m = v as 'values' | 'tokens';
              setTestMode(m);
              if (testCalcId) runTest(testCalcId, m);
            }}
            options={[
              { label: t('operationalPlan.render.values'), value: 'values' },
              { label: t('operationalPlan.render.tokens'), value: 'tokens' },
            ]}
          />
        </Space>
        <Alert
          type="info" showIcon style={{ marginBottom: 12 }}
          message={t('templates.mine.testNote')}
        />
        {testLoading ? (
          <div style={{ textAlign: 'center', padding: 60 }}><Spin /></div>
        ) : testHtml ? (
          <iframe
            srcDoc={testHtml}
            title={t('templates.mine.testWithForest')}
            style={{ width: '100%', height: 480, border: '1px solid #f0f0f0' }}
          />
        ) : (
          <Empty description={t('templates.mine.testPickForest')} />
        )}
      </Modal>
    </div>
  );
};

export default MyTemplatesPage;
