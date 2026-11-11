/** TemplatesLandingPage — the single entry point for OP templates
 *  (OP_TEMPLATE_MANAGEMENT_PLAN.md §3.4 / §3.10, T5).
 *
 *  Browse & Use   — everyone: the published gallery + "Use this template".
 *  Manage         — template_designer / super_admin: My templates, Map
 *                   variables, and (super admin) the admin tools
 *                   (review queue / System Template / categories).
 *
 *  The individual pages are rendered as-is inside tab panes; `?tab=` and
 *  `?sub=` make the old `/templates/mine` + `/admin/templates` URLs land in
 *  the right place.
 */
import React from 'react';
import { Tabs, Typography, Space, Button } from 'antd';
import { AppstoreOutlined, ToolOutlined, FileSearchOutlined, FileTextOutlined } from '@ant-design/icons';
import { Link, useSearchParams } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useT } from '../i18n/hooks';
import PublicTemplatesPage from './PublicTemplatesPage';
import SectionLibraryPanel from '../components/SectionLibraryPanel';
import MyTemplatesPage from './MyTemplatesPage';
import AdminTemplatesPage from './AdminTemplatesPage';

const { Text } = Typography;

const MapVariablesLinks: React.FC = () => {
  const t = useT();
  return (
    <div style={{ padding: 24, maxWidth: 720 }}>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        {t('templates.landing.mapVarsBlurb')}
      </Text>
      <Space>
        <Link to="/templates/map-variables">
          <Button icon={<FileSearchOutlined />}>{t('navigation.mapVariables')}</Button>
        </Link>
        <Link to="/templates/hazard-variables">
          <Button icon={<FileSearchOutlined />}>{t('templates.landing.hazardVars')}</Button>
        </Link>
      </Space>
    </div>
  );
};

const TemplatesLandingPage: React.FC = () => {
  const t = useT();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const canManage = user?.role === 'super_admin' || user?.role === 'template_designer';
  const isSuper = user?.role === 'super_admin';

  const tab = params.get('tab') === 'manage' && canManage ? 'manage' : params.get('tab') === 'sections' ? 'sections' : 'browse';
  const sub = params.get('sub') || 'mine';

  const setTab = (key: string) => {
    const next = new URLSearchParams(params);
    next.set('tab', key);
    setParams(next, { replace: true });
  };
  const setSub = (key: string) => {
    const next = new URLSearchParams(params);
    next.set('tab', 'manage');
    next.set('sub', key);
    setParams(next, { replace: true });
  };

  const manageItems = [
    {
      key: 'mine',
      label: t('templates.landing.subMine'),
      children: <MyTemplatesPage />,
    },
    {
      key: 'mapvars',
      label: t('templates.landing.subMapVars'),
      children: <MapVariablesLinks />,
    },
    ...(isSuper
      ? [{
          key: 'admin',
          label: t('templates.landing.subAdmin'),
          children: <AdminTemplatesPage />,
        }]
      : []),
  ];

  return (
    <div style={{ padding: '16px 24px 0' }}>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'browse',
            label: <span><AppstoreOutlined /> {t('templates.landing.browse')}</span>,
            children: <PublicTemplatesPage />,
          },
          {
            key: 'sections',
            label: <span><FileTextOutlined /> {t('sections.tab')}</span>,
            children: <div style={{ padding: 16 }}><SectionLibraryPanel mode="browse" initialScope={params.get('scope') === 'mine' ? 'mine' : 'published'} /></div>,
          },
          ...(canManage
            ? [{
                key: 'manage',
                label: <span><ToolOutlined /> {t('templates.landing.manage')}</span>,
                children: (
                  <Tabs
                    tabPosition="left"
                    activeKey={manageItems.some((i) => i.key === sub) ? sub : 'mine'}
                    onChange={setSub}
                    items={manageItems}
                  />
                ),
              }]
            : []),
        ]}
      />
    </div>
  );
};

export default TemplatesLandingPage;
