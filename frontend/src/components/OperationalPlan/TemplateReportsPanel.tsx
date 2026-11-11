/** TemplateReportsPanel -- super admin: complaints about shared templates. Dismiss one, or take the template off the shelf
 *  (it goes back to its author as a private draft, and every open complaint about it is closed). */
import React, { useCallback, useEffect, useState } from 'react';
import { List, Button, Tag, Typography, Empty, Spin, Space, Popconfirm, message } from 'antd';
import { operationalPlanApi } from '../../services/api';
import type { TemplateReport } from '../../services/api';
import { useT } from '../../i18n/hooks';

const { Text } = Typography;

export default function TemplateReportsPanel() {
  const t = useT();
  const [reports, setReports] = useState<TemplateReport[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setReports((await operationalPlanApi.listTemplateReports('open')).reports);
    } catch {
      setReports([]);
      message.error(t('templates.reports.loadFailed'));
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const act = async (r: TemplateReport, action: 'dismiss' | 'unpublish') => {
    setBusy(r.id);
    try {
      await operationalPlanApi.handleTemplateReport(r.id, action);
      message.success(t(action === 'dismiss' ? 'templates.reports.dismissed' : 'templates.reports.takenDown'));
      await load();
    } catch {
      message.error(t('templates.reports.failed'));
    } finally {
      setBusy(null);
    }
  };

  if (!reports) return <Spin />;
  if (reports.length === 0) return <Empty description={t('templates.reports.none')} />;
  return (
    <List
      dataSource={reports}
      renderItem={(r) => (
        <List.Item
          key={r.id}
          data-testid={`report-${r.id}`}
          actions={[
            <Button key="dismiss" size="small" loading={busy === r.id} onClick={() => act(r, 'dismiss')}>
              {t('templates.reports.dismiss')}
            </Button>,
            <Popconfirm key="down" title={t('templates.reports.takeDownConfirm')} onConfirm={() => act(r, 'unpublish')}>
              <Button size="small" danger loading={busy === r.id}>{t('templates.reports.takeDown')}</Button>
            </Popconfirm>,
          ]}
        >
          <List.Item.Meta
            title={<Space><Text strong>{r.template_name}</Text><Tag>{r.share_scope}</Tag></Space>}
            description={
              <div>
                <div>{r.reason}</div>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {t('templates.reports.from', { who: r.reporter ?? '—', when: r.created_at ? new Date(r.created_at).toLocaleDateString() : '' })}
                </Text>
              </div>
            }
          />
        </List.Item>
      )}
    />
  );
}
