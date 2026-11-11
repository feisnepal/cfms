/** Drawer panel that renders an HTML preview of the operational plan document fetched from the API. */
import React, { useState } from 'react';
import { Drawer, Button, Spin, message, Segmented } from 'antd';
import { EyeOutlined, CloseOutlined } from '@ant-design/icons';
import { operationalPlanApi } from '../../services/api';
import { useCanDesignTemplates } from '../calculation/HazardVarChip';
import { useT } from '../../i18n/hooks';

interface PreviewDrawerProps {
  planId: string;
  forestName?: string;
}

const PreviewDrawer: React.FC<PreviewDrawerProps> = ({ planId, forestName }) => {

  const t = useT();  const [open, setOpen] = useState(false);
  const [html, setHtml] = useState('');
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<'values' | 'tokens'>('values');
  const canDesign = useCanDesignTemplates();

  const load = async (m: 'values' | 'tokens') => {
    setLoading(true);
    try {
      const content = await operationalPlanApi.previewOperationalPlan(planId, m);
      setHtml(content);
    } catch {
      message.error(t('operationalPlan.drawer.loadFailed'));
    } finally {
      setLoading(false);
    }
  };

  const handleOpen = async () => {
    setOpen(true);
    await load(mode);
  };

  const handleModeChange = (m: 'values' | 'tokens') => {
    setMode(m);
    load(m);
  };

  return (
    <div>
      <Button icon={<EyeOutlined />} size="small" onClick={handleOpen}>
        {t('operationalPlan.drawer.preview')}
      </Button>
      <Drawer
        title={t('operationalPlan.drawer.titleNamed', { name: forestName || t('operationalPlan.page.title') })}
        placement="right"
        size="large"
        onClose={() => setOpen(false)}
        open={open}
        extra={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {canDesign && (
              <Segmented
                size="small"
                value={mode}
                onChange={(v) => handleModeChange(v as 'values' | 'tokens')}
                options={[
                  { label: t('operationalPlan.render.values'), value: 'values' },
                  { label: t('operationalPlan.render.tokens'), value: 'tokens' },
                ]}
              />
            )}
            <Button icon={<CloseOutlined />} onClick={() => setOpen(false)} type="text" />
          </div>
        }
      >
        {loading ? (
          <div style={{ textAlign: 'center', paddingTop: 80 }}>
            <Spin size="large" />
            <div style={{ marginTop: 12 }}>{t('operationalPlan.drawer.generatingPreview')}</div>
          </div>
        ) : (
          <iframe
            srcDoc={html}
            style={{ width: '100%', height: '100%', border: 'none' }}
            title={t('operationalPlan.drawer.title')}
          />
        )}
      </Drawer>
    </div>
  );
};

export default PreviewDrawer;
