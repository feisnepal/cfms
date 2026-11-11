/** SystemTemplatePanel — the one is_system template: seed-sync status, version
 *  history, "Edit in designer", and the "Adopt structure from a plan" wizard.
 *  OP_TEMPLATE_MANAGEMENT_PLAN.md §3.1 / §3.4 (T4). Super admin only. */
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Tag, Button, Spin, Alert, Space, Typography, Select, List, Popconfirm,
  Descriptions, message, Divider,
} from 'antd';
import { EditOutlined, ReloadOutlined, ExperimentOutlined } from '@ant-design/icons';
import { operationalPlanApi, forestApi } from '../../services/api';
import { useT } from '../../i18n/hooks';
import { formatDateTime } from '../../i18n/numberFormat';

const { Text, Paragraph } = Typography;

interface SysTmpl {
  template: { id: string; name: string; version?: number; published_version?: number | null };
  versions: Array<{ version: number; changelog?: string; created_at: string }>;
  seed_sync: { in_sync: boolean; missing_sections: string[]; unregistered_tokens: string[] };
}

interface Diff {
  added: string[];
  removed: string[];
  token_restored: string[];
  needs_review: string[];
  kept: number;
}

const SystemTemplatePanel: React.FC = () => {
  const t = useT();
  const navigate = useNavigate();
  const [data, setData] = useState<SysTmpl | null>(null);
  const [loading, setLoading] = useState(true);

  const [calcs, setCalcs] = useState<Array<{ id: string; forest_name?: string; status: string }>>([]);
  const [calcId, setCalcId] = useState<string | undefined>(undefined);
  const [planId, setPlanId] = useState<string | null>(null);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await operationalPlanApi.getSystemTemplate());
    } catch {
      message.error(t('templates.system.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    forestApi.listCalculations()
      .then((cs) => setCalcs((cs || []).filter(
        (c: { status: string }) => c.status === 'completed' || c.status === 'processing',
      )))
      .catch(() => setCalcs([]));
  }, []);

  const pickForest = async (id: string) => {
    setCalcId(id);
    setPlanId(null);
    setDiff(null);
    try {
      const plan = await operationalPlanApi.getByCalculation(id);
      setPlanId(plan.id);
    } catch {
      message.warning(t('templates.system.noPlanForForest'));
    }
  };

  const preview = async () => {
    if (!planId) return;
    setBusy(true);
    try {
      const res = await operationalPlanApi.adoptSystemTemplateFromPlan(planId, false);
      setDiff(res.diff);
    } catch {
      message.error(t('templates.system.previewFailed'));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!planId) return;
    setBusy(true);
    try {
      await operationalPlanApi.adoptSystemTemplateFromPlan(planId, true);
      message.success(t('templates.system.adopted'));
      setDiff(null);
      setPlanId(null);
      setCalcId(undefined);
      load();
    } catch {
      message.error(t('templates.system.adoptFailed'));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <div style={{ textAlign: 'center', padding: 60 }}><Spin size="large" /></div>;
  if (!data) return <Alert type="error" showIcon message={t('templates.system.loadFailed')} />;

  const s = data.seed_sync;

  return (
    <div style={{ maxWidth: 780 }}>
      <Card
        size="small"
        title={
          <Space wrap>
            <Text strong>{data.template.name}</Text>
            <Tag color="gold">{t('templates.system.badge')}</Tag>
            {data.template.published_version != null && (
              <Tag color="green">v{data.template.published_version}</Tag>
            )}
          </Space>
        }
        extra={
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={load}>
              {t('templates.system.refresh')}
            </Button>
            <Button
              size="small" type="primary" icon={<EditOutlined />}
              onClick={() => navigate(`/templates/designer/${data.template.id}`)}
            >
              {t('templates.system.editInDesigner')}
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary" style={{ fontSize: 12 }}>
          {t('templates.system.blurb')}
        </Paragraph>
        {s.in_sync ? (
          <Alert type="success" showIcon message={t('templates.system.inSync')} />
        ) : (
          <Alert
            type="warning" showIcon
            message={t('templates.system.outOfSync')}
            description={
              <div style={{ fontSize: 12 }}>
                {s.missing_sections.length > 0 && (
                  <div>{t('templates.system.missingSections', { n: s.missing_sections.length })}: {s.missing_sections.slice(0, 8).join(', ')}</div>
                )}
                {s.unregistered_tokens.length > 0 && (
                  <div>{t('templates.system.unregTokens', { n: s.unregistered_tokens.length })}: {s.unregistered_tokens.slice(0, 8).join(', ')}</div>
                )}
              </div>
            }
          />
        )}
      </Card>

      <Card
        size="small"
        style={{ marginTop: 16 }}
        title={<Space><ExperimentOutlined />{t('templates.system.adoptTitle')}</Space>}
      >
        <Paragraph type="secondary" style={{ fontSize: 12 }}>
          {t('templates.system.adoptBlurb')}
        </Paragraph>
        <Space wrap>
          <Select
            style={{ width: 320 }}
            placeholder={t('templates.system.pickForest')}
            value={calcId}
            onChange={pickForest}
            options={calcs.map((c) => ({ value: c.id, label: c.forest_name || c.id }))}
          />
          <Button onClick={preview} disabled={!planId} loading={busy}>
            {t('templates.system.previewChanges')}
          </Button>
        </Space>

        {diff && (
          <>
            <Divider style={{ margin: '12px 0' }} />
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={t('templates.system.diffKept')}>{diff.kept}</Descriptions.Item>
              <Descriptions.Item label={t('templates.system.diffTokenRestored')}>
                {diff.token_restored.length}
              </Descriptions.Item>
              <Descriptions.Item label={t('templates.system.diffAdded')}>
                {diff.added.length}{diff.added.length ? ` — ${diff.added.slice(0, 8).join(', ')}` : ''}
              </Descriptions.Item>
              <Descriptions.Item label={t('templates.system.diffRemoved')}>
                {diff.removed.length}{diff.removed.length ? ` — ${diff.removed.slice(0, 8).join(', ')}` : ''}
              </Descriptions.Item>
              <Descriptions.Item label={t('templates.system.diffNeedsReview')}>
                {diff.needs_review.length
                  ? <Text type="warning">{diff.needs_review.slice(0, 8).join(', ')}</Text>
                  : '0'}
              </Descriptions.Item>
            </Descriptions>
            <Popconfirm title={t('templates.system.confirmApply')} onConfirm={apply}>
              <Button type="primary" danger loading={busy} style={{ marginTop: 8 }}>
                {t('templates.system.apply')}
              </Button>
            </Popconfirm>
          </>
        )}
      </Card>

      <Card size="small" style={{ marginTop: 16 }} title={t('templates.system.history')}>
        <List
          size="small"
          dataSource={data.versions}
          locale={{ emptyText: t('templates.system.noHistory') }}
          renderItem={(v) => (
            <List.Item>
              <Space>
                <Tag>v{v.version}</Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {formatDateTime(v.created_at, { year: 'numeric', month: 'numeric', day: 'numeric' })}
                </Text>
                {v.changelog && <Text style={{ fontSize: 12 }}>{v.changelog}</Text>}
              </Space>
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
};

export default SystemTemplatePanel;
