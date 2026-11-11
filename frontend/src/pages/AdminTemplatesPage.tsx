/** AdminTemplatesPage — super-admin template tools: the system template, insights, complaints and categories. No approval queue: a user shares his own template himself. */
import React from 'react';
import { Tabs } from 'antd';
import { TagsOutlined, GoldOutlined, FlagOutlined, BarChartOutlined } from '@ant-design/icons';
import TemplateCategoryManager from '../components/OperationalPlan/TemplateCategoryManager';
import SystemTemplatePanel from '../components/OperationalPlan/SystemTemplatePanel';
import TemplateReportsPanel from '../components/OperationalPlan/TemplateReportsPanel';
import TemplateInsightsPanel from '../components/OperationalPlan/TemplateInsightsPanel';
import { useT } from '../i18n/hooks';

const AdminTemplatesPage: React.FC = () => {
  const t = useT();

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Tabs
        defaultActiveKey="system"
        items={[
          {
            key: 'system',
            label: <span><GoldOutlined /> {t('templates.system.tab')}</span>,
            children: <SystemTemplatePanel />,
          },
          {
            key: 'insights',
            label: <span><BarChartOutlined /> {t('templates.insights.tab')}</span>,
            children: <TemplateInsightsPanel />,
          },
          {
            key: 'reports',
            label: <span><FlagOutlined /> {t('templates.reports.tab')}</span>,
            children: <TemplateReportsPanel />,
          },
          {
            key: 'categories',
            label: <span><TagsOutlined /> {t('templates.admin.categories')}</span>,
            children: <TemplateCategoryManager />,
          },
        ]}
      />
    </div>
  );
};

export default AdminTemplatesPage;
