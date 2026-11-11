import React, { useEffect, useState } from 'react';
import { Card, Statistic, Row, Col, Button, Space, message, Spin } from 'antd';
import { ClearOutlined, ReloadOutlined, DatabaseOutlined } from '@ant-design/icons';
import { browserCache } from '../services/browserCache';
import { useTranslation } from 'react-i18next';

interface CacheStats {
  maps: number;
  charts: number;
  analysis: number;
  backend: string;
}

const CacheManagementPanel: React.FC = () => {
  const { t } = useTranslation();
  const [stats, setStats] = useState<CacheStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [clearing, setClearing] = useState(false);

  const loadStats = async () => {
    setLoading(true);
    try {
      const s = await browserCache.getStats();
      setStats(s);
    } catch {
      message.error(t('cache.loadError'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  const handleClear = async (store?: string) => {
    setClearing(true);
    try {
      if (store) {
        await browserCache.clearAll(store);
      } else {
        await browserCache.clearAll();
      }
      message.success(t('cache.cleared'));
      await loadStats();
    } catch {
      message.error(t('cache.clearError'));
    } finally {
      setClearing(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <DatabaseOutlined />
            {t('cache.title')}
          </Space>
        }
        extra={
          <Button icon={<ReloadOutlined />} onClick={loadStats}>
            {t('cache.refresh')}
          </Button>
        }
      >
        <Row gutter={[16, 16]}>
          <Col span={8}>
            <Card>
              <Statistic title={t('cache.maps')} value={stats?.maps ?? 0} />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic title={t('cache.charts')} value={stats?.charts ?? 0} />
            </Card>
          </Col>
          <Col span={8}>
            <Card>
              <Statistic title={t('cache.analysis')} value={stats?.analysis ?? 0} />
            </Card>
          </Col>
        </Row>

        <Row style={{ marginTop: 16 }} gutter={[16, 16]}>
          <Col span={24}>
            <Card size="small" title={t('cache.storage')}>
              <Statistic
                value={stats?.backend === 'indexeddb' ? t('cache.indexedDB') : t('cache.memory')}
                valueStyle={{ fontSize: 14 }}
              />
            </Card>
          </Col>
        </Row>

        <Space style={{ marginTop: 16 }} wrap>
          <Button
            danger
            icon={<ClearOutlined />}
            loading={clearing}
            onClick={() => handleClear('maps')}
          >
            {t('cache.clearMaps')}
          </Button>
          <Button
            danger
            icon={<ClearOutlined />}
            loading={clearing}
            onClick={() => handleClear('charts')}
          >
            {t('cache.clearCharts')}
          </Button>
          <Button
            danger
            icon={<ClearOutlined />}
            loading={clearing}
            onClick={() => handleClear('analysis')}
          >
            {t('cache.clearAnalysis')}
          </Button>
          <Button
            type="primary"
            danger
            icon={<ClearOutlined />}
            loading={clearing}
            onClick={() => handleClear()}
          >
            {t('cache.clearAll')}
          </Button>
        </Space>
      </Card>
    </div>
  );
};

export default CacheManagementPanel;
