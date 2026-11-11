/** TemplateInsightsPanel -- super admin: what people change in the plans built from each template. Anonymous counts only: the
 *  sections they edit, hide or remove, the sections they add, the variables they type by hand. It points at where the template,
 *  or the system, should develop next. */
import React, { useEffect, useState } from 'react';
import { Collapse, Table, Progress, Select, Space, Typography, Empty, Spin, Tag, message } from 'antd';
import { operationalPlanApi } from '../../services/api';
import { useT } from '../../i18n/hooks';
import i18n from '../../i18n';

const { Text } = Typography;

interface SectionRow {
  node_id: string; title_en: string; title_ne: string; plans: number; kept: number; edited: number; hidden: number;
  removed: number; no_data: number; changed_pct: number; no_data_pct: number;
}
interface TemplateRow {
  template_id: string; template_name: string; plans: number; owners: number; sections: SectionRow[];
  added_sections: { title: string; owners: number }[]; typed_variables: { variable: string; owners: number }[];
}

export default function TemplateInsightsPanel() {
  const t = useT();
  const isNe = i18n.language === 'ne';
  const [minOwners, setMinOwners] = useState(2);
  const [data, setData] = useState<TemplateRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    operationalPlanApi
      .getTemplateAnalytics(minOwners)
      .then((r) => { if (!cancelled) setData(r.templates as TemplateRow[]); })
      .catch(() => { if (!cancelled) { setData([]); message.error(t('templates.insights.loadFailed')); } });
    return () => { cancelled = true; };
  }, [minOwners, t]);

  const columns = [
    { title: t('templates.insights.section'), key: 'title', render: (_: unknown, r: SectionRow) => (isNe ? r.title_ne || r.title_en : r.title_en || r.title_ne) },
    { title: t('templates.insights.plans'), dataIndex: 'plans', key: 'plans', width: 70 },
    { title: t('templates.insights.kept'), dataIndex: 'kept', key: 'kept', width: 70 },
    { title: t('templates.insights.edited'), dataIndex: 'edited', key: 'edited', width: 80 },
    { title: t('templates.insights.hidden'), dataIndex: 'hidden', key: 'hidden', width: 80 },
    { title: t('templates.insights.removed'), dataIndex: 'removed', key: 'removed', width: 90 },
    {
      title: t('templates.insights.changed'), key: 'changed', width: 170,
      render: (_: unknown, r: SectionRow) => <Progress percent={r.changed_pct} size="small" status={r.changed_pct >= 50 ? 'exception' : 'normal'} />,
    },
    {
      title: t('templates.insights.noData'), key: 'nodata', width: 90,
      render: (_: unknown, r: SectionRow) => (r.no_data_pct > 0 ? <Tag color="red">{r.no_data_pct}%</Tag> : <Text type="secondary">0%</Text>),
    },
  ];

  return (
    <div data-testid="template-insights">
      <Space style={{ marginBottom: 12 }} wrap>
        <Text type="secondary">{t('templates.insights.hint')}</Text>
        <span>{t('templates.insights.minOwners')}</span>
        <Select size="small" value={minOwners} onChange={setMinOwners} style={{ width: 70 }}
          options={[1, 2, 3, 5].map((n) => ({ value: n, label: String(n) }))} />
      </Space>
      {data === null ? <Spin /> : data.length === 0 ? <Empty description={t('templates.insights.none')} /> : (
        <Collapse
          defaultActiveKey={[data[0].template_id]}
          items={data.map((tpl) => ({
            key: tpl.template_id,
            label: <span><b>{tpl.template_name}</b> <Text type="secondary">{t('templates.insights.summary', { plans: tpl.plans, owners: tpl.owners })}</Text></span>,
            children: (
              <div>
                <Table size="small" rowKey="node_id" columns={columns} dataSource={tpl.sections} pagination={{ pageSize: 15, hideOnSinglePage: true }} />
                <div style={{ display: 'flex', gap: 32, marginTop: 16, flexWrap: 'wrap' }}>
                  <div data-testid="insight-added">
                    <Text strong>{t('templates.insights.added')}</Text>
                    {tpl.added_sections.length === 0 ? <div><Text type="secondary">{t('templates.insights.noneYet')}</Text></div> : (
                      <ul style={{ margin: '4px 0', paddingLeft: 18 }}>{tpl.added_sections.map((a) => <li key={a.title}>{a.title} <Text type="secondary">({a.owners})</Text></li>)}</ul>
                    )}
                  </div>
                  <div data-testid="insight-typed">
                    <Text strong>{t('templates.insights.typed')}</Text>
                    {tpl.typed_variables.length === 0 ? <div><Text type="secondary">{t('templates.insights.noneYet')}</Text></div> : (
                      <ul style={{ margin: '4px 0', paddingLeft: 18 }}>{tpl.typed_variables.map((v) => <li key={v.variable}><code>{v.variable}</code> <Text type="secondary">({v.owners})</Text></li>)}</ul>
                    )}
                  </div>
                </div>
              </div>
            ),
          }))}
        />
      )}
    </div>
  );
}
